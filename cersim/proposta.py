"""Proposta dell'impianto sul tetto: tre taglie commentate invece di un numero da inventare.

Per un condominio c'è un solo tetto; per una comunità energetica si propone un tetto
alla volta, su edifici diversi: ogni proposta tiene conto degli impianti già scelti
(`altri`), che restano fermi, così l'energia condivisa non si conta due volte.

Dal tetto (superficie utile, orientamento, ombre) e dai consumi della tabella del
passo 2 si provano diverse taglie con il dimensionamento (`sizing.dimensiona`)
su tre anni meteo e tre livelli di prezzo, e se ne scelgono tre (`scegli_taglie`):
- **Prudente**: quella che rende di più per ogni euro investito;
- **Consigliata**: il beneficio complessivo più alto tra quelle che convengono sia a
  chi paga sia ai membri; a parità di beneficio, la più piccola;
- **Tutto il tetto** (il massimo stimato), oppure una **Intermedia** se la
  consigliata riempie già il tetto.
Su un tetto a falde rivolte a est e a ovest il massimo comprende tutte e due le
falde, e ogni taglia mette metà dei moduli su ciascuna (`SceltaTetto.azimut_2`).
Per ognuna: costo stimato, beneficio della configurazione e di chi investe con
l'intervallo degli scenari, quanto va ai membri, e fino a quale quota di riparto
chi investe rientra. "Conviene a entrambi" vuol dire: chi paga rientra e i membri
ricevono qualcosa. Nessun numero è certo: con dati di qualità C la proposta è
solo esplorativa.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from cersim.economics import ParametriEconomici
from cersim.model import Configuration
from cersim.normativa import PacchettoScadutoError, pacchetto_normativo, verifica_validita
from cersim.prices import PriceSeries
from cersim.pv import ANNI_METEO, pv_profile
from cersim.scenari import scenari_standard
from cersim.simulate import pv_profiles_for
from cersim.sizing import PuntoCurva, dimensiona
from cersim.ui_model import COLONNE_IMPIANTI, Generale, configurazione_da_tabelle, tipizza_impianti

NOME_IMPIANTO = "FV tetto"
QUASI_UGUALI = 0.95  # taglie entro il 5% del beneficio massimo: equivalenti, data l'incertezza
QUOTA_PROVVISORIA = 0.5  # riparto usato se al passo 4 non è ancora stato scelto
MESI_PER_ESERCIZIO = 4  # dalla costituzione all'entrata in esercizio, se non indicato
# Falde a est e a ovest: il picco orario (PVGIS, Torino 2021–2023) è 0,68–0,74 kW per kWp contro 0,85 a sud, e
# un inverter all'80% dei kWp non taglia energia. Il costo si stima sui kWp dei moduli, quindi l'inverter più piccolo
# non abbassa il costo stimato: cambiano solo la sostituzione dell'inverter e la potenza ai fini GSE.
INVERTER_DUE_FALDE = 0.8


@dataclass(frozen=True)
class SceltaTetto:
    """Che cosa l'utente ha confermato sul tetto e su chi paga."""
    kwp_max: float
    inclinazione: float
    azimut: float
    ombre_pct: float
    punto: str  # contatore a cui si collega l'impianto (etichetta della tabella)
    investitore: str  # membro che paga (nome della tabella)
    entrata: date
    azimut_2: float | None = None  # seconda falda (tetto est-ovest): metà dei moduli per falda, `kwp_max` le comprende
    nome: str = NOME_IMPIANTO  # nome dell'impianto nella tabella (`nome_impianto`)

    @property
    def due_falde(self) -> bool:
        return self.azimut_2 is not None


@dataclass
class Opzione:
    nome: str
    punto: PuntoCurva
    commento: str
    conviene_a_entrambi: bool


@dataclass
class Proposta:
    opzioni: list[Opzione]
    curva: list[PuntoCurva]
    qualita: str
    quota_membri: float
    quota_provvisoria: bool
    quasi_equivalenti: tuple[float, float] | None
    scelta: SceltaTetto
    investitore: str
    n_membri: int
    note: list[str] = field(default_factory=list)

    @property
    def nessuna_conviene(self) -> bool:
        return all(o.punto.van_consolidato_mediano <= 0 for o in self.opzioni)


