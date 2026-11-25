import json
from datetime import date
from pathlib import Path

import pytest

from cersim import schema, web
from cersim.cli import main
from cersim.pv import synthetic_profile
from cersim.ui_model import importa_json

jsonschema = pytest.importorskip("jsonschema")

RADICE = Path(__file__).resolve().parents[1]
TORINO = RADICE / "web" / "public" / "esempi" / "torino.json"


def _valida(dati: dict, quale: dict) -> None:
    jsonschema.Draft202012Validator(quale, format_checker=jsonschema.FormatChecker()).validate(dati)


def test_i_file_degli_schemi_sono_aggiornati():
    """Se fallisce: python -m cersim.schema, poi controlla le differenze."""
    for nome, atteso in schema.schemi().items():
        assert (schema.CARTELLA / nome).read_text(encoding="utf-8") == schema.testo(atteso), nome


def test_gli_schemi_sono_schemi_validi():
    for quale in schema.schemi().values():
        jsonschema.Draft202012Validator.check_schema(quale)


def test_ogni_campo_del_progetto_ha_una_descrizione():
    progetto = schema.schema_progetto()
    for modello in schema.DESCRIZIONI:
        nodo = progetto["$defs"][modello]
        assert nodo.get("description"), modello
        mancano = [c for c, v in nodo["properties"].items() if not v.get("description")]
        assert not mancano, f"{modello}: {mancano}"
    assert all(v.get("description") for v in progetto["properties"]["parametri"]["properties"].values())


def test_l_esempio_di_torino_rispetta_lo_schema_del_progetto():
    _valida(json.loads(TORINO.read_text(encoding="utf-8")), schema.schema_progetto())


@pytest.mark.parametrize("guasto", [
    lambda p: p.update(schema=2),
    lambda p: p["configurazione"].update(lat=60),
    lambda p: p["configurazione"].update(tipo="condominio"),
    lambda p: p["configurazione"]["members"][0].update(colore="blu"),
    lambda p: p.update(parametri={"quota_membri": 1.5}),
])
def test_lo_schema_rifiuta_i_progetti_sbagliati(guasto):
    progetto = json.loads(TORINO.read_text(encoding="utf-8"))
    guasto(progetto)
    with pytest.raises(jsonschema.ValidationError):
        _valida(progetto, schema.schema_progetto())


def test_l_esito_rispetta_lo_schema():
    testo = TORINO.read_text(encoding="utf-8")
    config, _ = importa_json(testo)
    esito = schema.esito(web.risultati(testo, {}, fetch_pv=synthetic_profile), config, oggi=date(2026, 11, 24))
    _valida(esito, schema.schema_esito())
    assert esito["formato"] == "esito-cer" and esito["ok"] and esito["calcolato_il"] == "2026-11-24"
    assert esito["progetto"] == {"nome": config.nome, "tipo": "CER", "membri": 14, "contatori": 14, "impianti": 1}
    _valida(schema.esito({"ok": False, "errore": "File non valido"}), schema.schema_esito())


# --- la riga di comando ---------------------------------------------------------------------------------------------

def _esegui(capsys, *argomenti) -> tuple[int, dict | None]:
    codice = main([str(a) for a in argomenti])
    uscita = capsys.readouterr().out
    return codice, json.loads(uscita) if uscita.strip() else None


def test_cli_schema(capsys):
    codice, uscita = _esegui(capsys, "schema", "progetto")
    assert codice == 0 and uscita == schema.schema_progetto()


def test_cli_valida(capsys, tmp_path):
    codice, uscita = _esegui(capsys, "valida", TORINO)
    assert codice == 0 and uscita["ok"] and uscita["riepilogo"]["contatori"] == 14 and uscita["da_verificare"]

    sbagliato = tmp_path / "sbagliato.json"
    progetto = json.loads(TORINO.read_text(encoding="utf-8"))
    progetto["configurazione"]["plants"][0]["investitore"] = "nessuno"
    sbagliato.write_text(json.dumps(progetto), encoding="utf-8")
    codice, uscita = _esegui(capsys, "valida", sbagliato)
    assert codice == 1 and "investitore sconosciuto" in uscita["errore"]

    codice, uscita = _esegui(capsys, "valida", tmp_path / "manca.json")
    assert codice == 1 and "Non riesco a leggere" in uscita["errore"]


def test_cli_analizza_e_cambia_i_parametri(capsys, tmp_path):
    esito = tmp_path / "esito.json"
    codice, _ = _esegui(capsys, "analizza", TORINO, "--senza-rete", "-o", esito)
    base = json.loads(esito.read_text(encoding="utf-8"))
    assert codice == 0 and base["ok"] and base["fonti_pv"] == ["sintetico"]
    _valida(base, schema.schema_esito())

    codice, piu_ai_membri = _esegui(capsys, "analizza", TORINO, "--senza-rete", "--parametro", "quota_membri=0.9")
    assert codice == 0
    assert sum(m["netto"] for m in piu_ai_membri["per_membro"]) != sum(m["netto"] for m in base["per_membro"])

    codice, uscita = _esegui(capsys, "analizza", TORINO, "--parametro", "pippo=1")
    assert codice == 1 and "Parametro sconosciuto" in uscita["errore"]
    codice, uscita = _esegui(capsys, "analizza", TORINO, "--senza-rete", "--parametro", "quota_membri=2")
    assert codice == 1 and "quota ai membri" in uscita["errore"]
    _valida(uscita, schema.schema_esito())


def test_cli_senza_riparto_non_calcola(capsys, tmp_path):
    progetto = json.loads(TORINO.read_text(encoding="utf-8"))
    progetto["parametri"] = {}
    senza = tmp_path / "senza.json"
    senza.write_text(json.dumps(progetto), encoding="utf-8")
    codice, uscita = _esegui(capsys, "valida", senza)
    assert codice == 0 and "quota_membri" in uscita["avvisi"][0]
    codice, uscita = _esegui(capsys, "analizza", senza, "--senza-rete")
    assert codice == 1 and "quanta parte dei contributi" in uscita["errore"]


def test_cli_report_excel(capsys, tmp_path):
    file = tmp_path / "scenario.xlsx"
    assert main(["report", str(TORINO), "--senza-rete", "-o", str(file)]) == 0
    assert file.read_bytes()[:2] == b"PK"
    assert main(["report", str(TORINO), "-o", str(tmp_path / "scenario.doc")]) == 2
