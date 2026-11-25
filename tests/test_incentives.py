from datetime import date

import numpy as np
import pytest

from cersim.eligibility import check
from cersim.incentives import contributi_anno, fattore_F, tip_oraria
from cersim.model import CapitalGrant
from cersim.normativa import PacchettoScadutoError, pacchetto_normativo
from cersim.simulate import simulate_year
from cersim.timebase import year_index
from conftest import configurazione, impianto, membro, punto

NORMA = pacchetto_normativo()


@pytest.mark.parametrize(
    "kw, regione, pz, attesa",
    [
        (20, "Piemonte", 50, 130),   # 80 + 130 → tetto 120, poi +10 Nord
        (20, "Piemonte", 150, 120),  # 80 + 30 + 10
        (20, "Piemonte", 200, 90),   # 80 + 0 + 10
        (20, "Lazio", 50, 124),      # Centro +4
        (20, "Sicilia", 50, 120),    # Sud
        (400, "Sicilia", 0, 110),
        (800, "Sicilia", 0, 100),
    ],
)
def test_tip_oraria(kw, regione, pz, attesa):
    assert tip_oraria(kw, regione, np.array([pz]), NORMA)[0] == pytest.approx(attesa)


def test_fascia_tip_da_potenza_nominale_gse():
    p = impianto("fv", "podc", "cond", kwp=210, kw_ac=180)
    assert tip_oraria(p.potenza_nominale_gse, "Sicilia", np.array([0.0]), NORMA)[0] == 120  # fascia ≤ 200 kW


def test_fattore_F():
    base = dict(importo_eur=1000, estremi_atto="n. 1")
    assert fattore_F(impianto("a", "podc", "cond"), NORMA) == 0
    assert fattore_F(impianto("a", "podc", "cond", contributo_capitale=CapitalGrant(fattore_F=0.3, **base)), NORMA) == 0.3
    assert fattore_F(impianto("a", "podc", "cond", contributo_capitale=CapitalGrant(intensita=0.2, **base)), NORMA) == pytest.approx(0.25)
    assert fattore_F(impianto("a", "podc", "cond", contributo_capitale=CapitalGrant(intensita=0.4, **base)), NORMA) == pytest.approx(0.5)


def _cer_un_ora(plants, cps=None, members=None):
    members = members or [membro("fam", "persona_fisica"), membro("bar", "pmi"), membro("cond", "condominio")]
    cps = cps or [punto("p_fam", "fam", area_convenzionale="A"), punto("p_bar", "bar", tipologia_profilo="pmi", kwh_annui=1, area_convenzionale="A"),
                  punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=1, area_convenzionale="A")]
    cfg = configurazione(tipo="CER", members=members, cps=cps, plants=plants)
    return cfg, check(cfg)


def _anno_costante(cfg, rep, carichi, produzione, anno=2028, ore=24):
    idx = year_index(anno)[:ore]
    loads = {k: np.full(ore, float(v)) for k, v in carichi.items()}
    prod = {k: np.full(ore, float(v)) for k, v in produzione.items()}
    return simulate_year(cfg, rep, idx, loads, prod)


def test_tip_con_F_solo_sulla_quota_non_esente():
    grant = CapitalGrant(importo_eur=10000, fattore_F=0.5, estremi_atto="n. 1")
    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond", contributo_capitale=grant)])
    yr = _anno_costante(cfg, rep, {"p_fam": 4, "p_bar": 2, "podc": 0}, {"fv1": 10}, ore=1)
    c = contributi_anno(cfg, rep, yr, np.array([200.0]))  # TIP = 90 €/MWh
    # EACI 6 kWh: 4 dei prelievi della persona fisica (esente), 2 del bar (non esente, F = 0,5)
    assert c.tip_esente_F_kwh["fv1"] == pytest.approx(4)
    assert c.tip == pytest.approx((4 * 90 + 2 * 90 * 0.5) / 1000)


def test_cacv_cer_e_gruppo():
    pz = np.full(24, 100.0)
    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond")])
    yr = _anno_costante(cfg, rep, {"p_fam": 1, "p_bar": 1, "podc": 0}, {"fv1": 5})
    c = contributi_anno(cfg, rep, yr, pz)
    assert c.cacv == pytest.approx(48 / 1000 * NORMA.trase(2028))  # 2 kWh × 24 ore
    assert set(c.cacv_componenti) == {"trasmissione"}

    gruppo = configurazione()
    rep_g = check(gruppo)
    yr_g = _anno_costante(gruppo, rep_g, {"pod1": 1, "pod2": 1, "pod3": 0, "podc": 0}, {"fv1": 5})
    c_g = contributi_anno(gruppo, rep_g, yr_g, pz)
    attesa = 48 / 1000 * (NORMA.trase(2028) + NORMA.btau(2028) + 0.026 * 100)  # impianto in BT
    assert c_g.cacv == pytest.approx(attesa)


def test_quota_eccedentaria():
    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond")])
    # immette 5, i prelievi ne assorbono 4: EACI/immessa = 80% → eccedenza 25 punti oltre il 55%
    yr = _anno_costante(cfg, rep, {"p_fam": 2, "p_bar": 2, "podc": 0}, {"fv1": 5})
    c = contributi_anno(cfg, rep, yr, np.full(24, 100.0))
    assert c.eccedenza["solo_tip"]["quota"] == pytest.approx(0.25)
    assert c.importo_eccedentario == pytest.approx(0.25 * c.tip)


