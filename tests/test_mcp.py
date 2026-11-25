"""Server MCP (cersim/mcp): protocollo su stdio, strumenti, PVGIS scaricato dal server, dati privati che non escono."""

import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from cersim.mcp import pvgis
from cersim.mcp.protocollo import PROTOCOL_VERSIONS, Handler, serve_stdio
from cersim.mcp.scheda import MIME_MCP_APP, SCHEDA, SCHEDA_URI
from cersim.mcp.server import INFO
from cersim.mcp.strumenti import Opzioni, Sessione, crea_strumenti
from test_prices import _scrivi_csv
from test_web import risposta_pvgis

ESEMPI = Path(__file__).resolve().parents[1] / "esempi"
NOME, INDIRIZZO, POD = "Condominio Segreto", "Via Riservata 7, Torino", "IT001E99887766"

GENERALE = {"tipo": "gruppo", "lat": 45.07, "lon": 7.69, "regione": "Piemonte", "nome": NOME,
            "indirizzo": INDIRIZZO, "data_costituzione": "2027-01-01"}
IMPIANTO = {"impianto": "FV", "punto": "Famiglia 1", "kwp_moduli": 6.0, "kw_inverter": 6.0, "inclinazione": 25.0,
            "orientamento": 10.0, "entrata_esercizio": "2027-04-01", "investitore": "Famiglia 1"}


class Client:
    """Un agente finto: chiama il gestore come farebbe un client MCP, e raccoglie le notifiche."""

    def __init__(self, tmp_path, rete=True):
        self.handler = Handler(INFO, crea_strumenti(Opzioni(cache_dir=tmp_path / "pvgis", rete=rete), Sessione()))
        self.notifiche = []
        self.n = 0
        assert self.richiesta("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0]})["result"]

    def richiesta(self, method, params=None):
        self.n += 1
        return self.handler.handle({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}},
                                   self.notifiche.append)

    def chiama(self, nome, argomenti=None, token=None):
        params = {"name": nome, "arguments": argomenti or {}}
        if token is not None:
            params["_meta"] = {"progressToken": token}
        r = self.richiesta("tools/call", params)["result"]
        return r


@pytest.fixture
def pvgis_finto(monkeypatch):
    """PVGIS che risponde con il profilo semplificato in forma di seriescalc; conta le chiamate."""
    chiamate = []

    class Risposta:
        def __init__(self, params):
            self.params = params

        def raise_for_status(self):
            pass

        def json(self):
            return risposta_pvgis(self.params)

    def get(url, params=None, timeout=None):
        chiamate.append(params)
        return Risposta(params)

    monkeypatch.setattr(requests, "get", get)
    return chiamate


def _crea(c, **altro):
    args = {"generale": GENERALE, "famiglie_tipo": {"numero": 3, "kwh_annui": 2700}, "impianti": [IMPIANTO],
            "parametri": {"quota_membri": 0.5}} | altro
    r = c.chiama("crea_progetto", args)
    assert not r["isError"], r["content"][0]["text"]
    return r["structuredContent"]["progetto_id"]


# --- protocollo -------------------------------------------------------------------------------------------


def test_initialize_e_elenco_strumenti(tmp_path):
    h = Handler(INFO, crea_strumenti(Opzioni(cache_dir=tmp_path)))
    r = h.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
    assert r["result"]["protocolVersion"] == "2024-11-05" and r["result"]["serverInfo"]["name"] == "cer"
    r = h.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
    assert r["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]
    nomi = [t["name"] for t in h.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]]
    assert nomi == ["valori_predefiniti", "controlla_progetto", "crea_progetto", "leggi_consumi", "leggi_prezzi",
                    "proponi_impianto", "analizza_scenario", "dimensiona_impianto", "scrivi_report",
                    "esporta_progetto"]
    assert h.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert h.handle({"jsonrpc": "2.0", "id": 4, "method": "boh"})["error"]["code"] == -32601
    assert h.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "boh"}})["error"]
    assert h.handle([1, 2])["error"]["code"] == -32600


