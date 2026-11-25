from datetime import date

import numpy as np
import pytest

from cersim.eligibility import UnsupportedConfigurationError, check
from cersim.model import ConnectionPoint, TERZO
from cersim.pv import synthetic_profile
from cersim.simulate import maschere_impianto, pv_profiles_for, simulate_project, simulate_year
from cersim.timebase import TZ, local_frame, year_index
from conftest import configurazione, impianto, membro, punto


def _costanti(n, **valori):
    return {k: np.full(n, float(v)) for k, v in valori.items()}


def test_autoconsumo_mai_oltre_il_carico():
    # carico 5, impianto da 4 sullo stesso punto: SC = 4, nessuna immissione
    cfg = configurazione(cps=[punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=1)], plants=[impianto("fv1", "podc", "cond")])
    idx = year_index(2028)[:4]
    r = simulate_year(cfg, check(cfg), idx, _costanti(4, podc=5), _costanti(4, fv1=4))
    np.testing.assert_allclose(r.SC, 4)
    np.testing.assert_allclose(r.I, 0)
    np.testing.assert_allclose(r.W, 1)
    assert r.violazioni_invarianti() == []


def test_energia_condivisa_a_mano():
    # tetto: produce 10, consuma 2 → immette 8; famiglie prelevano 1 + 2 + 3 = 6 → condivisa 6
    cfg = configurazione()
    idx = year_index(2028)[:3]
    loads = _costanti(3, pod1=1, pod2=2, pod3=3, podc=2)
    r = simulate_year(cfg, check(cfg), idx, loads, _costanti(3, fv1=10))
    np.testing.assert_allclose(r.EACV, 6)
    np.testing.assert_allclose(r.EACI, 6)
    np.testing.assert_allclose(r.EACVC, 6)  # gruppo: impianto nell'edificio
    np.testing.assert_allclose(r.EACV_per_punto[:, 0], [1, 2, 3, 0])  # riparto pro-quota prelievi
    assert r.violazioni_invarianti() == []


def test_condivisa_limitata_dall_immissione():
    cfg = configurazione()
    idx = year_index(2028)[:2]
    r = simulate_year(cfg, check(cfg), idx, _costanti(2, pod1=5, pod2=5, pod3=5, podc=1), _costanti(2, fv1=4))
    np.testing.assert_allclose(r.EACV, 3)  # immissione 3 < prelievi 15


def _due_impianti(data_a, data_b):
    members = [membro("a"), membro("b"), membro("c")]
    cps = [punto("pa", "a", kwh_annui=1), punto("pb", "b", kwh_annui=1), punto("pc", "c", kwh_annui=1)]
    plants = [impianto("fa", "pa", "a", entrata=data_a), impianto("fb", "pb", "b", entrata=data_b)]
    return configurazione(members=members, cps=cps, plants=plants, data_costituzione=date(2026, 1, 1))


def test_attribuzione_eaci_per_data_di_esercizio():
    cfg = _due_impianti(date(2027, 3, 1), date(2026, 6, 1))
    idx = year_index(2028)[:2]
    loads = _costanti(2, pa=0, pb=0, pc=5)
    r = simulate_year(cfg, check(cfg), idx, loads, _costanti(2, fa=4, fb=4))
    np.testing.assert_allclose(r.EACI, 5)
    np.testing.assert_allclose(r.EACI_per_impianto[:, 0], [1, 4])  # prima il più vecchio (fb)


def test_attribuzione_pro_quota_a_parita_di_data():
    cfg = _due_impianti(date(2027, 3, 1), date(2027, 3, 1))
    idx = year_index(2028)[:1]
    r = simulate_year(cfg, check(cfg), idx, _costanti(1, pa=0, pb=0, pc=5), _costanti(1, fa=4, fb=4))
    np.testing.assert_allclose(r.EACI_per_impianto[:, 0], [2.5, 2.5])


def test_maschere_orarie_in_ora_civile():
    p = impianto("fv1", "podc", "cond", entrata=date(2027, 5, 1),
                 data_decorrenza_servizio_cacer=date(2027, 7, 1), data_decorrenza_vendita=date(2027, 6, 1))
    idx = year_index(2027)
    m = maschere_impianto(p, idx)
    locale = idx.tz_convert(TZ)
    primo = locale[m.esercizio][0]
    assert (primo.month, primo.day, primo.hour) == (5, 1, 0)
    assert locale[m.servizio][0].month == 7
    assert locale[m.vendita][0].month == 6
    assert (m.tip <= m.servizio).all() and (m.servizio <= m.esercizio).all()


def test_tip_solo_nel_ventennio_mentre_il_cacv_prosegue():
    # adesione tardiva: servizio dal 2030, ma ventennio TIP dal 2027 → TIP fino a fine 2046
    plants = [impianto("fv1", "podc", "cond", entrata=date(2027, 1, 1), data_decorrenza_servizio_cacer=date(2030, 1, 1))]
    cfg = configurazione(plants=plants, data_costituzione=date(2026, 1, 1))
    rep = check(cfg)
    for anno, tip_attesa in ((2046, True), (2047, False), (2049, False)):
        idx = year_index(anno)[:24]
        r = simulate_year(cfg, rep, idx, _costanti(24, pod1=2, pod2=2, pod3=2, podc=0), _costanti(24, fv1=3))
        np.testing.assert_allclose(r.EACV, 3)
        np.testing.assert_allclose(r.EACI, 3 if tip_attesa else 0)


