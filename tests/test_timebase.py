from datetime import date

import numpy as np
import pandas as pd
import pytest

from cersim.timebase import (
    TZ,
    easter_sunday,
    italian_holidays,
    local_frame,
    remap_reference_year,
    weekday_shift,
    year_index,
)


@pytest.mark.parametrize("anno, ore", [(2023, 8760), (2027, 8760), (2028, 8784)])
def test_ore_per_anno(anno, ore):
    idx = year_index(anno)
    assert len(idx) == ore
    assert idx.is_unique
    assert str(idx.tz) == "UTC"
    assert idx[0].tz_convert(TZ) == pd.Timestamp(year=anno, month=1, day=1, tz=TZ)


def test_giorni_del_cambio_ora():
    cal = local_frame(year_index(2027))
    ore_per_giorno = cal.groupby("day").size()
    giorno = lambda m, d: (date(2027, m, d) - date(2027, 1, 1)).days
    assert ore_per_giorno[giorno(3, 28)] == 23  # ultima domenica di marzo 2027
    assert ore_per_giorno[giorno(10, 31)] == 25  # ultima domenica di ottobre 2027
    assert set(ore_per_giorno.drop([giorno(3, 28), giorno(10, 31)])) == {24}


def test_ora_ripetuta_distinta():
    cal = local_frame(year_index(2027))
    ripetute = cal[cal["fold"] == 1]
    assert len(ripetute) == 1
    assert ripetute["hour"].iloc[0] == 2
    # le due 02:00 di ottobre sono istanti UTC diversi
    due = cal[(cal["day"] == ripetute["day"].iloc[0]) & (cal["hour"] == 2)]
    assert len(due) == 2 and due.index.is_unique


@pytest.mark.parametrize("anno, pasqua", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2027, date(2027, 3, 28))])
def test_pasqua(anno, pasqua):
    assert easter_sunday(anno) == pasqua


def test_festivita_e_fasce():
    assert date(2027, 3, 29) in italian_holidays(2027)  # Pasquetta
    cal = local_frame(year_index(2027))
    locale = cal.index.tz_convert(TZ).tz_localize(None)

    def fascia(ts):
        return cal["fascia"].to_numpy()[locale.get_loc(pd.Timestamp(ts))]

    assert fascia("2027-01-11 10:00") == "F1"  # lunedì
    assert fascia("2027-01-11 07:00") == "F2"
    assert fascia("2027-01-11 19:00") == "F2"
    assert fascia("2027-01-11 23:00") == "F3"
    assert fascia("2027-01-16 10:00") == "F2"  # sabato
    assert fascia("2027-01-17 10:00") == "F3"  # domenica
    assert fascia("2027-01-06 10:00") == "F3"  # Epifania, mercoledì
    assert fascia("2027-03-29 12:00") == "F3"  # Pasquetta


@pytest.mark.parametrize("ref, target", [(2021, 2027), (2022, 2028), (2023, 2031), (2023, 2023)])
def test_rimappatura_allinea_giorno_settimana(ref, target):
    remap = remap_reference_year(ref, target)
    assert abs(remap.shift_giorni) <= 3
    t = local_frame(year_index(target))
    r = local_frame(year_index(ref))
    stesso = r["weekday"].to_numpy()[remap.positions] == t["weekday"].to_numpy()
    giorni_diversi = set(t["day"].to_numpy()[~stesso])
    assert len(giorni_diversi) <= 4  # solo ai bordi dell'anno


def test_rimappatura_completa_e_conservativa():
    ref_idx = year_index(2023)
    valori = np.random.default_rng(0).random(len(ref_idx))
    for target in (2027, 2028):  # anno normale e bisestile
        out = remap_reference_year(2023, target).apply(valori)
        assert len(out) == len(year_index(target))
        assert np.isfinite(out).all()
        rapporto = out.sum() / valori.sum() / (len(out) / len(valori))
        assert rapporto == pytest.approx(1.0, abs=0.01)


def test_rimappatura_stagione_preservata():
    # una serie che vale il mese di calendario: dopo la rimappatura il mese cambia al più ai bordi
    ref_idx = year_index(2023)
    mese_ref = local_frame(ref_idx)["month"].to_numpy().astype(float)
    out = remap_reference_year(2023, 2028).apply(mese_ref)
    mese_target = local_frame(year_index(2028))["month"].to_numpy()
    assert np.mean(out == mese_target) > 0.97


def test_rimappatura_ore_cambio_ora():
    ref_idx = year_index(2023)
    valori = np.arange(len(ref_idx), dtype=float)
    remap = remap_reference_year(2023, 2027)
    out = remap.apply(valori)
    cal = local_frame(year_index(2027))
    ottobre = cal[cal["day"] == (date(2027, 10, 31) - date(2027, 1, 1)).days]
    valori_ottobre = out[cal.index.get_indexer(ottobre.index)]
    assert len(valori_ottobre) == 25 and np.isfinite(valori_ottobre).all()


def test_shift():
    assert weekday_shift(2023, 2023) == 0
    assert all(abs(weekday_shift(r, t)) <= 3 for r in (2021, 2022, 2023) for t in range(2026, 2060))


def test_apply_rifiuta_lunghezza_sbagliata():
    with pytest.raises(ValueError):
        remap_reference_year(2023, 2027).apply(np.zeros(100))
