"""Bilancio energetico orario della configurazione, anno per anno.

Per ogni ora t e ogni punto di connessione (al massimo un impianto per punto):
    SC = min(L, P)      autoconsumo fisico dietro il contatore
    I  = P − SC         immissione in rete
    W  = L − SC         prelievo dalla rete
Con una batteria di casa sul punto (`BatteriaCasa`) il surplus P − min(L, P) la carica e la batteria si scarica sui
consumi del punto: SC comprende la scarica, I e W scendono. La batteria parte dalla riserva il 1° gennaio di ogni anno
e non perde capacità negli anni (ipotesi dichiarata).
Grandezze della configurazione, ciascuna con il proprio perimetro di impianti:
    EACI(t)  = min(Σ I degli impianti nel perimetro TIP,  Σ W)   → tariffa premio
    EACV(t)  = min(Σ I degli impianti nel perimetro CACV, Σ W)   → valorizzazione ARERA
    EACVC(t) = come EACV ma solo impianti nell'edificio, solo per il gruppo
Gli impianti entrano nei perimetri solo nelle ore in cui sono attivi: entrata
in esercizio, decorrenza del servizio CACER, ventennio della TIP, decorrenza
della vendita (maschere orarie, non proporzioni del totale annuo).
"""

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

from cersim import __version__
from cersim.eligibility import EligibilityReport, Stato, assert_supported
from cersim.loads import load_profile_anno, qualita_consumi, qualita_insieme
from cersim.model import BatteriaCasa, Configuration, Plant, TipoConfigurazione
from cersim.normativa import assunzioni_economiche, pacchetto_normativo
from cersim.pv import PVProfile, media_profili, plant_output, pv_profile
from cersim.timebase import TZ, remap_reference_year, year_index

# Attribuzione dell'energia condivisa tra impianti "a partire dalle immissioni degli
# impianti entrati prima in esercizio" (RO, Appendice A). A parità di data le RO
# non dicono nulla: ripartizione pro-quota sulle immissioni (ipotesi del modello).
REGOLA_ATTRIBUZIONE = "prima gli impianti entrati prima in esercizio (RO App. A); pro-quota a parità di data (ipotesi)"


def _da(index: pd.DatetimeIndex, giorno: date) -> np.ndarray:
    """Maschera oraria: True dalle 00:00 (ora civile) del giorno indicato."""
    return np.asarray(index >= pd.Timestamp(giorno, tz=TZ))


def _prima(index: pd.DatetimeIndex, giorno: date) -> np.ndarray:
    return ~_da(index, giorno)


def _fine_ventennio(plant: Plant) -> date:
    durata = pacchetto_normativo().tip.durata_anni
    return (pd.Timestamp(plant.inizio_incentivazione) + pd.DateOffset(years=durata)).date()


@dataclass(frozen=True)
class Maschere:
    esercizio: np.ndarray
    servizio: np.ndarray
    tip: np.ndarray
    vendita: np.ndarray


def _calcola_maschere(index, entrata, servizio_da, inizio_tip, fine_tip, vendita_da) -> Maschere:
    esercizio = _da(index, entrata)
    servizio = esercizio & _da(index, servizio_da)
    tip = servizio & _da(index, inizio_tip) & _prima(index, fine_tip)
    vendita = esercizio & _da(index, vendita_da)
    for m in (esercizio, servizio, tip, vendita):
        m.setflags(write=False)
    return Maschere(esercizio=esercizio, servizio=servizio, tip=tip, vendita=vendita)


@lru_cache(maxsize=1024)
def _maschere_anno(anno, entrata, servizio_da, inizio_tip, fine_tip, vendita_da) -> Maschere:
    return _calcola_maschere(year_index(anno), entrata, servizio_da, inizio_tip, fine_tip, vendita_da)


def maschere_impianto(plant: Plant, index: pd.DatetimeIndex) -> Maschere:
    date_ = (plant.data_entrata_esercizio, plant.decorrenza_servizio, plant.inizio_incentivazione,
             _fine_ventennio(plant), plant.decorrenza_vendita)
    if len(index):
        anno = int(index[0].tz_convert(TZ).year)
        full = year_index(anno)
        if len(index) == len(full) and index[0] == full[0]:
            return _maschere_anno(anno, *date_)
    return _calcola_maschere(index, *date_)


