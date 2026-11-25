"""Base temporale: timeline UTC oraria, calendario civile italiano, fasce ARERA.

- Ogni anno è l'anno civile italiano (dalla mezzanotte del 1° gennaio ora di
  Roma), espresso come istanti UTC orari: 8760 ore, 8784 negli anni bisestili.
  Il cambio d'ora non cambia il numero di ore dell'anno, solo quelle dei due
  giorni di transizione (23 h a marzo, 25 h a ottobre).
- Calendario, festività e fasce si calcolano in ora civile Europe/Rome.
- `remap_reference_year` riporta una serie di un anno storico (meteo/prezzi
  2021–2023) sul calendario di un anno di progetto, allineando il giorno della
  settimana.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

TZ = ZoneInfo("Europe/Rome")

# Festività nazionali usate da ARERA per le fasce orarie (oltre a Pasquetta).
FESTIVITA_FISSE = [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)]

MAX_SHIFT_GIORNI = 3


@lru_cache(maxsize=128)
def year_index(year: int) -> pd.DatetimeIndex:
    """Istanti UTC di inizio di ogni ora dell'anno civile italiano `year`."""
    start = pd.Timestamp(year=year, month=1, day=1, tz=TZ).tz_convert("UTC")
    end = pd.Timestamp(year=year + 1, month=1, day=1, tz=TZ).tz_convert("UTC")
    return pd.date_range(start, end, freq="h", inclusive="left")


def easter_sunday(year: int) -> date:
    """Domenica di Pasqua (algoritmo gregoriano anonimo)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def italian_holidays(year: int) -> set[date]:
    """Festività nazionali dell'anno, Pasquetta inclusa."""
    holidays = {date(year, m, d) for m, d in FESTIVITA_FISSE}
    holidays.add(easter_sunday(year) + timedelta(days=1))
    return holidays


def local_frame(index_utc: pd.DatetimeIndex) -> pd.DataFrame:
    """Informazioni di calendario civile per ogni istante UTC.

    Colonne: `day` (giorno dell'anno, da 0), `hour` (0–23, ora civile),
    `fold` (1 per la seconda occorrenza dell'ora ripetuta a ottobre),
    `month` (1–12), `weekday` (0 = lunedì), `day_type`
    ('feriale' | 'sabato' | 'festivo'), `fascia` ('F1' | 'F2' | 'F3').
    """
    local = index_utc.tz_convert(TZ)
    naive = local.tz_localize(None)
    day_start = naive.normalize()
    year = int(naive[0].year)
    day = np.asarray((day_start - pd.Timestamp(year=year, month=1, day=1)).days)
    hour = np.asarray(naive.hour)
    fold = np.asarray(naive.duplicated(), dtype=int)
    weekday = np.asarray(naive.weekday)

    years = sorted(set(naive.year))
    holidays = pd.to_datetime(sorted(d for y in years for d in italian_holidays(y)))
    is_holiday = np.asarray(day_start.isin(holidays))

    day_type = np.where(is_holiday | (weekday == 6), "festivo", np.where(weekday == 5, "sabato", "feriale"))

    fascia = np.full(len(index_utc), "F3", dtype=object)
    feriale = day_type == "feriale"
    sabato = day_type == "sabato"
    fascia[feriale & (hour >= 8) & (hour < 19)] = "F1"
    fascia[feriale & ((hour == 7) | ((hour >= 19) & (hour < 23)))] = "F2"
    fascia[sabato & (hour >= 7) & (hour < 23)] = "F2"

    return pd.DataFrame(
        {
            "day": day,
            "hour": hour,
            "fold": fold,
            "month": np.asarray(naive.month),
            "weekday": weekday,
            "day_type": day_type,
            "fascia": fascia,
        },
        index=index_utc,
    )


@lru_cache(maxsize=128)
def calendario_anno(year: int) -> pd.DataFrame:
    """`local_frame` dell'anno intero, calcolato una volta sola (da non modificare)."""
    return local_frame(year_index(year))


