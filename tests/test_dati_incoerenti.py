"""Dati incoerenti: un contatore a zero non rovina la comunità, un risultato non finito non arriva mai agli euro."""

import base64
import json
from datetime import date, timedelta
from functools import partial

import numpy as np
import pytest

from cersim import web
from cersim.analisi import analizza
from cersim.economics import ParametriEconomici
from cersim.loads import _tara, load_profile_anno
from cersim.model import CELLE_CURVA, ConnectionPoint, CurvaMisurata, Fasce, NaturaCurva
from cersim.pv import synthetic_profile
from cersim.ui_model import esporta_json, importa_json
from conftest import configurazione, impianto, membro, punto
from test_web import progetto, risposta_pvgis


def csv_tutto_zero(giorni=120) -> bytes:
    ore = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)] + ["00:00"]
    testa = "Giorno;" + ";".join(f"{a}-{b}" for a, b in zip(ore, ore[1:])) + ";\n"
    righe = "".join(f'"{date(2025, 3, 3) + timedelta(days=i):%d/%m/%Y}";' + ";".join(['"0,000"'] * 96) + ";\n"
                    for i in range(giorni))
    return (testa + righe).encode()


def serie_del_progetto(testo: str) -> dict:
    return {r["chiave"]: risposta_pvgis(r["parametri"]) for r in web.richieste_pvgis(testo)}


def test_consumo_zero_resta_zero_senza_nan():
    cp = punto("p1", "m1", kwh_annui=0.0)
    assert np.array_equal(_tara(np.zeros(5), np.array(["F1"] * 5), cp), np.zeros(5))


def test_fascia_senza_forma_conserva_il_consumo():
    cp = punto("p1", "m1", kwh_annui=None, fasce=Fasce(f1=100.0, f23=200.0))
    fascia = np.array(["F1", "F1", "F2", "F3"])
    out = _tara(np.array([0.0, 0.0, 1.0, 3.0]), fascia, cp)
    assert np.isfinite(out).all()
    assert out[:2].sum() == pytest.approx(100.0)
    assert out[2:].sum() == pytest.approx(200.0)


def test_curva_a_zero_con_consumo_positivo_rifiutata():
    with pytest.raises(ValueError, match="tutta a zero"):
        CurvaMisurata(ore=(0.0,) * CELLE_CURVA, natura=NaturaCurva.CALCOLATA, kwh_annui=1000.0, fonte="prova")


def test_file_del_distributore_a_zero_accettato_con_avviso():
    r = web.leggi_consumi([{"nome": "curva.csv", "base64": base64.b64encode(csv_tutto_zero()).decode()}])
    assert r["ok"] and r["curva"]["kwh_annui"] == 0
    assert any("zero" in a for a in r["avvisi"])


def test_un_contatore_a_zero_non_rovina_la_comunita():
    curva = web.leggi_consumi([{"nome": "curva.csv", "base64": base64.b64encode(csv_tutto_zero()).decode()}])["curva"]
    testo = progetto()
    dati = json.loads(testo)
    dati["configurazione"]["connection_points"][1]["curva_misurata"] = curva
    dati["configurazione"]["connection_points"][1]["kwh_annui"] = None
    testo = json.dumps(dati)
    r = web.risultati(testo, serie_del_progetto(testo), n_anni=2)
    assert r["ok"] and r["economia_disabilitata"] is None
    frase = "".join(t for t, _ in r["frase"])
    assert "nan" not in frase.lower() and "inf" not in frase.lower().replace("infatti", "")
    assert all(c["valore"] is not None for c in r["cifre"])


def test_serie_non_finita_ferma_gli_euro():
    def fv_rotto(lat, lon, tilt, azimut, perdite_pct, year, **_):
        p = synthetic_profile(lat, lon, tilt, azimut, perdite_pct, year)
        p.kw_per_kwp.iloc[3000] = float("nan")
        return p

    config = configurazione(members=[membro("m1"), membro("m2")], cps=[punto("p1", "m1"), punto("p2", "m2")],
                            plants=[impianto("fv", "p1", "m1")])
    a = analizza(config, ParametriEconomici(quota_membri=0.5), fetch_pv=fv_rotto, n_anni=2, con_sensibilita=False)
    assert a.dati_incoerenti and a.economia_disabilitata and a.base is None and not a.esiti


def test_risposta_web_senza_numeri_se_i_controlli_falliscono(monkeypatch):
    testo = progetto()
    originale = web.analizza

    def rompi(*args, **kwargs):
        a = originale(*args, **kwargs)
        a.dati_incoerenti, a.economia_disabilitata = True, "Bilanci non chiusi"
        return a

    monkeypatch.setattr(web, "analizza", rompi)
    r = web.risultati(testo, serie_del_progetto(testo), n_anni=2)
    assert r["ok"] is False and "Bilanci non chiusi" in r["errore"]
    assert "frase" not in r


@pytest.mark.parametrize("parametri, parola", [
    ({"tasso_sconto": -1.0}, "tasso"),
    ({"tasso_sconto": 0.5}, "tasso"),
    ({"costo_evitabile_eur_kwh": -1.0}, "costo"),
    ({"regime_vendita": "boh"}, "regime"),
    ({"quota_membri": 2}, "quota"),
    ({"tasso_sconto": "tanto"}, "tasso"),
    ({"tasso_sconto": True}, "tasso"),
    ({"gestione_eur_anno": -5}, "gestione"),
])
def test_parametri_fuori_intervallo_rifiutati(parametri, parola):
    config = configurazione(members=[membro("m1")], cps=[punto("p1", "m1")], plants=[])
    with pytest.raises(ValueError, match=parola):
        importa_json(esporta_json(config, parametri))
    assert web.risultati(esporta_json(config, parametri), {})["ok"] is False


def test_parametri_validi_e_vuoti_restano_accettati():
    config = configurazione(members=[membro("m1")], cps=[punto("p1", "m1")], plants=[])
    validi = {"quota_membri": 0.3, "costo_evitabile_eur_kwh": 0.2, "tasso_sconto": 0.0, "regime_vendita": "mercato",
              "om_assicurazione_quota_anno": None, "gestione_eur_anno": 0, "costituzione_eur": 100_000}
    assert importa_json(esporta_json(config, validi))[1] == validi


@pytest.mark.parametrize("campo", [{"tasso_sconto": -1.0}, {"costo_evitabile_eur_kwh": -0.1}, {"regime_vendita": "boh"}])
def test_parametri_economici_rifiutano_valori_assurdi(campo):
    with pytest.raises(ValueError):
        ParametriEconomici(quota_membri=0.5, **campo)


def test_profilo_annuo_di_un_contatore_a_zero():
    curva = CurvaMisurata(ore=(0.0,) * CELLE_CURVA, giorni=120, dal=date(2025, 1, 1), al=date(2025, 5, 1), kwh_annui=0.0,
                          fonte="prova")
    cp = ConnectionPoint(id="z", titolare="m1", tipologia_profilo="domestico", curva_misurata=curva)
    assert load_profile_anno(cp, 2027).sum() == 0