@dataclass
class YearResult:
    year: int
    index: pd.DatetimeIndex
    cp_ids: list[str]
    plant_ids: list[str]
    L: np.ndarray  # (punti, ore) consumo
    P: np.ndarray  # (punti, ore) produzione dell'impianto sul punto
    SC: np.ndarray
    I: np.ndarray
    W: np.ndarray
    EACI: np.ndarray  # (ore,)
    EACV: np.ndarray
    EACVC: np.ndarray
    EACI_per_impianto: np.ndarray  # (impianti, ore)
    EACV_per_punto: np.ndarray  # (punti, ore) quota di condivisa pro-quota prelievi (riparto contrattuale)
    I_vendita: np.ndarray  # (impianti, ore) immissione nel periodo di vendita
    I_tip: np.ndarray  # (impianti, ore) immissione nel perimetro TIP
    I_cacv: np.ndarray  # (impianti, ore) immissione nel perimetro CACV
    EACVC_per_impianto: np.ndarray  # (impianti, ore) per le perdite evitate del gruppo
    condizionale: bool = False
    carica: np.ndarray | None = None  # (punti, ore) energia del surplus entrata nelle batterie di casa
    scarica: np.ndarray | None = None  # (punti, ore) energia uscita dalle batterie verso i consumi (compresa in SC)

    def totali(self) -> dict[str, float]:
        produzione = float(self.P.sum())
        immissione = float(self.I.sum())
        consumo = float(self.L.sum())
        eacv = float(self.EACV.sum())
        return {
            "produzione_kwh": produzione,
            "consumo_kwh": consumo,
            "autoconsumo_fisico_kwh": float(self.SC.sum()),
            "scarica_batterie_kwh": float(self.scarica.sum()) if self.scarica is not None else 0.0,
            "immissione_kwh": immissione,
            "prelievo_kwh": float(self.W.sum()),
            "EACI_kwh": float(self.EACI.sum()),
            "EACV_kwh": eacv,
            "EACVC_kwh": float(self.EACVC.sum()),
            "quota_condivisa_su_immessa": eacv / immissione if immissione else 0.0,
            "copertura_consumi": (float(self.SC.sum()) + eacv) / consumo if consumo else 0.0,
        }

    def mensili(self) -> pd.DataFrame:
        mesi = self.index.tz_convert(TZ).month
        dati = pd.DataFrame(
            {
                "produzione_kwh": self.P.sum(axis=0),
                "consumo_kwh": self.L.sum(axis=0),
                "autoconsumo_fisico_kwh": self.SC.sum(axis=0),
                "immissione_kwh": self.I.sum(axis=0),
                "EACV_kwh": self.EACV,
                "EACI_kwh": self.EACI,
            }
        )
        return dati.groupby(np.asarray(mesi)).sum().rename_axis("mese")

    def violazioni_invarianti(self, tol: float = 1e-6) -> list[str]:
        """Controlli fisici: lista vuota se il bilancio è coerente."""
        errori = []
        carica = self.carica if self.carica is not None else np.zeros_like(self.P)
        scarica = self.scarica if self.scarica is not None else np.zeros_like(self.P)
        diretto = self.SC - scarica
        if not _vicini(self.P, diretto + carica + self.I, atol=tol):
            errori.append("P ≠ SC − scarica + carica + I")
        if not _vicini(self.L, self.SC + self.W, atol=tol):
            errori.append("L ≠ SC + W")
        if (diretto > np.minimum(self.L, self.P) + tol).any():
            errori.append("SC diretto > min(L, P)")
        if (carica < -tol).any() or (scarica < -tol).any():
            errori.append("carica o scarica negative")
        if (np.minimum(self.I, self.W) > tol).any():
            errori.append("immissione e prelievo contemporanei sullo stesso punto")
        if (self.EACV > np.minimum(self.I.sum(axis=0), self.W.sum(axis=0)) + tol).any():
            errori.append("EACV > min(ΣI, ΣW)")
        if not _vicini(self.EACI_per_impianto.sum(axis=0), self.EACI, atol=tol):
            errori.append("attribuzione EACI agli impianti non somma a EACI")
        if not _vicini(self.EACV_per_punto.sum(axis=0), self.EACV, atol=tol):
            errori.append("attribuzione EACV ai punti non somma a EACV")
        for arr, nome in ((self.L, "L"), (self.P, "P"), (self.EACI, "EACI"), (self.EACV, "EACV")):
            if (arr < -tol).any() or not np.isfinite(arr).all():
                errori.append(f"{nome} negativo o non finito")
        return errori


