import io
import re
from collections import defaultdict
from datetime import date

import pytest
from openpyxl import load_workbook

from cersim.analisi import analizza
from cersim.economics import ParametriEconomici
from cersim.model import Fasce
from cersim.report import (
    FOGLI,
    avvertenze_compatte,
    dati_da_migliorare,
    frase_precisione,
    neutralizza,
    report_excel,
    report_pdf,
)
from conftest import configurazione, impianto, membro, punto

PARAMS = ParametriEconomici(quota_membri=0.5)


def pagine(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


@pytest.fixture
def analisi(niente_rete):
    membri = [membro("fam1"), membro("fam2"), membro("fam3"), membro("cond", "condominio")]
    membri[0] = membri[0].model_copy(update={"nome": "=1+1"})  # un nome che Excel leggerebbe come formula
    return analizza(configurazione(members=membri), PARAMS, n_anni=3)


def test_pdf_di_tre_o_quattro_pagine(analisi):
    pdf = report_pdf(analisi, PARAMS, oggi=date(2026, 10, 16))
    assert pdf.startswith(b"%PDF")
    assert 3 <= pagine(pdf) <= 4


def test_pdf_anche_senza_euro():
    a = analizza(configurazione(), PARAMS, n_anni=2, oggi=date(2031, 1, 1))  # pacchetto normativo scaduto
    assert a.economia_disabilitata
    pdf = report_pdf(a, PARAMS)
    assert 2 <= pagine(pdf) <= 4


def test_niente_report_per_configurazioni_non_supportate():
    a = analizza(configurazione(plants=[impianto("fv1", "podc", "cond", entrata=date(2020, 1, 1))]), PARAMS, n_anni=2)
    with pytest.raises(ValueError):
        report_pdf(a, PARAMS)
    with pytest.raises(ValueError):
        report_excel(a, PARAMS)


def test_excel_fogli_e_ledger_che_torna(analisi):
    wb = load_workbook(io.BytesIO(report_excel(analisi, PARAMS)))
    assert tuple(wb.sheetnames) == FOGLI

    # dai movimenti: entrate meno uscite per soggetto e anno
    netto = defaultdict(float)
    righe = list(wb["Movimenti"].iter_rows(min_row=2, values_only=True))
    assert len(righe) == len(analisi.base.ledger.movimenti)
    for anno, _voce, paga, _, riceve, _, importo, _base in righe:
        netto[(riceve, anno)] += importo
        netto[(paga, anno)] -= importo
    for anno in {a for _, a in netto}:
        assert sum(v for (_, a), v in netto.items() if a == anno) == pytest.approx(0, abs=0.05)

    # i flussi per soggetto coincidono con il ledger e la somma di tutti i soggetti è zero
    led = analisi.base.ledger
    flussi = wb["Flussi di cassa"]
    intestazioni = [c.value for c in flussi[2]]
    controllo = intestazioni.index("Controllo: somma di tutti i soggetti")
    for riga in flussi.iter_rows(min_row=3, max_row=2 + led.n_anni, values_only=True):
        assert riga[controllo] == pytest.approx(0, abs=0.05)
    colonna_cond = intestazioni.index("Cond")
    valori_cond = [r[colonna_cond] for r in flussi.iter_rows(min_row=3, max_row=2 + led.n_anni, values_only=True)]
    assert valori_cond == pytest.approx(list(led.flussi_soggetto("cond")), abs=0.01)
    assert valori_cond == pytest.approx([netto[("cond", led.anno_inizio + i)] for i in range(led.n_anni)], abs=0.05)


def test_excel_testo_che_sembra_formula_resta_testo(analisi):
    wb = load_workbook(io.BytesIO(report_excel(analisi, PARAMS)))
    celle = [c for ws in wb for riga in ws.iter_rows() for c in riga]
    assert not [c.coordinate for c in celle if c.data_type == "f"]
    nomi = [c for c in celle if isinstance(c.value, str) and "=1+1" in c.value]
    assert nomi and all(c.value.startswith("'") and c.data_type == "s" for c in nomi)
    assert {c.parent.title for c in nomi} >= {"Per membro", "Flussi di cassa", "Movimenti"}


def test_neutralizza():
    assert [neutralizza(v) for v in ("=SOMMA(A1)", "+39 011", "-5", "@x", "testo", -5, 3.2, None)] == [
        "'=SOMMA(A1)", "'+39 011", "'-5", "'@x", "testo", -5, 3.2, None]


def test_avvertenze_ripetute_in_una_riga():
    avvisi = [f"{a}: quota eccedentaria della TIP di {v} € da destinare" for a, v in ((2027, 345), (2028, "1.346"))]
    compatte = avvertenze_compatte(avvisi + ["PVGIS non disponibile"])
    assert len(compatte) == 2 and "un altro caso" in compatte[0]


def test_dati_da_migliorare_dal_piu_importante(analisi):
    voci = dati_da_migliorare(analisi)
    cose = [v.cosa for v in voci]
    # tre famiglie senza bolletta, parti comuni senza fasce, PVGIS assente (niente rete), prezzi e costo tipici
    assert cose[0] == "3 contatori su 4 senza consumo dalla bolletta" and voci[0].passo == 2
    assert cose[1] == "1 contatore su 4 senza le fasce F1 e F2+F3"
    assert cose[2:] == ["Produzione stimata senza PVGIS", "Prezzo dell'energia costante invece che ora per ora",
                        "Costo dell'impianto senza preventivo", "4 contatori su 4 senza curva oraria misurata"]
    assert [v.passo for v in voci[2:]] == [None, 4, 3, 2]
    assert "il 75% dei consumi coperti" in voci[-1].perche and "il 0%" not in voci[-1].perche
    assert "il 67% dei consumi" in voci[0].perche  # 3 × 2.700 kWh su 12.100
    assert frase_precisione(analisi).startswith("Oggi il beneficio netto della configurazione va da ")


def test_con_bollette_e_preventivo_resta_poco_da_migliorare():
    fasce = Fasce(f1=900, f23=1800)
    cps = [punto(f"pod{i}", f"fam{i}", kwh_annui=2700, fasce=fasce) for i in (1, 2, 3)]
    cps.append(punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=2700, fasce=fasce))
    cfg = configurazione(cps=cps, plants=[impianto("fv1", "podc", "cond", costo_preventivo_eur=30_000)])
    cose = [v.cosa for v in dati_da_migliorare(analizza(cfg, PARAMS, n_anni=2))]
    assert not any("bolletta" in c or "fasce" in c or "preventivo" in c for c in cose)
    assert cose[-1] == "4 contatori su 4 senza curva oraria misurata"


def test_attribuzione_di_openstreetmap(analisi, monkeypatch):
    """ODbL: chi usa le sagome degli edifici per le ombre deve citare OpenStreetMap, nel PDF e nell'Excel."""
    wb = load_workbook(io.BytesIO(report_excel(analisi, PARAMS)))
    valori = [str(c) for riga in wb["Manifest"].iter_rows(values_only=True) for c in riga if c is not None]
    assert any("© OpenStreetMap contributors" in v for v in valori)
    import cersim.report as report
    scritte = []
    originale = report._coppie
    monkeypatch.setattr(report, "_coppie", lambda pdf, righe, **k: (scritte.extend(righe), originale(pdf, righe, **k)))
    report_pdf(analisi, PARAMS, oggi=date(2026, 10, 16))
    assert any("© OpenStreetMap contributors" in valore for _, valore in scritte)
