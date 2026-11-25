import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
import requests

from cersim import pv


def _finta_risposta_pvgis(anno):
    ore = pd.date_range(f"{anno}-01-01 00:10", f"{anno}-12-31 23:10", freq="h", tz="UTC")
    ora_locale = (ore.hour + 1) % 24
    potenza = np.where((ora_locale >= 8) & (ora_locale <= 16), 500.0, 0.0)  # W per 1 kWp
    orarie = [{"time": t.strftime("%Y%m%d:%H%M"), "P": float(p)} for t, p in zip(ore, potenza)]

    class Risposta:
        def raise_for_status(self):
            pass

        def json(self):
            return {"outputs": {"hourly": orarie}}

    return Risposta()


@pytest.fixture
def pvgis_finto(monkeypatch):
    chiamate = []

    def finto_get(url, params, timeout):
        chiamate.append(params)
        return _finta_risposta_pvgis(params["startyear"])

    monkeypatch.setattr(requests, "get", finto_get)
    return chiamate


def test_parse_allinea_all_anno_civile():
    risposta = _finta_risposta_pvgis(2023).json()["outputs"]["hourly"]
    serie = pv.parse_pvgis_hourly([h["time"] for h in risposta], [h["P"] for h in risposta], 2023)
    assert len(serie) == 8760
    assert serie.iloc[0] == 0.0  # mezzanotte del 1° gennaio (ora civile), assente nell'anno UTC
    assert serie.max() == pytest.approx(0.5)  # W → kW per kWp


def test_cache_atomica_e_coordinate_arrotondate(tmp_path, pvgis_finto):
    primo = pv.pvgis_profile(45.07123, 7.68654, 30, 0, 14, 2023, cache_dir=tmp_path)
    secondo = pv.pvgis_profile(45.0709, 7.6871, 30, 0, 14, 2023, cache_dir=tmp_path)
    assert not primo.cache_hit and secondo.cache_hit
    assert len(pvgis_finto) == 1  # stessa chiave dopo l'arrotondamento a 0,01°
    assert pvgis_finto[0]["lat"] == 45.07 and pvgis_finto[0]["lon"] == 7.69
    file = list(tmp_path.iterdir())
    assert len(file) == 1 and not file[0].name.startswith(".tmp")
    assert primo.fonte == "PVGIS" and primo.qualita == "B"
    pd.testing.assert_series_equal(primo.kw_per_kwp, secondo.kw_per_kwp)


def test_cache_scaduta(tmp_path, pvgis_finto):
    pv.pvgis_profile(45.07, 7.69, 30, 0, 14, 2023, cache_dir=tmp_path)
    percorso = next(tmp_path.iterdir())
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    dati["scaricato_il"] = (datetime.now(timezone.utc) - pv.CACHE_TTL - timedelta(days=1)).isoformat()
    percorso.write_text(json.dumps(dati), encoding="utf-8")
    assert not pv.pvgis_profile(45.07, 7.69, 30, 0, 14, 2023, cache_dir=tmp_path).cache_hit
    assert len(pvgis_finto) == 2


def test_fallback_sintetico_senza_rete(tmp_path):
    prof = pv.pv_profile(45.07, 7.69, 30, 0, 14, 2023, cache_dir=tmp_path)
    assert prof.fonte == "sintetico" and prof.qualita == "C" and prof.avviso
    with pytest.raises(requests.RequestException):
        pv.pv_profile(45.07, 7.69, 30, 0, 14, 2023, cache_dir=tmp_path, allow_fallback=False)


def test_anno_non_supportato():
    with pytest.raises(ValueError):
        pv.pv_profile(45.07, 7.69, 30, 0, 14, 2019)


def test_sintetico_plausibile():
    torino = pv.synthetic_profile(45.07, 7.69, 30, 0, 14, 2023)
    palermo = pv.synthetic_profile(38.12, 13.36, 30, 0, 14, 2023)
    assert 1100 < torino.producibilita_kwh_kwp < 1600
    assert palermo.producibilita_kwh_kwp > torino.producibilita_kwh_kwp
    est = pv.synthetic_profile(45.07, 7.69, 30, -90, 14, 2023)
    assert est.producibilita_kwh_kwp < torino.producibilita_kwh_kwp
    # a est si produce più di mattina che di pomeriggio (ora UTC: mezzogiorno solare ≈ 11:30 UTC a Torino)
    ore = est.kw_per_kwp.index.hour
    assert est.kw_per_kwp[ore < 11].sum() > est.kw_per_kwp[ore > 12].sum()


def test_clipping_inverter():
    profilo = np.array([0.0, 0.5, 0.9, 1.0])
    np.testing.assert_allclose(pv.plant_output(profilo, 210, 180), [0, 105, 180, 180])
    np.testing.assert_allclose(pv.plant_output(profilo, 10, 10, fattore_degrado=0.9), [0, 4.5, 8.1, 9.0])
