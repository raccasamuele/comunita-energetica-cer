from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

from cersim.economics import ParametriEconomici
from cersim.eligibility import check
from cersim.model import CapitalGrant, Fasce, Incasso
from cersim.prices import PriceSeries
from cersim.pv import synthetic_profile
from cersim.scenari import Scenario, bande, esegui_scenari, qualita_complessiva, scenari_standard, sensibilita
from cersim.sizing import dimensiona, griglia
from cersim.timebase import TZ, year_index
from conftest import configurazione, impianto, membro, punto

PARAMS = ParametriEconomici(quota_membri=0.5)


def _pv(anni=(2021, 2022, 2023), qualita="C"):
    out = {}
    for a in anni:
        p = synthetic_profile(45.07, 7.69, 30, 0, 14, a)
        out[a] = {"fv1": replace(p, qualita=qualita)}
    return out


def _prezzi_orari(anno):
    idx = year_index(anno)
    ora = idx.tz_convert(TZ).hour
    valori = np.where((ora >= 10) & (ora <= 15), 70.0, 130.0)
    return PriceSeries(pd.Series(valori, index=idx), anno, "NORD", "test", "B")


def _config_b(kwp=20, kwp_max=None):
    members = [membro(f"f{i}") for i in range(8)] + [membro("cond", "condominio")]
    cps = [punto(f"p{i}", f"f{i}", kwh_annui=2700, fasce=Fasce(f1=900, f23=1800)) for i in range(8)]
    cps.append(punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=4000, fasce=Fasce(f1=2000, f23=2000)))
    return configurazione(members=members, cps=cps,
                          plants=[impianto("fv1", "podc", "cond", kwp=kwp, potenza_moduli_max_kwp=kwp_max)])


def test_scenari_standard_e_prezzi_recenti():
    s = scenari_standard(anni_prezzi_recenti=(2024, 2025))
    assert len(s) == 3 * 3 + 2 * 3
    recenti = [x for x in s if x.anno_prezzi in (2024, 2025)]
    assert {x.anno_meteo for x in recenti} == {2023}
    assert "prezzi 2025" in recenti[-1].etichetta


def test_banda_ordinata_e_qualita():
    cfg = configurazione()
    rep = check(cfg)
    pv = _pv()
    esiti = esegui_scenari(cfg, rep, PARAMS, pv, {}, scenari_standard(), n_anni=3)
    assert len(esiti) == 9
    for b in bande(esiti).values():
        assert b.minimo <= b.mediana <= b.massimo
    assert bande(esiti)["van_consolidato"].minimo < bande(esiti)["van_consolidato"].massimo  # i prezzi contano
    assert qualita_complessiva(cfg, pv, esiti) == "C"  # FV sintetico, prezzo costante, famiglia tipo


def test_prezzi_orari_usati_nella_tip():
    cfg = _config_b()
    rep = check(cfg)
    pv = _pv(qualita="B")
    esito = esegui_scenari(cfg, rep, PARAMS, pv, {2023: _prezzi_orari(2023)}, [Scenario(2023, 2023, "base")], n_anni=2)[0]
    assert esito.qualita_prezzi == "B"
    assert qualita_complessiva(cfg, pv, [esito]) == "B"


def test_sensibilita_ordinata_e_coerente():
    cfg = configurazione()
    voci = sensibilita(cfg, check(cfg), PARAMS, _pv(), {}, Scenario(2023, 2023, "base"), n_anni=3)
    ampiezze = [v.ampiezza for v in voci]
    assert ampiezze == sorted(ampiezze, reverse=True)
    capex = next(v for v in voci if v.parametro == "costo dell'impianto")
    assert capex.van_consolidato_basso > capex.van_consolidato_alto  # CAPEX più basso → VAN più alto
    prezzi = next(v for v in voci if v.parametro == "livello dei prezzi")
    assert prezzi.van_consolidato_alto != prezzi.van_consolidato_basso