def _vicini(a: np.ndarray, b: np.ndarray, atol: float) -> bool:
    """Come `np.allclose(a, b, atol=atol)` (stessa tolleranza relativa 1e-5), senza i passaggi per NaN e infiniti, che i
    controlli qui sotto trattano a parte: con molti contatori np.isclose pesava quanto il bilancio dell'anno."""
    return bool(np.all(np.abs(a - b) <= atol + 1e-5 * np.abs(b)))


def simulate_year(
    config: Configuration,
    report: EligibilityReport,
    index: pd.DatetimeIndex,
    loads: dict[str, np.ndarray],
    production: dict[str, np.ndarray],
) -> YearResult:
    """Bilancio orario di un anno.

    `loads`: consumo orario per punto (kWh). `production`: produzione oraria per
    impianto (kWh) già degradata e limitata dall'inverter, senza maschere.
    """
    assert_supported(report)
    n = len(index)
    cps = config.connection_points
    plants = config.plants
    cp_ids = [c.id for c in cps]
    plant_ids = [p.id for p in plants]
    riga_punto = {cid: i for i, cid in enumerate(cp_ids)}

    L = np.vstack([np.asarray(loads.get(c.id, np.zeros(n)), dtype=float) for c in cps])
    P = np.zeros_like(L)
    maschere = {p.id: maschere_impianto(p, index) for p in plants}
    for p in plants:
        P[riga_punto[p.connection_point]] = np.asarray(production[p.id], dtype=float) * maschere[p.id].esercizio

    SC = np.minimum(L, P)
    I = P - SC
    W = L - SC
    carica = np.zeros_like(L)
    scarica = np.zeros_like(L)
    for r, c in enumerate(cps):
        if c.batteria is not None:
            carica[r], scarica[r] = batteria_di_casa(I[r], W[r], c.batteria)
            I[r] -= carica[r]
            W[r] -= scarica[r]
            SC[r] += scarica[r]
    W_tot = W.sum(axis=0)

    I_impianto = np.vstack([I[riga_punto[p.connection_point]] for p in plants]) if plants else np.zeros((0, n))

    def nel_perimetro(esito_attr: str, maschera_attr: str, filtro=lambda p: True) -> np.ndarray:
        righe = np.zeros_like(I_impianto)
        for k, p in enumerate(plants):
            esito = getattr(report.impianti[p.id], esito_attr)
            if esito.stato is not Stato.NON_AMMESSO and filtro(p):
                righe[k] = I_impianto[k] * getattr(maschere[p.id], maschera_attr)
        return righe

    I_tip = nel_perimetro("tip", "tip")
    I_cacv = nel_perimetro("cacv", "servizio")
    EACI = np.minimum(I_tip.sum(axis=0), W_tot)
    EACV = np.minimum(I_cacv.sum(axis=0), W_tot)
    if config.tipo is TipoConfigurazione.GRUPPO:
        I_edificio = nel_perimetro("cacv", "servizio", lambda p: p.nell_edificio)
    else:
        I_edificio = np.zeros_like(I_impianto)
    EACVC = np.minimum(I_edificio.sum(axis=0), W_tot)

    EACI_per_impianto = _attribuisci_per_data(plants, I_tip, EACI)
    EACVC_per_impianto = _attribuisci_per_data(plants, I_edificio, EACVC)
    with np.errstate(invalid="ignore", divide="ignore"):
        quota_prelievi = np.where(W_tot > 0, W / W_tot, 0.0)
    EACV_per_punto = quota_prelievi * EACV

    I_vendita = (
        np.vstack([I_impianto[k] * maschere[p.id].vendita for k, p in enumerate(plants)]) if plants else np.zeros((0, n))
    )

    return YearResult(
        year=int(index.tz_convert(TZ)[0].year),
        index=index,
        cp_ids=cp_ids,
        plant_ids=plant_ids,
        L=L, P=P, SC=SC, I=I, W=W,
        EACI=EACI, EACV=EACV, EACVC=EACVC,
        EACI_per_impianto=EACI_per_impianto,
        EACV_per_punto=EACV_per_punto,
        I_vendita=I_vendita,
        I_tip=I_tip,
        I_cacv=I_cacv,
        EACVC_per_impianto=EACVC_per_impianto,
        condizionale=report.condizionale,
        carica=carica,
        scarica=scarica,
    )