def test_vendita_solo_dalla_decorrenza():
    cfg = configurazione(plants=[impianto("fv1", "podc", "cond", data_decorrenza_vendita=date(2027, 9, 1))])
    idx = year_index(2027)
    n = len(idx)
    r = simulate_year(cfg, check(cfg), idx, _costanti(n, pod1=0, pod2=0, pod3=0, podc=0), _costanti(n, fv1=1))
    mese = local_frame(idx)["month"].to_numpy()
    assert r.I_vendita[0][mese < 9].sum() == 0
    assert r.I_vendita[0][mese >= 9].sum() == pytest.approx(r.I[3][mese >= 9].sum())


def test_perimetri_non_ammessi_esclusi():
    cps = [punto("pod1", "fam1", area_convenzionale="A"), punto("pod2", "fam2", area_convenzionale="B"),
           punto("pod3", "fam3", area_convenzionale="A"),
           punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=4000, area_convenzionale="A")]
    cfg = configurazione(tipo="CER", cps=cps)
    idx = year_index(2028)[:2]
    r = simulate_year(cfg, check(cfg), idx, _costanti(2, pod1=1, pod2=1, pod3=1, podc=0), _costanti(2, fv1=5))
    np.testing.assert_allclose(r.EACV, 0)  # cabine diverse: niente condivisa incentivabile
    np.testing.assert_allclose(r.EACI, 0)
    np.testing.assert_allclose(r.EACVC, 0)  # CER: niente EACVC


def test_cabina_sconosciuta_resta_condizionale():
    cfg = configurazione(tipo="CER")  # nessuna area convenzionale indicata
    r = simulate_year(cfg, check(cfg), year_index(2028)[:2], _costanti(2, pod1=1, pod2=1, pod3=1, podc=0), _costanti(2, fv1=5))
    assert r.condizionale
    np.testing.assert_allclose(r.EACV, 3)  # calcolata, ma da presentare come condizionale


def test_configurazione_non_supportata_rifiutata():
    cfg = configurazione(plants=[impianto("fv1", "podc", "cond", entrata=date(2021, 6, 1))])
    with pytest.raises(UnsupportedConfigurationError):
        simulate_year(cfg, check(cfg), year_index(2028)[:2], {}, _costanti(2, fv1=1))


def test_punto_di_sola_immissione():
    members = [membro("fam1"), membro("esco", "pmi")]
    cps = [punto("pod1", "fam1", kwh_annui=3000), ConnectionPoint(id="pod_fv", titolare="esco", ruolo="sola_immissione", edificio_id="ed1")]
    cfg = configurazione(members=members, cps=cps, plants=[impianto("fv", "pod_fv", TERZO)])
    r = simulate_year(cfg, check(cfg), year_index(2028)[:2], _costanti(2, pod1=2), _costanti(2, fv=3))
    np.testing.assert_allclose(r.SC[1], 0)
    np.testing.assert_allclose(r.EACV, 2)


@pytest.fixture(scope="module")
def progetto():
    cfg = configurazione(plants=[impianto("fv1", "podc", "cond", kwp=20, kw_ac=18, entrata=date(2027, 5, 1))])
    prof = synthetic_profile(45.07, 7.69, 30, 0, 14, 2023)
    return cfg, simulate_project(cfg, check(cfg), {"fv1": prof}, 2023, n_years=4)


def test_progetto_bilancio_coerente_ogni_anno(progetto):
    _, res = progetto
    assert [r.year for r in res.anni] == [2027, 2028, 2029, 2030]
    assert len(res.anni[1].index) == 8784  # 2028 bisestile
    for r in res.anni:
        assert r.violazioni_invarianti() == []
        t = r.totali()
        assert t["EACI_kwh"] <= t["EACV_kwh"] + 1e-6
    assert res.manifest["controlli_bilancio"] == "ok"
    assert res.manifest["qualita_complessiva"] == "C"  # FV sintetico e consumi da famiglia tipo
    assert res.manifest["anni_progetto"] == [2027, 2030]


def test_progetto_degrado_rifa_il_bilancio(progetto):
    _, res = progetto
    p29, p30 = (res.anni[i].totali()["produzione_kwh"] for i in (2, 3))
    assert p30 == pytest.approx(p29 * 0.995, rel=0.01)


def test_stagione_di_avvio_conta():
    prof = synthetic_profile(45.07, 7.69, 30, 0, 14, 2023)
    produzione_primo_anno = {}
    for mese in (5, 11):
        cfg = configurazione(plants=[impianto("fv1", "podc", "cond", entrata=date(2027, mese, 1))],
                             data_costituzione=date(2026, 1, 1))
        res = simulate_project(cfg, check(cfg), {"fv1": prof}, 2023, n_years=2)
        produzione_primo_anno[mese] = res.anni[0].totali()["produzione_kwh"] / res.anni[1].totali()["produzione_kwh"]
    # novembre–dicembre sono il 17% dell'anno ma producono molto meno del 17%
    assert produzione_primo_anno[11] < 0.10
    assert produzione_primo_anno[5] > 0.65


def test_profili_condivisi_per_orientamento():
    cfg = _due_impianti(date(2027, 3, 1), date(2027, 3, 1))
    chiamate = []

    def finto(lat, lon, tilt, azimut, perdite, anno):
        chiamate.append((lat, lon, tilt, azimut))
        return synthetic_profile(lat, lon, tilt, azimut, perdite, anno)

    profili = pv_profiles_for(cfg, 2023, fetch=finto)
    assert set(profili) == {"fa", "fb"} and len(chiamate) == 1


def test_anno_di_riferimento_coerente():
    cfg = configurazione()
    prof = synthetic_profile(45.07, 7.69, 30, 0, 14, 2022)
    with pytest.raises(ValueError, match="anno di riferimento"):
        simulate_project(cfg, check(cfg), {"fv1": prof}, 2023, n_years=1)