def test_scheda_nella_chat(tmp_path):
    """MCP Apps: la risorsa ui:// si elenca e si legge; gli strumenti la indicano nel loro _meta."""
    h = Handler(INFO, crea_strumenti(Opzioni(cache_dir=tmp_path)), [SCHEDA])
    r = h.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSIONS[0]}})
    assert "resources" in r["result"]["capabilities"]
    risorse = h.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/list"})["result"]["resources"]
    assert [(x["uri"], x["mimeType"]) for x in risorse] == [(SCHEDA_URI, MIME_MCP_APP)]
    assert h.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/templates/list"})["result"] == {"resourceTemplates": []}
    c = h.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": SCHEDA_URI}})["result"]["contents"][0]
    assert c["mimeType"] == MIME_MCP_APP and c["_meta"] == {"ui": {"prefersBorder": False}}
    html = c["text"]
    assert html.startswith("<!doctype html>") and 'lang="it"' in html and "ui/notifications/tool-result" in html
    # Nessuna risorsa esterna: la scheda gira con la CSP predefinita del client. L'unico indirizzo è lo spazio dei nomi SVG.
    assert set(re.findall(r"https?://[^\s\"')]+", html)) == {"http://www.w3.org/2000/svg"}
    assert "innerHTML" not in html  # i testi del progetto non diventano mai HTML
    errore = h.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": "ui://cer/boh"}})
    assert errore["error"]["code"] == -32002
    strumenti = h.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/list"})["result"]["tools"]
    con_scheda = {t["name"] for t in strumenti if t.get("_meta", {}).get("ui", {}).get("resourceUri") == SCHEDA_URI}
    assert con_scheda == {t["name"] for t in strumenti} - {"esporta_progetto"}
    # Senza risorse i metodi resources/* restano non supportati.
    senza = Handler(INFO, crea_strumenti(Opzioni(cache_dir=tmp_path)))
    assert senza.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})["error"]["code"] == -32601


def test_versione_vecchia_senza_structured_content(tmp_path):
    h = Handler(INFO, crea_strumenti(Opzioni(cache_dir=tmp_path)))
    h.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
    r = h.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "valori_predefiniti"}})
    assert "structuredContent" not in r["result"] and len(r["result"]["content"]) == 2
    assert "Piemonte" in json.loads(r["result"]["content"][1]["text"])["regioni"]


def test_stdio_una_riga_per_messaggio(tmp_path, monkeypatch):
    righe = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}), "non json", "",
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})]
    uscita = io.StringIO()
    serve_stdio(Handler(INFO, crea_strumenti(Opzioni(cache_dir=tmp_path))), io.StringIO("\n".join(righe) + "\n"),
                uscita)
    risposte = [json.loads(r) for r in uscita.getvalue().splitlines()]
    assert [r.get("id") for r in risposte] == [1, None, 2]
    assert risposte[1]["error"]["code"] == -32700


def test_avvio_come_processo(tmp_path):
    """Come lo avvia un client MCP: un processo, richieste su stdin, risposte su stdout, log su stderr."""
    righe = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "valori_predefiniti", "arguments": {"tipo": "CER"}}}]
    p = subprocess.run([sys.executable, "-m", "cersim.mcp.server", "--cache", str(tmp_path), "--senza-rete"],
                       input="\n".join(json.dumps(r) for r in righe) + "\n", capture_output=True, text=True,
                       encoding="utf-8", timeout=120, cwd=Path(__file__).resolve().parents[1])
    risposte = [json.loads(r) for r in p.stdout.splitlines()]
    assert [r["id"] for r in risposte] == [1, 2]
    assert risposte[1]["result"]["structuredContent"]["economia"]["tipo"] == "CER"
    assert "cersim-mcp" in p.stderr and "senza rete" in p.stderr


# --- progetto ---------------------------------------------------------------------------------------------


def test_crea_e_controlla_senza_dati_privati(tmp_path):
    c = Client(tmp_path)
    pid = _crea(c)
    r = c.chiama("controlla_progetto", {"progetto_id": pid})
    s = r["structuredContent"]
    assert not r["isError"] and s["riepilogo"]["contatori"] == 3 and s["serie_pvgis"] == 3
    assert s["impianti"][0]["kwp"] == 6.0 and not s["manca_quota_membri"]
    uscita = json.dumps(r, ensure_ascii=False)
    assert NOME not in uscita and INDIRIZZO not in uscita