@lru_cache(maxsize=128)
def calendario_np(year: int) -> dict[str, np.ndarray]:
    """Colonne del calendario annuale come array numpy in sola lettura (accesso veloce)."""
    cal = calendario_anno(year)
    out = {}
    for col in cal.columns:
        dtype = str if col in ("day_type", "fascia") else None
        arr = np.asarray(cal[col].to_numpy(dtype=dtype))
        arr.setflags(write=False)
        out[col] = arr
    return out


def frame_per(index_utc: pd.DatetimeIndex) -> pd.DataFrame:
    """Calendario per un indice: usa la cache se l'indice è un anno intero."""
    if len(index_utc):
        year = int(index_utc[0].tz_convert(TZ).year)
        full = year_index(year)
        if len(index_utc) == len(full) and index_utc[0] == full[0] and index_utc[-1] == full[-1]:
            return calendario_anno(year)
    return local_frame(index_utc)


def weekday_shift(ref_year: int, target_year: int) -> int:
    """Spostamento in giorni (|k| ≤ 3) che allinea il giorno della settimana."""
    diff = (date(target_year, 1, 1).weekday() - date(ref_year, 1, 1).weekday()) % 7
    return diff if diff <= MAX_SHIFT_GIORNI else diff - 7


@dataclass(frozen=True)
class Remap:
    """Mappatura ora per ora da un anno storico a un anno di progetto."""

    ref_year: int
    target_year: int
    shift_giorni: int
    positions: np.ndarray  # per ogni ora del target, posizione nell'anno storico

    def apply(self, values_ref) -> np.ndarray:
        values_ref = np.asarray(values_ref)
        if len(values_ref) != len(year_index(self.ref_year)):
            raise ValueError(f"La serie storica deve avere le ore dell'anno {self.ref_year}")
        return values_ref[self.positions]


@lru_cache(maxsize=256)
def remap_reference_year(ref_year: int, target_year: int) -> Remap:
    """Costruisce la mappatura dall'anno storico `ref_year` all'anno `target_year`.

    Regole (deterministiche):
    - il giorno n dell'anno di progetto prende il giorno storico n + k, con k
      costante (|k| ≤ 3) scelto perché coincida il giorno della settimana; così
      ogni giorno di progetto, 29 febbraio compreso, ha un giorno storico dello
      stesso tipo (lunedì→lunedì, …) e della stessa stagione;
    - ai bordi dell'anno i pochi giorni che escono dall'anno storico si
      riprendono dall'altro capo dello stesso anno (inverno con inverno; in
      quei giorni il giorno della settimana può differire di uno);
    - meteo e prezzi dello stesso anno storico usano la stessa mappatura, così
      la correlazione oraria sole–prezzi resta intatta;
    - ora civile: l'ora h del giorno di progetto prende l'ora h del giorno
      storico; l'ora ripetuta di ottobre prende la sua gemella storica se
      esiste, altrimenti l'ora h; un'ora che nel giorno storico non esiste
      (cambio d'ora di marzo) prende l'ora precedente.
    """
    ref = calendario_anno(ref_year)
    tgt = calendario_anno(target_year)
    k = weekday_shift(ref_year, target_year)
    n_days_ref = int(ref["day"].max()) + 1

    def key(day, hour, fold):
        return (np.asarray(day) * 24 + np.asarray(hour)) * 2 + np.asarray(fold)

    ref_keys = pd.Index(key(ref["day"], ref["hour"], ref["fold"]))
    mapped_day = (tgt["day"].to_numpy() + k) % n_days_ref
    hour = tgt["hour"].to_numpy()
    fold = tgt["fold"].to_numpy()

    positions = ref_keys.get_indexer(key(mapped_day, hour, fold))
    for alt_hour, alt_fold in ((hour, 0), (hour - 1, 0), (hour + 1, 0)):
        missing = positions < 0
        if not missing.any():
            break
        alt = ref_keys.get_indexer(key(mapped_day[missing], np.asarray(alt_hour)[missing], alt_fold))
        positions[missing] = alt
    if (positions < 0).any():
        raise RuntimeError("Rimappatura incompleta: ore senza corrispondenza nell'anno storico")
    return Remap(ref_year=ref_year, target_year=target_year, shift_giorni=k, positions=positions)
