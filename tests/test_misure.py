"""Lettore dei consumi misurati, con file costruiti sui formati reali documentati in cersim/misure.py."""

from datetime import date, timedelta

import numpy as np
import pytest

from cersim.loads import load_profile, qualita_consumi, qualita_insieme, quota_misurata
from cersim.misure import curva_da_file, curva_misurata, descrivi, leggi_file, unisci
from cersim.model import Fasce
from cersim.timebase import TZ, year_index
from conftest import punto

COLONNE = [f"{(i * 15) // 60:02d}:{(i * 15) % 60:02d}-{((i + 1) * 15) // 60 % 24:02d}:{((i + 1) * 15) % 60:02d}"
           for i in range(96)]
POD = "IT001E12345678"


def _quarti(giorno: date) -> list[float]:
    """Una famiglia: poco di notte, di più la sera; i giorni festivi un po' di più a mezzogiorno."""
    festivo = giorno.weekday() == 6
    return [0.25 if 76 <= i < 92 else (0.15 if festivo and 44 <= i < 56 else 0.05) for i in range(96)]


def _virgola(x: float) -> str:
    return f"{x:.3f}".replace(".", ",")


def sito(giorni: list[date], righe_extra: dict | None = None) -> bytes:
    """ExportData_<mese>.csv dal sito: virgolette, virgola decimale, ';' finale."""
    righe = ["Giorno;" + ";".join(COLONNE)]
    for g in giorni:
        for valori in (righe_extra or {}).get(g, [_quarti(g)]):
            righe.append(f'"{g:%d/%m/%Y}";' + ";".join(f'"{_virgola(v)}"' for v in valori) + ";")
    return ("\r\n".join(righe) + "\r\n").encode()


def app(giorni: list[date]) -> bytes:
    """FORNUTA<POD>.csv dall'app: data con l'ora, valori senza virgolette."""
    righe = ["Giorno;" + ";".join(COLONNE)]
    righe += [f"{g:%d/%m/%Y} 00:00;" + ";".join(_virgola(v) for v in _quarti(g)) + ";" for g in giorni]
    return ("\n".join(righe) + "\n").encode()


def portale(giorni: list[date], sostituite: dict | None = None) -> bytes:
    """letture.csv del Portale Consumi: POD in testa, punto decimale, ea1…ea96."""
    testa = ("pod;data_lettura;data_ricezione;motivazione;lettura_monoraria;lettura_f1;lettura_f2;lettura_f3;"
             "lettura_f4;lettura_f5;lettura_f6;tipo_flusso;annomese_riferimento;" + ";".join(f"ea{i}" for i in range(1, 97)))
    righe = [testa]
    for g in giorni:
        valori = [_quarti(g)] + ([(sostituite or {})[g]] if g in (sostituite or {}) else [])
        for n, v in enumerate(valori):
            motivo = "lettura sostitutiva" if n else ""
            righe.append(f"{POD};{g:%d/%m/%Y};{g + timedelta(days=1):%d/%m/%Y};{motivo};;1234.5;567.8;910.1;0.0;0.0;0.0;"
                         f"PDO;{g:%Y%m};" + ";".join(f"{x:.3f}" for x in v))
    return ("\n".join(righe) + "\n").encode()


def mese(anno: int, m: int) -> list[date]:
    inizio = date(anno, m, 1)
    fine = date(anno + (m == 12), m % 12 + 1, 1)
    return [inizio + timedelta(days=i) for i in range((fine - inizio).days)]


def anno(a: int) -> list[date]:
    return [g for m in range(1, 13) for g in mese(a, m)]


def test_i_tre_formati_danno_le_stesse_letture():
    giorni = mese(2025, 6)
    letture = {nome: leggi_file(f(giorni)) for nome, f in (("sito", sito), ("app", app), ("portale", portale))}
    assert letture["sito"].fonte == "e-distribuzione, sito"
    assert letture["app"].fonte == "e-distribuzione, app"
    assert letture["portale"].fonte == "Portale Consumi"
    for l in letture.values():
        assert len(l.quarti) == 30 * 96 and not l.avvisi
        assert l.quarti.sum() == pytest.approx(sum(sum(_quarti(g)) for g in giorni))
        # 01/06/2025 00:00 in ora legale = 31/05 22:00 UTC
        assert l.quarti.index[0].isoformat() == "2025-05-31T22:00:00+00:00"


def test_il_pod_non_esce_dal_lettore():
    letture = leggi_file(portale(mese(2025, 6)))
    assert POD not in repr(letture) and POD not in letture.fonte
    curva = curva_misurata(letture)
    assert POD not in curva.model_dump_json()


