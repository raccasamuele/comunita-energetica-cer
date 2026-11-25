"""Banda di scenari, sensibilità e qualità complessiva dei risultati.

Uno scenario = anno meteo (PVGIS 2021–2023) + anno dei prezzi + livello medio
dei prezzi (basso/base/alto) + variante dei profili di consumo (tipici, più di
giorno, più la sera: le ultime due solo sul meteo 2023).
- Di regola l'anno dei prezzi coincide con l'anno meteo (correlazione sole–prezzi).
- Lo scenario "prezzi recenti" abbina i prezzi di un anno più nuovo (2024, 2025…)
  al meteo 2023: si perde la correlazione di quell'anno, ma la forma dei prezzi
  è più attuale. I prezzi si aggiornano una volta l'anno.
Il risultato è una BANDA (minimo – mediana – massimo degli scenari simulati),
non una distribuzione di probabilità.
"""

from dataclasses import dataclass, replace
from datetime import date

import numpy as np

from cersim.economics import Kpi, Ledger, ParametriEconomici, costruisci_ledger, kpi
from cersim.eligibility import EligibilityReport
from cersim.geo import zona_mercato
from cersim.incentives import contributi_anno
from cersim.loads import nome_variante, qualita_insieme
from cersim.model import Configuration
from cersim.normativa import assunzioni_economiche
from cersim.prices import PriceSeries, prezzo_costante
from cersim.pv import PVProfile
from cersim.simulate import ProjectResult, simulate_project

ANNO_METEO_PREZZI_RECENTI = 2023


@dataclass(frozen=True)
class Scenario:
    anno_meteo: int
    anno_prezzi: int
    livello: str  # "basso" | "base" | "alto"
    variante: int = 0

    @property
    def etichetta(self) -> str:
        prezzi = "stesso anno" if self.anno_prezzi == self.anno_meteo else f"prezzi {self.anno_prezzi}"
        return f"meteo {self.anno_meteo}, {prezzi}, livello {self.livello}, {nome_variante(self.variante)}"


def scenari_standard(
    anni_meteo=(2021, 2022, 2023),
    anni_prezzi_recenti=(),
    livelli=("basso", "base", "alto"),
    varianti=(0,),
    varianti_anno_base=(),
) -> list[Scenario]:
    """`varianti_anno_base`: varianti dei consumi simulate solo sull'anno meteo 2023, per non moltiplicare i tempi."""
    scenari = [Scenario(m, m, liv, v) for m in anni_meteo for liv in livelli for v in varianti]
    scenari += [Scenario(ANNO_METEO_PREZZI_RECENTI, p, liv, v) for p in anni_prezzi_recenti for liv in livelli for v in varianti]
    scenari += [Scenario(ANNO_METEO_PREZZI_RECENTI, ANNO_METEO_PREZZI_RECENTI, liv, v)
                for v in varianti_anno_base if v not in varianti for liv in livelli]
    return scenari


@dataclass
class EsitoScenario:
    scenario: Scenario
    energia: ProjectResult
    ledger: Ledger
    kpi: Kpi
    qualita_prezzi: str
    fonte_prezzi: str


@dataclass(frozen=True)
class Banda:
    minimo: float
    mediana: float
    massimo: float

    @staticmethod
    def da(valori) -> "Banda":
        v = np.asarray(list(valori), dtype=float)
        return Banda(float(v.min()), float(np.median(v)), float(v.max()))


def _serie_prezzi(prezzi: dict[int, PriceSeries], anno: int, media: float, regione: str) -> PriceSeries:
    """Prezzi dell'anno se caricati; altrimenti la forma oraria reale più recente (si perde la
    correlazione sole–prezzi di quell'anno, ma resta il calo dei prezzi nelle ore di sole);
    senza alcun file, prezzo costante (qualità C)."""
    if anno in prezzi:
        return prezzi[anno].scalata(media)
    if prezzi:
        s = prezzi[max(prezzi)].scalata(media)
        return replace(s, fonte=f"{s.fonte}, forma oraria usata al posto del {anno}")
    return prezzo_costante(media, anno, zona_mercato(regione, max(anno, 2021)))