def entrata_predefinita(data_costituzione: date | None, oggi: date | None = None) -> date:
    """Qualche mese dopo la costituzione (o da oggi), primo giorno del mese."""
    base = max(data_costituzione or date.min, oggi or date.today())
    giorno = base + timedelta(days=30 * MESI_PER_ESERCIZIO)
    return giorno.replace(day=1)


def nome_impianto(tipo: str, punto: str) -> str:
    """Un solo tetto nel condominio; in una comunità energetica uno per edificio, chiamato come il suo contatore."""
    return NOME_IMPIANTO if tipo == "gruppo" else f"FV {punto}"[:80]


def riga_impianto(scelta: SceltaTetto, kwp: float) -> dict:
    """Riga della tabella del passo 3 per la taglia scelta: inverter della stessa potenza dei moduli, o all'80% con
    le due falde, che non producono mai al massimo insieme."""
    kwp = round(kwp, 1)
    inverter = round(kwp * INVERTER_DUE_FALDE, 1) if scelta.due_falde else kwp
    return {"Impianto": scelta.nome, "Punto": scelta.punto, "kWp moduli": kwp, "kW inverter": inverter,
            "kWp max installabili": round(max(scelta.kwp_max, kwp), 1), "Inclinazione °": scelta.inclinazione,
            "Orientamento °": scelta.azimut, "Seconda falda °": scelta.azimut_2, "Ombre %": scelta.ombre_pct or None,
            "Entrata in esercizio": pd.Timestamp(scelta.entrata), "Investitore": scelta.investitore}


def tabella_impianto(scelta: SceltaTetto, kwp: float, altri: pd.DataFrame | None = None) -> pd.DataFrame:
    """La tabella degli impianti con la taglia scelta. Gli `altri` impianti restano, tranne quello con lo stesso nome
    o sullo stesso contatore, che viene sostituito: al massimo un impianto per contatore."""
    nuova = pd.DataFrame([riga_impianto(scelta, kwp)], columns=COLONNE_IMPIANTI)
    if altri is None or altri.empty:
        return tipizza_impianti(nuova)
    tenuti = altri[(altri["Impianto"] != scelta.nome) & (altri["Punto"] != scelta.punto)].dropna(how="all")
    return tipizza_impianti(pd.concat([tipizza_impianti(tenuti), nuova], ignore_index=True))


def _euro(x: float) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def _kwp(x: float) -> str:
    return f"{x:.1f} kWp".replace(".", ",")


def _conviene_a_entrambi(p: PuntoCurva) -> bool:
    return p.van_consolidato_mediano > 0 and p.van_investitore_mediano >= 0 and p.euro_anno_membri > 0


def _rendimento(p: PuntoCurva) -> float:
    return p.van_consolidato_mediano / p.costo_eur if p.costo_eur > 0 else 0.0


def scegli_taglie(curva: list[PuntoCurva]) -> list[tuple[str, PuntoCurva]]:
    """Le tre taglie da proporre, dalla più piccola alla più grande.

    - Consigliata: il beneficio complessivo più alto tra le taglie che convengono sia a chi paga sia ai membri
      (se nessuna, tra tutte); a parità di beneficio (entro il 5%) la più piccola, che rischia meno.
    - Prudente: tra le taglie più piccole, quella che rende di più per ogni euro investito.
    - Tutto il tetto, se la consigliata non lo riempie già; altrimenti una taglia intermedia."""
    curva = sorted(curva, key=lambda p: p.potenza_moduli_kwp)
    candidate = [p for p in curva if _conviene_a_entrambi(p)] or curva
    massimo = max(p.van_consolidato_mediano for p in candidate)
    soglia = QUASI_UGUALI * massimo if massimo > 0 else massimo
    consigliata = next(p for p in candidate if p.van_consolidato_mediano >= soglia)

    piu_piccole = [p for p in curva if p.potenza_moduli_kwp < consigliata.potenza_moduli_kwp * 0.85]
    prudente = None
    if piu_piccole:
        prudente = max(piu_piccole, key=_rendimento) if massimo > 0 else piu_piccole[0]
    taglie = [("Prudente", prudente)] if prudente else []
    taglie.append(("Consigliata", consigliata))

    ultima = curva[-1]
    if ultima.potenza_moduli_kwp > consigliata.potenza_moduli_kwp * 1.1:
        taglie.append(("Tutto il tetto", ultima))
    elif prudente is not None:
        meta = (prudente.potenza_moduli_kwp + consigliata.potenza_moduli_kwp) / 2
        intermedie = [p for p in curva if prudente.potenza_moduli_kwp < p.potenza_moduli_kwp
                      < consigliata.potenza_moduli_kwp]
        if intermedie:
            taglie.insert(1, ("Intermedia", min(intermedie, key=lambda p: abs(p.potenza_moduli_kwp - meta))))
    return taglie


