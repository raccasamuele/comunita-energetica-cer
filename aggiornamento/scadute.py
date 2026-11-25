"""Voci dell'inventario da controllare (scadono, ultimo_controllo + frequenza_mesi, prima della
routine successiva, cioè entro frequenza_routine_mesi da oggi) e pacchetti di dati con la scadenza entro i prossimi mesi.

python aggiornamento/scadute.py [--tutte] [--oggi AAAA-MM-GG]
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parent.parent
PACCHETTI = (
    "cersim/data/parametri_normativi.yaml",
    "cersim/data/assunzioni_economiche.yaml",
    "cersim/data/classificazione_soggetti.yaml",
)
PREAVVISO_MESI = 4  # una routine ogni tre mesi, più un mese di margine


def mesi_dopo(d: date, mesi: int) -> date:
    m = d.month - 1 + mesi
    anno, mese = d.year + m // 12, m % 12 + 1
    giorni = [31, 29 if anno % 4 == 0 and (anno % 100 or anno % 400 == 0) else 28,
              31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mese - 1]
    return date(anno, mese, min(d.day, giorni))


def scadenza_voce(voce: dict) -> date:
    return mesi_dopo(date.fromisoformat(voce["ultimo_controllo"]), voce["frequenza_mesi"])


def da_controllare(voce: dict, oggi: date, mesi_routine: int) -> bool:
    return scadenza_voce(voce) < mesi_dopo(oggi, mesi_routine)


def scadenze_pacchetti(oggi: date) -> list[dict]:
    righe = []
    for nome in PACCHETTI:
        dati = yaml.safe_load((RADICE / nome).read_text(encoding="utf-8"))
        scad = dati["scadenza"]
        righe.append({"file": nome, "scadenza": scad.isoformat(),
                      "vicina": scad <= mesi_dopo(oggi, PREAVVISO_MESI)})
    return righe


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tutte", action="store_true")
    p.add_argument("--oggi", type=date.fromisoformat, default=date.today())
    a = p.parse_args()
    inv = json.loads((RADICE / "aggiornamento/fonti.json").read_text(encoding="utf-8"))
    voci = [{"id": v["id"], "ultimo_controllo": v["ultimo_controllo"],
             "scade": scadenza_voce(v).isoformat(), "automatico": v["automatico"],
             "da_controllare": da_controllare(v, a.oggi, inv["frequenza_routine_mesi"])}
            for v in inv["fonti"]]
    pacchetti = scadenze_pacchetti(a.oggi)
    print(json.dumps({
        "progetto": inv["progetto"], "oggi": a.oggi.isoformat(),
        "prossimo_controllo": mesi_dopo(a.oggi, inv["frequenza_routine_mesi"]).isoformat(),
        "voci": [v for v in voci if a.tutte or v["da_controllare"]],
        "pacchetti": [r for r in pacchetti if a.tutte or r["vicina"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
