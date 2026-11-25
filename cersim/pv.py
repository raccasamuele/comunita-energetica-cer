"""Produzione fotovoltaica oraria per 1 kWp: PVGIS, con cache su disco e fallback sintetico.

- Fonte principale: PVGIS v5.3 `seriescalc` (JRC), anni meteo 2021–2023.
- Cache: un file JSON per (coordinate arrotondate a 0,01°, orientamento,
  perdite, anno), scritto in modo atomico, con scadenza (TTL). Le coordinate
  arrotondate sono un dato di localizzazione minimizzato, non anonimo.
- Fallback sintetico (cielo sereno attenuato per mese) se PVGIS non risponde:
  i risultati che lo usano hanno qualità dati `C`.
"""

import json
import math
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from cersim.timebase import year_index

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/seriescalc"
ANNI_METEO = (2021, 2022, 2023)
CACHE_TTL = timedelta(days=90)
DECIMALI_COORDINATE = 2


@dataclass(frozen=True)
class PVProfile:
    """Produzione AC oraria di 1 kWp (kWh per ora = kW medi), perdite di sistema incluse."""

    kw_per_kwp: pd.Series  # indice: ore UTC dell'anno civile italiano `year`
    year: int
    fonte: str  # "PVGIS" | "sintetico"
    qualita: str  # "B" | "C"
    cache_hit: bool = False
    avviso: str | None = None

    @property
    def producibilita_kwh_kwp(self) -> float:
        return float(self.kw_per_kwp.sum())


def default_cache_dir() -> Path:
    return Path(os.environ.get("CERSIM_CACHE_DIR", Path.home() / ".cache" / "cersim")) / "pvgis"


def _parametri(lat, lon, tilt, azimut, perdite_pct, year) -> dict:
    return {
        "lat": round(lat, DECIMALI_COORDINATE),
        "lon": round(lon, DECIMALI_COORDINATE),
        "peakpower": 1,
        "loss": perdite_pct,
        "angle": tilt,
        "aspect": azimut,
        "pvcalculation": 1,
        "startyear": year,
        "endyear": year,
        "outputformat": "json",
    }


def _nome_cache(p: dict) -> str:
    return f"pvgis_{p['lat']:.2f}_{p['lon']:.2f}_t{p['angle']:g}_a{p['aspect']:g}_l{p['loss']:g}_{p['startyear']}.json"


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_per(chiave: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(chiave, threading.Lock())


def _leggi_cache(percorso: Path) -> dict | None:
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
        scaricato = datetime.fromisoformat(dati["scaricato_il"])
    except (OSError, ValueError, KeyError):
        return None
    if datetime.now(timezone.utc) - scaricato > CACHE_TTL:
        return None
    return dati


def _scrivi_cache_atomica(percorso: Path, dati: dict) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=percorso.parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dati, f)
        os.replace(tmp, percorso)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def parse_pvgis_hourly(times: list[str], power_w: list[float], year: int) -> pd.Series:
    """Converte le serie orarie PVGIS (UTC, 'YYYYMMDD:HHMM', W per 1 kWp) sull'anno civile italiano.

    L'anno UTC di PVGIS e l'anno civile italiano differiscono di un'ora ai bordi:
    l'ora mancante (la mezzanotte del 1° gennaio, di notte) vale 0.
    """
    stamps = pd.to_datetime(times, format="%Y%m%d:%H%M", utc=True).floor("h")
    serie = pd.Series(np.asarray(power_w, dtype=float) / 1000.0, index=stamps)
    serie = serie[~serie.index.duplicated()]
    idx = year_index(year)
    mancanti = idx.difference(serie.index)
    if len(mancanti) > 2:
        raise ValueError(f"Serie PVGIS incompleta per il {year}: {len(mancanti)} ore mancanti")
    return serie.reindex(idx, fill_value=0.0).clip(lower=0.0).rename("kw_per_kwp")


def pvgis_profile(
    lat: float,
    lon: float,
    tilt: float,
    azimut: float,
    perdite_pct: float,
    year: int,
    *,
    cache_dir: Path | None = None,
    timeout: float = 60.0,
) -> PVProfile:
    """Profilo PVGIS per 1 kWp, dalla cache se valida, altrimenti scaricato."""
    if year not in ANNI_METEO:
        raise ValueError(f"Anno meteo non supportato: {year} (ammessi: {ANNI_METEO})")
    params = _parametri(lat, lon, tilt, azimut, perdite_pct, year)
    percorso = (cache_dir or default_cache_dir()) / _nome_cache(params)

    with _lock_per(str(percorso)):  # una sola richiesta per chiave anche con sessioni concorrenti
        dati = _leggi_cache(percorso)
        cache_hit = dati is not None
        if dati is None:
            risposta = requests.get(PVGIS_URL, params=params, timeout=timeout)
            risposta.raise_for_status()
            orarie = risposta.json()["outputs"]["hourly"]
            dati = {
                "scaricato_il": datetime.now(timezone.utc).isoformat(),
                "parametri": params,
                "time": [h["time"] for h in orarie],
                "P": [h["P"] for h in orarie],
            }
            _scrivi_cache_atomica(percorso, dati)

    serie = parse_pvgis_hourly(dati["time"], dati["P"], year)
    return PVProfile(kw_per_kwp=serie, year=year, fonte="PVGIS", qualita="B", cache_hit=cache_hit)


