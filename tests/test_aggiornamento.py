"""Inventario dei dati da tenere aggiornati (aggiornamento/fonti.json):
coerente con i file YAML, non in ritardo, pacchetti non in scadenza imminente."""

import importlib.util
import json
import re
from datetime import date, timedelta
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parent.parent
INV = json.loads((RADICE / "aggiornamento/fonti.json").read_text(encoding="utf-8"))

_spec = importlib.util.spec_from_file_location("scadute", RADICE / "aggiornamento/scadute.py")
scadute = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scadute)


def _valore(dati, percorso):
    for chiave in percorso.split("."):
        if isinstance(dati, list):
            dati = dati[int(chiave)]
        elif chiave in dati:
            dati = dati[chiave]
        else:
            dati = dati[int(chiave)]
    return dati


def test_inventario_ben_formato():
    assert INV["versione"] == 1
    ids = [v["id"] for v in INV["fonti"]]
    assert len(set(ids)) == len(ids)
    for v in INV["fonti"]:
        assert re.fullmatch(r"[a-z0-9-]+", v["id"])
        assert date.fromisoformat(v["ultimo_controllo"]) <= date.today()
        assert v["frequenza_mesi"] > 0
        assert len(v["fonte"]) > 10
        assert len(v["come_controllare"]) > 20
        assert len(v["se_cambia"]) > 10
        assert isinstance(v["automatico"], bool)


def test_i_file_indicati_esistono():
    for v in INV["fonti"]:
        for p in v["dove"]:
            assert (RADICE / p).exists(), f"{v['id']}: {p}"


def test_i_valori_dell_inventario_sono_quelli_dei_file():
    for v in INV["fonti"]:
        for x in v["valori"]:
            dati = yaml.safe_load((RADICE / x["file"]).read_text(encoding="utf-8"))
            trovato = _valore(dati, x["percorso"])
            if isinstance(trovato, date):
                trovato = trovato.isoformat()
            assert trovato == x["valore"], f"{v['id']}: {x['percorso']}"


def test_nessuna_voce_in_ritardo_oltre_tre_mesi():
    # se fallisce, la routine trimestrale non è passata o la pull request non è stata accolta:
    # vedi aggiornamento/ISTRUZIONI.md
    oggi = date.today()
    in_ritardo = [v["id"] for v in INV["fonti"]
                  if scadute.mesi_dopo(date.fromisoformat(v["ultimo_controllo"]), v["frequenza_mesi"] + 3) < oggi]
    assert in_ritardo == []


def test_nessun_pacchetto_scade_entro_trenta_giorni():
    # la routine avvisa con quattro mesi di anticipo; qui si ferma la pubblicazione a un mese
    limite = (date.today() + timedelta(days=30)).isoformat()
    vicini = [r["file"] for r in scadute.scadenze_pacchetti(date.today()) if r["scadenza"] <= limite]
    assert vicini == []


def test_da_controllare_le_voci_che_scadono_prima_della_routine_successiva():
    # controllo il 5 gennaio: ARERA vista il 2 novembre ogni 3 mesi scade il 2 febbraio, prima del 5 aprile
    voce = {"ultimo_controllo": "2026-11-02", "frequenza_mesi": 3}
    assert scadute.da_controllare(voce, date(2027, 1, 5), 3)
    assert not scadute.da_controllare(voce, date(2026, 11, 1), 3)
    # una voce che scade proprio il giorno della routine successiva aspetta quella
    assert not scadute.da_controllare({"ultimo_controllo": "2027-01-05", "frequenza_mesi": 3}, date(2027, 1, 5), 3)


def test_mesi_dopo_fine_mese():
    assert scadute.mesi_dopo(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert scadute.mesi_dopo(date(2027, 11, 30), 3) == date(2028, 2, 29)
    assert scadute.mesi_dopo(date(2026, 10, 15), 12) == date(2027, 10, 15)
