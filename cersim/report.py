"""Report PDF da portare in assemblea ed export Excel dei risultati.

Dato un oggetto `Analisi` e i parametri economici usati:
- `report_pdf` produce 3–4 pagine leggibili da chi non è tecnico: scenario
  preliminare, configurazione, requisiti, cifre con intervallo degli scenari,
  confronto con il solo fotovoltaico, grafici, chi paga e chi riceve, ipotesi,
  prezzi, versioni dei pacchetti, manifest e avvertenze;
- `report_excel` produce i fogli Riepilogo, Per membro, Flussi di cassa,
  Movimenti, Confronto e Manifest. Le celle di testo che iniziano con = + - @
  ricevono il prefisso ' per non essere lette come formule.
Niente Streamlit qui: il modulo si usa anche da script. Carattere Geist da
static/ (istanze statiche del font variabile) e colori di DESIGN.md.
"""

import io
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from cersim import __version__
from cersim.analisi import (
    Analisi,
    anno_rappresentativo,
    cassa_cumulata,
    chi_riceve_cosa,
    fonti_prezzi,
    giorno_tipo,
    mensile,
    nomi_leggibili,
)
from cersim.economics import ESCLUSIONI, ParametriEconomici, capex
from cersim.eligibility import Stato
from cersim.loads import QUOTA_MISURATA_PER_A, qualita_consumi, quota_misurata
from cersim.model import Ruolo
from cersim.normativa import assunzioni_economiche, classificazione_soggetti, pacchetto_normativo
from cersim.scenari import Banda
from cersim.tetto import ATTRIBUZIONE as ATTRIBUZIONE_OSM

CARTELLA_FONT = Path(__file__).resolve().parents[1] / "static"
FONT = {"": "Geist-Regular.ttf", "B": "Geist-SemiBold.ttf"}

# colori di DESIGN.md
TESTO = "#172026"
TENUE = "#55626a"
BORDO = "#d6dee2"
PANNELLO = "#eaf0f2"
ACCENTO = "#1f5f6b"
TONI = {"ok": ("#346c42", "#e1f5e4"), "no": ("#a83630", "#ffe7e4"), "forse": ("#845a0f", "#fcedcd")}
COLORI_GRAFICI = {"Produzione FV": "#e6ac3d", "Consumi": "#314968", "Autoconsumo fisico": "#4b9779",
                  "Energia condivisa": "#b44e2e"}
NEUTRO = "#87939a"

STATO_ETICHETTA = {
    Stato.AMMESSO: ("Coerente con i dati", "ok"),
    Stato.NON_AMMESSO: ("Non ammesso", "no"),
    Stato.SCONOSCIUTO: ("Da verificare", "forse"),
}
QUALITA = {
    "A": ("Curva completa", "ok", "consumi misurati per quasi un anno; non è una garanzia del risultato"),
    "B": ("Qualità B", "ok", "dati da bolletta e fonti pubbliche"),
    "C": ("Qualità C", "forse", "valori di default o semplificati: risultati solo esplorativi"),
}
NOMI_CONTROLLI = {"soci": "Soci ammessi", "cabina_primaria": "Stessa cabina primaria"}
AVVISO_PRELIMINARE = "Scenario preliminare: non sostituisce uno studio di fattibilità."
NOTA_INTERVALLI = ("Intervalli: il minimo e il massimo degli scenari di meteo, prezzi e orari di consumo, non "
                   "probabilità.")
