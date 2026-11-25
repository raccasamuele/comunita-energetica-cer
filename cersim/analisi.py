"""Analisi completa di una configurazione, pronta per l'interfaccia o un report.

Passi: checklist → profili FV per i 3 anni meteo → banda di scenari → scenario
base, sensibilità e dati per i grafici. Casi gestiti senza eccezioni:
- configurazione non supportata in v1 → solo l'elenco dei motivi;
- pacchetto normativo scaduto → solo il bilancio energetico, niente euro.
"""

from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from cersim.economics import ParametriEconomici, costruisci_ledger, kpi
from cersim.eligibility import EligibilityReport, check
from cersim.loads import VARIANTI
from cersim.model import Configuration
from cersim.normativa import PacchettoScadutoError, pacchetto_normativo, verifica_validita
from cersim.prices import PriceSeries
from cersim.pv import ANNI_METEO, PVProfile, pv_profile
from cersim.scenari import (
    Banda,
    EsitoScenario,
    Scenario,
    VoceSensibilita,
    bande,
    esegui_scenari,
    qualita_complessiva,
    scenari_standard,
    sensibilita,
)
from cersim.simulate import ProjectResult, YearResult, pv_profiles_for, simulate_project
from cersim.timebase import TZ


@dataclass
class Analisi:
    config: Configuration
    report: EligibilityReport
    qualita: str = "C"
    scenari: list[Scenario] = field(default_factory=list)  # gli stessi servono al dimensionamento
    esiti: list[EsitoScenario] = field(default_factory=list)
    bande: dict[str, Banda] = field(default_factory=dict)
    base: EsitoScenario | None = None
    sensibilita: list[VoceSensibilita] = field(default_factory=list)
    energia_base: ProjectResult | None = None  # sempre presente se la configurazione è supportata
    pv: dict[int, dict[str, PVProfile]] = field(default_factory=dict)
    economia_disabilitata: str | None = None
    dati_incoerenti: bool = False  # i bilanci non tornano: né energia né euro sono affidabili
    avvisi: list[str] = field(default_factory=list)

    @property
    def supportata(self) -> bool:
        return self.report.supportata


def analizza(
    config: Configuration,
    params: ParametriEconomici,
    prezzi: dict[int, PriceSeries] | None = None,
    *,
    fetch_pv=pv_profile,
    n_anni: int | None = None,
    con_sensibilita: bool = True,
    oggi: date | None = None,
) -> Analisi:
    report = check(config)
    analisi = Analisi(config=config, report=report)
    if not report.supportata:
        return analisi
    prezzi = prezzi or {}

    analisi.pv = {anno: pv_profiles_for(config, anno, fetch=fetch_pv) for anno in ANNI_METEO}
    try:
        verifica_validita(pacchetto_normativo(), oggi)
    except PacchettoScadutoError as e:
        analisi.economia_disabilitata = str(e)
        analisi.energia_base = simulate_project(config, report, analisi.pv[ANNI_METEO[-1]], ANNI_METEO[-1], n_years=n_anni)
        analisi.avvisi = analisi.energia_base.manifest["avvisi"]
        return analisi

    recenti = tuple(sorted(a for a in prezzi if a not in ANNI_METEO))
    analisi.scenari = scenari_standard(anni_prezzi_recenti=recenti, varianti_anno_base=tuple(VARIANTI))
    analisi.esiti = esegui_scenari(config, report, params, analisi.pv, prezzi, analisi.scenari, n_anni=n_anni, oggi=oggi)
    if violazioni := [v for e in analisi.esiti if (v := e.energia.manifest["controlli_bilancio"]) != "ok"]:
        analisi.dati_incoerenti = True
        analisi.economia_disabilitata = ("I bilanci dell'energia non tornano, quindi il calcolo si ferma: controlla i "
                                         f"dati inseriti ({next(iter(violazioni[0].values()))[0]}).")
        analisi.energia_base = analisi.esiti[0].energia
        analisi.esiti = []
        return analisi
    analisi.bande = bande(analisi.esiti)
    analisi.bande.update(_confronto_senza_configurazione(config, report, params, analisi.esiti, oggi))
    analisi.qualita = qualita_complessiva(config, analisi.pv, analisi.esiti)
    scenario_base = Scenario(ANNI_METEO[-1], recenti[-1] if recenti else ANNI_METEO[-1], "base")
    analisi.base = next(e for e in analisi.esiti if e.scenario == scenario_base)
    analisi.energia_base = analisi.base.energia
    if con_sensibilita:
        analisi.sensibilita = sensibilita(config, report, params, analisi.pv, prezzi, scenario_base,
                                          esiti=analisi.esiti, n_anni=n_anni, oggi=oggi)
    avvisi = set(analisi.energia_base.manifest["avvisi"])
    for e in analisi.esiti:
        avvisi |= set(e.ledger.avvisi)
    analisi.avvisi = sorted(avvisi) + analisi.base.ledger.contributi_esclusi
    return analisi


