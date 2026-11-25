"""Crea l'estensione per Claude Desktop: dist/cer-<versione>.mcpb (guida: docs/GUIDA-MCP.md §4).

Uso, dalla cartella del repository: python estensione/crea_pacchetto.py [--uscita <file .mcpb>]

Il pacchetto è un archivio zip con manifest.json (formato MCPB, server di tipo «uv»), un pyproject.toml con le sole
dipendenze del motore, il pacchetto `cersim`, i caratteri del report e la licenza. Nessuna libreria dentro: le
installa Claude Desktop con uv al primo avvio, per il sistema di chi lo usa (Windows, macOS, Linux).
"""

import argparse
import json
import sys
import tomllib
import zipfile
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADICE))

from cersim import __version__
from cersim.mcp.strumenti import crea_strumenti

FILE_FISSI = {
    "server.py": RADICE / "estensione" / "server.py",
    "icona.png": RADICE / "estensione" / "icona.png",
    "LICENSE": RADICE / "LICENSE",
    "LICENZA.md": RADICE / "LICENZA.md",
    "static/Geist-Regular.ttf": RADICE / "static" / "Geist-Regular.ttf",
    "static/Geist-SemiBold.ttf": RADICE / "static" / "Geist-SemiBold.ttf",
    "static/Geist-OFL.txt": RADICE / "static" / "Geist-OFL.txt",
}
ESTENSIONI_MOTORE = {".py", ".yaml", ".json", ".html"}

DESCRIZIONE_LUNGA = """Il simulatore di comunità energetiche rinnovabili (CER) e gruppi di autoconsumatori di \
cer.raccasamuele.it, con lo stesso motore del sito, dentro Claude.

Si chiede a parole: «simula un gruppo di autoconsumatori a Torino con 12 famiglie e il tetto del condominio», \
«controlla il lavoro salvato in questa cartella», «quanti kWp ci stanno su 120 m² di tetto?». Claude crea il \
progetto, scarica la produzione da PVGIS, calcola energia condivisa, contributi GSE, beneficio netto e requisiti, e \
mostra i risultati in una scheda con i grafici. Il report PDF o Excel si salva sul computer.

Tutto il calcolo resta sul computer: nomi, indirizzi e codici POD non vengono mandati a Claude. Stima del modello, \
non un preventivo né una consulenza legale o fiscale."""


def manifest() -> dict:
    strumenti = crea_strumenti()
    return {
        "manifest_version": "0.4",
        "name": "cer",
        "display_name": "Simulatore CER",
        "version": __version__,
        "description": "Comunità energetiche rinnovabili e gruppi di autoconsumatori: energia condivisa, contributi "
                       "GSE, beneficio netto e requisiti, con lo stesso motore di cer.raccasamuele.it.",
        "long_description": DESCRIZIONE_LUNGA,
        "author": {"name": "Samuele Racca", "url": "https://raccasamuele.it"},
        "homepage": "https://cer.raccasamuele.it",
        "documentation": "https://cer.raccasamuele.it",
        "icon": "icona.png",
        "server": {
            "type": "uv",
            "entry_point": "server.py",
            "mcp_config": {"command": "uv", "args": ["run", "--directory", "${__dirname}", "server.py"]},
        },
        "tools": [{"name": t.name, "description": t.title + ". " + t.description.split(". ")[0].rstrip(".") + "."}
                  for t in strumenti],
        "tools_generated": False,
        "keywords": ["comunità energetica", "CER", "autoconsumo", "fotovoltaico", "GSE", "PVGIS", "energia"],
        "license": "MIT",
        "compatibility": {"platforms": ["win32", "darwin", "linux"], "runtimes": {"python": ">=3.11"}},
    }


def pyproject() -> str:
    """Solo le dipendenze del motore: Claude Desktop le installa con uv. Il progetto non si installa (package = false)."""
    dati = tomllib.loads((RADICE / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dipendenze = "\n".join(f'    "{d}",' for d in dati["dependencies"])
    return (f'[project]\nname = "cer-mcpb"\nversion = "{__version__}"\n'
            f'description = "Estensione di Claude Desktop del simulatore CER"\n'
            f'requires-python = "{dati["requires-python"]}"\ndependencies = [\n{dipendenze}\n]\n\n'
            '[tool.uv]\npackage = false\n')


def file_del_motore() -> dict[str, Path]:
    motore = RADICE / "cersim"
    return {f"cersim/{p.relative_to(motore).as_posix()}": p for p in sorted(motore.rglob("*"))
            if p.is_file() and p.suffix in ESTENSIONI_MOTORE and "__pycache__" not in p.parts}


def crea(uscita: Path) -> Path:
    m = manifest()
    uscita.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(uscita, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(m, ensure_ascii=False, indent=2) + "\n")
        z.writestr("pyproject.toml", pyproject())
        for nome, sorgente in {**FILE_FISSI, **file_del_motore()}.items():
            z.write(sorgente, nome)
    return uscita


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crea l'estensione cer.mcpb per Claude Desktop.")
    parser.add_argument("--uscita", type=Path, default=RADICE / "dist" / f"cer-{__version__}.mcpb")
    a = parser.parse_args(argv)
    file = crea(a.uscita)
    print(f"{file} ({file.stat().st_size // 1024} kB)")


if __name__ == "__main__":
    main()
