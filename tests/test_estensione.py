"""Estensione per Claude Desktop (estensione/crea_pacchetto.py): il pacchetto .mcpb ha tutto quello che serve."""

import json
import tomllib
import zipfile

from cersim import __version__
from cersim.mcp.strumenti import crea_strumenti
from estensione import crea_pacchetto


def test_pacchetto_mcpb(tmp_path):
    file = crea_pacchetto.crea(tmp_path / "cer.mcpb")
    with zipfile.ZipFile(file) as z:
        nomi = set(z.namelist())
        m = json.loads(z.read("manifest.json"))
        progetto = tomllib.loads(z.read("pyproject.toml").decode())
    # Server di tipo uv: Claude Desktop installa le dipendenze, nel pacchetto nessuna libreria.
    assert m["manifest_version"] == "0.4" and m["server"]["type"] == "uv" and m["version"] == __version__
    assert m["server"]["entry_point"] == "server.py" and m["name"] == "cer" and m["license"] == "MIT"
    assert [t["name"] for t in m["tools"]] == [t.name for t in crea_strumenti()]
    assert {"server.py", "icona.png", "LICENSE", "cersim/__init__.py", "cersim/mcp/scheda.html",
            "cersim/data/parametri_normativi.yaml", "static/Geist-Regular.ttf", "static/Geist-SemiBold.ttf"} <= nomi
    assert not any(n.startswith(("server/lib", "server/venv", ".venv")) or "__pycache__" in n for n in nomi)
    assert progetto["tool"]["uv"]["package"] is False
    radice = tomllib.loads((crea_pacchetto.RADICE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert progetto["project"]["dependencies"] == radice["dependencies"]
    assert progetto["project"]["requires-python"] == radice["requires-python"]