def test_corrispettivi_solo_durante_la_tip_e_vendita():
    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond", kwp=50, entrata=date(2027, 1, 1))])
    durante = contributi_anno(cfg, rep, _anno_costante(cfg, rep, {"p_fam": 1, "p_bar": 1, "podc": 0}, {"fv1": 5}, 2030),
                              np.full(24, 100.0))
    dopo = contributi_anno(cfg, rep, _anno_costante(cfg, rep, {"p_fam": 1, "p_bar": 1, "podc": 0}, {"fv1": 5}, 2048),
                           np.full(24, 100.0))
    assert durante.corrispettivi_gse_per_impianto["fv1"] == 45 and dopo.corrispettivi_gse_per_impianto["fv1"] == 0
    assert dopo.tip == 0 and dopo.cacv > 0
    lordo = 5 * 24 / 1000 * 100  # si vende tutta l'immissione (anche la quota condivisa): 5 kWh/h × 24 h a 100 €/MWh
    # tariffa GSE del ritiro dedicato, per l'anno intero (DM 24/12/2014): 50 kW → 20 × 0,70 + 30 × 0,65 = 33,5 €
    assert durante.vendita_per_impianto["fv1"] == pytest.approx(lordo - 33.5)


def test_risparmio_al_titolare():
    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond")])
    yr = _anno_costante(cfg, rep, {"p_fam": 1, "p_bar": 1, "podc": 2}, {"fv1": 5})
    c = contributi_anno(cfg, rep, yr, np.full(24, 100.0), costo_evitabile_eur_kwh=0.2)
    assert c.risparmio_per_punto["podc"] == pytest.approx(2 * 24 * 0.2)
    assert c.risparmio_per_punto["p_fam"] == 0


def test_pacchetto_scaduto_blocca_i_contributi():
    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond")])
    yr = _anno_costante(cfg, rep, {"p_fam": 1, "p_bar": 1, "podc": 0}, {"fv1": 5})
    with pytest.raises(PacchettoScadutoError):
        contributi_anno(cfg, rep, yr, np.full(24, 100.0), oggi=date(2031, 1, 1))


def test_prezzi_di_lunghezza_sbagliata():
    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond")])
    yr = _anno_costante(cfg, rep, {"p_fam": 1, "p_bar": 1, "podc": 0}, {"fv1": 5})
    with pytest.raises(ValueError, match="ogni ora"):
        contributi_anno(cfg, rep, yr, np.full(10, 100.0))


def test_prezzo_della_bolletta_della_casa_per_fasce():
    from types import SimpleNamespace

    import pandas as pd

    from cersim.incentives import prezzo_bolletta
    from cersim.model import PrezzoBolletta

    # giovedì 2/1/2025 alle 10 (F1) e alle 20 (F2), sabato 4/1 alle 10 (F2), domenica 5/1 alle 10 (F3)
    ore = pd.DatetimeIndex(["2025-01-02 10:00", "2025-01-02 20:00", "2025-01-04 10:00", "2025-01-05 10:00"],
                           tz="Europe/Rome").tz_convert("UTC")
    fasce = PrezzoBolletta(eur_kwh=0.3, fasce={"F1": 0.32, "F2": 0.29, "F3": 0.25}, stato="documentato")
    unico = PrezzoBolletta(eur_kwh=0.3, stato="documentato")
    casa = lambda b: SimpleNamespace(profilo=SimpleNamespace(bolletta=b))
    np.testing.assert_allclose(prezzo_bolletta(casa(fasce), ore, 0.15), [0.32, 0.29, 0.29, 0.25])
    np.testing.assert_allclose(prezzo_bolletta(casa(unico), ore, 0.15), [0.3] * 4)
    np.testing.assert_allclose(prezzo_bolletta(casa(None), ore, 0.15), [0.15] * 4)
    np.testing.assert_allclose(prezzo_bolletta(SimpleNamespace(profilo=None), ore, 0.15), [0.15] * 4)


def test_fasce_della_bolletta_incomplete_rifiutate():
    from cersim.model import PrezzoBolletta

    with pytest.raises(ValueError, match="F1, F2 e F3"):
        PrezzoBolletta(eur_kwh=0.3, fasce={"F1": 0.32, "F2": 0.29}, stato="documentato")


def test_risparmio_con_il_prezzo_della_bolletta_della_casa():
    from cersim.model import PrezzoBolletta

    cfg, rep = _cer_un_ora([impianto("fv1", "podc", "cond")])
    yr = _anno_costante(cfg, rep, {"p_fam": 1, "p_bar": 1, "podc": 2}, {"fv1": 5})
    podc = cfg.connection_point("podc")
    bolletta = PrezzoBolletta(eur_kwh=0.3, stato="documentato")
    profilo = type("P", (), {"bolletta": bolletta})()
    cfg.connection_points[cfg.connection_points.index(podc)] = podc.model_copy(update={"profilo": profilo})
    c = contributi_anno(cfg, rep, yr, np.full(24, 100.0), costo_evitabile_eur_kwh=0.2)
    assert c.risparmio_per_punto["podc"] == pytest.approx(2 * 24 * 0.3)  # il prezzo della casa vince sullo scenario
