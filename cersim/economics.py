"""Chi paga e chi riceve: ledger dei flussi, VAN per soggetto e consolidato, TIR, payback.

Ogni flusso è un `Movimento(anno, voce, pagatore, percettore, importo, base)`.
Soggetti esterni: GSE, mercato, fornitori, bolletta evitata, terzo investitore.
Soggetti interni: i membri e la `configurazione` (CER o gruppo, tramite il referente).

- La configurazione riceve TIP e CACV dal GSE, paga corrispettivi GSE e costi di
  gestione, e ripartisce il netto: `quota_membri` ai membri (pro-quota sui loro
  prelievi nelle ore di condivisione), il resto all'investitore. Un netto
  negativo è coperto dall'investitore (ipotesi).
- Il produttore incassa la vendita dell'energia; il titolare del punto il
  risparmio in bolletta; l'investitore sostiene CAPEX, O&M, assicurazione,
  inverter e smaltimento e riceve l'eventuale contributo in capitale alle date
  dello scadenzario (senza scadenzario il contributo resta fuori dal VAN).
- VAN consolidato: solo i flussi tra interni ed esterni (i trasferimenti interni
  si annullano), quindi non dipende dalla quota di riparto.
Valori reali (euro costanti) e pre-imposte: IVA, imposte sui contributi e
detrazioni sono escluse.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from cersim.eligibility import EligibilityReport, Stato
from cersim.incentives import ContributiAnno, Regime, contributi_anno
from cersim.model import BOLLETTA, CONFIGURAZIONE, FORNITORI, GSE, MERCATO, TERZO, Configuration, Plant
from cersim.normativa import AssunzioniEconomiche, assunzioni_economiche, classificazione_soggetti, pacchetto_normativo
from cersim.simulate import ProjectResult, maschere_impianto
from cersim.timebase import year_index

ESTERNI = frozenset({GSE, MERCATO, FORNITORI, BOLLETTA, TERZO})

ESCLUSIONI = (
    "IVA",
    "imposte dirette sui contributi e sui ricavi",
    "detrazioni fiscali e altri incentivi non indicati",
    "finanziamento (interessi) dell'investimento",
)


@dataclass(frozen=True)
class Movimento:
    anno: int
    voce: str
    pagatore: str
    percettore: str
    importo: float
    base: str


@dataclass(frozen=True)
class ParametriEconomici:
    """Scelte dello scenario. `quota_membri` è obbligatoria: non esiste un riparto "consigliato"."""

    quota_membri: float
    costo_evitabile_eur_kwh: float | None = None
    tasso_sconto: float | None = None
    regime_vendita: Regime = "RID"
    fattore_capex: float = 1.0
    fattore_condivisa: float = 1.0  # sensibilità: scala TIP e CACV
    fattore_cacv_futuro: float = 1.0  # sensibilità: CACV negli anni oltre l'ultimo valore noto
    ritardo_incasso_contributo_anni: int = 0
    # False = stesso impianto senza gruppo né CER: niente TIP, CACV, contributo in capitale, corrispettivi GSE
    # e costi della configurazione; restano autoconsumo fisico e vendita (per il confronto).
    con_configurazione: bool = True
    # costi da preventivo (None = valore delle assunzioni economiche)
    om_assicurazione_quota_anno: float | None = None  # quota del costo dell'impianto all'anno
    gestione_eur_anno: float | None = None
    costituzione_eur: float | None = None

    def __post_init__(self):
        if not 0 <= self.quota_membri <= 1:
            raise ValueError("quota_membri deve essere tra 0 e 1")
        if self.tasso_sconto is not None and self.tasso_sconto <= -1:
            raise ValueError("tasso_sconto deve essere maggiore di -1")
        if self.costo_evitabile_eur_kwh is not None and self.costo_evitabile_eur_kwh < 0:
            raise ValueError("costo_evitabile_eur_kwh non può essere negativo")
        if self.regime_vendita not in ("RID", "mercato"):
            raise ValueError("regime_vendita sconosciuto")
        for nome in ("om_assicurazione_quota_anno", "gestione_eur_anno", "costituzione_eur"):
            valore = getattr(self, nome)
            if valore is not None and valore < 0:
                raise ValueError(f"{nome} non può essere negativo")


@dataclass
class Ledger:
    movimenti: list[Movimento]
    anno_inizio: int
    n_anni: int
    tasso_sconto: float
    interni: frozenset[str]
    contributi: list[ContributiAnno]
    contributi_esclusi: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)

    def _vettore(self, filtro) -> np.ndarray:
        flussi = np.zeros(self.n_anni)
        for m in self.movimenti:
            segno = filtro(m)
            if segno:
                flussi[m.anno - self.anno_inizio] += segno * m.importo
        return flussi

    def flussi_soggetto(self, soggetto: str) -> np.ndarray:
        """Flusso netto annuo del soggetto (entrate − uscite)."""
        return self._per_soggetto().get(soggetto, np.zeros(self.n_anni)).copy()

    def _per_soggetto(self) -> dict[str, np.ndarray]:
        """I flussi di tutti i soggetti in un solo passaggio sui movimenti, come `_vettore` per ciascuno (stesse somme
        nello stesso ordine), tenuti finché i movimenti non cambiano: con molti membri `kpi` li chiede uno per uno."""
        cache = self.__dict__.get("_cache_soggetti")
        if cache is not None and cache[0] is self.movimenti and cache[1] == len(self.movimenti):
            return cache[2]
        out: dict[str, np.ndarray] = {}
        for m in self.movimenti:
            if m.percettore == m.pagatore:
                continue
            i = m.anno - self.anno_inizio
            out.setdefault(m.percettore, np.zeros(self.n_anni))[i] += m.importo
            out.setdefault(m.pagatore, np.zeros(self.n_anni))[i] += -1 * m.importo
        self.__dict__["_cache_soggetti"] = (self.movimenti, len(self.movimenti), out)
        return out

    def flussi_consolidati(self) -> np.ndarray:
        """Flusso netto della configurazione verso l'esterno (trasferimenti interni eliminati)."""
        return self._vettore(lambda m: (m.percettore in self.interni) - (m.pagatore in self.interni))

    def van(self, flussi: np.ndarray) -> float:
        anni = np.arange(len(flussi))
        return float((flussi / (1 + self.tasso_sconto) ** anni).sum())

    def totali_per_voce(self, anno: int) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for m in self.movimenti:
            if m.anno == anno:
                out[m.voce] += m.importo
        return dict(out)

    def soggetti(self) -> set[str]:
        return {m.pagatore for m in self.movimenti} | {m.percettore for m in self.movimenti}


