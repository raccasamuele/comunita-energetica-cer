"""Curve dei consumi calcolate (per esempio dal simulatore della casa): formato di scambio, validazione, qualità."""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cersim.curva_calcolata import (
    FORMATO,
    MAX_BYTE,
    cella,
    esporta,
    forma_media,
    leggi_curva_calcolata,
)
from cersim.loads import load_profile_anno, qualita_consumi, qualita_insieme, quota_misurata
from cersim.misure import curva_misurata, descrivi, kwh_anno_riferimento, leggi_file
from cersim.model import CELLE_CURVA, CurvaMisurata, Fasce, NaturaCurva
from cersim.timebase import TZ, year_index
from conftest import punto
from test_misure import anno, portale

ESEMPIO = Path(__file__).resolve().parents[1] / "esempi" / "curva_consumi_esempio.json"


def casa(a: int = 2025) -> pd.Series:
    """Una casa con pompa di calore: base, sera, e riscaldamento che d'inverno pesa di più al mattino e alla sera."""
    idx = year_index(a)
    locale = idx.tz_convert(TZ)
    ora, mese = np.asarray(locale.hour), np.asarray(locale.month)
    inverno = np.array([1.0, 0.85, 0.55, 0.2, 0, 0, 0, 0, 0, 0.25, 0.6, 0.95])[mese - 1]
    picchi = np.isin(ora, [6, 7, 8, 18, 19, 20, 21])
    kwh = 0.25 + 0.5 * ((ora >= 19) & (ora < 23)) + inverno * np.where(picchi, 2.0, 0.6)
    return pd.Series(kwh, index=idx)


_BASE = esporta(casa(), motore="casa-1R1C 0.4", descrizione="Casa Rossi, pompa di calore aria-acqua")


def file_casa(**cambi) -> bytes:
    """Il file di scambio della casa di prova; un campo a `...` si toglie."""
    dati = {**_BASE, **cambi}
    for campo in [k for k, v in cambi.items() if v is ...]:
        del dati[campo]
    return json.dumps(dati).encode()


def test_andata_e_ritorno_con_il_modello():
    orarie = casa()
    curva, avvisi = leggi_curva_calcolata(file_casa())
    assert curva.natura is NaturaCurva.CALCOLATA and not curva.misurata
    assert curva.giorni is None and curva.dal is None and curva.al is None
    assert curva.kwh_annui == pytest.approx(orarie.sum(), abs=0.1)
    assert np.allclose(curva.ore, forma_media(orarie).reshape(CELLE_CURVA), atol=1e-5)
    assert curva.fonte == "simulatore della casa: Casa Rossi, pompa di calore aria-acqua"
    assert not avvisi  # stessa forma, calendario diverso dal 2023: scarto sotto lo 0,5%

    cp = punto("casa", "rossi", curva_misurata=curva)
    assert cp.kwh_effettivi == curva.kwh_annui and not cp.kwh_da_default
    profilo = load_profile_anno(cp, 2027)
    assert profilo.sum() == pytest.approx(curva.kwh_annui, rel=1e-6)
    locale = year_index(2027).tz_convert(TZ)
    gennaio_7 = profilo[(locale.month == 1) & (locale.hour == 7)].mean()
    luglio_7 = profilo[(locale.month == 7) & (locale.hour == 7)].mean()
    assert gennaio_7 == pytest.approx(0.25 + 2.0, rel=0.01) and luglio_7 == pytest.approx(0.25, rel=0.01)
    assert np.array_equal(load_profile_anno(cp, 2027, variante=1), profilo)  # come una misurata


def test_l_ordine_delle_celle():
    assert cella(0) == "feriale, gennaio, ore 0"
    assert cella((1 * 12 + 6) * 24 + 13) == "sabato, luglio, ore 13"
    assert cella(CELLE_CURVA - 1) == "festivo, dicembre, ore 23"
    curva, _ = leggi_curva_calcolata(file_casa())
    assert curva.valore(0, 1, 7) == curva.ore[7] == pytest.approx(2.25)