def batteria_di_casa(surplus: np.ndarray, deficit: np.ndarray, b: BatteriaCasa) -> tuple[np.ndarray, np.ndarray]:
    """Carica dal surplus e scarica sul deficit del punto, ora per ora (kWh), come `simulateBattery` del simulatore
    della casa: rendimento √η in carica e in scarica, carica minima `riserva_pct`, potenza massima uguale nei due
    versi. Si parte dalla riserva."""
    cap = b.capacita_kwh
    minimo = cap * b.riserva_pct / 100
    pmax = b.potenza_kw
    eta = (b.rendimento_pct / 100) ** 0.5
    soc = minimo
    sur, dfc = surplus.tolist(), deficit.tolist()
    n = len(sur)
    carica, scarica = [0.0] * n, [0.0] * n
    for h in range(n):
        s = sur[h]
        if s > 0:
            x = min(s, pmax, (cap - soc) / eta)
            if x > 0:
                soc += x * eta
                carica[h] = x
        else:
            d = dfc[h]
            if d > 0:
                x = min(d, pmax, (soc - minimo) * eta)
                if x > 0:
                    soc -= x / eta
                    scarica[h] = x
    return np.asarray(carica), np.asarray(scarica)


def _attribuisci_per_data(plants: list[Plant], I_tip: np.ndarray, EACI: np.ndarray) -> np.ndarray:
    """EACI agli impianti: prima i più vecchi, pro-quota a parità di data."""
    out = np.zeros_like(I_tip)
    residuo = EACI.copy()
    for data in sorted({p.data_entrata_esercizio for p in plants}):
        righe = [k for k, p in enumerate(plants) if p.data_entrata_esercizio == data]
        gruppo = I_tip[righe].sum(axis=0)
        preso = np.minimum(gruppo, residuo)
        with np.errstate(invalid="ignore", divide="ignore"):
            frazione = np.where(gruppo > 0, preso / gruppo, 0.0)
        out[righe] = I_tip[righe] * frazione
        residuo = residuo - preso
    return out


def pv_profiles_for(config: Configuration, ref_year: int, fetch=pv_profile) -> dict[str, PVProfile]:
    """Profili per 1 kWp di ogni impianto (una sola richiesta per orientamento e luogo).

    Impianto su due falde (`azimut_2`): media dei profili delle due falde, metà dei moduli per falda."""
    cache: dict[tuple, PVProfile] = {}

    def profilo(lat, lon, tilt, azimut, perdite):
        chiave = (round(lat, 2), round(lon, 2), tilt, azimut, perdite)
        if chiave not in cache:
            cache[chiave] = fetch(lat, lon, tilt, azimut, perdite, ref_year)
        return cache[chiave]

    out = {}
    for p in config.plants:
        cp = config.connection_point(p.connection_point)
        lat = cp.lat if cp.lat is not None else config.lat
        lon = cp.lon if cp.lon is not None else config.lon
        out[p.id] = profilo(lat, lon, p.tilt, p.azimut, p.perdite_pct)
        if p.azimut_2 is not None:
            out[p.id] = media_profili([out[p.id], profilo(lat, lon, p.tilt, p.azimut_2, p.perdite_pct)], [0.5, 0.5])
    return out


@dataclass
class ProjectResult:
    ref_year: int
    anni: list[YearResult]
    manifest: dict = field(default_factory=dict)


def anno_inizio(config: Configuration) -> int:
    """Primo anno di progetto: quello della prima entrata in esercizio."""
    return min((p.data_entrata_esercizio.year for p in config.plants), default=date.today().year)


