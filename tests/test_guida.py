import json
import re
from datetime import date
from pathlib import Path

import pytest

from cersim.guida import (
    COSA_SERVE,
    FORMATO,
    MAX_BYTE,
    Contatore,
    Scheda,
    controlla,
    crea_scheda,
    leggi_scheda,
    link_famiglie,
    nome_file,
    unisci_schede,
)
from cersim.report import scheda_famiglia_pdf
from cersim.ui_model import Generale, configurazione_da_tabelle, famiglie_tipo, impianti_vuoti, punti_vuoti

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def famiglia(nome="Rossi, interno 3", kwh=2400.0, f1=800.0, f23=1600.0):
    return Scheda(membro=nome, tipo_soggetto="Persona fisica",
                  contatori=[Contatore("Contatore", "Famiglia", kwh, f1, f23)], configurazione="Condominio Via Roma 1",
                  compilata_il=date(2026, 10, 16))


def test_ogni_gruppo_dice_cosa_e_dove():
    assert set(COSA_SERVE) == {"coordina", "famiglia", "attivita", "parti_comuni"}
    for gruppo in COSA_SERVE.values():
        assert gruppo.voci and all(v.cosa and v.dove for v in gruppo.voci)


def test_scheda_andata_e_ritorno():
    testo = crea_scheda(famiglia())
    assert json.loads(testo)["formato"] == FORMATO
    letta = leggi_scheda(testo.encode())
    assert letta.membro == "Rossi, interno 3" and letta.contatori[0].kwh_annui == 2400
    assert letta.configurazione == "Condominio Via Roma 1" and letta.compilata_il == date(2026, 10, 16)
    assert nome_file(letta) == "consumi_rossi_interno_3.json"


def test_controlli_comprensibili():
    assert controlla(famiglia()) == []
    assert controlla(famiglia(kwh=None, f1=None, f23=None)) == []  # si userà la famiglia tipo
    assert any("F2+F3" in e for e in controlla(famiglia(f23=None)))
    # fasce di una sola bolletta (due mesi) contro il consumo annuo
    assert any("una sola bolletta" in e for e in controlla(famiglia(kwh=2400, f1=130, f23=270)))
    assert any("nome" in e for e in controlla(famiglia(nome="  ")))


@pytest.mark.parametrize("dati, motivo", [
    (b"non json", "illeggibile"),
    (json.dumps({"formato": "altro"}).encode(), "non è una scheda"),
    (b" " * (MAX_BYTE + 1), "troppo grande"),
], ids=["illeggibile", "altro_formato", "troppo_grande"])
def test_file_non_validi(dati, motivo):
    with pytest.raises(ValueError, match=motivo):
        leggi_scheda(dati)


def test_valori_manomessi_rifiutati():
    contenuto = json.loads(crea_scheda(famiglia()))
    contenuto["contatori"][0]["kwh_annui"] = "=1+1"
    with pytest.raises(ValueError, match="serve un numero"):
        leggi_scheda(json.dumps(contenuto))
    contenuto["contatori"][0]["kwh_annui"] = 1e12
    with pytest.raises(ValueError, match="fuori scala"):
        leggi_scheda(json.dumps(contenuto))


def test_unione_aggiunge_aggiorna_e_non_sovrascrive_altri():
    punti = famiglie_tipo(2)
    punti, messaggi = unisci_schede(punti, [famiglia()])
    assert len(punti) == 3 and messaggi[0].startswith("Contatori aggiunti: 1; aggiornati: 0")
    # la stessa famiglia rimanda la scheda corretta: si aggiorna la sua riga
    punti, messaggi = unisci_schede(punti, [famiglia(kwh=3000, f1=1000, f23=2000)])
    assert len(punti) == 3 and "aggiornati: 1" in messaggi[0]
    assert punti.loc[punti["Punto"] == "Rossi, interno 3", "kWh annui"].item() == 3000
    assert "(Rossi, interno 3)" in messaggi[0]  # chi coordina vede di chi sono i dati sostituiti
    # un contatore di un altro membro con lo stesso nome non viene sovrascritto
    punti, _ = unisci_schede(punti, [famiglia(nome="Panetteria, Negozio")])
    negozio = Scheda(membro="Panetteria", tipo_soggetto="PMI", contatori=[
        Contatore("Negozio", "Ufficio / negozio", 14000), Contatore("Forno", "PMI / laboratorio", 9000)])
    punti, messaggi = unisci_schede(punti, [negozio])
    assert len(punti) == 6 and "Panetteria, Negozio (2)" in set(punti["Punto"])
    assert any("un altro membro" in m for m in messaggi)


