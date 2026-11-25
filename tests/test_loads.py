import numpy as np
import pytest

from cersim.loads import load_profile, qualita_consumi
from cersim.model import ConnectionPoint, Fasce
from cersim.timebase import TZ, local_frame, year_index
from conftest import punto


@pytest.mark.parametrize("anno", [2027, 2028])
@pytest.mark.parametrize("tipologia, kwh", [("domestico", 2700), ("ufficio_commerciale", 15000), ("scuola", 40000),
                                             ("pa_municipio", 30000), ("pmi", 80000)])
def test_consumo_annuo_rispettato(anno, tipologia, kwh):
    profilo = load_profile(punto("p", "t", tipologia_profilo=tipologia, kwh_annui=kwh), year_index(anno))
    assert len(profilo) == len(year_index(anno))
    assert profilo.sum() == pytest.approx(kwh)
    assert (profilo > 0).all()


def _per_fascia(profilo, anno):
    fascia = local_frame(year_index(anno))["fascia"].to_numpy()
    return {f: profilo[fascia == f].sum() for f in ("F1", "F2", "F3")}


def test_taratura_f1_f2_f3():
    cp = punto("p", "t", fasce=Fasce(f1=900, f2=800, f3=1300))
    totali = _per_fascia(load_profile(cp, year_index(2027)), 2027)
    assert totali["F1"] == pytest.approx(900)
    assert totali["F2"] == pytest.approx(800)
    assert totali["F3"] == pytest.approx(1300)


def test_taratura_f1_f23_con_kwh_annui():
    cp = punto("p", "t", kwh_annui=3000, fasce=Fasce(f1=1000, f23=1950))
    profilo = load_profile(cp, year_index(2027))
    totali = _per_fascia(profilo, 2027)
    assert profilo.sum() == pytest.approx(3000)
    # quote delle fasce dalla bolletta, totale dal consumo annuo
    assert totali["F1"] == pytest.approx(3000 * 1000 / 2950)


def test_varianti_deterministiche_e_conservative():
    cp = punto("p", "t", fasce=Fasce(f1=900, f2=800, f3=1300))
    idx = year_index(2027)
    base = load_profile(cp, idx)
    v1 = load_profile(cp, idx, variante=1)
    assert not np.allclose(base, v1)
    np.testing.assert_allclose(v1, load_profile(cp, idx, variante=1))
    assert v1.sum() == pytest.approx(base.sum())
    assert _per_fascia(v1, 2027)["F1"] == pytest.approx(900)
    # punti diversi ricevono perturbazioni diverse
    altro = punto("q", "t", fasce=Fasce(f1=900, f2=800, f3=1300))
    assert not np.allclose(v1, load_profile(altro, idx, variante=1))


def test_varianti_spostano_i_consumi_tra_giorno_e_sera():
    cp = punto("p", "t", kwh_annui=2700)  # senza fasce: nulla vincola la ripartizione nella giornata
    idx = year_index(2027)
    ora = idx.tz_convert(TZ).hour
    giorno = (ora >= 8) & (ora < 19)

    def quota_di_giorno(variante):
        profilo = load_profile(cp, idx, variante)
        return profilo[giorno].sum() / profilo.sum()

    assert quota_di_giorno(1) > quota_di_giorno(0) > quota_di_giorno(2)
    with pytest.raises(ValueError):
        load_profile(cp, idx, variante=9)


def test_scuola_vuota_ad_agosto():
    cp = punto("s", "t", tipologia_profilo="scuola", kwh_annui=40000)
    idx = year_index(2027)
    profilo = load_profile(cp, idx)
    mese = local_frame(idx)["month"].to_numpy()
    assert profilo[mese == 8].sum() < 0.25 * profilo[mese == 3].sum()


def test_qualita():
    assert qualita_consumi(punto("p", "t")) == "C"  # famiglia tipo ARERA
    assert qualita_consumi(punto("p", "t", kwh_annui=2500)) == "C"  # senza fasce
    assert qualita_consumi(punto("p", "t", kwh_annui=2500, fasce=Fasce(f1=1000, f23=1500))) == "B"


def test_sola_immissione_senza_consumi():
    cp = ConnectionPoint(id="fv", titolare="t", ruolo="sola_immissione")
    assert load_profile(cp, year_index(2027)).sum() == 0
