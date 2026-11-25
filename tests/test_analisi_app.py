from datetime import date
from pathlib import Path

import pytest

from cersim.analisi import (
    analizza,
    anno_rappresentativo,
    cassa_cumulata,
    chi_riceve_cosa,
    giorno_tipo,
    mensile,
    nomi_leggibili,
    scenari_dimensionamento,
)
from cersim.economics import ParametriEconomici
from conftest import configurazione, impianto

PARAMS = ParametriEconomici(quota_membri=0.5)
APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def analisi(niente_rete):  # scope di funzione: deve partire dopo il blocco della rete
    return analizza(configurazione(), PARAMS, n_anni=3)


def test_analisi_completa(analisi):
    assert analisi.supportata and analisi.economia_disabilitata is None
    # 3 anni meteo × 3 livelli di prezzo, più 2 varianti dei consumi sul 2023 × 3 livelli
    assert len(analisi.esiti) == 15 and analisi.base.scenario.livello == "base"
    assert {e.scenario.variante for e in analisi.esiti} == {0, 1, 2}
    assert all(s.variante == 0 and s.livello == "base" for s in scenari_dimensionamento(analisi))
    # confronto con il solo fotovoltaico: la differenza è il valore aggiunto della configurazione
    b = analisi.bande
    assert b["valore_configurazione"].minimo <= b["valore_configurazione"].massimo
    assert b["van_consolidato"].mediana != b["van_solo_fv"].mediana
    assert analisi.qualita == "C"  # senza rete: FV sintetico
    assert any("PVGIS non disponibile" in a for a in analisi.avvisi)
    assert analisi.sensibilita


def test_dati_per_i_grafici(analisi):
    yr = anno_rappresentativo(analisi.energia_base)
    gt = giorno_tipo(yr, 6)
    assert list(gt.index) == list(range(24)) and gt["Produzione FV"].iloc[12] > gt["Produzione FV"].iloc[2]
    assert len(mensile(yr)) == 12
    assert len(cassa_cumulata(analisi.base)) == 3
    tabella = chi_riceve_cosa(analisi.base, nomi_leggibili(analisi.config))
    assert {"Voce", "Chi paga", "Chi riceve", "€"} <= set(tabella.columns)
    assert "GSE" in set(tabella["Chi paga"])


def test_anni_compattati_dopo_i_primi_due(analisi):
    anni = analisi.base.energia.anni
    assert hasattr(anni[1], "EACV") and not hasattr(anni[2], "EACV")
    assert anni[2].totali()["produzione_kwh"] > 0


def test_configurazione_non_supportata():
    cfg = configurazione(plants=[impianto("fv1", "podc", "cond", entrata=date(2020, 1, 1))])
    a = analizza(cfg, PARAMS, n_anni=2)
    assert not a.supportata and a.esiti == [] and a.report.non_supportati


def test_pacchetto_scaduto_solo_energia():
    a = analizza(configurazione(), PARAMS, n_anni=2, oggi=date(2031, 1, 1))
    assert a.economia_disabilitata and "scaduto" in a.economia_disabilitata
    assert a.esiti == [] and a.energia_base is not None


def test_app_si_avvia_e_calcola_l_esempio():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    at.sidebar.button[0].click().run()  # carica l'esempio di Torino
    assert not at.exception
    quota = next(r for r in at.radio if r.label.startswith("Quota"))
    quota.set_value(0.5).run()
    calcola = next(b for b in at.button if "Calcola lo scenario" in b.label)
    calcola.click().run()
    assert not at.exception, at.exception
    analisi = at.session_state["analisi"]
    assert analisi.supportata and analisi.bande["van_consolidato"].mediana != 0
    assert any(s.value == "Requisiti" for s in at.subheader)
    assert any(s.value == "Chi paga e chi riceve" for s in at.subheader)
    report = at.session_state["report"]  # i file dei due pulsanti di download
    assert report["pdf"].startswith(b"%PDF") and report["xlsx"].startswith(b"PK")