def test_attivita_con_due_contatori_e_tabella_valida():
    negozio = Scheda(membro="Panetteria", tipo_soggetto="PMI", contatori=[
        Contatore("Negozio", "Ufficio / negozio", 14000, 8400, 5600),
        Contatore("Laboratorio", "PMI / laboratorio", 9000, None, None, "MT"),
    ])
    punti, _ = unisci_schede(punti_vuoti(), [leggi_scheda(crea_scheda(negozio)), famiglia()])
    assert list(punti["Punto"]) == ["Panetteria, Negozio", "Panetteria, Laboratorio", "Rossi, interno 3"]
    esito = configurazione_da_tabelle(Generale("Prova", "gruppo", 45.07, 7.69, "Piemonte"), punti, impianti_vuoti())
    assert esito.config is not None and not esito.errori
    assert len(esito.config.connection_points) == 3 and len(esito.config.members) == 2


def test_link_per_famiglie():
    link = link_famiglie("https://cersim.example/app?vecchio=1#x", "Condominio Via Roma 1, Torino")
    assert link == "https://cersim.example/app?modulo=famiglia&per=Condominio+Via+Roma+1%2C+Torino"
    assert link_famiglie("http://localhost:8501/", "") == "http://localhost:8501/?modulo=famiglia"


def test_scheda_stampabile_di_una_pagina():
    pdf = scheda_famiglia_pdf("Condominio Via Roma 1", "http://localhost:8501/?modulo=famiglia")
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page(?!s)", pdf)) == 1
    assert scheda_famiglia_pdf().startswith(b"%PDF")


def test_modulo_famiglia_nell_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["modulo"] = "famiglia"
    at.query_params["per"] = "Condominio Via Roma 1"
    at.run()
    assert not at.exception, at.exception
    assert not at.tabs  # niente percorso in 5 passi: solo la scheda
    at.text_input[0].set_value("Rossi, interno 3").run()
    consumi = [n for n in at.number_input if n.label.startswith(("Consumo", "di cui"))]
    for campo, valore in zip(consumi, (2400.0, 800.0, 1600.0)):
        campo.set_value(valore)
    at.run()
    assert not at.exception and not at.warning
    assert at.get("download_button")


def test_prima_di_iniziare_e_link_nell_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    assert at.tabs[0].label == "Prima di iniziare"
    assert any("modulo=famiglia" in c.value for c in at.code)


def test_percorso_con_i_pulsanti_avanti():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    next(b for b in at.button if b.label == "Inizia dal passo 1").click().run()
    assert not at.exception, at.exception
    assert at.session_state["passo"] == "Luogo"
    next(b for b in at.button if b.label == "Prova con l'esempio di Torino").click().run()
    assert at.session_state["passo"] == "Luogo" and len(at.session_state["punti_base"]) == 14
    for n, passo in enumerate(("Membri e consumi", "Impianti", "Economia", "Risultati"), start=2):
        next(b for b in at.button if b.label == f"Avanti: {n}. {passo}").click().run()
        assert not at.exception, at.exception
        assert at.session_state["passo"] == passo
    # al passo 5 manca il riparto: un pulsante riporta al passo 4
    next(b for b in at.button if b.label == "Torna al passo 4").click().run()
    assert at.session_state["passo"] == "Economia"