def _intervallo(minimo: float, massimo: float) -> str:
    return f"tra {_euro(minimo)} e {_euro(massimo)}"


def _commento(nome: str, p: PuntoCurva, consigliata: PuntoCurva, quasi: list[float], investitore: str,
              quota: float, n_membri: int) -> str:
    """Il commento sotto la taglia. Costo, beneficio e quota annua ai membri sono già nella scheda: qui solo perché
    la si propone, chi paga e quanto si può dare ai membri."""
    parti = []
    condivisa = f"Il {p.quota_condivisa_su_immessa:.0%} dell'energia immessa è condivisa"
    if nome == "Consigliata":
        if p.van_consolidato_mediano > 0:
            parti.append("Il beneficio più alto negli scenari simulati, e conviene sia a chi paga sia ai membri.")
            if len(quasi) > 1 and max(quasi) - min(quasi) >= 1:
                parti.append(f"Tra {_kwp(min(quasi))} e {_kwp(max(quasi))} il risultato è quasi uguale: si propone "
                             "la più piccola, che costa e rischia meno.")
        else:
            parti.append("In nessuna taglia il beneficio è positivo negli scenari simulati: questa è quella che perde "
                         "meno. Non investire vale 0 €.")
    elif nome == "Prudente":
        rapporto = (p.van_consolidato_mediano / consigliata.van_consolidato_mediano
                    if consigliata.van_consolidato_mediano > 0 else None)
        parti.append(f"Rende di più per ogni euro investito: costa {_euro(consigliata.costo_eur - p.costo_eur)} meno "
                     "della consigliata" + (f" e dà circa il {rapporto:.0%} del suo beneficio." if rapporto and rapporto > 0
                                            else "."))
        parti.append(f"{condivisa}: dipende poco dal prezzo di vendita.")
    elif nome == "Intermedia":
        parti.append(f"A metà strada tra la prudente e la consigliata. {condivisa}.")
    else:
        parti.append(f"Usa tutto il tetto stimato, con {_euro(p.costo_eur - consigliata.costo_eur)} in più della "
                     f"consigliata. {condivisa}: il resto si vende, quindi conta di più il prezzo dell'energia.")

    if p.van_investitore_mediano >= 0:
        rientro = f"in circa {p.payback_investitore} anni" if p.payback_investitore is not None else "nel tempo"
        parti.append(f"{investitore} rientra della spesa {rientro} (beneficio netto "
                     f"{_intervallo(p.van_investitore_min, p.van_investitore_max)}).")
    elif p.quota_pareggio is not None and p.quota_pareggio > 0:
        parti.append(f"Dando il {quota:.0%} dei contributi ai membri, {investitore} non rientra della spesa: rientra se "
                     f"ai membri va al massimo il {p.quota_pareggio:.0%}.")
    else:
        parti.append(f"{investitore} non rientra della spesa neanche tenendo tutti i contributi.")
    if p.euro_anno_membri > 0 and n_membri:
        parti.append(f"Ai membri circa {_euro(p.euro_anno_membri / n_membri)} a testa all'anno, in media.")
    else:
        parti.append("Ai membri non va nulla: con questo riparto non hanno un vantaggio diretto.")
    if p.van_investitore_mediano >= 0 and p.quota_pareggio is not None and quota < p.quota_pareggio < 1:
        parti.append(f"Ai membri si può dare fino al {p.quota_pareggio:.0%} dei contributi senza che {investitore} "
                     "vada in perdita in nessuno scenario.")
    return " ".join(parti)