def test_errori_di_creazione_leggibili(tmp_path):
    c = Client(tmp_path)
    r = c.chiama("crea_progetto", {"generale": {**GENERALE, "lat": 60}, "famiglie_tipo": {"numero": 2}})
    assert r["isError"] and "latitudine" in r["content"][0]["text"]
    r = c.chiama("crea_progetto", {"generale": GENERALE, "impianti": [{"potenza": 3}]})
    assert r["isError"] and "potenza" in r["content"][0]["text"]
    r = c.chiama("crea_progetto", {"generale": GENERALE, "consumi": {"Famiglia 1": "consumi-9"}})
    assert r["isError"] and "leggi_consumi" in r["content"][0]["text"]


def test_progetto_da_file_e_percorsi_rifiutati(tmp_path):
    c = Client(tmp_path)
    file = tmp_path / "lavoro.json"
    file.write_text(c.chiama("esporta_progetto", {"progetto_id": _crea(c)})["content"][0]["text"].split("\n\n", 1)[1])
    r = c.chiama("controlla_progetto", {"percorso": str(file)})
    assert not r["isError"] and r["structuredContent"]["progetto_id"] == "progetto-2"
    (tmp_path / "cartella.json").mkdir()
    for percorso, messaggio in [("//server/condivisa/x.json", "non ammesso"), (str(tmp_path / "x.csv"), ".json"),
                                (str(tmp_path / "manca.json"), "non trovato"),
                                (str(tmp_path / "cartella.json"), "non è un file")]:
        r = c.chiama("controlla_progetto", {"percorso": percorso})
        assert r["isError"] and messaggio in r["content"][0]["text"], (percorso, r["content"][0]["text"])
        assert percorso not in r["content"][0]["text"]
    r = c.chiama("controlla_progetto", {"contenuto": "{}", "percorso": str(file)})
    assert r["isError"] and "uno solo" in r["content"][0]["text"]
    r = c.chiama("controlla_progetto", {"contenuto": json.dumps({"schema": 99})})
    assert r["isError"] and "non è un salvataggio" in r["content"][0]["text"]


# --- analisi con PVGIS ------------------------------------------------------------------------------------


def test_analisi_scarica_pvgis_una_volta_sola(tmp_path, pvgis_finto):
    c = Client(tmp_path)
    pid = _crea(c)
    r = c.chiama("analizza_scenario", {"progetto_id": pid}, token="t1")
    s = r["structuredContent"]
    assert not r["isError"], r["content"][0]["text"]
    assert s["fonti_pv"] == ["PVGIS"] and s["pvgis"] | {"frase": ""} == {
        "serie": 3, "dalla_cache": 0, "scaricate": 3, "mancanti": 0, "frase": ""}
    assert len(pvgis_finto) == 3 and len(list((tmp_path / "pvgis").glob("pvgis_*.json"))) == 3
    progressi = [n["params"]["progress"] for n in c.notifiche if n["method"] == "notifications/progress"]
    assert progressi == [1, 2, 3]
    testo = r["content"][0]["text"]
    assert "Qualità C" in testo and "non è un preventivo" in testo and "Energia condivisa" in testo
    assert {"cifre", "confronto", "per_membro", "sensibilita", "requisiti", "analisi_id"} <= set(s)
    assert "giorno_tipo" not in s
    uscita = json.dumps(r, ensure_ascii=False)
    assert NOME not in uscita and INDIRIZZO not in uscita
    # la seconda volta tutto dalla cache, nessuna nuova richiesta
    r = c.chiama("analizza_scenario", {"progetto_id": pid})
    assert r["structuredContent"]["pvgis"]["dalla_cache"] == 3 and len(pvgis_finto) == 3


def test_senza_pvgis_modello_semplificato(tmp_path):
    c = Client(tmp_path)  # conftest: la rete solleva ConnectionError
    r = c.chiama("analizza_scenario", {"progetto_id": _crea(c)})
    s = r["structuredContent"]
    assert not r["isError"] and s["fonti_pv"] == ["sintetico"] and s["qualita"]["lettera"] == "C"
    assert s["pvgis"]["mancanti"] == 3 and "PVGIS non raggiungibile" in r["content"][0]["text"]


