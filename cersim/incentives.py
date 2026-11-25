"""Contributi e ricavi di un anno, dal bilancio orario e dai prezzi zonali.

Formule (docs/fonti_normative.md):
- TIP_h = { min[CAP; TPbase + max(0; 180 − Pz)] + FCzonale } × (1 − F), su EACI per impianto;
  F non si applica alla quota di EACI dei punti di soggetti esenti, allocata per
  prima agli impianti con contributo in capitale (RO p. 41).
- CACV (CER)    = TRASE × EACV
  CACV (gruppo) = TRASE × EACV + BTAU × EACVC + Σ_h EACVC_impianto × cPR(tensione) × Pz
- quota eccedentaria: per insieme di impianti (solo TIP / con contributo),
  max(0; EACI/E_immessa − soglia) × contributo TIP dell'insieme.
- vendita: immissioni nel periodo di vendita × Pz, al produttore (RID o mercato).
- risparmio fisico: autoconsumo × costo evitabile, al titolare del punto; per un contatore caricato da un profilo
  energetico con il prezzo della bolletta, autoconsumo orario × quel prezzo (per fascia ARERA se ci sono le fasce).
Importi in euro, sempre tramite `units.eur` (kWh × €/MWh).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

from cersim.eligibility import EligibilityReport, Stato
from cersim.geo import area_geografica
from cersim.model import Configuration, Plant, TipoConfigurazione
from cersim.normativa import (
    PacchettoNormativo,
    assunzioni_economiche,
    classificazione_soggetti,
    pacchetto_normativo,
    verifica_validita,
)
from cersim.simulate import YearResult, maschere_impianto
from cersim.timebase import frame_per
from cersim.units import eur

Regime = Literal["RID", "mercato"]


def fattore_F(plant: Plant, norma: PacchettoNormativo) -> float:
    """F dall'atto di concessione; altrimenti lineare sull'intensità (0 → 0, 40% → 0,5)."""
    grant = plant.contributo_capitale
    if grant is None:
        return 0.0
    if grant.fattore_F is not None:
        return grant.fattore_F
    return norma.tip.F_massimo * min(1.0, grant.intensita / norma.tip.intensita_per_F_massimo)


def tip_oraria(potenza_nominale_kw: float, regione: str, pz_eur_mwh: np.ndarray, norma: PacchettoNormativo) -> np.ndarray:
    """TIP oraria in €/MWh prima del fattore F (tetto applicato prima della correzione geografica)."""
    fascia = norma.fascia_tip(potenza_nominale_kw)
    variabile = np.maximum(0.0, norma.tip.prezzo_riferimento_eur_mwh - np.asarray(pz_eur_mwh, dtype=float))
    correzione = norma.tip.correzione_geografica_fv_eur_mwh[area_geografica(regione)]
    return np.minimum(fascia.cap_eur_mwh, fascia.base_eur_mwh + variabile) + correzione


def punti_esenti_F(config: Configuration) -> tuple[np.ndarray, list[str]]:
    """Maschera dei punti i cui titolari sono esenti da F; elenco dei titolari con esito sconosciuto."""
    soggetti = classificazione_soggetti().soggetti
    esenti, sconosciuti = [], []
    for cp in config.connection_points:
        voce = soggetti[config.member(cp.titolare).tipo_soggetto.value]
        esenti.append(voce.soggetto_esente_F == "si")
        if voce.soggetto_esente_F == "sconosciuto":
            sconosciuti.append(cp.titolare)
    return np.asarray(esenti, dtype=bool), sorted(set(sconosciuti))


@dataclass
class ContributiAnno:
    anno: int
    tip_per_impianto: dict[str, float]
    tip_esente_F_kwh: dict[str, float]
    cacv: float
    cacv_componenti: dict[str, float]
    vendita_per_impianto: dict[str, float]  # netto degli oneri
    oneri_vendita_per_impianto: dict[str, float]
    risparmio_per_punto: dict[str, float]
    corrispettivi_gse_per_impianto: dict[str, float]
    eccedenza: dict[str, dict[str, float]]  # insieme → {quota, importo}
    eacv_per_punto_kwh: dict[str, float]  # base del riparto contrattuale
    avvisi: list[str] = field(default_factory=list)

    @property
    def tip(self) -> float:
        return sum(self.tip_per_impianto.values())

    @property
    def importo_eccedentario(self) -> float:
        return sum(v["importo"] for v in self.eccedenza.values())


def prezzo_bolletta(cp, index: pd.DatetimeIndex, costo_evitabile: float) -> np.ndarray:
    """Costo evitato per kWh autoconsumato in ogni ora: il prezzo della bolletta della casa se il contatore viene da
    un profilo energetico che lo porta (per fasce ARERA se le ha), altrimenti il costo evitabile dello scenario."""
    b = cp.profilo.bolletta if cp.profilo is not None else None
    if b is None:
        return np.full(len(index), costo_evitabile)
    if not b.fasce:
        return np.full(len(index), b.eur_kwh)
    fascia = frame_per(index)["fascia"].to_numpy(dtype=str)
    return np.select([fascia == "F1", fascia == "F2"], [b.fasce["F1"], b.fasce["F2"]], b.fasce["F3"])


def contributi_anno(
    config: Configuration,
    report: EligibilityReport,
    yr: YearResult,
    pz_eur_mwh: np.ndarray,
    *,
    regime_vendita: Regime = "RID",
    costo_evitabile_eur_kwh: float | None = None,
    oggi: date | None = None,
) -> ContributiAnno:
    norma = pacchetto_normativo()
    verifica_validita(norma, oggi)
    pz = np.asarray(pz_eur_mwh, dtype=float)
    if pz.shape != yr.EACV.shape:
        raise ValueError("I prezzi devono avere un valore per ogni ora dell'anno simulato")
    costo_evitabile = (
        assunzioni_economiche().bolletta.costo_evitabile_eur_kwh if costo_evitabile_eur_kwh is None else costo_evitabile_eur_kwh
    )
    avvisi: list[str] = []
    plants = config.plants
    riga = {pid: k for k, pid in enumerate(yr.plant_ids)}

    # --- TIP con fattore F e quota esente -------------------------------------------------
    esenti, sconosciuti = punti_esenti_F(config)
    F = {p.id: fattore_F(p, norma) for p in plants}
    con_F = [p for p in plants if F[p.id] > 0]
    W_tot = yr.W.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        quota_esente = np.where(W_tot > 0, yr.W[esenti].sum(axis=0) / W_tot, 0.0)
    esente_totale = yr.EACI * quota_esente  # ipotesi: EACI afferente ai punti esenti pro-quota sui prelievi
    eaci_con_F = sum((yr.EACI_per_impianto[riga[p.id]] for p in con_F), np.zeros_like(yr.EACI))
    esente_su_con_F = np.minimum(esente_totale, eaci_con_F)  # allocato per primo agli impianti con contributo
    if con_F and sconosciuti:
        avvisi.append("Esenzione dal fattore F non determinabile per: " + ", ".join(sconosciuti) + " (trattati come non esenti)")

    tip_per_impianto, tip_esente = {}, {}
    for p in plants:
        k = riga[p.id]
        eaci_p = yr.EACI_per_impianto[k]
        tariffa = tip_oraria(p.potenza_nominale_gse, config.regione, pz, norma)
        if F[p.id] > 0:
            with np.errstate(invalid="ignore", divide="ignore"):
                quota_p = np.where(eaci_con_F > 0, eaci_p / eaci_con_F, 0.0)
            esente_p = esente_su_con_F * quota_p
        else:
            esente_p = np.zeros_like(eaci_p)
        tip_per_impianto[p.id] = float(eur(esente_p, tariffa).sum() + eur(eaci_p - esente_p, tariffa * (1 - F[p.id])).sum())
        tip_esente[p.id] = float(esente_p.sum())

    # --- CACV --------------------------------------------------------------------------
    componenti = {"trasmissione": float(eur(yr.EACV, norma.trase(yr.year)).sum())}
    if config.tipo is TipoConfigurazione.GRUPPO:
        componenti["distribuzione"] = float(eur(yr.EACVC, norma.btau(yr.year)).sum())
        perdite = 0.0
        for p in plants:
            tensione = config.connection_point(p.connection_point).tensione.value
            cpr = norma.cacv.coefficiente_perdite_evitate[tensione]
            perdite += float(eur(yr.EACVC_per_impianto[riga[p.id]] * cpr, pz).sum())
        componenti["perdite_evitate"] = perdite

    # --- vendita, corrispettivi GSE, risparmio -----------------------------------------
    vendita, oneri, corrispettivi = {}, {}, {}
    sconto = assunzioni_economiche().prezzi.vendita_mercato_sconto
    for p in plants:
        lordo = float(eur(yr.I_vendita[riga[p.id]], pz).sum())
        if regime_vendita == "RID":  # dovuta per intero se la convenzione è attiva anche un solo giorno nell'anno
            onere = norma.rid.onere_annuo(p.potenza_nominale_gse) if yr.I_vendita[riga[p.id]].any() else 0.0
        else:
            onere = lordo * sconto
        vendita[p.id] = lordo - onere
        oneri[p.id] = onere
        tip_attiva = maschere_impianto(p, yr.index).tip.any() and report.impianti[p.id].tip.stato is not Stato.NON_AMMESSO
        corrispettivi[p.id] = norma.corrispettivo_gse_annuo(p.potenza_nominale_gse) if tip_attiva else 0.0
    if regime_vendita == "RID" and not norma.rid.verificato:
        avvisi.append("Oneri del ritiro dedicato non verificati sulle fonti (valore prudente)")

    risparmio = {cid: float(yr.SC[i] @ prezzo_bolletta(config.connection_point(cid), yr.index, costo_evitabile))
                 for i, cid in enumerate(yr.cp_ids)}

    # --- quota eccedentaria ------------------------------------------------------------
    eccedenza = {}
    insiemi = {
        "solo_tip": ([p for p in plants if p.contributo_capitale is None], norma.eccedenza.soglia_solo_tip),
        "con_contributo": ([p for p in plants if p.contributo_capitale is not None], norma.eccedenza.soglia_con_contributo_capitale),
    }
    for nome, (gruppo, soglia) in insiemi.items():
        if not gruppo:
            continue
        eaci_j = sum(yr.EACI_per_impianto[riga[p.id]].sum() for p in gruppo)
        immessa_j = sum(yr.I_tip[riga[p.id]].sum() for p in gruppo)
        quota = max(0.0, eaci_j / immessa_j - soglia) if immessa_j > 0 else 0.0
        eccedenza[nome] = {"quota": quota, "importo": quota * sum(tip_per_impianto[p.id] for p in gruppo)}

    return ContributiAnno(
        anno=yr.year,
        tip_per_impianto=tip_per_impianto,
        tip_esente_F_kwh=tip_esente,
        cacv=sum(componenti.values()),
        cacv_componenti=componenti,
        vendita_per_impianto=vendita,
        oneri_vendita_per_impianto=oneri,
        risparmio_per_punto=risparmio,
        corrispettivi_gse_per_impianto=corrispettivi,
        eccedenza=eccedenza,
        eacv_per_punto_kwh={cid: float(yr.EACV_per_punto[i].sum()) for i, cid in enumerate(yr.cp_ids)},
        avvisi=avvisi,
    )