def test_griglia_include_le_soglie():
    p = impianto("fv1", "podc", "cond", kwp=300, kw_ac=250, potenza_moduli_max_kwp=700)  # DC/AC = 1,2
    punti = griglia(p)
    assert 240.0 in punti and 242.4 in punti  # nominale 200 kW = 240 kWp DC
    assert 720.0 not in punti  # soglia 600 kW oltre il massimo installabile
    assert max(punti) == 700 and 300.0 in punti


def test_dimensionamento_qualita_c_senza_taglia():
    cfg = configurazione(plants=[impianto("fv1", "podc", "cond", kwp=10, potenza_moduli_max_kwp=30)])
    r = dimensiona(cfg, "fv1", PARAMS, _pv(anni=(2023,)), {}, [Scenario(2023, 2023, "base")], n_punti=4, n_anni=2)
    assert r.curva and r.taglia_indicata is None and "esplorativa" in r.dicitura


def test_dimensionamento_qualita_b():
    cfg = _config_b(kwp=10, kwp_max=40)
    r = dimensiona(cfg, "fv1", PARAMS, _pv(anni=(2023,), qualita="B"), {2023: _prezzi_orari(2023)},
                   [Scenario(2023, 2023, "base")], n_punti=5)  # 25 anni: l'investimento ha il tempo di rientrare
    assert r.qualita == "B" and r.taglia_indicata is not None
    assert r.taglia_indicata.van_consolidato_mediano == max(p.van_consolidato_mediano for p in r.curva) > 0
    quote = [p.quota_condivisa_su_immessa for p in r.curva]
    assert quote == sorted(quote, reverse=True)  # più FV → quota condivisa non crescente
    assert "beneficio netto mediano" in r.dicitura


def test_dimensionamento_tutte_le_taglie_in_perdita_indica_non_investire():
    cfg = _config_b(kwp=10, kwp_max=40)
    r = dimensiona(cfg, "fv1", PARAMS, _pv(anni=(2023,), qualita="B"), {2023: _prezzi_orari(2023)},
                   [Scenario(2023, 2023, "base")], n_punti=4, n_anni=3)  # in 3 anni il CAPEX non rientra
    assert r.qualita == "B" and max(p.van_consolidato_mediano for p in r.curva) < 0
    assert r.taglia_indicata is None and "non investire" in r.dicitura


def test_dimensionamento_esclude_il_contributo_in_capitale():
    grant = CapitalGrant(importo_eur=5000, fattore_F=0.2, estremi_atto="Det. 1/2027",
                         scadenzario_incassi=[Incasso(data=date(2027, 6, 1), importo_eur=5000)])
    senza = _config_b(kwp=10, kwp_max=20)
    con = senza.model_copy(update={"plants": [senza.plants[0].model_copy(update={"contributo_capitale": grant})]})
    args = ("fv1", PARAMS, _pv(anni=(2023,), qualita="B"), {2023: _prezzi_orari(2023)}, [Scenario(2023, 2023, "base")])
    r_con, r_senza = dimensiona(con, *args, n_punti=2, n_anni=2), dimensiona(senza, *args, n_punti=2, n_anni=2)
    assert [p.van_consolidato_mediano for p in r_con.curva] == [p.van_consolidato_mediano for p in r_senza.curva]
    assert "contributo in capitale" in r_con.dicitura and "contributo in capitale" not in r_senza.dicitura


def test_prezzi_di_un_anno_recente_danno_forma_reale_agli_altri_anni():
    cfg = _config_b()
    pv = _pv(qualita="B")
    esiti = esegui_scenari(cfg, check(cfg), PARAMS, pv, {2024: _prezzi_orari(2024)},
                           scenari_standard(livelli=("base",), anni_prezzi_recenti=(2024,)), n_anni=2)
    assert all(e.qualita_prezzi == "B" for e in esiti)
    assert qualita_complessiva(cfg, pv, esiti) == "B"
    del_2021 = next(e for e in esiti if e.scenario.anno_meteo == 2021)
    assert "al posto del 2021" in del_2021.fonte_prezzi