def esegui_scenari(
    config: Configuration,
    report: EligibilityReport,
    params: ParametriEconomici,
    pv_per_anno: dict[int, dict[str, PVProfile]],
    prezzi: dict[int, PriceSeries],
    scenari: list[Scenario],
    *,
    n_anni: int | None = None,
    oggi: date | None = None,
) -> list[EsitoScenario]:
    """Esegue gli scenari: un solo bilancio energetico per (anno meteo, variante), riusato per
    tutti i livelli di prezzo; i contributi si calcolano anno per anno durante la simulazione
    e dei dati orari si tengono solo i primi due anni (per i grafici)."""
    medie = assunzioni_economiche().prezzi.media_eur_mwh
    gruppi: dict[tuple[int, int], list[Scenario]] = {}
    for s in scenari:
        gruppi.setdefault((s.anno_meteo, s.variante), []).append(s)

    risultati: dict[Scenario, EsitoScenario] = {}
    for (anno_meteo, variante), del_gruppo in gruppi.items():
        serie = {s: _serie_prezzi(prezzi, s.anno_prezzi, medie[s.livello], config.regione) for s in del_gruppo}
        contributi: dict[Scenario, list] = {s: [] for s in del_gruppo}

        def per_anno(yr, serie=serie, contributi=contributi):
            for s, ps in serie.items():
                contributi[s].append(contributi_anno(
                    config, report, yr, ps.per_anno_progetto(yr.year), regime_vendita=params.regime_vendita,
                    costo_evitabile_eur_kwh=params.costo_evitabile_eur_kwh, oggi=oggi))

        energia = simulate_project(config, report, pv_per_anno[anno_meteo], anno_meteo, n_years=n_anni,
                                   variante_carichi=variante, per_anno=per_anno, mantieni_orari=2)
        for s in del_gruppo:
            ledger = costruisci_ledger(config, report, energia, None, params, contributi=contributi[s], oggi=oggi)
            risultati[s] = EsitoScenario(s, energia, ledger, kpi(config, ledger), serie[s].qualita, serie[s].fonte)
    return [risultati[s] for s in scenari]


def qualita_complessiva(config: Configuration, pv_per_anno: dict[int, dict[str, PVProfile]], esiti: list[EsitoScenario]) -> str:
    """Qualità dei risultati (`loads.qualita_insieme`): decidono i consumi, purché produzione e prezzi non siano
    tipici."""
    return qualita_insieme(config.connection_points,
                           [p.qualita for profili in pv_per_anno.values() for p in profili.values()],
                           [e.qualita_prezzi for e in esiti])


def bande(esiti: list[EsitoScenario]) -> dict[str, Banda]:
    """Banda di energia condivisa, contributi del primo anno intero e VAN."""
    def primo_intero(e):
        return e.energia.anni[1] if len(e.energia.anni) > 1 else e.energia.anni[0]

    return {
        "energia_condivisa_kwh": Banda.da(primo_intero(e).totali()["EACV_kwh"] for e in esiti),
        "tip_eur_anno": Banda.da(e.kpi.contributi_primo_anno_intero.get("tariffa premio (TIP)", 0.0) for e in esiti),
        "cacv_eur_anno": Banda.da(e.kpi.contributi_primo_anno_intero.get("valorizzazione ARERA (CACV)", 0.0) for e in esiti),
        "van_investitore": Banda.da(e.kpi.van_investitore for e in esiti),
        "van_consolidato": Banda.da(e.kpi.van_consolidato for e in esiti),
    }