def test_qualita_dei_consumi_calcolati_mai_a():
    calcolata, _ = leggi_curva_calcolata(file_casa())
    misurata = curva_misurata(leggi_file(portale(anno(2025))))
    bolletta = dict(kwh_annui=2700, fasce=Fasce(f1=900, f23=1800))
    assert qualita_consumi(punto("c", "x", curva_misurata=calcolata)) == "B"
    assert qualita_consumi(punto("m", "x", curva_misurata=misurata)) == "A"

    tutte_calcolate = [punto(f"c{i}", "x", curva_misurata=calcolata) for i in range(4)]
    assert quota_misurata(tutte_calcolate) == 0
    assert qualita_insieme(tutte_calcolate, ["B"], ["B"]) == "B"  # come la bolletta, non come le misure

    # tre misurate e una calcolata: la calcolata non conta come misurata, ma non abbassa a C
    misti = [punto(f"m{i}", "x", curva_misurata=misurata) for i in range(3)] + [
        punto("c", "y", curva_misurata=calcolata)]
    quota_attesa = 3 * misurata.kwh_annui / (3 * misurata.kwh_annui + calcolata.kwh_annui)
    assert quota_misurata(misti) == pytest.approx(quota_attesa)
    assert qualita_insieme(misti, ["B"], ["B"]) == ("A" if quota_attesa >= 0.75 else "B")
    assert qualita_insieme([punto("c", "y", curva_misurata=calcolata), punto("b", "z", **bolletta)],
                           ["B"], ["B"]) == "B"


def test_i_salvataggi_senza_natura_restano_misurati():
    misurata = curva_misurata(leggi_file(portale(anno(2025))))
    vecchio = misurata.model_dump(mode="json")
    del vecchio["natura"]  # come nei file salvati prima della natura
    riletta = CurvaMisurata.model_validate(vecchio)
    assert riletta.misurata and riletta == misurata
    assert qualita_consumi(punto("a", "x", curva_misurata=riletta)) == "A"


def test_natura_nel_salvataggio_e_nelle_tabelle():
    from cersim.ui_model import (
        Generale,
        configurazione_da_tabelle,
        esporta_json,
        famiglie_tipo,
        impianti_vuoti,
        importa_json,
        tabelle_da_configurazione,
    )

    calcolata, _ = leggi_curva_calcolata(file_casa())
    generale = Generale("Prova", "gruppo", 45.07, 7.69, "Piemonte", data_costituzione=date(2027, 1, 1))
    esito = configurazione_da_tabelle(generale, famiglie_tipo(2, kwh=2700), impianti_vuoti(),
                                      curve={"Famiglia 1": calcolata})
    ricaricata, _ = importa_json(esporta_json(esito.config, {}))
    cp = ricaricata.connection_points[0]
    assert cp.curva_misurata == calcolata and cp.curva_misurata.natura is NaturaCurva.CALCOLATA
    assert qualita_consumi(cp) == "B"
    _, tabella, _ = tabelle_da_configurazione(ricaricata)
    assert tabella["kWh annui"].iloc[0] == pytest.approx(calcolata.kwh_annui)


def test_il_modello_tiene_distinte_le_due_nature():
    misurata = curva_misurata(leggi_file(portale(anno(2025))))
    base = dict(ore=misurata.ore, kwh_annui=1000.0, fonte="prova")
    with pytest.raises(ValueError, match="non ha giorni"):
        CurvaMisurata(natura="calcolata", giorni=365, dal=date(2025, 1, 1), al=date(2025, 12, 31), **base)
    with pytest.raises(ValueError, match="giorni e periodo"):
        CurvaMisurata(giorni=365, dal=date(2025, 1, 1), **base)
    with pytest.raises(ValueError, match="natura"):
        CurvaMisurata(natura="stimata", **base)


