"""Server MCP del simulatore: gira sul computer di chi lo usa e parla con l'agente da stdin e stdout.

Uso: cersim-mcp [--cache <cartella della cache PVGIS>] [--senza-rete]
(oppure python -m cersim.mcp.server). Guida: docs/GUIDA-MCP.md.
"""

import argparse
import sys
from pathlib import Path

from cersim import __version__
from cersim.mcp.protocollo import Handler, ServerInfo, serve_stdio
from cersim.mcp.scheda import SCHEDA
from cersim.mcp.strumenti import Opzioni, crea_strumenti
from cersim.pv import default_cache_dir

INFO = ServerInfo(
    name="cer",
    title="CER: comunità energetiche e gruppi di autoconsumatori",
    version=__version__,
    instructions=(
        "Strumenti del simulatore di comunità energetiche rinnovabili e gruppi di autoconsumatori "
        "(cer.raccasamuele.it), con lo stesso motore del sito. Gira sul computer dell'utente. Flusso tipico: "
        "valori_predefiniti → crea_progetto (o controlla_progetto su un file salvato) → proponi_impianto se manca "
        "l'impianto → analizza_scenario → dimensiona_impianto o scrivi_report. Gli identificativi (progetto_id, "
        "consumi_id, prezzi_id, analisi_id) valgono finché il server è acceso. Quando puoi, passa il percorso dei "
        "file invece del contenuto. Riporta sempre insieme ai numeri la qualità dei dati, gli intervalli, le "
        "avvertenze e l'avvertenza finale. Non presentare come certi i requisiti «da verificare»."),
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="cersim-mcp", description="Server MCP del simulatore CER (stdio).")
    parser.add_argument("--cache", type=Path, help="cartella della cache PVGIS (predefinita: quella di cersim)")
    parser.add_argument("--senza-rete", action="store_true",
                        help="non scarica da PVGIS: solo la cache, altrimenti il modello semplificato")
    a = parser.parse_args(argv)
    opz = Opzioni(cache_dir=a.cache.expanduser().resolve() if a.cache else None, rete=not a.senza_rete)
    for flusso in (sys.stdin, sys.stdout):  # su Windows la console non è UTF-8
        if hasattr(flusso, "reconfigure"):
            flusso.reconfigure(encoding="utf-8")
    sys.stderr.write(f"cersim-mcp {__version__}: cache PVGIS in {opz.cache_dir or default_cache_dir()}"
                     f"{', senza rete' if not opz.rete else ''}\n")
    try:
        serve_stdio(Handler(INFO, crea_strumenti(opz), [SCHEDA]))
    except (BrokenPipeError, KeyboardInterrupt):  # il client ha chiuso: si esce senza traccia su stderr
        pass


if __name__ == "__main__":
    main()