def test_dopo_due_errori_non_insiste(tmp_path, monkeypatch):
    chiamate = []

    def get(*a, **kw):
        chiamate.append(1)
        raise requests.Timeout()

    monkeypatch.setattr(requests, "get", get)
    esito = pvgis.scarica_serie([{"chiave": f"k{i}", "parametri": {}} for i in range(6)], cache_dir=tmp_path)
    assert len(chiamate) == pvgis.MAX_ERRORI_DI_FILA and len(esito.mancanti) == 6
    assert "in tempo" in esito.frase()


def test_senza_rete_solo_cache(tmp_path, pvgis_finto):
    c = Client(tmp_path, rete=False)
    r = c.chiama("analizza_scenario", {"progetto_id": _crea(c)})
    assert not pvgis_finto and "senza rete" in r["content"][0]["text"]


def test_proposta_dimensionamento_e_report(tmp_path, pvgis_finto):
    c = Client(tmp_path)
    pid = _crea(c, impianti=[])
    r = c.chiama("proponi_impianto", {"progetto_id": pid, "tetto": {
        "punto": "Famiglia 1", "investitore": "Famiglia 1", "superficie_m2": 60, "inclinazione": 25, "azimut": 0}})
    assert not r["isError"], r["content"][0]["text"]
    opzioni = r["structuredContent"]["opzioni"]
    assert len(opzioni) == 3 and all(o["progetto_id"] for o in opzioni)
    assert opzioni[0]["kwp"] <= opzioni[1]["kwp"] <= opzioni[2]["kwp"]

    scelto = opzioni[1]["progetto_id"]
    r = c.chiama("analizza_scenario", {"progetto_id": scelto})
    aid = r["structuredContent"]["analisi_id"]
    assert r["structuredContent"]["impianti"]

    r = c.chiama("dimensiona_impianto", {"analisi_id": aid, "n_punti": 4})
    assert not r["isError"], r["content"][0]["text"]
    assert len(r["structuredContent"]["curva"]) >= 3

    file = tmp_path / "scenario.xlsx"
    r = c.chiama("scrivi_report", {"analisi_id": aid, "formato": "xlsx", "percorso": str(file)})
    assert not r["isError"], r["content"][0]["text"]
    assert file.read_bytes()[:2] == b"PK"
    r = c.chiama("scrivi_report", {"analisi_id": aid, "formato": "xlsx", "percorso": str(file)})
    assert r["isError"] and "non sovrascrive" in r["content"][0]["text"]
    r = c.chiama("scrivi_report", {"analisi_id": aid, "formato": "pdf", "percorso": str(tmp_path / "a.xlsx")})
    assert r["isError"] and ".pdf" in r["content"][0]["text"]
    r = c.chiama("dimensiona_impianto", {"analisi_id": "analisi-99"})
    assert r["isError"] and "analizza_scenario" in r["content"][0]["text"]


def test_analisi_restano_distinte(tmp_path, pvgis_finto):
    """dimensiona_impianto usa l'analisi indicata, non l'ultima calcolata."""
    c = Client(tmp_path)
    a1 = c.chiama("analizza_scenario", {"progetto_id": _crea(c)})["structuredContent"]["analisi_id"]
    piccolo = {**IMPIANTO, "impianto": "Piccolo", "kwp_moduli": 2.0, "kw_inverter": 2.0}
    c.chiama("analizza_scenario", {"progetto_id": _crea(c, impianti=[piccolo])})
    r = c.chiama("dimensiona_impianto", {"analisi_id": a1})
    assert r["structuredContent"]["impianto"] == "FV"


# --- consumi e prezzi -------------------------------------------------------------------------------------