def test_descrizione_per_l_interfaccia():
    curva, _ = leggi_curva_calcolata(file_casa())
    testo = descrivi(curva)
    assert testo.startswith("consumi calcolati, non misurati, circa ") and "kWh all'anno" in testo
    assert "giorni con misure" not in testo


def test_piccolo_scarto_sul_consumo_annuo_si_segnala():
    dichiarato = round(kwh_anno_riferimento(_BASE["ore"]) * 1.01, 1)
    curva, avvisi = leggi_curva_calcolata(file_casa(kwh_annui=dichiarato))
    assert curva.kwh_annui == dichiarato  # vale quello dichiarato: la forma si tara su questo
    assert len(avvisi) == 1 and "si usa quello dichiarato" in avvisi[0]


def test_testi_ripuliti_e_accorciati():
    curva, _ = leggi_curva_calcolata(file_casa(descrizione="[clic](http://x.it) **Casa** <script>!\n" + "a" * 300))
    assert not any(c in curva.fonte for c in "[]<>*!\n")
    assert len(curva.fonte) <= 80 and curva.fonte.endswith("…")
    curva, _ = leggi_curva_calcolata(file_casa(descrizione=None, motore=None))
    assert curva.fonte == "simulatore della casa"
    curva, _ = leggi_curva_calcolata(file_casa(descrizione=..., motore="casa 0.4", fonte="altro-modello"))
    assert curva.fonte == "altro-modello: casa 0.4"


def _ore(i: int, valore) -> list:
    ore = list(_BASE["ore"])
    ore[i] = valore
    return ore


@pytest.mark.parametrize("contenuto, messaggio", [
    (b"non json", "non è un JSON valido"),
    ("{}".encode("utf-16"), "UTF-8"),
    (b"[1, 2]", "formato"),
    (json.dumps({"formato": "scheda-consumi"}).encode(), "formato"),
    pytest.param(b"[" * 100_000 + b"]" * 100_000, "JSON valido", id="annidato-profondo"),
    (file_casa(versione=4), "aggiorna il simulatore"),
    (file_casa(versione=3), "Mancano i campi: batteria_kwh"),
    (file_casa(versione=3, batteria_kwh=-1), "batteria_kwh"),
    (file_casa(versione=3, batteria_kwh=True), "batteria_kwh"),
    (file_casa(versione=3, batteria_kwh=5000), "batteria_kwh"),
    (file_casa(batteria_kwh=10), "Campi non previsti.*batteria_kwh"),
    (file_casa(fv_sottratto_kwp=...), "Mancano i campi: fv_sottratto_kwp"),
    (file_casa(fv_sottratto_kwp=-1), "fv_sottratto_kwp"),
    (file_casa(fv_sottratto_kwp="3"), "fv_sottratto_kwp"),
    (file_casa(versione=1), "Campi non previsti.*fv_sottratto_kwp"),
    (file_casa(versione=0), "Versione 0 del formato non supportata"),
    (file_casa(versione="1"), "numero intero"),
    (file_casa(versione=True), "numero intero"),
    (file_casa(colore="rosso"), "Campi non previsti.*colore"),
    (file_casa(ore=...), "Mancano i campi: ore"),
    (file_casa(kwh_annui=...), "Mancano i campi: kwh_annui"),
    (file_casa(natura="misurato"), "Portale Consumi"),
    (file_casa(natura="stimato"), "natura"),
    (file_casa(unita="Wh"), "kWh"),
    (file_casa(fonte="Simulatore Casa"), "fonte"),
    (file_casa(fonte=3), "fonte"),
    (file_casa(motore=7), "motore deve essere un testo"),
    (file_casa(ore=[0.1] * 863), "864 valori: ne ha 863"),
    (file_casa(ore={"a": 1}), "864 valori"),
    (file_casa(ore=_ore(5, -0.1)), r"Valore 5 .*feriale, gennaio, ore 5"),
    (file_casa(ore=_ore(300, "0,4")), r"Valore 300 .*sabato, gennaio, ore 12"),
    (file_casa(ore=_ore(10, True)), "Valore 10"),
    (file_casa(ore=_ore(10, None)), "Valore 10"),
    (file_casa(ore=[0.0] * 864), "tutta a zero"),
    (file_casa(kwh_annui=0), "maggiore di zero"),
    (file_casa(kwh_annui=-5), "maggiore di zero"),
    (file_casa(kwh_annui=2e7), "al massimo"),
    (file_casa(kwh_annui="3000"), "kwh_annui"),
    (file_casa(kwh_annui=round(casa().sum() * 1.05, 1)), "non torna con la curva"),
], ids=lambda v: "file" if isinstance(v, bytes) else None)  # id brevi: il file intero supera i limiti di Windows
def test_file_non_validi(contenuto, messaggio):
    with pytest.raises(ValueError, match=messaggio):
        leggi_curva_calcolata(contenuto)