def test_cambio_ora_di_marzo_e_ottobre():
    # 30/03/2025: le 02:00-03:00 non esistono e nel file sono a zero
    marzo = [0.1] * 8 + [0.0] * 4 + [0.1] * 84
    l = leggi_file(sito([date(2025, 3, 30)], {date(2025, 3, 30): [marzo]}))
    assert len(l.quarti) == 92 and l.quarti.sum() == pytest.approx(9.2) and not l.avvisi
    ore = l.quarti.index.tz_convert(TZ)
    assert ore[7].strftime("%H:%M%z") == "01:45+0100" and ore[8].strftime("%H:%M%z") == "03:00+0200"
    # 26/10/2025: due righe, la prima in ora legale fino alle 03:00, la seconda in ora solare dalle 02:00
    legale = [0.1] * 8 + [0.2] * 4 + [0.0] * 84
    solare = [0.0] * 8 + [0.3] * 4 + [0.1] * 84
    l = leggi_file(sito([date(2025, 10, 26)], {date(2025, 10, 26): [legale, solare]}))
    assert len(l.quarti) == 100 and l.quarti.sum() == pytest.approx(0.8 + 0.8 + 1.2 + 8.4)
    assert l.quarti.index.is_unique


def test_lettura_sostitutiva_del_portale():
    g = date(2025, 6, 10)
    corretta = [0.5] * 96
    l = leggi_file(portale(mese(2025, 6), {g: corretta}))
    del_giorno = l.quarti[l.quarti.index.tz_convert(TZ).date == g]
    assert del_giorno.sum() == pytest.approx(48.0)


def test_piu_mesi_di_e_distribuzione_si_uniscono():
    curva, avvisi = curva_da_file([sito(mese(2025, m)) for m in range(1, 13)])
    assert curva.giorni == 365 and curva.dal == date(2025, 1, 1) and curva.al == date(2025, 12, 31)
    assert curva.fonte == "e-distribuzione, sito"
    assert avvisi == ["26/10/2025: ritorno all'ora solare in una sola riga, un'ora letta una volta"]
    atteso = sum(sum(_quarti(g)) for g in anno(2025))
    assert curva.kwh_annui == pytest.approx(atteso, rel=0.01)  # forma media sul calendario 2023: quasi uguale
    doppio = unisci([leggi_file(sito(mese(2025, 6))), leggi_file(sito(mese(2025, 6)))])
    assert len(doppio.quarti) == 30 * 96  # lo stesso mese caricato due volte vale una volta


def test_forma_media_per_tipo_di_giorno_mese_e_ora():
    curva = curva_misurata(leggi_file(portale(anno(2025))))
    sera, notte = curva.valore(0, 1, 20), curva.valore(0, 1, 3)  # feriale di gennaio
    assert sera == pytest.approx(1.0) and notte == pytest.approx(0.2)
    assert curva.valore(2, 7, 12) > curva.valore(0, 7, 12)  # festivi più alti a mezzogiorno
    assert "365 giorni" in descrivi(curva)


def test_mesi_mancanti_presi_dagli_altri():
    curva = curva_misurata(leggi_file(sito(mese(2025, 6) + mese(2025, 7))))
    assert curva.giorni == 61
    assert curva.valore(0, 1, 20) == pytest.approx(curva.valore(0, 6, 20))
    assert np.isfinite(curva.ore).all()


def test_file_non_validi():
    with pytest.raises(ValueError, match="Formato non riconosciuto"):
        leggi_file(b"data;consumo\n01/01/2025;3\n")
    with pytest.raises(ValueError, match="vuoto"):
        leggi_file(b"Giorno;" + ";".join(COLONNE).encode())
    with pytest.raises(ValueError, match="almeno 28 giorni"):
        curva_misurata(leggi_file(sito([date(2025, 6, 1)])))
    with pytest.raises(ValueError, match="Riga 2"):
        leggi_file(("Giorno;" + ";".join(COLONNE) + "\nieri;" + ";".join(["0"] * 96)).encode())


def test_la_simulazione_usa_la_curva_misurata():
    curva = curva_misurata(leggi_file(portale(anno(2025))))
    misurato = punto("p1", "fam1", curva_misurata=curva)
    tipico = punto("p2", "fam2", kwh_annui=curva.kwh_annui)
    idx = year_index(2027)
    m, t = load_profile(misurato, idx), load_profile(tipico, idx)
    assert m.sum() == pytest.approx(curva.kwh_annui, rel=1e-6) == pytest.approx(t.sum(), rel=1e-6)
    ore = idx.tz_convert(TZ).hour
    sera = (ore >= 19) & (ore < 23)  # 4 kWh su 8 al giorno: metà dei consumi la sera, come nelle misure
    assert m[sera].sum() / m.sum() == pytest.approx(0.49, abs=0.02) and t[sera].sum() / t.sum() < 0.4
    assert np.array_equal(load_profile(misurato, idx, variante=1), m)  # nessuna variante sulle ore vere


