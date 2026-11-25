"""Strato minimo del Model Context Protocol (MCP) su stdio, scritto a mano: nessuna dipendenza nuova.

Come mcp/protocollo.ts di Casa. Messaggi JSON-RPC 2.0, uno per riga. Metodi: initialize, ping, tools/list,
tools/call, resources/list, resources/templates/list, resources/read; le notifiche ricevute si ignorano. Se la chiamata porta `_meta.progressToken`, gli strumenti lunghi
mandano `notifications/progress`. Su stdout passano solo i messaggi del protocollo; i log vanno su stderr.
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import IO, Any

# Dalla più recente: si risponde con quella chiesta dal client se la conosciamo, altrimenti con la prima.
PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
STRUCTURED_FROM = "2025-06-18"  # da questa versione i risultati possono avere `structuredContent`

Progress = Callable[[float, float, str | None], None]
Notify = Callable[[dict], None]


@dataclass
class ToolOutput:
    text: str  # in italiano, da citare così com'è
    structured: dict = field(default_factory=dict)
    is_error: bool = False


@dataclass
class ToolDef:
    name: str
    title: str
    description: str
    input_schema: dict
    run: Callable[[dict, Progress | None], ToolOutput]
    annotations: dict = field(default_factory=dict)
    meta: dict | None = None  # es. `ui.resourceUri`: la scheda MCP Apps che il client mostra con il risultato

    def definizione(self) -> dict:
        d = {"name": self.name, "title": self.title, "description": self.description,
             "inputSchema": self.input_schema, "annotations": self.annotations}
        if self.meta:
            d["_meta"] = self.meta
        return d


@dataclass
class ResourceDef:
    """Risorsa di sola lettura, es. la scheda HTML di MCP Apps (`ui://…`)."""
    uri: str
    name: str
    title: str
    description: str
    mime_type: str
    text: Callable[[], str]
    meta: dict | None = None

    def definizione(self) -> dict:
        return {"uri": self.uri, "name": self.name, "title": self.title, "description": self.description,
                "mimeType": self.mime_type}

    def contenuto(self) -> dict:
        c = {"uri": self.uri, "mimeType": self.mime_type, "text": self.text()}
        if self.meta:
            c["_meta"] = self.meta
        return c


@dataclass
class ServerInfo:
    name: str
    title: str
    version: str
    instructions: str


def _is_id(v: Any) -> bool:
    return isinstance(v, str) or (isinstance(v, int | float) and not isinstance(v, bool) and v == v)


def _ok(id_, result) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _fail(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


class Handler:
    """Gestore dei messaggi: `handle` restituisce la risposta, o None per le notifiche."""

    def __init__(self, info: ServerInfo, tools: list[ToolDef], resources: list[ResourceDef] | None = None):
        self.info = info
        self.tools = {t.name: t for t in tools}
        self.resources = {r.uri: r for r in resources or []}
        self.version = PROTOCOL_VERSIONS[0]

    def handle(self, raw: Any, notify: Notify | None = None) -> dict | None:
        if isinstance(raw, list):
            return _fail(None, -32600, "Richieste multiple non supportate.")
        msg = raw if isinstance(raw, dict) else {}
        method = msg.get("method")
        if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _fail(msg["id"], -32600, "Richiesta JSON-RPC non valida.") if _is_id(msg.get("id")) else None
        if "id" not in msg:
            return None  # notifica (es. notifications/initialized)
        id_ = msg["id"]
        if not _is_id(id_):
            return _fail(None, -32600, "Identificativo della richiesta non valido.")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        # Senza risorse i metodi resources/* restano non supportati, come prima della scheda nella chat.
        if not self.resources and method.startswith("resources/"):
            return _fail(id_, -32601, f"Metodo non supportato: {method[:60]}.")

        if method == "initialize":
            chiesta = params.get("protocolVersion")
            self.version = chiesta if chiesta in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return _ok(id_, {
                "protocolVersion": self.version,
                "capabilities": {"tools": {"listChanged": False},
                                 **({"resources": {"listChanged": False}} if self.resources else {})},
                "serverInfo": {"name": self.info.name, "title": self.info.title, "version": self.info.version},
                "instructions": self.info.instructions,
            })
        if method == "ping":
            return _ok(id_, {})
        if method == "tools/list":
            return _ok(id_, {"tools": [t.definizione() for t in self.tools.values()]})
        if method == "tools/call":
            return self._call(id_, params, notify)
        if method == "resources/list":
            return _ok(id_, {"resources": [r.definizione() for r in self.resources.values()]})
        if method == "resources/templates/list":
            return _ok(id_, {"resourceTemplates": []})
        if method == "resources/read":
            uri = params.get("uri")
            res = self.resources.get(uri) if isinstance(uri, str) else None
            if res is None:
                return _fail(id_, -32002, f"Risorsa sconosciuta: {str(uri)[:80]}.")
            return _ok(id_, {"contents": [res.contenuto()]})
        return _fail(id_, -32601, f"Metodo non supportato: {method[:60]}.")

    def _call(self, id_, params: dict, notify: Notify | None) -> dict:
        nome = params.get("name")
        tool = self.tools.get(nome) if isinstance(nome, str) else None
        if tool is None:
            return _fail(id_, -32602, f"Strumento sconosciuto: {str(nome)[:60]}.")
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return _fail(id_, -32602, "Gli argomenti devono essere un oggetto.")
        meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        token = meta.get("progressToken")
        progress = None
        if notify is not None and _is_id(token):
            ultimo = [0.0]

            def progress(fatti: float, totale: float, messaggio: str | None = None) -> None:
                if not fatti > ultimo[0]:  # l'avanzamento deve crescere a ogni notifica
                    return
                ultimo[0] = fatti
                p = {"progressToken": token, "progress": fatti, "total": totale}
                if messaggio:
                    p["message"] = messaggio
                notify({"jsonrpc": "2.0", "method": "notifications/progress", "params": p})
        try:
            out = tool.run(args, progress)
        except Exception as e:  # noqa: BLE001 - l'errore torna all'agente come risultato, il server resta acceso
            out = ToolOutput(f"Errore interno dello strumento: {e}", {}, True)
        strutturato = self.version >= STRUCTURED_FROM
        contenuto = [{"type": "text", "text": out.text}]
        if not strutturato:
            contenuto.append({"type": "text", "text": json.dumps(out.structured, ensure_ascii=False)})
        risultato = {"content": contenuto, "isError": bool(out.is_error)}
        if strutturato:
            risultato["structuredContent"] = out.structured
        return _ok(id_, risultato)


def serve_stdio(handler: Handler, input: IO[str] | None = None, output: IO[str] | None = None) -> None:
    """Legge le richieste da stdin, una per riga, e risponde in ordine su stdout."""
    input = input or sys.stdin
    output = output or sys.stdout

    def scrivi(messaggio: dict) -> None:
        output.write(json.dumps(messaggio, ensure_ascii=False) + "\n")
        output.flush()

    for riga in input:
        riga = riga.lstrip("\ufeff")  # BOM UTF-8 che la pipe di PowerShell 5.1 mette davanti alla prima riga
        if not riga.strip():
            continue
        try:
            raw = json.loads(riga)
        except ValueError:
            scrivi(_fail(None, -32700, "Messaggio non leggibile: JSON non valido."))
            continue
        risposta = handler.handle(raw, scrivi)
        if risposta is not None:
            scrivi(risposta)