MAX_RIGHE_MEMBRI_PDF = 16
MAX_AVVISI_PDF = 12
INIZIO_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def euro(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def kwh(x: float) -> str:
    return f"{x:,.0f} kWh".replace(",", ".")


def _formatta(x: float, unita: str) -> str:
    return euro(x) if unita == "€" else kwh(x)


# --- contenuti comuni a PDF ed Excel ---------------------------------------------------
@dataclass(frozen=True)
class Cifra:
    voce: str
    valore: float
    minimo: float
    massimo: float
    unita: str  # "kWh" o "€"
    significato: str


def _anno_rif(analisi: Analisi) -> int:
    return anno_rappresentativo(analisi.energia_base).year


def cifre(analisi: Analisi, nomi: dict[str, str]) -> list[Cifra]:
    """La tabella delle cifre della scheda Risultati: valore centrale e intervallo degli scenari."""
    tot = anno_rappresentativo(analisi.energia_base).totali()
    if analisi.economia_disabilitata:
        return [Cifra("Energia condivisa", tot["EACV_kwh"], tot["EACV_kwh"], tot["EACV_kwh"], "kWh",
                      "Energia prodotta e consumata nella stessa ora dai membri (solo anno meteo più recente).")]
    b = analisi.bande
    k = analisi.base.kpi
    investitore = nomi.get(k.investitore, k.investitore)
    rientro = (f"{k.payback_investitore} anni ({k.payback_attualizzato_investitore} attualizzato)"
               if k.payback_investitore is not None else "oltre la vita dell'impianto")
    if analisi.qualita == "C":
        tir = "TIR non mostrato con dati di qualità C"
    elif k.tir_investitore is not None:
        tir = f"TIR {k.tir_investitore:.1%}"
    else:
        tir = "TIR non definito"
    tip, cacv = b["tip_eur_anno"], b["cacv_eur_anno"]
    return [
        Cifra("Energia condivisa all'anno", tot["EACV_kwh"], b["energia_condivisa_kwh"].minimo,
              b["energia_condivisa_kwh"].massimo, "kWh",
              f"Energia prodotta e consumata nella stessa ora dai membri. Copre il {tot['copertura_consumi']:.0%} dei "
              "consumi insieme all'autoconsumo diretto."),
        Cifra("Contributi GSE all'anno", tip.mediana + cacv.mediana, tip.minimo + cacv.minimo, tip.massimo + cacv.massimo,
              "€", "Tariffa premio più valorizzazione ARERA, prima della divisione tra membri e chi investe."),
        Cifra("Beneficio netto della configurazione", b["van_consolidato"].mediana, b["van_consolidato"].minimo,
              b["van_consolidato"].massimo, "€",
              "Valore attuale netto su 25 anni di tutti i flussi con l'esterno: contributi, vendite, bollette evitate, "
              "costi."),
        Cifra(f"Beneficio netto di chi investe ({investitore})", b["van_investitore"].mediana,
              b["van_investitore"].minimo, b["van_investitore"].massimo, "€",
              f"Rientro in {rientro}, {tir}, nello scenario base."),
    ]


def frase_sintesi(analisi: Analisi) -> list[tuple[str, bool]]:
    """La frase che un sindaco può ripetere, a segmenti (testo, grassetto)."""
    if analisi.dati_incoerenti:
        return [(analisi.economia_disabilitata, False)]
    yr = anno_rappresentativo(analisi.energia_base)
    tot = yr.totali()
    testa = [(f"Nel {yr.year}, primo anno intero, ", False), (analisi.config.nome, True), (" condivide ", False),
             (kwh(tot["EACV_kwh"]), True), (f", il {tot['quota_condivisa_su_immessa']:.0%} dell'energia immessa", False)]
    if analisi.economia_disabilitata:
        return testa + [(". I contributi non sono calcolati: il pacchetto normativo va aggiornato.", False)]
    b = analisi.bande
    contributi = b["tip_eur_anno"].mediana + b["cacv_eur_anno"].mediana
    coda = " Gli importi sono condizionali: alcuni requisiti restano da verificare." if analisi.report.condizionale else ""
    return testa + [
        (", e riceve circa ", False), (euro(contributi), True),
        (" di contributi GSE. Su 25 anni il beneficio netto per la configurazione è stimato tra ", False),
        (euro(b["van_consolidato"].minimo), True), (" e ", False), (euro(b["van_consolidato"].massimo), True),
        (f".{coda}", False),
    ]


def _nome_configurazione(analisi: Analisi) -> str:
    return "gruppo di autoconsumatori" if analisi.config.tipo.value == "gruppo" else "comunità energetica"


def confronto(analisi: Analisi) -> list[tuple[str, Banda | None, str]]:
    """Non investire, solo fotovoltaico, fotovoltaico con la configurazione."""
    b = analisi.bande
    gruppo = analisi.config.tipo.value == "gruppo"
    nome_cfg = _nome_configurazione(analisi)
    autoconsumo = ("i consumi delle parti comuni o del contatore a cui è collegato" if gruppo
                   else "i consumi del contatore a cui è collegato")
    return [
        ("Non investire", None, "Nessuna spesa, nessun beneficio."),
        ("Solo fotovoltaico", b["van_solo_fv"], f"Senza {nome_cfg}: copre {autoconsumo} e vende il resto."),
        (f"Fotovoltaico con {nome_cfg}", b["van_consolidato"],
         "In più i contributi GSE sull'energia condivisa, meno costituzione e gestione."),
    ]


def frase_confronto(analisi: Analisi) -> str:
    aggiunta = analisi.bande["valore_configurazione"]
    il_cfg = ("il " if analisi.config.tipo.value == "gruppo" else "la ") + _nome_configurazione(analisi)
    if aggiunta.massimo <= 0:
        return (f"In questi scenari costituire {il_cfg} non conviene: i suoi costi superano i contributi "
                f"(tra {euro(aggiunta.minimo)} e {euro(aggiunta.massimo)} rispetto al solo fotovoltaico).")
    if aggiunta.minimo < 0:
        return (f"Costituire {il_cfg} cambia il beneficio netto tra {euro(aggiunta.minimo)} e "
                f"{euro(aggiunta.massimo)} rispetto al solo fotovoltaico: la convenienza dipende dallo scenario.")
    return (f"Costituire {il_cfg} aggiunge tra {euro(aggiunta.minimo)} e {euro(aggiunta.massimo)} di beneficio "
            "netto rispetto al solo fotovoltaico, già tolti i suoi costi.")


@dataclass(frozen=True)
class Miglioramento:
    cosa: str  # il dato che manca
    perche: str  # che cosa cambia nella stima
    passo: int | None  # dove si inserisce (None: non dipende dall'utente)


def frase_precisione(analisi: Analisi) -> str:
    """Quanto è largo oggi l'intervallo e perché i dati reali lo restringono."""
    coda = "Con dati più reali la stima si avvicina alla realtà: ecco quali mancano."
    banda = analisi.bande.get("van_consolidato")
    if analisi.economia_disabilitata or banda is None:  # senza euro non ci sono intervalli degli scenari
        return coda
    return f"Oggi il beneficio netto della configurazione va da {euro(banda.minimo)} a {euro(banda.massimo)}. {coda}"


def _contatori(n: int) -> str:
    return f"{n} contatore" if n == 1 else f"{n} contatori"


def dati_da_migliorare(analisi: Analisi) -> list[Miglioramento]:
    """I dati che mancano, dal più importante: quelli che spostano di più il risultato vengono prima."""
    cfg = analisi.config
    consumano = [c for c in cfg.connection_points if c.ruolo is not Ruolo.SOLA_IMMISSIONE]
    totale = sum(c.kwh_effettivi for c in consumano) or 1.0
    out = []

    tipici = [c for c in consumano if c.kwh_da_default]
    if tipici:
        quota = sum(c.kwh_effettivi for c in tipici) / totale
        out.append(Miglioramento(
            f"{_contatori(len(tipici))} su {len(consumano)} senza consumo dalla bolletta",
            f"Usano il consumo di una famiglia tipo e fanno il {quota:.0%} dei consumi. L'energia condivisa dipende "
            "da quanto consumano i membri: è il dato che sposta di più il risultato.", 2))
    senza_fasce = [c for c in consumano if not c.kwh_da_default and c.fasce is None and c.curva_misurata is None]
    if senza_fasce:
        out.append(Miglioramento(
            f"{_contatori(len(senza_fasce))} su {len(consumano)} senza le fasce F1 e F2+F3",
            "Le fasce dicono quanta energia si usa di giorno, quando c'è il sole, e quanta la sera.", 2))
    if any(p.fonte != "PVGIS" for profili in analisi.pv.values() for p in profili.values()):
        out.append(Miglioramento(
            "Produzione stimata senza PVGIS",
            "PVGIS non ha risposto e la produzione viene da un modello semplificato. Ricalcola più tardi.", None))
    if not analisi.economia_disabilitata and any(e.qualita_prezzi == "C" for e in analisi.esiti):
        out.append(Miglioramento(
            "Prezzo dell'energia costante invece che ora per ora",
            "Il prezzo costante sovrastima le vendite nelle ore di sole: con prezzi orari vendita e tariffa premio "
            "sono più realistiche.", 4))
    if cfg.tipo.value == "CER":
        senza_area = [c for c in cfg.connection_points if not c.area_convenzionale]
        if senza_area:
            out.append(Miglioramento(
                f"{_contatori(len(senza_area))} senza area convenzionale",
                "Senza, non si può verificare che tutti siano sotto la stessa cabina primaria: i contributi restano "
                "condizionali.", 2))
    senza_preventivo = [p for p in cfg.plants if p.costo_preventivo_eur is None]
    if senza_preventivo:
        out.append(Miglioramento(
            "Costo dell'impianto senza preventivo",
            "Si usa il costo massimo di riferimento del DM 414/2023, una stima alta.", 3))
    misurata = quota_misurata(consumano)
    if misurata < QUOTA_MISURATA_PER_A:
        senza = [c for c in consumano if qualita_consumi(c) != "A"]
        out.append(Miglioramento(
            f"{_contatori(len(senza))} su {len(consumano)} senza curva oraria misurata",
            (f"Oggi il {misurata:.0%} dei consumi viene da curve misurate. " if misurata > 0 else "")
            + "Usano curve tipiche o calcolate. Con almeno 11 mesi di file dal Portale Consumi o da e-distribuzione si "
            f"usano le ore vere; con il {QUOTA_MISURATA_PER_A:.0%} dei consumi coperti si arriva alla curva completa.", 2))
    return out


def requisiti(analisi: Analisi, *, tutti: bool = True) -> list[tuple[str, Stato, str]]:
    """Controlli della configurazione e, per ogni impianto, tariffa premio e contributo in capitale.
    Con `tutti=False` gli esiti degli impianti compaiono solo se non sono coerenti con i dati."""
    rep = analisi.report
    righe = [(NOMI_CONTROLLI.get(nome, nome), e.stato, e.motivo) for nome, e in rep.configurazione.items()]
    for pid, e in rep.impianti.items():
        nome = next((p.nome for p in analisi.config.plants if p.id == pid), pid)
        voci = [("Tariffa premio", e.tip)]
        if e.contributo_capitale is not None:
            voci.append(("Contributo in capitale", e.contributo_capitale))
        righe += [(f"{voce}, {nome}", esito.stato, esito.motivo) for voce, esito in voci
                  if tutti or esito.stato is not Stato.AMMESSO]
    return righe


def ipotesi(analisi: Analisi, params: ParametriEconomici) -> list[tuple[str, str]]:
    """Le scelte dello scenario, con i valori predefiniti quando non indicati."""
    ip = assunzioni_economiche()
    tipo = analisi.config.tipo.value
    om = (ip.impianto.om_quota_capex_anno + ip.impianto.assicurazione_quota_capex_anno
          if params.om_assicurazione_quota_anno is None else params.om_assicurazione_quota_anno)
    gestione = ip.configurazione.gestione_eur_anno[tipo] if params.gestione_eur_anno is None else params.gestione_eur_anno
    costituzione = ip.configurazione.costituzione_eur[tipo] if params.costituzione_eur is None else params.costituzione_eur
    costo_evitabile = (ip.bolletta.costo_evitabile_eur_kwh if params.costo_evitabile_eur_kwh is None
                       else params.costo_evitabile_eur_kwh)
    tasso = ip.finanza.tasso_sconto_reale if params.tasso_sconto is None else params.tasso_sconto
    righe = [
        ("Quota del netto ai membri", f"{params.quota_membri:.0%}, in proporzione all'energia condivisa con i loro "
                                      "consumi; il resto a chi ha pagato l'impianto"),
        ("Costo evitato in bolletta", f"{costo_evitabile:.3f} € per kWh autoconsumato".replace(".", ",")
         + ("; per i contatori arrivati con il profilo di una casa, il prezzo della loro bolletta"
            if any(cp.profilo is not None and cp.profilo.bolletta is not None
                   for cp in analisi.config.connection_points) else "")),
        ("Tasso di sconto reale", f"{tasso:.1%}".replace(".", ",")),
        ("Vendita dell'energia immessa", "Ritiro dedicato GSE" if params.regime_vendita == "RID" else "a un trader"),
        ("Durata", f"{len(analisi.energia_base.anni)} anni dalla prima entrata in esercizio"),
        ("Manutenzione e assicurazione", f"{om:.1%} del costo dell'impianto all'anno".replace(".", ",")),
        ("Gestione della configurazione", f"{euro(gestione)} all'anno"),
        ("Costituzione", f"{euro(costituzione)} una tantum"),
    ]
    for p in analisi.config.plants:
        fonte = "da preventivo" if p.costo_preventivo_eur is not None else "costo massimo di riferimento del DM 414/2023"
        righe.append((f"Costo di {p.nome}", f"{euro(capex(p, ip))}, {fonte}"))
    righe += [
        ("Valori", "in euro costanti (reali) e prima delle imposte"),
        ("Disavanzo della configurazione", "se in un anno i costi superano i contributi, li copre chi investe"),
    ]
    return righe


# attribuzione richiesta dalla licenza ODbL: il report non sa se le ombre sono state stimate dalla mappa o scelte a
# mano, quindi la riga c'è sempre e lo dice
FONTE_OMBRE = ("Ombre degli edifici vicini", f"{ATTRIBUZIONE_OSM}, quando sono stimate dalla mappa")


def versioni() -> list[tuple[str, str]]:
    norma, eco, soggetti = pacchetto_normativo(), assunzioni_economiche(), classificazione_soggetti()

    def data(d: date) -> str:
        return d.strftime("%d/%m/%Y")

    return [
        ("cersim", __version__),
        ("Pacchetto normativo", f"versione {norma.versione}, rivisto il {data(norma.revisione)}, "
                                f"valido fino al {data(norma.scadenza)}"),
        ("Assunzioni economiche", f"versione {eco.versione}, riviste il {data(eco.revisione)}, "
                                  f"valide fino al {data(eco.scadenza)}"),
        ("Classificazione dei soggetti", f"versione {soggetti.versione}, valida fino al {data(soggetti.scadenza)}"),
    ]


def avvertenze(analisi: Analisi) -> list[str]:
    return list(analisi.avvisi) + ["Valori prima delle imposte. Esclusi: " + ", ".join(ESCLUSIONI) + "."]


def avvertenze_compatte(avvisi: list[str]) -> list[str]:
    """Avvertenze uguali che cambiano solo per anno o importi ("2031: quota eccedentaria ...") in una sola riga."""
    gruppi: dict[str, list[str]] = {}
    for a in avvisi:
        trovato = re.match(r"^\d{4}: (.*)$", a)
        chiave = re.sub(r"\d[\d.,]*", "#", trovato.group(1)) if trovato else a
        gruppi.setdefault(chiave, []).append(a)
    out = []
    for voci in gruppi.values():
        if len(voci) == 1:
            out.append(voci[0])
        else:
            altri = "un altro caso" if len(voci) == 2 else f"altri {len(voci) - 1} casi"
            out.append(f"{voci[0]} (lo stesso in {altri} tra anni e scenari; elenco completo nel file Excel)")
    return out


def per_membro(analisi: Analisi, nomi: dict[str, str]) -> pd.DataFrame:
    """Per ogni membro, nel primo anno intero dello scenario base: energia condivisa, entrate per voce, uscite,
    netto e beneficio netto su tutta la durata."""
    led = analisi.base.ledger
    anno = _anno_rif(analisi)
    contributi = led.contributi[anno - led.anno_inizio]
    condivisa: dict[str, float] = {}
    for cp in analisi.config.connection_points:
        condivisa[cp.titolare] = condivisa.get(cp.titolare, 0.0) + float(contributi.eacv_per_punto_kwh.get(cp.id, 0.0))
    righe = []
    for m in analisi.config.members:
        entrate = {"riparto": 0.0, "bolletta": 0.0, "vendita": 0.0, "altro": 0.0}
        uscite = 0.0
        for mv in led.movimenti:
            if mv.anno != anno:
                continue
            if mv.percettore == m.id:
                chiave = {"riparto ai membri": "riparto", "quota all'investitore": "riparto",
                          "risparmio in bolletta": "bolletta", "vendita energia": "vendita"}.get(mv.voce, "altro")
                entrate[chiave] += mv.importo
            if mv.pagatore == m.id:
                uscite += mv.importo
        righe.append({
            "Membro": nomi.get(m.id, m.id),
            "Tipo di soggetto": m.tipo_soggetto.value.replace("_", " "),
            "Contatori": sum(cp.titolare == m.id for cp in analisi.config.connection_points),
            "Energia condivisa kWh": condivisa.get(m.id, 0.0),
            "Quota dei contributi €": entrate["riparto"],
            "Risparmio in bolletta €": entrate["bolletta"],
            "Vendita energia €": entrate["vendita"] + entrate["altro"],
            "Spese €": uscite,
            "Netto nell'anno €": float(led.flussi_soggetto(m.id)[anno - led.anno_inizio]),
            "Beneficio netto su tutta la durata €": led.van(led.flussi_soggetto(m.id)),
        })
    return pd.DataFrame(righe)


def _chi_paga_compatto(analisi: Analisi, nomi: dict[str, str], max_nomi: int = 3) -> pd.DataFrame:
    """Come `chi_riceve_cosa`, ma con molti percettori (o pagatori) della stessa voce raggruppati in una riga."""
    df = chi_riceve_cosa(analisi.base, nomi)
    if df.empty:
        return df
    for colonna, altra in (("Chi riceve", "Chi paga"), ("Chi paga", "Chi riceve")):
        righe = []
        for (voce, chi), gruppo in df.groupby(["Voce", altra], sort=False):
            if len(gruppo) > max_nomi:
                righe.append({"Voce": voce, altra: chi, colonna: f"{len(gruppo)} membri", "€": gruppo["€"].sum()})
            else:
                righe += gruppo.to_dict("records")
        df = pd.DataFrame(righe, columns=["Voce", "Chi paga", "Chi riceve", "€"])
    return df.sort_values("€", ascending=False)


# --- grafici (matplotlib, senza pyplot) ------------------------------------------------
_font_registrati = False


def _percorso_font(stile: str) -> Path:
    percorso = CARTELLA_FONT / FONT[stile]
    if not percorso.exists():
        raise FileNotFoundError(f"Manca il carattere {percorso.name} in {CARTELLA_FONT}")
    return percorso


def _stile_grafici() -> dict:
    global _font_registrati
    from matplotlib import font_manager

    if not _font_registrati:
        for stile in FONT:
            font_manager.fontManager.addfont(str(_percorso_font(stile)))
        _font_registrati = True
    return {
        "font.family": "Geist", "font.size": 7, "text.color": TESTO, "axes.labelcolor": TENUE,
        "axes.edgecolor": BORDO, "axes.titlesize": 8, "axes.titleweight": 600, "axes.titlelocation": "left",
        "axes.titlecolor": TESTO, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "axes.axisbelow": True, "grid.color": BORDO, "grid.linewidth": 0.5, "xtick.color": TENUE, "ytick.color": TENUE,
        "legend.frameon": False, "legend.fontsize": 6.5, "figure.facecolor": "white", "axes.facecolor": "white",
    }


def _migliaia(x, _pos=None) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _figura(disegna, larghezza_mm: float, altezza_mm: float) -> io.BytesIO:
    import matplotlib
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    with matplotlib.rc_context(_stile_grafici()):
        fig = Figure(figsize=(larghezza_mm / 25.4, altezza_mm / 25.4), dpi=220)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot()
        disegna(ax)
        fig.tight_layout(pad=0.4)
        out = io.BytesIO()
        fig.savefig(out, format="png")
    out.seek(0)
    return out


def _grafico_giorno(analisi: Analisi, mese: int = 6):
    dati = giorno_tipo(anno_rappresentativo(analisi.energia_base), mese)

    def disegna(ax):
        for colonna in dati.columns:
            ax.plot(dati.index, dati[colonna], color=COLORI_GRAFICI[colonna], linewidth=1.4, label=colonna)
        ax.set_title("Giorno tipo di giugno")
        ax.set_xlabel("ora del giorno")
        ax.set_ylabel("kWh medi")
        ax.set_xticks(range(0, 24, 3))
        ax.legend(loc="upper left", ncols=2)
        ax.set_ylim(bottom=0, top=float(dati.to_numpy().max()) * 1.35 or 1)
    return disegna


def _grafico_mesi(analisi: Analisi):
    dati = mensile(anno_rappresentativo(analisi.energia_base))
    colori = ["#b44e2e", "#c5d0d6", "#4b9779"]

    def disegna(ax):
        sotto = np.zeros(len(dati))
        for colonna, colore in zip(dati.columns, colori):
            ax.bar(dati.index, dati[colonna], bottom=sotto, color=colore, width=0.7,
                   label=colonna.replace(" (kWh)", ""))
            sotto += dati[colonna].to_numpy()
        ax.set_title("Mese per mese")
        ax.set_ylabel("kWh")
        ax.yaxis.set_major_formatter(_migliaia)
        ax.tick_params(axis="x", labelsize=6)
        ax.legend(loc="upper left", ncols=1)
        ax.set_ylim(top=float(sotto.max()) * 1.45 or 1)
        ax.grid(axis="x", visible=False)
    return disegna


def _grafico_cassa(analisi: Analisi, nomi: dict[str, str]):
    dati = cassa_cumulata(analisi.base)
    investitore = nomi.get(analisi.base.kpi.investitore, analisi.base.kpi.investitore)

    def disegna(ax):
        ax.axhline(0, color=NEUTRO, linewidth=0.8)
        ax.plot(dati.index, dati.iloc[:, 0], color=ACCENTO, linewidth=1.4, label="Configurazione (consolidato)")
        ax.plot(dati.index, dati.iloc[:, 1], color="#b44e2e", linewidth=1.4, label=f"Chi investe ({investitore})")
        ax.set_title("Cassa cumulata, scenario base")
        ax.set_ylabel("€ cumulati, non attualizzati")
        ax.yaxis.set_major_formatter(_migliaia)
        ax.legend(loc="upper left")
    return disegna


def _grafico_tornado(analisi: Analisi):
    voci = analisi.sensibilita
    base = analisi.base.kpi.van_consolidato

    def disegna(ax):
        y = np.arange(len(voci))[::-1]
        basso = [v.van_consolidato_basso - base for v in voci]
        alto = [v.van_consolidato_alto - base for v in voci]
        ax.barh(y, basso, left=base, height=0.55, color="#314968", label="parametro basso")
        ax.barh(y, alto, left=base, height=0.55, color="#e6ac3d", label="parametro alto")
        ax.axvline(base, color=NEUTRO, linewidth=0.8)
        ax.set_yticks(y, [f"{v.parametro} ({v.variazione})" for v in voci], fontsize=6)
        ax.set_title("Che cosa pesa di più")
        ax.set_xlabel("Beneficio netto della configurazione (€)")
        ax.xaxis.set_major_formatter(_migliaia)
        ax.tick_params(axis="x", labelsize=6)
        ax.legend(loc="lower right")
        ax.grid(axis="y", visible=False)
    return disegna


# --- PDF ------------------------------------------------------------------------------
def _rgb(colore: str) -> tuple[int, int, int]:
    colore = colore.lstrip("#")
    return tuple(int(colore[i:i + 2], 16) for i in (0, 2, 4))


def _nuovo_pdf(piede: str):
    from fpdf import FPDF

    class _Pdf(FPDF):
        def footer(self):
            self.set_y(-11)
            self.set_font("Geist", "", 7)
            self.set_text_color(*_rgb(TENUE))
            self.cell(0, 4, piede, align="L")
            self.cell(0, 4, f"pagina {self.page_no()} di {{nb}}", align="R")

    pdf = _Pdf(format="A4", unit="mm")
    for stile in FONT:
        pdf.add_font("Geist", stile, str(_percorso_font(stile)))
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_text_color(*_rgb(TESTO))
    pdf.set_draw_color(*_rgb(BORDO))
    pdf.set_line_width(0.25)
    return pdf


def _spazio_per(pdf, altezza: float) -> None:
    """Nuova pagina se dal punto attuale non ci stanno `altezza` mm."""
    if pdf.get_y() + altezza > pdf.h - pdf.b_margin:
        pdf.add_page()


def _titolo(pdf, testo: str, *, prima: float = 6.0, spazio_dopo: float = 30.0) -> None:
    _spazio_per(pdf, prima + 8 + spazio_dopo)
    pdf.ln(prima)
    pdf.set_font("Geist", "B", 12.5)
    pdf.set_text_color(*_rgb(TESTO))
    pdf.cell(0, 7, testo, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _paragrafo(pdf, testo: str, *, dimensione: float = 9.5, colore: str = TESTO, altezza: float = 4.8) -> None:
    pdf.set_font("Geist", "", dimensione)
    pdf.set_text_color(*_rgb(colore))
    pdf.multi_cell(0, altezza, testo, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_rgb(TESTO))


def _segmenti(pdf, segmenti: list[tuple[str, bool]], *, dimensione: float = 11, altezza: float = 6) -> None:
    for testo, grassetto in segmenti:
        pdf.set_font("Geist", "B" if grassetto else "", dimensione)
        pdf.write(altezza, testo)
    pdf.ln(altezza)


def _pillola(pdf, testo: str, tono: str, *, dimensione: float = 7.5) -> float:
    """Etichetta di stato a pillola, con testo e colore (mai il solo colore). Restituisce la larghezza."""
    colore, sfondo = TONI[tono]
    pdf.set_font("Geist", "B", dimensione)
    larghezza = pdf.get_string_width(testo) + 4.5
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_fill_color(*_rgb(sfondo))
    pdf.set_draw_color(*_rgb(colore))
    pdf.rect(x, y + 0.4, larghezza, 4.4, style="DF", round_corners=True, corner_radius=2.2)
    pdf.set_text_color(*_rgb(colore))
    pdf.set_xy(x, y + 0.4)
    pdf.cell(larghezza, 4.4, testo, align="C")
    pdf.set_xy(x + larghezza, y)
    pdf.set_text_color(*_rgb(TESTO))
    pdf.set_draw_color(*_rgb(BORDO))
    return larghezza


def _tabella(pdf, intestazioni: list[str], righe: list[list[str]], larghezze: tuple, allinea: tuple,
             *, dimensione: float = 8.5, grassetto_prima: bool = False) -> None:
    from fpdf.fonts import FontFace

    pdf.set_font("Geist", "", dimensione)
    pdf.set_draw_color(*_rgb(BORDO))
    pdf.set_fill_color(255, 255, 255)
    intestazione = FontFace(emphasis="BOLD", color=_rgb(TENUE), fill_color=_rgb(PANNELLO), size_pt=dimensione - 0.5)
    with pdf.table(col_widths=larghezze, text_align=allinea, borders_layout="HORIZONTAL_LINES",
                   headings_style=intestazione, line_height=dimensione * 0.48, padding=(1.4, 1.6),
                   width=pdf.epw, first_row_as_headings=True, cell_fill_mode="NONE") as tabella:
        riga = tabella.row()
        for testo in intestazioni:
            riga.cell(testo)
        for valori in righe:
            riga = tabella.row()
            for i, testo in enumerate(valori):
                stile = FontFace(emphasis="BOLD") if grassetto_prima and i == 0 else None
                riga.cell(str(testo), style=stile)
    pdf.ln(1.5)


def _elenco(pdf, voci: list[str], *, dimensione: float = 8.5) -> None:
    pdf.set_font("Geist", "", dimensione)
    for voce in voci:
        _spazio_per(pdf, 5)
        pdf.set_x(pdf.l_margin)
        pdf.cell(4, dimensione * 0.5, "•")
        pdf.multi_cell(0, dimensione * 0.5, voce, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.6)


def _coppie(pdf, coppie: list[tuple[str, str]], *, dimensione: float = 8.5, colonna: float = 52) -> None:
    for chiave, valore in coppie:
        _spazio_per(pdf, 5)
        pdf.set_font("Geist", "B", dimensione)
        pdf.set_x(pdf.l_margin)
        y = pdf.get_y()
        pdf.multi_cell(colonna - 3, dimensione * 0.5, chiave, align="L", new_x="LMARGIN", new_y="NEXT")
        fine_chiave = pdf.get_y()
        pdf.set_font("Geist", "", dimensione)
        pdf.set_xy(pdf.l_margin + colonna, y)
        pdf.multi_cell(0, dimensione * 0.5, valore, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_y(max(pdf.get_y(), fine_chiave) + 0.6)


def _intestazione(pdf, analisi: Analisi, oggi: date) -> None:
    cfg = analisi.config
    _pillola(pdf, "Scenario preliminare", "forse", dimensione=8)
    pdf.ln(7)
    pdf.set_font("Geist", "B", 18)
    pdf.multi_cell(0, 8.5, cfg.nome, align="L", new_x="LMARGIN", new_y="NEXT")
    tipo = "Gruppo di autoconsumatori" if cfg.tipo.value == "gruppo" else "Comunità energetica rinnovabile"
    _paragrafo(pdf, f"{tipo}, {cfg.regione}. Report del {oggi.strftime('%d/%m/%Y')}, cersim {__version__}. "
                    f"{AVVISO_PRELIMINARE}", dimensione=9, colore=TENUE)
    y = pdf.get_y() + 2.5
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.set_y(y + 3)


def _pagina_cifre(pdf, analisi: Analisi, nomi: dict[str, str]) -> None:
    _segmenti(pdf, frase_sintesi(analisi))
    pdf.ln(2)
    testo_q, tono_q, spiegazione_q = QUALITA[analisi.qualita]
    pdf.set_x(pdf.l_margin)
    larghezza = _pillola(pdf, testo_q, tono_q)
    pdf.set_x(pdf.l_margin + larghezza + 2)
    pdf.set_font("Geist", "", 8.5)
    pdf.set_text_color(*_rgb(TENUE))
    pdf.multi_cell(0, 5.2, f"{spiegazione_q[0].upper()}{spiegazione_q[1:]}.", align="L", new_x="LMARGIN", new_y="NEXT")
    _paragrafo(pdf, NOTA_INTERVALLI, dimensione=8.5, colore=TENUE, altezza=4.2)
    if analisi.economia_disabilitata:
        pdf.ln(2)
        _paragrafo(pdf, analisi.economia_disabilitata, dimensione=9, colore=TONI["no"][0])

    _titolo(pdf, "Le cifre")
    righe = [[c.voce, _formatta(c.valore, c.unita),
              "" if c.minimo == c.massimo else f"{_formatta(c.minimo, c.unita)} – {_formatta(c.massimo, c.unita)}",
              c.significato] for c in cifre(analisi, nomi)]
    _tabella(pdf, ["Indicatore", "Valore centrale", "Intervallo degli scenari", "Che cosa significa"], righe,
             (26, 16, 24, 34), ("LEFT", "RIGHT", "RIGHT", "LEFT"), grassetto_prima=True)
    if not analisi.economia_disabilitata:
        _paragrafo(pdf, "Prezzi usati: " + "; ".join(fonti_prezzi(analisi)) + ".", dimensione=7.5, colore=TENUE,
                   altezza=3.8)

        _titolo(pdf, "Conviene costituire la configurazione?")
        _paragrafo(pdf, frase_confronto(analisi), dimensione=10, altezza=5.2)
        pdf.ln(1.5)
        righe = [[voce, euro(0) if banda is None else euro(banda.mediana),
                  "" if banda is None else f"{euro(banda.minimo)} – {euro(banda.massimo)}", descrizione]
                 for voce, banda, descrizione in confronto(analisi)]
        _tabella(pdf, ["Alternativa", "Beneficio netto su 25 anni", "Intervallo degli scenari", "Che cosa comprende"],
                 righe, (26, 16, 24, 34), ("LEFT", "RIGHT", "RIGHT", "LEFT"), grassetto_prima=True)


def _pagina_configurazione(pdf, analisi: Analisi, nomi: dict[str, str]) -> None:
    cfg = analisi.config
    _titolo(pdf, "La configurazione", prima=2)
    tot = anno_rappresentativo(analisi.energia_base).totali()
    impianti = ("1 impianto fotovoltaico nuovo" if len(cfg.plants) == 1
                else f"{len(cfg.plants)} impianti fotovoltaici nuovi")
    _paragrafo(pdf, f"{len(cfg.members)} membri con {len(cfg.connection_points)} contatori, consumo stimato di "
                    f"{kwh(tot['consumo_kwh'])} all'anno; {impianti} che producono "
                    f"{kwh(tot['produzione_kwh'])} all'anno ({_anno_rif(analisi)}).", dimensione=9.5)
    pdf.ln(1.5)
    ip = assunzioni_economiche()
    righe = [[p.nome, f"{p.potenza_moduli_kwp:.1f} kWp / {p.potenza_inverter_kw:.1f} kW".replace(".", ","),
              p.data_entrata_esercizio.strftime("%d/%m/%Y"), nomi.get(p.investitore, p.investitore),
              euro(capex(p, ip)) + (" (preventivo)" if p.costo_preventivo_eur is not None else " (stima)")]
             for p in cfg.plants]
    _tabella(pdf, ["Impianto", "Moduli / inverter", "Entrata in esercizio", "Chi paga", "Costo"], righe,
             (22, 20, 18, 22, 18), ("LEFT", "RIGHT", "RIGHT", "LEFT", "RIGHT"), grassetto_prima=True)

    _titolo(pdf, "Requisiti")
    _paragrafo(pdf, "Controllo sui dati dichiarati, non verifica documentale.", dimensione=8.5, colore=TENUE)
    pdf.ln(1)
    colonna = 36
    for nome, stato, motivo in requisiti(analisi):
        testo, tono = STATO_ETICHETTA[stato]
        _spazio_per(pdf, 10)
        y = pdf.get_y()
        pdf.set_xy(pdf.l_margin, y + 0.6)
        _pillola(pdf, testo, tono)
        pdf.set_xy(pdf.l_margin + colonna, y + 0.8)
        pdf.set_font("Geist", "B", 8.5)
        pdf.multi_cell(0, 4.2, nome, align="L", new_x="LMARGIN", new_y="NEXT")
        if motivo:
            pdf.set_x(pdf.l_margin + colonna)
            pdf.set_font("Geist", "", 8.5)
            pdf.set_text_color(*_rgb(TENUE))
            pdf.multi_cell(0, 4.2, motivo, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*_rgb(TESTO))
        y = pdf.get_y() + 1.5
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.set_y(y + 0.5)
    pdf.ln(2)
    pdf.set_font("Geist", "B", 9)
    pdf.cell(0, 5, "Da verificare con un professionista", new_x="LMARGIN", new_y="NEXT")
    _elenco(pdf, analisi.report.da_verificare)


def _pagina_grafici(pdf, analisi: Analisi, nomi: dict[str, str]) -> None:
    larghezza = (pdf.epw - 6) / 2
    altezza = 62
    _titolo(pdf, "Come si comporta l'energia e il denaro", prima=4, spazio_dopo=altezza * 2 + 8)
    grafici = [_grafico_giorno(analisi), _grafico_mesi(analisi)]
    if not analisi.economia_disabilitata:
        grafici += [_grafico_cassa(analisi, nomi)]
        if analisi.sensibilita:
            grafici += [_grafico_tornado(analisi)]
    y0 = pdf.get_y()
    for i, disegna in enumerate(grafici):
        x = pdf.l_margin + (i % 2) * (larghezza + 6)
        y = y0 + (i // 2) * (altezza + 3)
        pdf.image(_figura(disegna, larghezza, altezza), x=x, y=y, w=larghezza, h=altezza)
    pdf.set_y(y0 + ((len(grafici) + 1) // 2) * (altezza + 3))
    note = [f"Giorno tipo e mesi: anno {_anno_rif(analisi)}, meteo {analisi.energia_base.ref_year}. L'energia condivisa "
            "è quella immessa e consumata nella stessa ora dai membri."]
    if not analisi.economia_disabilitata:
        note.append("Cassa cumulata: sotto lo zero l'investimento non è ancora ripagato.")
        if analisi.sensibilita:
            note.append(f"Sensibilità: ogni barra parte dal beneficio netto dello scenario base, "
                        f"{euro(analisi.base.kpi.van_consolidato)} (meteo {analisi.base.scenario.anno_meteo}, prezzo "
                        "base), e arriva al valore con il parametro basso o alto.")
    _paragrafo(pdf, " ".join(note), dimensione=7.5, colore=TENUE, altezza=3.8)


def _pagina_chi_paga(pdf, analisi: Analisi, nomi: dict[str, str]) -> None:
    _titolo(pdf, "Chi paga e chi riceve")
    _paragrafo(pdf, f"Scenario base, anno {_anno_rif(analisi)}. Elenco completo dei movimenti nel file Excel.",
               dimensione=8.5, colore=TENUE)
    pdf.ln(1)
    righe = [[r["Voce"], r["Chi paga"], r["Chi riceve"], euro(r["€"])]
             for r in _chi_paga_compatto(analisi, nomi).to_dict("records")]
    _tabella(pdf, ["Voce", "Chi paga", "Chi riceve", "Importo"], righe, (30, 26, 26, 14),
             ("LEFT", "LEFT", "LEFT", "RIGHT"), dimensione=8)

    membri = per_membro(analisi, nomi).sort_values("Netto nell'anno €", ascending=False)
    _titolo(pdf, "Per membro, nell'anno", prima=3)
    righe = [[r["Membro"], kwh(r["Energia condivisa kWh"]), euro(r["Quota dei contributi €"]),
              euro(r["Risparmio in bolletta €"]), euro(r["Spese €"]), euro(r["Netto nell'anno €"])]
             for r in membri.head(MAX_RIGHE_MEMBRI_PDF).to_dict("records")]
    _tabella(pdf, ["Membro", "Energia condivisa", "Quota contributi", "Risparmio bolletta", "Spese", "Netto"], righe,
             (28, 16, 14, 14, 14, 14), ("LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"), dimensione=8)
    nota = ("Netto: quota dei contributi, risparmio in bolletta e vendite, meno le spese. Per chi investe comprende "
            "anche l'impianto.")
    if len(membri) > MAX_RIGHE_MEMBRI_PDF:
        nota += f" Mostrati {MAX_RIGHE_MEMBRI_PDF} membri su {len(membri)}: gli altri nel file Excel."
    _paragrafo(pdf, nota, dimensione=7.5, colore=TENUE, altezza=3.8)


def _ipotesi_pdf(pdf, analisi: Analisi, params: ParametriEconomici) -> None:
    if not analisi.economia_disabilitata:
        _titolo(pdf, "Ipotesi ed esclusioni")
        _coppie(pdf, ipotesi(analisi, params) + [("Esclusi dal calcolo", ", ".join(ESCLUSIONI))])


def _pagina_provenienza(pdf, analisi: Analisi) -> None:
    if not analisi.economia_disabilitata:
        _titolo(pdf, "Prezzi dell'energia", prima=3, spazio_dopo=10)
        _elenco(pdf, fonti_prezzi(analisi))

    _titolo(pdf, "Come rendere la stima più precisa", prima=3, spazio_dopo=20)
    _paragrafo(pdf, frase_precisione(analisi), dimensione=8.5, colore=TENUE, altezza=4.2)
    pdf.ln(1)
    _coppie(pdf, [(f"{i}. {m.cosa}", m.perche + (f" Nel simulatore: passo {m.passo}." if m.passo else ""))
                  for i, m in enumerate(dati_da_migliorare(analisi), start=1)], dimensione=8, colonna=62)

    _titolo(pdf, "Versioni e provenienza dei dati", prima=3, spazio_dopo=15)
    m = analisi.energia_base.manifest
    fonti_pv = sorted({v["fonte"] for v in m.get("fonti_pv", {}).values()})
    qualita_consumi = m.get("qualita_consumi", {})
    conteggio = {q: sum(v == q for v in qualita_consumi.values()) for q in "ABC"}
    manifest = [
        ("Anni di progetto", " – ".join(str(a) for a in m.get("anni_progetto", []))),
        ("Produzione FV", "; ".join(fonti_pv) or "non disponibile"),
        FONTE_OMBRE,
        ("Qualità dei consumi", ", ".join(f"{n} contatori {q}" for q, n in conteggio.items() if n)),
        ("Qualità complessiva", analisi.qualita),
        ("Controlli di bilancio", "superati" if m.get("controlli_bilancio") == "ok" else "con anomalie: vedi Excel"),
    ]
    _coppie(pdf, versioni() + manifest)

    _titolo(pdf, "Avvertenze", prima=3, spazio_dopo=10)
    voci = avvertenze_compatte(avvertenze(analisi))
    if len(voci) > MAX_AVVISI_PDF:
        voci = voci[: MAX_AVVISI_PDF - 1] + [f"Altre {len(voci) - MAX_AVVISI_PDF + 1} avvertenze nel file Excel, "
                                             "foglio Riepilogo."]
    _elenco(pdf, [AVVISO_PRELIMINARE] + voci)


def report_pdf(analisi: Analisi, params: ParametriEconomici, *, oggi: date | None = None) -> bytes:
    """Report di 3–4 pagine. Richiede una configurazione supportata."""
    if not analisi.supportata:
        raise ValueError("Configurazione non supportata: nessun report")
    oggi = oggi or date.today()
    nomi = nomi_leggibili(analisi.config)
    pdf = _nuovo_pdf(f"{analisi.config.nome[:70]}. Scenario preliminare, cersim {__version__}")
    pdf.set_title(f"{analisi.config.nome}: scenario preliminare")
    pdf.set_author("cersim")
    pdf.set_creation_date(pd.Timestamp(oggi).to_pydatetime())
    pdf.add_page()
    _intestazione(pdf, analisi, oggi)
    _pagina_cifre(pdf, analisi, nomi)
    pdf.add_page()
    _pagina_configurazione(pdf, analisi, nomi)
    _ipotesi_pdf(pdf, analisi, params)
    _pagina_grafici(pdf, analisi, nomi)
    if not analisi.economia_disabilitata:
        _pagina_chi_paga(pdf, analisi, nomi)
    _pagina_provenienza(pdf, analisi)
    return bytes(pdf.output())


def scheda_famiglia_pdf(configurazione: str | None = None, link: str | None = None) -> bytes:
    """Una pagina da girare o stampare per ogni famiglia o attività: che cosa serve, dove trovarlo, come
    consegnarlo (con il link oppure compilando la tabella a mano)."""
    from cersim.guida import COSA_SERVE, KWH_FAMIGLIA_TIPO, PORTALE_CONSUMI, PRIVACY_SCHEDA

    pdf = _nuovo_pdf(f"Scheda dei consumi{f' per {configurazione[:60]}' if configurazione else ''}. cersim "
                     f"{__version__}")
    pdf.set_title("Scheda dei consumi")
    pdf.set_author("cersim")
    pdf.add_page()
    _pillola(pdf, "Scheda per la simulazione", "forse", dimensione=8)
    pdf.ln(7)
    pdf.set_font("Geist", "B", 17)
    titolo = f"I consumi di luce per {configurazione}" if configurazione else "I consumi di luce di casa o dell'attività"
    pdf.multi_cell(0, 8, titolo, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    _paragrafo(pdf, "Stiamo valutando un impianto fotovoltaico da condividere: un gruppo di autoconsumatori o una "
                    "comunità energetica. Per stimare quanta energia si condivide e quanto vale servono i consumi di "
                    "luce di ogni contatore. Bastano pochi minuti e una bolletta.", dimensione=10, altezza=5.2)

    _titolo(pdf, "Che cosa serve", prima=4, spazio_dopo=20)
    for voce in COSA_SERVE["famiglia"].voci[:2]:
        _coppie(pdf, [(voce.cosa, voce.dove)], dimensione=9, colonna=62)
    _paragrafo(pdf, "Se non trovi nulla, scrivi solo il tipo di utenza: si userà il consumo di una famiglia tipo, "
                    f"{kwh(KWH_FAMIGLIA_TIPO)} all'anno, con risultati meno precisi.",
               dimensione=8.5, colore=TENUE, altezza=4.3)

    _titolo(pdf, "Dove trovarli", prima=4, spazio_dopo=15)
    _elenco(pdf, [PORTALE_CONSUMI, "In bolletta: il consumo annuo è di solito in prima pagina, vicino al grafico "
                  "dei consumi. Il codice POD non serve."], dimensione=9)

    _titolo(pdf, "Come consegnarli", prima=4, spazio_dopo=60)
    if link:
        pdf.set_font("Geist", "B", 9)
        pdf.cell(0, 5, "Online", new_x="LMARGIN", new_y="NEXT")
        _paragrafo(pdf, "Apri questo indirizzo, segui le istruzioni e alla fine manda il file che scarichi a chi "
                        "coordina:", dimensione=9)
        pdf.set_font("Geist", "", 8)
        pdf.set_text_color(*_rgb(ACCENTO))
        pdf.multi_cell(0, 4.2, link, align="L", new_x="LMARGIN", new_y="NEXT", link=link)
        pdf.set_text_color(*_rgb(TESTO))
        pdf.ln(2)
        pdf.set_font("Geist", "B", 9)
        pdf.cell(0, 5, "Su carta", new_x="LMARGIN", new_y="NEXT")
    _paragrafo(pdf, "Compila una riga per ogni contatore e riconsegna il foglio a chi coordina.", dimensione=9)
    pdf.ln(1)
    vuote = [[" \n ", "", "", "", ""] for _ in range(5)]  # righe alte, da scrivere a mano
    _tabella(pdf, ["Nome o interno", "Famiglia o attività", "Consumo annuo kWh", "F1 kWh", "F2+F3 kWh"], vuote,
             (30, 22, 18, 15, 15), ("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"), dimensione=9)
    pdf.ln(1)
    _paragrafo(pdf, PRIVACY_SCHEDA if link else "Come nome puoi usare quello che preferisci, per esempio "
                                                "\"interno 3\".", dimensione=8, colore=TENUE, altezza=4)
    return bytes(pdf.output())


# --- Excel ----------------------------------------------------------------------------
FOGLI = ("Riepilogo", "Per membro", "Flussi di cassa", "Movimenti", "Confronto", "Manifest")


def neutralizza(valore):
    """Testo che Excel o un foglio di calcolo leggerebbe come formula: prefisso ' (resta testo)."""
    if isinstance(valore, str) and valore.startswith(INIZIO_FORMULA):
        return "'" + valore
    if isinstance(valore, np.generic):
        return valore.item()
    return valore


def _riga(ws, valori=(), *, stile: str | None = None, formato: dict[int, str] | None = None) -> None:
    from openpyxl.styles import Font, PatternFill

    ws.append([neutralizza(v) for v in valori])
    riga = ws.max_row
    for i, cella in enumerate(ws[riga], start=1):
        if isinstance(cella.value, str):
            cella.data_type = "s"  # mai una formula, qualunque sia il contenuto
        if formato and i in formato and isinstance(cella.value, (int, float)):
            cella.number_format = formato[i]
        if stile == "intestazione":
            cella.font = Font(bold=True, color=TENUE.lstrip("#"))
            cella.fill = PatternFill("solid", fgColor=PANNELLO.lstrip("#"))
        elif stile == "titolo":
            cella.font = Font(bold=True, size=14, color=TESTO.lstrip("#"))
        elif stile == "sezione":
            cella.font = Font(bold=True, size=11, color=ACCENTO.lstrip("#"))


def _larghezze(ws, larghezze: list[float]) -> None:
    from openpyxl.utils import get_column_letter

    for i, w in enumerate(larghezze, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


EURO = "#,##0 €"
KWH = "#,##0"


def _foglio_riepilogo(ws, analisi: Analisi, params: ParametriEconomici, nomi, oggi: date) -> None:
    cfg = analisi.config
    _riga(ws, [cfg.nome], stile="titolo")
    _riga(ws, [AVVISO_PRELIMINARE])
    _riga(ws, ["Tipo", "Gruppo di autoconsumatori" if cfg.tipo.value == "gruppo" else "Comunità energetica rinnovabile"])
    _riga(ws, ["Regione", cfg.regione])
    _riga(ws, ["Data del report", oggi.strftime("%d/%m/%Y")])
    testo_q, _, spiegazione_q = QUALITA[analisi.qualita]
    _riga(ws, ["Qualità dei dati", f"{testo_q}: {spiegazione_q}"])
    _riga(ws, ["Intervalli", NOTA_INTERVALLI])
    if analisi.economia_disabilitata:
        _riga(ws, ["Contributi", analisi.economia_disabilitata])
    _riga(ws)
    _riga(ws, ["Le cifre"], stile="sezione")
    _riga(ws, ["Indicatore", "Valore centrale", "Minimo degli scenari", "Massimo degli scenari", "Unità",
               "Che cosa significa"], stile="intestazione")
    for c in cifre(analisi, nomi):
        fmt = EURO if c.unita == "€" else KWH
        _riga(ws, [c.voce, round(c.valore), round(c.minimo), round(c.massimo), c.unita, c.significato],
              formato={2: fmt, 3: fmt, 4: fmt})
    _riga(ws)
    _riga(ws, ["Requisiti"], stile="sezione")
    _riga(ws, ["Controllo", "Esito", "Motivo"], stile="intestazione")
    for nome, stato, motivo in requisiti(analisi):
        _riga(ws, [nome, STATO_ETICHETTA[stato][0], motivo])
    for voce in analisi.report.da_verificare:
        _riga(ws, ["Da verificare con un professionista", "Da verificare", voce])
    if not analisi.economia_disabilitata:
        _riga(ws)
        _riga(ws, ["Ipotesi"], stile="sezione")
        for chiave, valore in ipotesi(analisi, params):
            _riga(ws, [chiave, valore])
        _riga(ws, ["Esclusi dal calcolo", ", ".join(ESCLUSIONI)])
        _riga(ws)
        _riga(ws, ["Prezzi usati"], stile="sezione")
        for fonte in fonti_prezzi(analisi):
            _riga(ws, [fonte])
    _riga(ws)
    _riga(ws, ["Avvertenze"], stile="sezione")
    for voce in avvertenze(analisi):
        _riga(ws, [voce])
    _larghezze(ws, [42, 18, 20, 20, 8, 90])


def _foglio_membri(ws, analisi: Analisi, nomi) -> None:
    if analisi.economia_disabilitata:
        _riga(ws, ["Contributi non calcolati: " + analisi.economia_disabilitata])
        return
    df = per_membro(analisi, nomi)
    _riga(ws, [f"Scenario base, anno {_anno_rif(analisi)}; beneficio netto attualizzato su tutta la durata."])
    _riga(ws, list(df.columns), stile="intestazione")
    formati = {i: (KWH if "kWh" in c else EURO) for i, c in enumerate(df.columns, start=1) if c.endswith(("€", "kWh"))}
    for r in df.itertuples(index=False):
        _riga(ws, [round(v, 2) if isinstance(v, float) else v for v in r], formato=formati)
    ws.freeze_panes = "B3"
    _larghezze(ws, [30, 18, 10] + [18] * (len(df.columns) - 3))


def _nomi_colonne(soggetti: list[str], nomi: dict[str, str]) -> list[str]:
    etichette = [nomi.get(s, s) for s in soggetti]
    return [f"{e} [{s}]" if etichette.count(e) > 1 else e for e, s in zip(etichette, soggetti)]


def _ordina_soggetti(analisi: Analisi) -> list[str]:
    led = analisi.base.ledger
    presenti = led.soggetti()
    membri = [m.id for m in analisi.config.members if m.id in presenti]
    return membri + sorted(presenti - set(membri))


def _foglio_flussi(ws, analisi: Analisi, nomi) -> None:
    if analisi.economia_disabilitata:
        _riga(ws, ["Contributi non calcolati: " + analisi.economia_disabilitata])
        return
    led = analisi.base.ledger
    soggetti = _ordina_soggetti(analisi)
    _riga(ws, ["Scenario base: " + analisi.base.scenario.etichetta + ". Entrate meno uscite, euro costanti, "
               "non attualizzati."])
    _riga(ws, ["Anno"] + _nomi_colonne(soggetti, nomi) + ["Configurazione verso l'esterno (consolidato)",
                                                          "Controllo: somma di tutti i soggetti"],
          stile="intestazione")
    flussi = {s: led.flussi_soggetto(s) for s in soggetti}
    consolidato = led.flussi_consolidati()
    formati = {i: EURO for i in range(2, len(soggetti) + 4)}
    for i in range(led.n_anni):
        valori = [round(float(flussi[s][i]), 2) for s in soggetti]
        _riga(ws, [led.anno_inizio + i] + valori + [round(float(consolidato[i]), 2), round(sum(valori), 2)],
              formato=formati)
    _riga(ws, ["Beneficio netto attualizzato"] + [round(led.van(flussi[s]), 2) for s in soggetti]
          + [round(led.van(consolidato), 2), None], stile="intestazione", formato=formati)
    ws.freeze_panes = "B3"
    _larghezze(ws, [26] + [18] * (len(soggetti) + 2))


def _foglio_movimenti(ws, analisi: Analisi, nomi) -> None:
    if analisi.economia_disabilitata:
        _riga(ws, ["Contributi non calcolati: " + analisi.economia_disabilitata])
        return
    _riga(ws, ["Anno", "Voce", "Chi paga (codice)", "Chi paga", "Chi riceve (codice)", "Chi riceve", "Importo €",
               "Base di calcolo"], stile="intestazione")
    for m in analisi.base.ledger.movimenti:
        _riga(ws, [m.anno, m.voce, m.pagatore, nomi.get(m.pagatore, m.pagatore), m.percettore,
                   nomi.get(m.percettore, m.percettore), round(m.importo, 2), m.base], formato={7: "#,##0.00 €"})
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    _larghezze(ws, [8, 32, 18, 26, 18, 26, 14, 52])


def _foglio_confronto(ws, analisi: Analisi) -> None:
    if analisi.economia_disabilitata:
        _riga(ws, ["Contributi non calcolati: " + analisi.economia_disabilitata])
        return
    _riga(ws, [frase_confronto(analisi)])
    _riga(ws)
    _riga(ws, ["Alternativa", "Beneficio netto su 25 anni (mediana)", "Minimo", "Massimo", "Che cosa comprende"],
          stile="intestazione")
    formati = {2: EURO, 3: EURO, 4: EURO}
    for voce, banda, descrizione in confronto(analisi):
        banda = banda or Banda(0.0, 0.0, 0.0)
        _riga(ws, [voce, round(banda.mediana), round(banda.minimo), round(banda.massimo), descrizione], formato=formati)
    aggiunta = analisi.bande["valore_configurazione"]
    _riga(ws, ["Valore aggiunto della configurazione", round(aggiunta.mediana), round(aggiunta.minimo),
               round(aggiunta.massimo), "Differenza scenario per scenario rispetto al solo fotovoltaico"],
          formato=formati)
    _riga(ws)
    _riga(ws, ["Scenari simulati"], stile="sezione")
    _riga(ws, ["Scenario", "Energia condivisa kWh (primo anno intero)", "Contributi GSE € (primo anno intero)",
               "Beneficio netto della configurazione €", "Beneficio netto di chi investe €", "Qualità dei prezzi",
               "Fonte dei prezzi"], stile="intestazione")
    for e in analisi.esiti:
        yr = anno_rappresentativo(e.energia)
        contributi = sum(e.kpi.contributi_primo_anno_intero.get(v, 0.0)
                         for v in ("tariffa premio (TIP)", "valorizzazione ARERA (CACV)"))
        _riga(ws, [e.scenario.etichetta, round(yr.totali()["EACV_kwh"]), round(contributi), round(e.kpi.van_consolidato),
                   round(e.kpi.van_investitore), e.qualita_prezzi, e.fonte_prezzi],
              formato={2: KWH, 3: EURO, 4: EURO, 5: EURO})
    _larghezze(ws, [56, 22, 20, 22, 22, 12, 60])


def _foglio_manifest(ws, analisi: Analisi, params: ParametriEconomici, oggi: date) -> None:
    _riga(ws, ["Voce", "Valore"], stile="intestazione")
    for chiave, valore in versioni():
        _riga(ws, [chiave, valore])
    _riga(ws, ["Data del report", oggi.isoformat()])
    _riga(ws, list(FONTE_OMBRE))
    for chiave, valore in params.__dict__.items():
        _riga(ws, [f"parametro: {chiave}", valore if isinstance(valore, (int, float, str)) or valore is None
                   else str(valore)])
    for chiave, valore in analisi.energia_base.manifest.items():
        if not isinstance(valore, (int, float, str)) or isinstance(valore, bool):
            valore = json.dumps(valore, ensure_ascii=False, default=str)
        _riga(ws, [chiave, valore])
    _larghezze(ws, [36, 120])


def report_excel(analisi: Analisi, params: ParametriEconomici, *, oggi: date | None = None) -> bytes:
    """Cartella di lavoro con i fogli di `FOGLI`. Richiede una configurazione supportata."""
    from openpyxl import Workbook

    if not analisi.supportata:
        raise ValueError("Configurazione non supportata: nessun export")
    oggi = oggi or date.today()
    nomi = nomi_leggibili(analisi.config)
    wb = Workbook()
    fogli = {nome: (wb.active if i == 0 else wb.create_sheet()) for i, nome in enumerate(FOGLI)}
    for nome, ws in fogli.items():
        ws.title = nome
    _foglio_riepilogo(fogli["Riepilogo"], analisi, params, nomi, oggi)
    _foglio_membri(fogli["Per membro"], analisi, nomi)
    _foglio_flussi(fogli["Flussi di cassa"], analisi, nomi)
    _foglio_movimenti(fogli["Movimenti"], analisi, nomi)
    _foglio_confronto(fogli["Confronto"], analisi)
    _foglio_manifest(fogli["Manifest"], analisi, params, oggi)
    wb.properties.creator = "cersim"
    wb.properties.title = f"{analisi.config.nome}: scenario preliminare"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