@pytest.mark.parametrize("letterale", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_valori_non_finiti(letterale):
    ore = "[" + ", ".join([letterale] + [repr(v) for v in _BASE["ore"][1:]]) + "]"
    testo = json.dumps({**_BASE, "ore": "__ORE__"}).replace('"__ORE__"', ore)
    with pytest.raises(ValueError, match="non numerico|Valore 0"):
        leggi_curva_calcolata(testo.encode())
    testo = json.dumps({**_BASE, "kwh_annui": "__KWH__"}).replace('"__KWH__"', letterale)
    with pytest.raises(ValueError, match="non numerico|kwh_annui"):
        leggi_curva_calcolata(testo.encode())


def test_file_troppo_grande():
    with pytest.raises(ValueError, match="kB"):
        leggi_curva_calcolata(b" " * (MAX_BYTE + 1))


def test_bom_e_campi_facoltativi_nulli():
    curva, _ = leggi_curva_calcolata(b"\xef\xbb\xbf" + file_casa(motore=None, descrizione=None))
    assert curva.natura is NaturaCurva.CALCOLATA


def test_esporta_vuole_un_anno_intero_con_fuso():
    with pytest.raises(ValueError, match="fuso"):
        forma_media(pd.Series([1.0] * 24, index=pd.date_range("2025-01-01", periods=24, freq="h")))
    with pytest.raises(ValueError, match="anno intero"):
        forma_media(casa().iloc[:24 * 31])


def test_il_file_di_esempio_si_legge():
    dati = json.loads(ESEMPIO.read_text(encoding="utf-8"))
    assert dati["formato"] == FORMATO and len(dati["ore"]) == CELLE_CURVA
    curva, avvisi = leggi_curva_calcolata(ESEMPIO.read_bytes())
    assert curva.natura is NaturaCurva.CALCOLATA and not avvisi


def test_app_con_una_curva_calcolata():
    from streamlit.testing.v1 import AppTest

    curva, _ = leggi_curva_calcolata(file_casa())
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=180)
    at.run()
    at.sidebar.button[0].click().run()  # esempio di Torino
    etichetta = at.session_state["punti_base"]["Punto"].iloc[0]
    at.session_state["curve_misurate"] = {etichetta: curva}
    at.session_state["esito_curva"] = ("calcolata", f"{etichetta}: {descrivi(curva)}.", [])  # come dopo il caricamento
    at.run()
    assert any(e.label == "Consumi ora per ora: 1 contatore" for e in at.expander)
    assert any("consumi calcolati, non misurati" in m.value for m in at.markdown)
    assert any("qualità di questo contatore resta **B**" in i.value for i in at.info)
    assert not at.error
    next(r for r in at.radio if r.label.startswith("Quota")).set_value(0.5).run()
    next(b for b in at.button if "Calcola lo scenario" in b.label).click().run()
    assert not at.exception, at.exception
    cp = at.session_state["analisi"].config.connection_points[0]
    assert cp.curva_misurata == curva and qualita_consumi(cp) == "B"


