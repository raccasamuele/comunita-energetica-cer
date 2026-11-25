from datetime import date

import numpy as np
import pytest

from cersim.economics import CONFIGURAZIONE, ParametriEconomici, costruisci_ledger, kpi, payback, tir
from cersim.eligibility import check
from cersim.model import TERZO, CapitalGrant, Incasso
from cersim.prices import prezzo_costante
from cersim.pv import synthetic_profile
from cersim.simulate import simulate_project
from conftest import configurazione, impianto, membro, punto

PV = synthetic_profile(45.07, 7.69, 30, 0, 14, 2023)


def _scenario(plants=None, n_years=3, quota=0.5, members=None, cps=None, prezzo=110, **params):
    cfg = configurazione(plants=plants, members=members, cps=cps)
    rep = check(cfg)
    en = simulate_project(cfg, rep, {p.id: PV for p in cfg.plants}, 2023, n_years=n_years)
    pz = [prezzo_costante(prezzo, 2023).per_anno_progetto(r.year) for r in en.anni]
    led = costruisci_ledger(cfg, rep, en, pz, ParametriEconomici(quota_membri=quota, **params))
    return cfg, led


def test_vendita_negativa_resta_nel_ledger_in_verso_opposto():
    cfg, led = _scenario(prezzo=-30)
    anno = led.anno_inizio + 1
    vendita = [m for m in led.movimenti if m.anno == anno and m.voce == "vendita energia"]
    assert len(vendita) == 1 and vendita[0].pagatore == "cond" and vendita[0].percettore == "GSE"
    assert vendita[0].importo == pytest.approx(-led.contributi[1].vendita_per_impianto["fv1"])
    totale = sum(led.flussi_soggetto(s) for s in led.soggetti())
    np.testing.assert_allclose(totale, 0, atol=1e-6)


def test_solo_fotovoltaico_senza_configurazione():
    grant = CapitalGrant(importo_eur=5000, intensita=0.3, estremi_atto="Det. 1",
                         scadenzario_incassi=[Incasso(data=date(2027, 9, 1), importo_eur=5000)])
    _, led = _scenario(plants=[impianto("fv1", "podc", "cond", contributo_capitale=grant)], con_configurazione=False)
    voci = {m.voce for m in led.movimenti}
    assert voci.isdisjoint({"tariffa premio (TIP)", "valorizzazione ARERA (CACV)", "corrispettivi GSE",
                            "gestione configurazione", "costituzione configurazione", "contributo in capitale"})
    assert {"vendita energia", "risparmio in bolletta", "CAPEX impianto"} <= voci
    assert "spetta solo con la configurazione" in led.contributi_esclusi[0]


def test_costi_da_preventivo():
    _, led = _scenario(plants=[impianto("fv1", "podc", "cond", costo_preventivo_eur=21_000)],
                       om_assicurazione_quota_anno=0.01, gestione_eur_anno=500, costituzione_eur=1000)
    anno = led.anno_inizio + 1
    capex = next(m for m in led.movimenti if m.voce == "CAPEX impianto")
    assert capex.importo == 21_000 and capex.base == "preventivo"
    om = next(m for m in led.movimenti if m.anno == anno and m.voce == "manutenzione e assicurazione")
    assert om.importo == pytest.approx(210)
    assert next(m for m in led.movimenti if m.anno == anno and m.voce == "gestione configurazione").importo == 500
    assert next(m for m in led.movimenti if m.voce == "costituzione configurazione").importo == 1000


def test_un_membro_non_puo_chiamarsi_come_un_conto_esterno():
    members = [membro("fam1"), membro("GSE"), membro("cond", "condominio")]
    cps = [punto("pod1", "fam1"), punto("pod2", "GSE"), punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=4000)]
    with pytest.raises(ValueError, match="riservato"):
        configurazione(members=members, cps=cps)


def test_tir_e_payback():
    assert tir(np.array([-100.0, 60, 60])) == pytest.approx(0.1307, abs=1e-4)
    assert tir(np.array([-100.0, 50, -30, 100])) is None  # tre cambi di segno: TIR non definito
    assert tir(np.array([100.0, 50])) is None
    assert payback(np.array([-100.0, 40, 40, 40])) == 3
    assert payback(np.array([-100.0, 40, 40, 40]), 0.1) is None
    assert payback(np.array([-100.0, 10])) is None