def tir(flussi: np.ndarray) -> float | None:
    """TIR solo se il flusso ha esattamente un cambio di segno, altrimenti None (non definito)."""
    segni = np.sign(flussi[np.abs(flussi) > 1e-9])
    if len(segni) < 2 or int((np.diff(segni) != 0).sum()) != 1:
        return None
    anni = np.arange(len(flussi))

    def van(r):
        return float((flussi / (1 + r) ** anni).sum())

    basso, alto = -0.99, 1.0
    while van(alto) * van(basso) > 0 and alto < 1e3:
        alto *= 2
    if van(alto) * van(basso) > 0:
        return None
    for _ in range(200):
        medio = (basso + alto) / 2
        if van(basso) * van(medio) <= 0:
            alto = medio
        else:
            basso = medio
    return (basso + alto) / 2


def payback(flussi: np.ndarray, tasso: float = 0.0) -> int | None:
    """Anni (contando l'anno 0) dopo i quali il cumulato, eventualmente attualizzato, torna ≥ 0."""
    attualizzati = flussi / (1 + tasso) ** np.arange(len(flussi))
    cumulato = np.cumsum(attualizzati)
    if cumulato[0] >= 0:
        return 0
    positivi = np.nonzero(cumulato >= 0)[0]
    return int(positivi[0]) if len(positivi) else None


def _potenza_capex(plant: Plant, ipotesi: AssunzioniEconomiche) -> float:
    base = ipotesi.capex.base_potenza
    if base == "DC":
        return plant.potenza_moduli_kwp
    if base == "AC":
        return plant.potenza_inverter_kw
    return plant.potenza_nominale_gse