def test_fv_gia_sottratto_dalla_casa():
    """Versione 2: i kWp già tolti dai prelievi arrivano nella curva e fanno avvisare di non reinserire l'impianto."""
    senza, avvisi = leggi_curva_calcolata(file_casa())
    assert senza.fv_sottratto_kwp is None and not any("fotovoltaico" in a for a in avvisi)
    con, avvisi = leggi_curva_calcolata(file_casa(fv_sottratto_kwp=3.5))
    assert con.fv_sottratto_kwp == 3.5
    assert any("fotovoltaico da 3,5 kWp" in a and "Non inserire di nuovo" in a for a in avvisi)


def test_versione_1_ancora_letta():
    dati = json.loads(file_casa())
    dati["versione"] = 1
    del dati["fv_sottratto_kwp"]
    curva, _ = leggi_curva_calcolata(json.dumps(dati).encode())
    assert curva.fv_sottratto_kwp is None


def test_avviso_se_il_punto_ha_anche_un_impianto():
    from conftest import configurazione, impianto, membro
    from cersim.simulate import avvisi_fv_sottratto
    con, _ = leggi_curva_calcolata(file_casa(fv_sottratto_kwp=3.5))
    senza, _ = leggi_curva_calcolata(file_casa())
    membri = [membro("rossi"), membro("cond", "condominio")]
    punti = [punto("casa", "rossi", curva_misurata=con), punto("podc", "cond", kwh_annui=4000)]
    assert avvisi_fv_sottratto(configurazione(members=membri, cps=punti, plants=[impianto("fv1", "podc", "cond")])) == []
    [avviso] = avvisi_fv_sottratto(configurazione(members=membri, cps=punti, plants=[impianto("fv1", "casa", "rossi", kwp=3.5)]))
    assert "punto casa" in avviso and "3,5 kWp" in avviso and "contata due volte" in avviso
    punti[0] = punto("casa", "rossi", curva_misurata=senza)
    assert avvisi_fv_sottratto(configurazione(members=membri, cps=punti, plants=[impianto("fv1", "casa", "rossi")])) == []


def test_batteria_gia_considerata():
    """Versione 3: la batteria di casa è già nei prelievi; cersim lo dice e avverte che riduce l'energia condivisa."""
    con, avvisi = leggi_curva_calcolata(file_casa(versione=3, batteria_kwh=10, fv_sottratto_kwp=4))
    assert con.batteria_kwh == 10 and con.fv_sottratto_kwp == 4
    assert any("batteria di casa da 10 kWh" in a and "riduce l'energia condivisa" in a for a in avvisi)
    zero, avvisi = leggi_curva_calcolata(file_casa(versione=3, batteria_kwh=0))
    assert zero.batteria_kwh is None and not any("batteria" in a for a in avvisi)
    # i file della versione 2 si leggono come prima, senza batteria
    due, _ = leggi_curva_calcolata(file_casa())
    assert due.batteria_kwh is None


def test_esporta_versione_3_solo_con_la_batteria():
    assert esporta(casa())["versione"] == 2 and "batteria_kwh" not in esporta(casa())
    con = esporta(casa(), fv_sottratto_kwp=4, batteria_kwh=7.5)
    assert con["versione"] == 3 and con["batteria_kwh"] == 7.5
    curva, _ = leggi_curva_calcolata(json.dumps(con).encode())
    assert curva.batteria_kwh == 7.5


def test_batteria_nel_salvataggio():
    con, _ = leggi_curva_calcolata(file_casa(versione=3, batteria_kwh=10))
    assert CurvaMisurata.model_validate_json(con.model_dump_json()).batteria_kwh == 10
    vecchio = json.loads(con.model_dump_json())
    del vecchio["batteria_kwh"]
    assert CurvaMisurata.model_validate(vecchio).batteria_kwh is None