def test_consumi_dal_csv_del_distributore(tmp_path):
    c = Client(tmp_path)
    r = c.chiama("leggi_consumi", {"percorsi": [str(ESEMPI / "letture_esempio_sintetico.csv")]})
    assert not r["isError"], r["content"][0]["text"]
    s = r["structuredContent"]
    assert s["consumi_id"] == "consumi-1" and s["kwh_annui"] > 0 and "ore" not in json.dumps(s)
    pid = _crea(c, punti=[{"punto": "Casa 1", "membro": "Casa 1", "tipo_soggetto": "Persona fisica",
                           "tipologia": "Famiglia"}],
                famiglie_tipo={"numero": 1}, consumi={"Casa 1": "consumi-1"},
                impianti=[{**IMPIANTO, "punto": "Casa 1", "investitore": "Casa 1"}])
    s = c.chiama("controlla_progetto", {"progetto_id": pid})["structuredContent"]
    assert s["riepilogo"]["qualita_consumi"]["A"] + s["riepilogo"]["qualita_consumi"]["B"] >= 1


def test_profilo_di_casa_chiede_lo_scenario(tmp_path):
    c = Client(tmp_path)
    r = c.chiama("leggi_consumi", {"percorsi": [str(ESEMPI / "profilo_energetico_esempio.json")]})
    assert not r["isError"] and r["structuredContent"]["scegli_scenario"]
    scenario = r["structuredContent"]["scenari"][0]["id"]
    r = c.chiama("leggi_consumi", {"percorsi": [str(ESEMPI / "profilo_energetico_esempio.json")],
                                   "scenario": scenario})
    assert not r["isError"], r["content"][0]["text"]


def test_prezzi_orari_restano_sul_computer(tmp_path, pvgis_finto):
    c = Client(tmp_path)
    csv = tmp_path / "prezzi.csv"
    _scrivi_csv(csv, 2024)
    r = c.chiama("leggi_prezzi", {"percorsi": [str(csv)], "regione": "Piemonte"})
    assert not r["isError"], r["content"][0]["text"]
    assert r["structuredContent"]["anni"][0]["anno"] == 2024 and "valori" not in r["structuredContent"]
    r = c.chiama("analizza_scenario", {"progetto_id": _crea(c), "prezzi_id": "prezzi-1"})
    assert not r["isError"] and any("2024" in f for f in r["structuredContent"]["fonti_prezzi"])
    r = c.chiama("leggi_prezzi", {"percorsi": [str(tmp_path / "x.pdf")], "regione": "Piemonte"})
    assert r["isError"]


def test_pod_nome_e_indirizzo_non_escono(tmp_path, pvgis_finto):
    c = Client(tmp_path)
    file = json.loads(c.chiama("esporta_progetto", {"progetto_id": _crea(c)})["content"][0]["text"].split("\n\n", 1)[1])
    file["configurazione"]["connection_points"][0]["codice_pod"] = POD
    contenuto = json.dumps(file)
    for nome, args in [("controlla_progetto", {"contenuto": contenuto}),
                       ("analizza_scenario", {"contenuto": contenuto})]:
        r = c.chiama(nome, args)
        assert not r["isError"], r["content"][0]["text"]
        uscita = json.dumps(r, ensure_ascii=False)
        assert POD not in uscita and NOME not in uscita and INDIRIZZO not in uscita, nome
    aid = r["structuredContent"]["analisi_id"]
    uscita = json.dumps(c.chiama("dimensiona_impianto", {"analisi_id": aid}), ensure_ascii=False)
    assert NOME not in uscita


def test_bom_iniziale_ignorato(tmp_path):
    """La pipe di PowerShell 5.1 mette un BOM UTF-8 davanti alla prima riga: la richiesta vale lo stesso."""
    righe = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
             {"jsonrpc": "2.0", "id": 2, "method": "ping"}]
    dati = b"\xef\xbb\xbf" + "\n".join(json.dumps(r) for r in righe).encode() + b"\n"
    p = subprocess.run([sys.executable, "-m", "cersim.mcp.server", "--cache", str(tmp_path), "--senza-rete"],
                       input=dati, capture_output=True, timeout=120, cwd=Path(__file__).resolve().parents[1])
    risposte = [json.loads(r) for r in p.stdout.decode("utf-8").splitlines()]
    assert [r["id"] for r in risposte] == [1, 2] and all("result" in r for r in risposte)
    uscita = io.StringIO()
    serve_stdio(Handler(INFO, crea_strumenti(Opzioni(cache_dir=tmp_path))),
                io.StringIO("﻿" + json.dumps(righe[1]) + "\n"), uscita)
    assert json.loads(uscita.getvalue())["result"] == {}