def test_qualita_a_con_tre_quarti_dei_consumi_misurati():
    lunga = curva_misurata(leggi_file(portale(anno(2025))))
    corta = curva_misurata(leggi_file(portale(mese(2025, 6) + mese(2025, 7))))
    bolletta = dict(kwh_annui=2700, fasce=Fasce(f1=900, f23=1800))
    assert qualita_consumi(punto("a", "x", curva_misurata=lunga)) == "A"
    assert qualita_consumi(punto("b", "x", curva_misurata=corta)) == "B"
    tre_misurati = [punto(f"m{i}", "x", curva_misurata=lunga) for i in range(3)] + [punto("b", "y", **bolletta)]
    assert quota_misurata(tre_misurati) > 0.7
    assert qualita_insieme(tre_misurati, ["B"], ["B"]) == "A"
    assert qualita_insieme(tre_misurati, ["B"], ["C"]) == "C"  # prezzo costante
    pochi = [punto("m", "x", curva_misurata=lunga)] + [punto(f"b{i}", "y", **bolletta) for i in range(3)]
    assert qualita_insieme(pochi, ["B"], ["B"]) == "B"
    assert qualita_insieme(pochi + [punto("t", "z")], ["B"], ["B"]) == "C"  # una famiglia tipo


def test_curve_nelle_tabelle_nel_salvataggio_e_nelle_schede():
    from cersim.guida import Contatore, Scheda, crea_scheda, leggi_scheda, unisci_schede
    from cersim.ui_model import (
        Generale,
        configurazione_da_tabelle,
        esporta_json,
        famiglie_tipo,
        impianti_vuoti,
        importa_json,
        punti_vuoti,
        tabelle_da_configurazione,
    )

    curva = curva_misurata(leggi_file(portale(anno(2025))))
    generale = Generale("Prova", "gruppo", 45.07, 7.69, "Piemonte", data_costituzione=date(2027, 1, 1))
    punti = famiglie_tipo(2, kwh=2700)
    esito = configurazione_da_tabelle(generale, punti, impianti_vuoti(), curve={"Famiglia 1": curva})
    cp1, cp2 = esito.config.connection_points
    assert cp1.curva_misurata == curva and cp1.kwh_annui is None and cp1.kwh_effettivi == curva.kwh_annui
    assert cp2.curva_misurata is None and cp2.kwh_annui == 2700

    # salva e ricarica: la curva resta, il POD non c'è
    salvato = esporta_json(esito.config, {})
    assert POD not in salvato
    ricaricata, _ = importa_json(salvato)
    assert ricaricata.connection_points[0].curva_misurata == curva
    _, tabella, _ = tabelle_da_configurazione(ricaricata)
    assert tabella["kWh annui"].iloc[0] == pytest.approx(curva.kwh_annui)

    # una famiglia allega i suoi consumi alla scheda: a chi coordina arriva la forma media
    scheda = Scheda("Rossi, interno 3", "Persona fisica",
                    [Contatore("Contatore", "Famiglia", curva=curva)], configurazione="Prova")
    testo = crea_scheda(scheda)
    assert POD not in testo
    riletta = leggi_scheda(testo)
    assert "giorni_veri" not in testo  # a chi coordina arriva solo la forma media
    sola_media = curva.model_copy(update={"giorni_veri": ()})
    assert riletta.contatori[0].curva == sola_media
    curve: dict = {}
    tabella, _ = unisci_schede(punti_vuoti(), [riletta], curve=curve)
    assert curve == {"Rossi, interno 3": sola_media}
    # la scheda con cinque curve resta sotto il limite di dimensione
    cinque = Scheda("Bar", "PMI", [Contatore(f"C{i}", "Ufficio / negozio", curva=curva) for i in range(5)])
    leggi_scheda(crea_scheda(cinque))


def test_app_calcola_con_le_curve_misurate():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    curva = curva_misurata(leggi_file(portale(anno(2025))))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=180)
    at.run()
    at.sidebar.button[0].click().run()  # esempio di Torino
    etichette = list(at.session_state["punti_base"]["Punto"])
    at.session_state["curve_misurate"] = {e: curva for e in etichette}
    at.run()
    assert any("14 contatori" in e.label for e in at.expander)
    next(r for r in at.radio if r.label.startswith("Quota")).set_value(0.5).run()
    next(b for b in at.button if "Calcola lo scenario" in b.label).click().run()
    assert not at.exception, at.exception
    analisi = at.session_state["analisi"]
    assert all(c.curva_misurata == curva for c in analisi.config.connection_points)
    assert analisi.qualita == "C"  # i consumi sono misurati, ma il prezzo dell'energia resta costante
