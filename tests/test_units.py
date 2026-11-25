import numpy as np

from cersim.units import eur


def test_kwh_per_eur_mwh():
    # 1000 kWh = 1 MWh a 120 €/MWh = 120 €, non 120.000 €
    assert eur(1000, 120) == 120.0
    assert eur(1, 100) == 0.1


def test_vettoriale_orario():
    kwh = np.array([0.0, 500.0, 2000.0])
    prezzi = np.array([100.0, 100.0, 50.0])
    np.testing.assert_allclose(eur(kwh, prezzi), [0.0, 50.0, 100.0])