# Rapporto medio mensile tra irraggiamento reale e di cielo sereno (ipotesi del
# fallback, tarata a mano per l'Italia; corretta con la latitudine).
_SERENITA_MENSILE = np.array([0.55, 0.60, 0.65, 0.68, 0.70, 0.75, 0.80, 0.78, 0.72, 0.62, 0.55, 0.52])


def synthetic_profile(lat: float, lon: float, tilt: float, azimut: float, perdite_pct: float, year: int) -> PVProfile:
    """Profilo approssimato senza rete: geometria solare + cielo sereno (Haurwitz) attenuato."""
    idx = year_index(year)
    t = idx + pd.Timedelta(minutes=30)
    doy = np.asarray(t.dayofyear, dtype=float)
    ore_utc = np.asarray(t.hour + t.minute / 60.0, dtype=float)

    phi = math.radians(lat)
    beta = math.radians(tilt)
    gamma = math.radians(azimut)
    delta = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365)
    b = 2 * np.pi * (doy - 81) / 364
    eot_min = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)
    ora_solare = ore_utc + lon / 15.0 + eot_min / 60.0
    h = np.radians(15.0 * (ora_solare - 12.0))

    cos_z = np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.cos(h)
    sole = cos_z > 0.05
    ghi_sereno = np.where(sole, 1098.0 * cos_z * np.exp(-0.057 / np.where(sole, cos_z, 1.0)), 0.0)
    serenita = np.clip(_SERENITA_MENSILE[np.asarray(t.month) - 1] + (45.0 - lat) * 0.01, 0.3, 0.9)
    ghi = ghi_sereno * serenita

    cos_inc = (
        np.sin(delta) * np.sin(phi) * np.cos(beta)
        - np.sin(delta) * np.cos(phi) * np.sin(beta) * np.cos(gamma)
        + np.cos(delta) * np.cos(phi) * np.cos(beta) * np.cos(h)
        + np.cos(delta) * np.sin(phi) * np.sin(beta) * np.cos(gamma) * np.cos(h)
        + np.cos(delta) * np.sin(beta) * np.sin(gamma) * np.sin(h)
    )
    diretta = 0.75 * ghi
    diffusa = 0.25 * ghi
    poa = (
        np.where(sole, diretta * np.clip(cos_inc, 0, None) / np.maximum(cos_z, 0.087), 0.0)
        + diffusa * (1 + math.cos(beta)) / 2
        + ghi * 0.2 * (1 - math.cos(beta)) / 2
    )
    kw = np.clip(poa / 1000.0 * (1 - perdite_pct / 100.0) * 0.95, 0.0, 1.0)
    return PVProfile(
        kw_per_kwp=pd.Series(kw, index=idx, name="kw_per_kwp"),
        year=year,
        fonte="sintetico",
        qualita="C",
        avviso="PVGIS non disponibile: produzione stimata con un modello semplificato",
    )


def pv_profile(lat, lon, tilt, azimut, perdite_pct, year, *, cache_dir=None, allow_fallback=True) -> PVProfile:
    """PVGIS se possibile; altrimenti, se consentito, il fallback sintetico (qualità C)."""
    if year not in ANNI_METEO:
        raise ValueError(f"Anno meteo non supportato: {year} (ammessi: {ANNI_METEO})")
    try:
        return pvgis_profile(lat, lon, tilt, azimut, perdite_pct, year, cache_dir=cache_dir)
    except (requests.RequestException, KeyError, ValueError):
        if not allow_fallback:
            raise
        return synthetic_profile(lat, lon, tilt, azimut, perdite_pct, year)


def media_profili(profili: list[PVProfile], pesi: list[float]) -> PVProfile:
    """Profilo per 1 kWp di un impianto con i moduli su più orientamenti e un solo inverter: media dei profili
    pesata sui kWp di ogni orientamento. La produzione DC è lineare nei kWp, quindi la media è esatta; il limite
    dell'inverter si applica poi alla somma (`plant_output`)."""
    totale = sum(pesi)
    serie = sum(p.kw_per_kwp * (w / totale) for p, w in zip(profili, pesi))
    fonti = {p.fonte for p in profili}
    return PVProfile(
        kw_per_kwp=serie.rename("kw_per_kwp"),
        year=profili[0].year,
        fonte=fonti.pop() if len(fonti) == 1 else "sintetico",
        qualita=max(p.qualita for p in profili),  # 'C' > 'B': vale la peggiore
        cache_hit=all(p.cache_hit for p in profili),
        avviso=next((p.avviso for p in profili if p.avviso), None),
    )


def plant_output(kw_per_kwp: np.ndarray, potenza_moduli_kwp: float, potenza_inverter_kw: float, fattore_degrado: float = 1.0) -> np.ndarray:
    """Produzione oraria dell'impianto (kWh): moduli DC scalati e limitati dalla potenza inverter."""
    return np.minimum(np.asarray(kw_per_kwp) * potenza_moduli_kwp * fattore_degrado, potenza_inverter_kw)