def capex(plant: Plant, ipotesi: AssunzioniEconomiche, fattore: float = 1.0) -> float:
    """Costo dell'impianto: dal preventivo se indicato, altrimenti dalla tabella delle assunzioni economiche."""
    if plant.costo_preventivo_eur is not None:
        return plant.costo_preventivo_eur * fattore
    return ipotesi.capex_totale(_potenza_capex(plant, ipotesi)) * fattore


def costruisci_ledger(
    config: Configuration,
    report: EligibilityReport,
    energia: ProjectResult,
    prezzi_per_anno: list[np.ndarray] | None,
    params: ParametriEconomici,
    *,
    contributi: list[ContributiAnno] | None = None,
    oggi: date | None = None,
) -> Ledger:
    """Ledger dello scenario. I contributi annui si passano già calcolati (`contributi`)
    quando gli anni orari sono stati compattati; altrimenti si calcolano dai prezzi."""
    ipotesi = assunzioni_economiche()
    norma = pacchetto_normativo()
    tasso = ipotesi.finanza.tasso_sconto_reale if params.tasso_sconto is None else params.tasso_sconto
    anno_inizio = energia.anni[0].year
    n_anni = len(energia.anni)
    anno_fine = anno_inizio + n_anni - 1
    if contributi is None:
        if prezzi_per_anno is None or len(prezzi_per_anno) != n_anni:
            raise ValueError("Serve una serie di prezzi per ogni anno simulato")
        contributi = [
            contributi_anno(config, report, yr, pz, regime_vendita=params.regime_vendita,
                            costo_evitabile_eur_kwh=params.costo_evitabile_eur_kwh, oggi=oggi)
            for yr, pz in zip(energia.anni, prezzi_per_anno)
        ]
    elif len(contributi) != n_anni:
        raise ValueError("Servono i contributi di ogni anno simulato")
    ultimo_cacv_noto = max(norma.cacv.trase_eur_mwh)
    tipo = config.tipo.value
    costi_cfg = (ipotesi.configurazione.costituzione_eur[tipo] if params.costituzione_eur is None else params.costituzione_eur,
                 ipotesi.configurazione.gestione_eur_anno[tipo] if params.gestione_eur_anno is None else params.gestione_eur_anno)
    mov: list[Movimento] = []
    esclusi: list[str] = []
    avvisi: list[str] = []

    def aggiungi(anno, voce, pagatore, percettore, importo, base):
        if importo < 0:  # es. vendita annua negativa con prezzi negativi: il flusso va nel verso opposto
            pagatore, percettore, importo = percettore, pagatore, -importo
        if importo > 1e-9 and anno_inizio <= anno <= anno_fine:
            mov.append(Movimento(anno, voce, pagatore, percettore, float(importo), base))

    # --- costi e contributi in capitale per impianto ---------------------------------------
    imp = ipotesi.impianto
    quota_om = (imp.om_quota_capex_anno + imp.assicurazione_quota_capex_anno
                if params.om_assicurazione_quota_anno is None else params.om_assicurazione_quota_anno)
    for p in config.plants:
        costo = capex(p, ipotesi, params.fattore_capex)
        entrata = p.data_entrata_esercizio.year
        aggiungi(entrata, "CAPEX impianto", p.investitore, FORNITORI, costo,
                 "preventivo" if p.costo_preventivo_eur is not None else "assunzioni_economiche.capex")
        aggiungi(entrata + imp.anno_sostituzione_inverter, "sostituzione inverter", p.investitore, FORNITORI,
                 imp.sostituzione_inverter_eur_per_kw_ac * p.potenza_inverter_kw, "assunzioni_economiche.impianto")
        aggiungi(entrata + imp.vita_utile_anni - 1, "smaltimento", p.investitore, FORNITORI,
                 imp.smaltimento_eur_per_kwp * p.potenza_moduli_kwp, "assunzioni_economiche.impianto")
        for yr in energia.anni:
            frazione = float(maschere_impianto(p, year_index(yr.year)).esercizio.mean())
            aggiungi(yr.year, "manutenzione e assicurazione", p.investitore, FORNITORI,
                     costo * quota_om * frazione,
                     "assunzioni_economiche.impianto")

        grant = p.contributo_capitale
        if grant is not None and not params.con_configurazione:
            esclusi.append(f"{p.id}: contributo in capitale escluso (spetta solo con la configurazione)")
        elif grant is not None:
            esito = report.impianti[p.id].contributo_capitale
            if esito is not None and esito.stato is Stato.NON_AMMESSO:
                esclusi.append(f"{p.id}: contributo in capitale non ammesso ({esito.motivo})")
            elif not grant.scadenzario_incassi:
                esclusi.append(f"{p.id}: contributo in capitale di {grant.importo_eur:,.0f} € escluso dal VAN "
                               "(data di incasso non nota)")
            else:
                for incasso in grant.scadenzario_incassi:
                    aggiungi(incasso.data.year + params.ritardo_incasso_contributo_anni, "contributo in capitale", GSE,
                             p.investitore, incasso.importo_eur, f"atto {grant.estremi_atto}")

    if params.con_configurazione:
        aggiungi(anno_inizio, "costituzione configurazione", CONFIGURAZIONE, FORNITORI, costi_cfg[0],
                 "assunzioni_economiche.configurazione")

    # --- flussi annuali ---------------------------------------------------------------
    for yr, c in zip(energia.anni, contributi):
        if params.con_configurazione:
            _flussi_configurazione(aggiungi, config, yr.year, c, params, costi_cfg, anno_inizio, ultimo_cacv_noto)

        for p in config.plants:
            aggiungi(yr.year, "vendita energia", GSE if params.regime_vendita == "RID" else MERCATO,
                     p.produttore_effettivo, c.vendita_per_impianto[p.id], params.regime_vendita)
        for cp in config.connection_points:
            aggiungi(yr.year, "risparmio in bolletta", BOLLETTA, cp.titolare, c.risparmio_per_punto[cp.id],
                     "autoconsumo fisico × costo evitabile")
        avvisi += c.avvisi

    if params.con_configurazione:
        avvisi += _verifica_eccedenza(config, contributi, mov)
    interni = frozenset({m.id for m in config.members} | {CONFIGURAZIONE})
    return Ledger(mov, anno_inizio, n_anni, tasso, interni, list(contributi), esclusi, sorted(set(avvisi)))


