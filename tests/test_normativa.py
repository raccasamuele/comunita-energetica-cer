from datetime import date

import numpy as np
import pytest

from cersim.normativa import (
    PacchettoScadutoError,
    assunzioni_economiche,
    classificazione_soggetti,
    pacchetto_normativo,
    verifica_validita,
)


def test_pacchetti_validi_e_non_scaduti_oggi():
    for pacchetto in (pacchetto_normativo(), assunzioni_economiche(), classificazione_soggetti()):
        assert pacchetto.revisione <= pacchetto.scadenza
        verifica_validita(pacchetto, date(2026, 10, 15))


def test_pacchetto_scaduto():
    with pytest.raises(PacchettoScadutoError, match="scaduto"):
        verifica_validita(pacchetto_normativo(), date(2030, 1, 1))


@pytest.mark.parametrize("kw, base, cap", [(10, 80, 120), (200, 80, 120), (200.5, 70, 110), (600, 70, 110), (601, 60, 100), (1000, 60, 100)])
def test_fasce_tip(kw, base, cap):
    f = pacchetto_normativo().fascia_tip(kw)
    assert (f.base_eur_mwh, f.cap_eur_mwh) == (base, cap)


def test_oltre_1mw_nessuna_fascia():
    with pytest.raises(ValueError):
        pacchetto_normativo().fascia_tip(1001)


@pytest.mark.parametrize("kw, euro", [(3, 0), (3.1, 15), (10, 15), (20, 15), (20.1, 15.1), (50, 45), (100, 95), (1000, 995)])
def test_corrispettivi_gse(kw, euro):
    assert pacchetto_normativo().corrispettivo_gse_annuo(kw) == pytest.approx(euro)


@pytest.mark.parametrize("kw, euro", [(3, 0), (19, 13.3), (100, 66), (1200, 20 * 0.7 + 180 * 0.65 + 1000 * 0.6),
                                      (100_000, 10_000)])
def test_oneri_ritiro_dedicato_a_scaglioni(kw, euro):
    # DM 24/12/2014, tabella 3: esempio GSE 19 kW → 13,3 €/anno; massimale 10.000 €
    assert pacchetto_normativo().rid.onere_annuo(kw) == pytest.approx(euro)


def test_trase_per_anno_e_congelamento():
    norma = pacchetto_normativo()
    assert norma.trase(2024) == 10.57
    assert norma.trase(2025) == 11.89
    assert norma.trase(2040) == 11.90  # oltre l'ultimo anno noto: congelato in termini reali
    assert norma.btau(2024) == 0.65  # coincide con il GSE
    assert norma.btau(2025) == 0.73
    assert norma.btau(2030) == 0.68  # TIT 2026, delibera 575/2025/R/eel


def test_capex_massimali_dm_a_scaglioni():
    ipotesi = assunzioni_economiche()
    assert ipotesi.capex_eur_per_kw(20) == 1500
    assert ipotesi.capex_eur_per_kw(21) == 1200
    assert ipotesi.capex.base_potenza == "DC"
    assert ipotesi.capex_totale(10) == 15000
    assert ipotesi.capex_totale(30) == 20 * 1500 + 10 * 1200
    potenze = np.linspace(1, 1000, 2000)
    costi = np.array([ipotesi.capex_totale(p) for p in potenze])
    assert (np.diff(costi) > 0).all()  # niente impianti più grandi che costano meno
    assert ipotesi.capex_totale(20.2) > ipotesi.capex_totale(20)