def test_ledger_in_pareggio_e_importi_positivi():
    _, led = _scenario()
    assert all(m.importo > 0 for m in led.movimenti)
    totale = sum(led.flussi_soggetto(s) for s in led.soggetti())
    np.testing.assert_allclose(totale, 0, atol=1e-6)


def test_van_consolidato_non_dipende_dal_riparto():
    vans = [kpi(cfg, led).van_consolidato for cfg, led in (_scenario(quota=q) for q in (0.0, 0.5, 1.0))]
    assert vans[0] == pytest.approx(vans[1]) == pytest.approx(vans[2])
    inv = [kpi(cfg, led).van_investitore for cfg, led in (_scenario(quota=q) for q in (0.0, 1.0))]
    assert inv[0] > inv[1]  # più riparto ai membri, meno all'investitore


def test_riparto_pro_quota_e_somma():
    cfg, led = _scenario(quota=0.6)
    anno = led.anno_inizio + 1
    riparto = [m for m in led.movimenti if m.anno == anno and m.voce == "riparto ai membri"]
    investitore = [m for m in led.movimenti if m.anno == anno and m.voce == "quota all'investitore"]
    totale = sum(m.importo for m in riparto) + sum(m.importo for m in investitore)
    assert sum(m.importo for m in riparto) == pytest.approx(0.6 * totale)
    assert {m.pagatore for m in riparto} == {CONFIGURAZIONE}


def test_tip_finisce_dopo_vent_anni_il_cacv_no():
    _, led = _scenario(n_years=25, plants=[impianto("fv1", "podc", "cond", entrata=date(2027, 1, 1))])
    tip = {m.anno for m in led.movimenti if m.voce == "tariffa premio (TIP)"}
    cacv = {m.anno for m in led.movimenti if m.voce.startswith("valorizzazione")}
    assert max(tip) == 2046 and max(cacv) == 2051


def test_contributo_senza_scadenzario_escluso_dal_van():
    grant = CapitalGrant(importo_eur=8000, intensita=0.4, estremi_atto="Decreto n. 1")
    cfg, led = _scenario(plants=[impianto("fv1", "podc", "cond", contributo_capitale=grant)])
    assert not any(m.voce == "contributo in capitale" for m in led.movimenti)
    assert "escluso dal VAN" in led.contributi_esclusi[0]

    con_date = CapitalGrant(importo_eur=8000, intensita=0.4, estremi_atto="Decreto n. 1",
                            scadenzario_incassi=[Incasso(data=date(2027, 6, 1), importo_eur=3000),
                                                 Incasso(data=date(2028, 6, 1), importo_eur=5000)])
    cfg2, led2 = _scenario(plants=[impianto("fv1", "podc", "cond", contributo_capitale=con_date)])
    incassi = {m.anno: m.importo for m in led2.movimenti if m.voce == "contributo in capitale"}
    assert incassi == {2027: 3000, 2028: 5000}
    assert kpi(cfg2, led2).van_investitore > kpi(cfg, led).van_investitore


def test_investitore_terzo_fuori_dal_consolidato():
    cfg, led = _scenario(plants=[impianto("fv1", "podc", TERZO)])
    capex = [m for m in led.movimenti if m.voce == "CAPEX impianto"]
    assert capex and capex[0].pagatore == TERZO
    # il condominio non paga l'impianto: il VAN consolidato è il beneficio netto per i membri
    k = kpi(cfg, led)
    assert k.investitore == TERZO and k.van_consolidato > 0


def test_quota_membri_obbligatoria_e_valida():
    with pytest.raises(TypeError):
        ParametriEconomici()
    with pytest.raises(ValueError):
        ParametriEconomici(quota_membri=1.5)


def test_avviso_quota_eccedentaria():
    # molte famiglie e poco FV: quasi tutta l'immessa è condivisa (> 55%)
    members = [membro(f"f{i}") for i in range(10)] + [membro("bar", "pmi"), membro("cond", "condominio")]
    cps = [punto(f"p{i}", f"f{i}", kwh_annui=3000) for i in range(10)]
    cps += [punto("pbar", "bar", tipologia_profilo="ufficio_commerciale", kwh_annui=20000),
            punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=1000)]
    _, led = _scenario(members=members, cps=cps, plants=[impianto("fv1", "podc", "cond", kwp=5)], quota=0.0)
    assert any(c.importo_eccedentario > 0 for c in led.contributi)
    assert any("quota eccedentaria" in a for a in led.avvisi)
