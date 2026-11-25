"""Punto d'ingresso del server MCP dentro l'estensione per Claude Desktop (cer.mcpb).

Claude Desktop lo avvia con uv, che installa le dipendenze del pyproject.toml del pacchetto in un ambiente suo.
Il motore `cersim` e i caratteri del report (`static/`) stanno accanto a questo file.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cersim.mcp.server import main

if __name__ == "__main__":
    main(sys.argv[1:])