def simulate_project(
    config: Configuration,
    report: EligibilityReport,
    pv_ref: dict[str, PVProfile],
    ref_year: int,
    *,
    start_year: int | None = None,
    n_years: int | None = None,
    degradazione_annua: float | None = None,
    variante_carichi: int = 0,
    per_anno=None,
    mantieni_orari: int | None = None,
) -> ProjectResult:
    """Simula `n_years` anni di progetto con il meteo dell'anno storico `ref_year`.

    Ogni anno di progetto riceve i dati storici tramite `remap_reference_year`
    e rifà il bilancio orario con la produzione degradata di quell'anno.
    Default di vita utile e degrado da `assunzioni_economiche.yaml`.

    Memoria: `per_anno(yr)` viene chiamata su ogni anno orario appena calcolato
    (es. per i contributi); con `mantieni_orari = k` si conservano i dati orari
    solo dei primi k anni, gli altri diventano `YearSummary` (solo totali).
    """
    assert_supported(report)
    ipotesi = assunzioni_economiche().impianto
    n_years = ipotesi.vita_utile_anni if n_years is None else n_years
    degradazione_annua = ipotesi.degradazione_annua if degradazione_annua is None else degradazione_annua
    for pid, prof in pv_ref.items():
        if prof.year != ref_year:
            raise ValueError(f"Il profilo FV di {pid} è del {prof.year}, non dell'anno di riferimento {ref_year}")
    if start_year is None:
        start_year = anno_inizio(config)

    anni = []
    violazioni: dict[int, list[str]] = {}
    for k in range(n_years):
        anno = start_year + k
        index = year_index(anno)
        remap = remap_reference_year(ref_year, anno)
        loads = {c.id: load_profile_anno(c, anno, variante_carichi) for c in config.connection_points}
        production = {}
        for p in config.plants:
            eta = max(0, anno - p.data_entrata_esercizio.year)
            production[p.id] = plant_output(
                remap.apply(pv_ref[p.id].kw_per_kwp.to_numpy()),
                p.potenza_moduli_kwp,
                p.potenza_inverter_kw,
                (1 - degradazione_annua) ** eta,
            )
        yr = simulate_year(config, report, index, loads, production)
        violazioni[anno] = yr.violazioni_invarianti()
        if per_anno is not None:
            per_anno(yr)
        anni.append(yr if mantieni_orari is None or k < mantieni_orari else YearSummary.da(yr))

    risultato = ProjectResult(ref_year=ref_year, anni=anni)
    risultato.manifest = build_manifest(config, report, pv_ref, risultato, degradazione_annua, variante_carichi, violazioni)
    return risultato


@dataclass(frozen=True)
class YearSummary:
    """Anno compattato: solo totali e mensili (i dati orari sono stati usati e liberati)."""

    year: int
    _totali: dict
    _mensili: pd.DataFrame
    condizionale: bool

    @staticmethod
    def da(yr: "YearResult") -> "YearSummary":
        return YearSummary(yr.year, yr.totali(), yr.mensili(), yr.condizionale)

    @property
    def index(self) -> pd.DatetimeIndex:
        return year_index(self.year)

    def totali(self) -> dict[str, float]:
        return dict(self._totali)

    def mensili(self) -> pd.DataFrame:
        return self._mensili.copy()


def avvisi_fv_sottratto(config) -> list[str]:
    """Punti con consumi calcolati da cui è già tolto un FV e con un impianto: forse lo stesso, contato due volte."""
    con_impianto = {p.connection_point for p in config.plants}
    avvisi = []
    for c in config.connection_points:
        fv = c.curva_misurata.fv_sottratto_kwp if c.curva_misurata else None
        if fv and c.id in con_impianto:
            avvisi.append(f"Il punto {c.id} ha consumi dal simulatore della casa che hanno già tolto un fotovoltaico da "
                          f"{f'{fv:g}'.replace('.', ',')} kWp e ha anche un impianto: se è lo stesso, la sua produzione "
                          "è contata due volte")
    return avvisi


def build_manifest(config, report, pv_ref, risultato: ProjectResult, degradazione_annua, variante_carichi,
                   violazioni: dict) -> dict:
    """Riepilogo di provenienza dei dati e controlli, senza dati personali (niente nomi né indirizzi)."""
    qualita_pv = {pid: prof.qualita for pid, prof in pv_ref.items()}
    qualita_punti = {c.id: qualita_consumi(c) for c in config.connection_points}
    avvisi = sorted({prof.avviso for prof in pv_ref.values() if prof.avviso})
    if report.condizionale:
        avvisi.append("Contributi condizionali: alcuni requisiti non sono verificati")
    avvisi += avvisi_fv_sottratto(config)
    return {
        "versione_cersim": __version__,
        "anno_riferimento_meteo": risultato.ref_year,
        "anni_progetto": [risultato.anni[0].year, risultato.anni[-1].year] if risultato.anni else [],
        "fonti_pv": {pid: {"fonte": prof.fonte, "cache_hit": prof.cache_hit} for pid, prof in pv_ref.items()},
        "qualita_pv": qualita_pv,
        "qualita_consumi": qualita_punti,
        "qualita_complessiva": qualita_insieme(config.connection_points, list(qualita_pv.values()), []),
        "degradazione_annua": degradazione_annua,
        "variante_carichi": variante_carichi,
        "regola_attribuzione_EACI": REGOLA_ATTRIBUZIONE,
        "stato_configurazione": report.stato_configurazione.value,
        "esiti": {nome: e.stato.value for nome, e in report.configurazione.items()},
        "controlli_bilancio": "ok" if not any(violazioni.values()) else {a: v for a, v in violazioni.items() if v},
        "avvisi": avvisi,
    }