def _confronto_senza_configurazione(config, report, params, esiti: list[EsitoScenario], oggi) -> dict[str, Banda]:
    """Stessi impianti senza gruppo né CER, scenario per scenario: quanto aggiunge la configurazione.

    La fisica è la stessa; cambiano solo i flussi (niente contributi GSE né costi della configurazione)."""
    senza_cfg = replace(params, con_configurazione=False)
    solo_fv, aggiunta = [], []
    for e in esiti:
        led = costruisci_ledger(config, report, e.energia, None, senza_cfg, contributi=e.ledger.contributi, oggi=oggi)
        van = kpi(config, led).van_consolidato
        solo_fv.append(van)
        aggiunta.append(e.kpi.van_consolidato - van)
    return {"van_solo_fv": Banda.da(solo_fv), "valore_configurazione": Banda.da(aggiunta)}


def scenari_dimensionamento(analisi: Analisi) -> list[Scenario]:
    """Scenari di livello base dell'analisi, con i consumi tipici: la curva usa gli stessi anni e prezzi dei
    risultati (le varianti dei consumi moltiplicherebbero i tempi per ogni taglia provata)."""
    return [s for s in analisi.scenari if s.livello == "base" and s.variante == 0]


def fonti_prezzi(analisi: Analisi) -> list[str]:
    """Da dove vengono i prezzi di ogni scenario (livello base), senza ripetizioni."""
    return list(dict.fromkeys(e.fonte_prezzi for e in analisi.esiti if e.scenario.livello == "base"))


def anno_rappresentativo(energia: ProjectResult) -> YearResult:
    """Primo anno intero di esercizio (il primo è di solito parziale)."""
    return energia.anni[1] if len(energia.anni) > 1 else energia.anni[0]


def giorno_tipo(yr: YearResult, mese: int) -> pd.DataFrame:
    """Profilo medio orario (ora civile) di un mese: produzione, consumo, autoconsumo, condivisa."""
    locale = yr.index.tz_convert(TZ)
    sel = np.asarray(locale.month == mese)
    ore = np.asarray(locale.hour)[sel]
    df = pd.DataFrame({
        "ora": ore,
        "Produzione FV": yr.P.sum(axis=0)[sel],
        "Consumi": yr.L.sum(axis=0)[sel],
        "Autoconsumo fisico": yr.SC.sum(axis=0)[sel],
        "Energia condivisa": yr.EACV[sel],
    })
    return df.groupby("ora").mean()


def mensile(yr: YearResult) -> pd.DataFrame:
    m = yr.mensili()
    out = pd.DataFrame({
        "Condivisa (kWh)": m["EACV_kwh"],
        "Immessa non condivisa (kWh)": (m["immissione_kwh"] - m["EACV_kwh"]).clip(lower=0),
        "Autoconsumo fisico (kWh)": m["autoconsumo_fisico_kwh"],
    })
    out.index = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"][: len(out)]
    return out


def cassa_cumulata(esito: EsitoScenario) -> pd.DataFrame:
    led = esito.ledger
    anni = np.arange(led.anno_inizio, led.anno_inizio + led.n_anni)
    investitore = esito.kpi.investitore
    return pd.DataFrame({
        "anno": anni,
        "Configurazione (consolidato)": np.cumsum(led.flussi_consolidati()),
        "Investitore": np.cumsum(led.flussi_soggetto(investitore)),
    }).set_index("anno")


def chi_riceve_cosa(esito: EsitoScenario, nomi: dict[str, str], anno: int | None = None) -> pd.DataFrame:
    """Movimenti di un anno raggruppati per voce, pagatore e percettore (con nomi leggibili)."""
    led = esito.ledger
    anno = anno or led.anno_inizio + (1 if led.n_anni > 1 else 0)
    righe = [(m.voce, nomi.get(m.pagatore, m.pagatore), nomi.get(m.percettore, m.percettore), m.importo)
             for m in led.movimenti if m.anno == anno]
    df = pd.DataFrame(righe, columns=["Voce", "Chi paga", "Chi riceve", "€"])
    if df.empty:
        return df
    return df.groupby(["Voce", "Chi paga", "Chi riceve"], as_index=False)["€"].sum().sort_values("€", ascending=False)


def nomi_leggibili(config: Configuration) -> dict[str, str]:
    from cersim.economics import BOLLETTA, CONFIGURAZIONE, FORNITORI, GSE, MERCATO
    from cersim.model import TERZO

    nomi = {m.id: m.nome for m in config.members}
    nomi.update({
        CONFIGURAZIONE: "CER / gruppo (referente)", GSE: "GSE", MERCATO: "Mercato elettrico",
        FORNITORI: "Fornitori e installatori", BOLLETTA: "Bolletta (spesa evitata)", TERZO: "Investitore esterno",
    })
    return nomi