def proponi(
    generale: Generale,
    punti: pd.DataFrame,
    scelta: SceltaTetto,
    params: ParametriEconomici,
    prezzi: dict[int, PriceSeries] | None = None,
    *,
    quota_provvisoria: bool = False,
    altri: pd.DataFrame | None = None,
    curve: dict | None = None,
    fetch_pv=pv_profile,
    n_punti: int = 7,
    n_anni: int | None = None,
    oggi: date | None = None,
) -> Proposta:
    """Tre taglie commentate per l'impianto sul tetto. Solleva ValueError con un messaggio leggibile se i dati
    non bastano (tabella dei consumi incompleta, pacchetto normativo scaduto)."""
    try:
        verifica_validita(pacchetto_normativo(), oggi)
    except PacchettoScadutoError as e:
        raise ValueError(str(e)) from None
    if scelta.kwp_max < 1:
        raise ValueError("Il tetto è troppo piccolo: servono almeno 1 kWp installabili")
    esito = configurazione_da_tabelle(generale, punti, tabella_impianto(scelta, scelta.kwp_max, altri), curve=curve)
    if esito.config is None:
        raise ValueError("Prima completa i dati: " + "; ".join(esito.errori))
    config: Configuration = esito.config
    prezzi = prezzi or {}
    pv = {anno: pv_profiles_for(config, anno, fetch=fetch_pv) for anno in ANNI_METEO}
    recenti = tuple(sorted(a for a in prezzi if a not in ANNI_METEO))
    scenari = scenari_standard(anni_prezzi_recenti=recenti)  # con i tre livelli di prezzo: è il rischio principale
    plant = next(p for p in config.plants if p.nome == scelta.nome)
    dim = dimensiona(config, plant.id, params, pv, prezzi, scenari, n_punti=n_punti, n_anni=n_anni, oggi=oggi)
    if not dim.curva:
        raise ValueError("Nessuna taglia è supportata con questi dati")

    nomi = {m.id: m.nome for m in config.members}
    investitore = nomi.get(plant.investitore, plant.investitore)
    n_membri = sum(m.id != plant.investitore for m in config.members)
    taglie = scegli_taglie(dim.curva)
    consigliata = next(p for nome, p in taglie if nome == "Consigliata")
    massimo = max(p.van_consolidato_mediano for p in dim.curva)
    quasi = [p.potenza_moduli_kwp for p in dim.curva if massimo > 0 and p.van_consolidato_mediano >= QUASI_UGUALI * massimo]
    opzioni = [Opzione(nome, p, _commento(nome, p, consigliata, quasi, investitore, params.quota_membri, n_membri),
                       _conviene_a_entrambi(p)) for nome, p in taglie]

    note = list(dim.note)
    if len(config.plants) > 1:
        note.append(f"La proposta tiene conto degli altri {len(config.plants) - 1} impianti già nella tabella, che "
                    "restano come sono: l'energia condivisa non si conta due volte.")
    if scelta.due_falde:
        note.append("Moduli su tutte e due le falde (est e ovest), metà per falda, con un solo inverter: ogni taglia "
                    "produce un po' meno che su una falda a sud, ma più al mattino e alla sera, quando ci sono più "
                    "consumi da condividere.")
        kwp = consigliata.potenza_moduli_kwp
        note.append(f"Le due falde non producono mai al massimo insieme: basta un inverter di circa l'"
                    f"{INVERTER_DUE_FALDE:.0%} della potenza dei moduli (per {_kwp(kwp)} circa "
                    f"{kwp * INVERTER_DUE_FALDE:.0f} kW), da confermare con l'installatore. La simulazione usa "
                    "questo inverter; il costo resta stimato sui kWp dei moduli.")
    if dim.qualita == "C":
        note.append("Dati di qualità C (consumi tipici o produzione stimata senza PVGIS): la proposta è esplorativa, "
                    "da rifare con le bollette vere.")
    if quota_provvisoria:
        note.append(f"Riparto provvisorio: il {params.quota_membri:.0%} dei contributi ai membri. Si sceglie al passo 4.")
    termine = pacchetto_normativo().tip.termine_accesso_entrata_esercizio
    if scelta.entrata > termine:
        note.append(f"Con l'entrata in esercizio dopo il {termine:%d/%m/%Y} la tariffa premio non spetta: i benefici "
                    "sono molto più bassi.")
    return Proposta(opzioni=opzioni, curva=dim.curva, qualita=dim.qualita, quota_membri=params.quota_membri,
                    quota_provvisoria=quota_provvisoria,
                    quasi_equivalenti=(min(quasi), max(quasi)) if len(quasi) > 1 else None, scelta=scelta,
                    investitore=investitore, n_membri=n_membri, note=note)