def _flussi_configurazione(aggiungi, config, anno, c: ContributiAnno, params, costi_cfg, anno_inizio, ultimo_cacv_noto):
    """Contributi GSE dell'anno, costi della configurazione (costituzione, gestione annua) e riparto del netto."""
    fattore_cacv = params.fattore_cacv_futuro if anno > ultimo_cacv_noto else 1.0
    tip = c.tip * params.fattore_condivisa
    cacv = c.cacv * params.fattore_condivisa * fattore_cacv
    corrispettivi = sum(c.corrispettivi_gse_per_impianto.values())
    costituzione_eur, gestione = costi_cfg

    aggiungi(anno, "tariffa premio (TIP)", GSE, CONFIGURAZIONE, tip, "DM 414/2023 All. 1; RO 2.2.2.1.2")
    aggiungi(anno, "valorizzazione ARERA (CACV)", GSE, CONFIGURAZIONE, cacv, "TIAD; RO 2.2.2.2.2")
    aggiungi(anno, "corrispettivi GSE", CONFIGURAZIONE, GSE, corrispettivi, "DM 106/2024")
    aggiungi(anno, "gestione configurazione", CONFIGURAZIONE, FORNITORI, gestione, "assunzioni_economiche.configurazione")

    costituzione = costituzione_eur if anno == anno_inizio else 0.0
    netto = tip + cacv - corrispettivi - gestione - costituzione
    quote_inv = _quote_investitori(config, c)
    if netto >= 0:
        _riparto(aggiungi, anno, config, c, netto, params.quota_membri, quote_inv)
    else:
        for investitore, quota in quote_inv.items():
            aggiungi(anno, "copertura disavanzo configurazione", investitore, CONFIGURAZIONE, -netto * quota,
                     "ipotesi: disavanzo coperto dagli investitori")