@dataclass(frozen=True)
class VoceSensibilita:
    parametro: str
    variazione: str
    van_consolidato_basso: float
    van_consolidato_alto: float
    van_investitore_basso: float
    van_investitore_alto: float

    @property
    def ampiezza(self) -> float:
        return abs(self.van_consolidato_alto - self.van_consolidato_basso)


def sensibilita(
    config: Configuration,
    report: EligibilityReport,
    params: ParametriEconomici,
    pv_per_anno: dict[int, dict[str, PVProfile]],
    prezzi: dict[int, PriceSeries],
    scenario_base: Scenario,
    *,
    esiti: list[EsitoScenario] | None = None,
    n_anni: int | None = None,
    oggi: date | None = None,
) -> list[VoceSensibilita]:
    """Dati per il grafico a tornado, attorno a uno scenario base, ordinati per impatto sul VAN consolidato.

    Riusa bilancio energetico e contributi dello scenario base (passato in `esiti`, se già calcolato):
    le variazioni economiche cambiano solo il ledger, non la fisica.
    """
    per_scenario = {e.scenario: e for e in (esiti or [])}

    def esito(s: Scenario) -> EsitoScenario:
        if s not in per_scenario:
            per_scenario[s] = esegui_scenari(config, report, params, pv_per_anno, prezzi, [s], n_anni=n_anni, oggi=oggi)[0]
        return per_scenario[s]

    base = esito(scenario_base)
    costo_base = params.costo_evitabile_eur_kwh or assunzioni_economiche().bolletta.costo_evitabile_eur_kwh

    def van(p: ParametriEconomici, fattore_risparmio: float = 1.0):
        contributi = base.ledger.contributi
        if fattore_risparmio != 1.0:  # il risparmio è lineare nel costo evitabile
            contributi = [replace(c, risparmio_per_punto={k: v * fattore_risparmio for k, v in c.risparmio_per_punto.items()})
                          for c in contributi]
        ledger = costruisci_ledger(config, report, base.energia, None, p, contributi=contributi, oggi=oggi)
        k = kpi(config, ledger)
        return k.van_consolidato, k.van_investitore

    casi = [
        ("costo dell'impianto", "±20%", (replace(params, fattore_capex=0.8), 1.0), (replace(params, fattore_capex=1.2), 1.0)),
        ("costo evitabile in bolletta", "±30%",
         (replace(params, costo_evitabile_eur_kwh=costo_base * 0.7), 0.7),
         (replace(params, costo_evitabile_eur_kwh=costo_base * 1.3), 1.3)),
        ("energia condivisa (TIP e CACV)", "±10%", (replace(params, fattore_condivisa=0.9), 1.0),
         (replace(params, fattore_condivisa=1.1), 1.0)),
        ("valorizzazione ARERA negli anni futuri", "±20%", (replace(params, fattore_cacv_futuro=0.8), 1.0),
         (replace(params, fattore_cacv_futuro=1.2), 1.0)),
    ]
    voci = []
    for nome, variazione, basso, alto in casi:
        (cb, ib), (ca, ia) = van(*basso), van(*alto)
        voci.append(VoceSensibilita(nome, variazione, cb, ca, ib, ia))
    e_basso, e_alto = esito(replace(scenario_base, livello="basso")), esito(replace(scenario_base, livello="alto"))
    voci.append(VoceSensibilita("livello dei prezzi", "basso / alto", e_basso.kpi.van_consolidato, e_alto.kpi.van_consolidato,
                                e_basso.kpi.van_investitore, e_alto.kpi.van_investitore))
    if any(p.contributo_capitale and p.contributo_capitale.scadenzario_incassi for p in config.plants):
        (cb, ib), (ca, ia) = van(replace(params, ritardo_incasso_contributo_anni=2)), van(params)
        voci.append(VoceSensibilita("incasso del contributo in capitale", "+2 anni / previsto", cb, ca, ib, ia))
    return sorted(voci, key=lambda v: v.ampiezza, reverse=True)