def _quote_investitori(config: Configuration, c: ContributiAnno) -> dict[str, float]:
    """Peso di ogni investitore nella quota non ripartita ai membri: pro-quota sulla TIP dei suoi impianti."""
    pesi: dict[str, float] = defaultdict(float)
    for p in config.plants:
        pesi[p.investitore] += c.tip_per_impianto.get(p.id, 0.0)
    totale = sum(pesi.values())
    if totale <= 0:  # nessuna TIP (es. a fine ventennio): in parti uguali per impianto
        pesi = defaultdict(float)
        for p in config.plants:
            pesi[p.investitore] += 1.0
        totale = sum(pesi.values()) or 1.0
    return {k: v / totale for k, v in pesi.items()}


def _riparto(aggiungi, anno, config, c: ContributiAnno, netto, quota_membri, quote_investitori):
    ai_membri = netto * quota_membri
    per_titolare: dict[str, float] = defaultdict(float)
    for cp in config.connection_points:
        per_titolare[cp.titolare] += c.eacv_per_punto_kwh[cp.id]
    totale = sum(per_titolare.values())
    if totale > 0:
        for titolare, kwh in per_titolare.items():
            aggiungi(anno, "riparto ai membri", CONFIGURAZIONE, titolare, ai_membri * kwh / totale,
                     "scenario di riparto: pro-quota prelievi nelle ore di condivisione")
    else:
        ai_membri = 0.0
    for investitore, quota in quote_investitori.items():
        aggiungi(anno, "quota all'investitore", CONFIGURAZIONE, investitore, (netto - ai_membri) * quota,
                 "scenario di riparto")


def _verifica_eccedenza(config, contributi: list[ContributiAnno], mov: list[Movimento]) -> list[str]:
    """La quota eccedentaria della TIP deve andare a non-imprese o a finalità sociali (DM art. 3 c. 2 g)."""
    soggetti = classificazione_soggetti().soggetti
    flag = {m.id: soggetti[m.tipo_soggetto.value].impresa_ai_fini_eccedenza for m in config.members}
    avvisi = []
    for c in contributi:
        dovuto = c.importo_eccedentario
        if dovuto <= 0:
            continue
        ai_non_imprese = sum(m.importo for m in mov if m.anno == c.anno and m.voce == "riparto ai membri"
                             and flag.get(m.percettore) == "no")
        if ai_non_imprese + 1e-6 < dovuto:
            avvisi.append(f"{c.anno}: quota eccedentaria della TIP di {dovuto:,.0f} € da destinare a non-imprese o "
                          f"fini sociali; assegnati {ai_non_imprese:,.0f} €")
        if any(v == "sconosciuto" for v in flag.values()):
            avvisi.append("Per alcuni membri non è noto se siano imprese ai fini della quota eccedentaria")
    return avvisi


@dataclass
class Kpi:
    investitore: str
    van_investitore: float
    van_consolidato: float
    tir_investitore: float | None
    payback_investitore: int | None
    payback_attualizzato_investitore: int | None
    van_per_investitore: dict[str, float]
    contributi_primo_anno_intero: dict[str, float]
    euro_anno_per_membro: dict[str, float]


def kpi(config: Configuration, ledger: Ledger) -> Kpi:
    """KPI dello scenario. Con più investitori, i KPI singoli si riferiscono al primo impianto."""
    investitore = config.plants[0].investitore if config.plants else TERZO
    flussi_inv = ledger.flussi_soggetto(investitore)
    anno_rif = ledger.anno_inizio + (1 if ledger.n_anni > 1 else 0)  # primo anno intero
    per_membro = {m.id: float(ledger.flussi_soggetto(m.id)[anno_rif - ledger.anno_inizio]) for m in config.members}
    return Kpi(
        investitore=investitore,
        van_per_investitore={i: ledger.van(ledger.flussi_soggetto(i)) for i in {p.investitore for p in config.plants}},
        van_investitore=ledger.van(flussi_inv),
        van_consolidato=ledger.van(ledger.flussi_consolidati()),
        tir_investitore=tir(flussi_inv),
        payback_investitore=payback(flussi_inv),
        payback_attualizzato_investitore=payback(flussi_inv, ledger.tasso_sconto),
        contributi_primo_anno_intero=ledger.totali_per_voce(anno_rif),
        euro_anno_per_membro=per_membro,
    )
