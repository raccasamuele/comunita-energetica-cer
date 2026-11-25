"""Caso studio di Torino: lo stesso condominio come gruppo di autoconsumatori e come comunità energetica.

    python esempi/caso_studio_torino.py      # scarica i dati PVGIS (serve la rete la prima volta)

Sono i dati dell'esempio dell'app (12 famiglie, una panetteria, le parti comuni, 20 kWp sul tetto), simulati
due volte cambiando solo il tipo di configurazione. Stampa una tabella in Markdown: è quella di
docs/caso_studio_torino.md.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cersim.analisi import analizza  # noqa: E402
from cersim.economics import ParametriEconomici  # noqa: E402
from cersim.normativa import assunzioni_economiche  # noqa: E402
from cersim.report import euro, kwh  # noqa: E402
from cersim.ui_model import (  # noqa: E402
    COLONNE_IMPIANTI,
    COLONNE_PUNTI,
    Generale,
    configurazione_da_tabelle,
    famiglie_tipo,
    tipizza_impianti,
    tipizza_punti,
)

CONSUMI = [1800, 2200, 2700, 2700, 3100, 3500, 2400, 1600, 2900, 3300, 2000, 2600]
AREA = "AC-ESEMPIO"  # codice fittizio: in una CER vera si legge sulla mappa delle cabine primarie del GSE


def tabelle(tipo: str):
    punti = famiglie_tipo(12)
    punti["kWh annui"] = CONSUMI
    punti["F1 kWh"] = [round(c * 0.33) for c in CONSUMI]
    punti["F23 kWh"] = [c - round(c * 0.33) for c in CONSUMI]
    altri = pd.DataFrame([
        {"Punto": "Panetteria", "Membro": "Panetteria", "Tipo soggetto": "PMI", "Tipologia consumo": "Ufficio / negozio",
         "kWh annui": 14000, "F1 kWh": 8400, "F23 kWh": 5600, "Tensione": "BT"},
        {"Punto": "Parti comuni", "Membro": "Condominio", "Tipo soggetto": "Condominio",
         "Tipologia consumo": "Municipio / uffici pubblici", "kWh annui": 4500, "F1 kWh": 2000, "F23 kWh": 2500,
         "Tensione": "BT"},
    ], columns=COLONNE_PUNTI)
    punti = pd.concat([punti, altri], ignore_index=True)
    if tipo == "CER":
        punti["Area convenzionale GSE"] = AREA
    impianti = pd.DataFrame([{
        "Impianto": "FV tetto", "Punto": "Parti comuni", "kWp moduli": 20.0, "kW inverter": 18.0,
        "kWp max installabili": 35.0, "Inclinazione °": 25.0, "Orientamento °": 10.0,
        "Entrata in esercizio": date(2027, 4, 1), "Investitore": "Condominio",
    }], columns=COLONNE_IMPIANTI)
    generale = Generale(nome="Condominio Via Esempio 1, Torino", tipo=tipo, lat=45.0703, lon=7.6869,
                        regione="Piemonte", indirizzo="Piazza Castello, Torino", data_costituzione=date(2027, 1, 15))
    return generale, tipizza_punti(punti), tipizza_impianti(impianti)


def intervallo(banda, formato) -> str:
    return f"{formato(banda.minimo)} – {formato(banda.massimo)}"


def main():
    params = ParametriEconomici(quota_membri=0.5)
    ipotesi = assunzioni_economiche().configurazione
    risultati = {}
    for tipo in ("gruppo", "CER"):
        esito = configurazione_da_tabelle(*tabelle(tipo))
        if esito.config is None:
            raise SystemExit("; ".join(esito.errori))
        risultati[tipo] = analizza(esito.config, params)

    righe = [
        ("Qualità dei dati", lambda a, t: a.qualita),
        ("Energia condivisa all'anno", lambda a, t: intervallo(a.bande["energia_condivisa_kwh"], kwh)),
        ("Tariffa premio all'anno", lambda a, t: intervallo(a.bande["tip_eur_anno"], euro)),
        ("Valorizzazione ARERA all'anno", lambda a, t: intervallo(a.bande["cacv_eur_anno"], euro)),
        ("Costituzione (una tantum)", lambda a, t: euro(ipotesi.costituzione_eur[t])),
        ("Gestione all'anno", lambda a, t: euro(ipotesi.gestione_eur_anno[t])),
        ("Beneficio netto della configurazione, 25 anni", lambda a, t: intervallo(a.bande["van_consolidato"], euro)),
        ("Beneficio netto del condominio, che paga", lambda a, t: intervallo(a.bande["van_investitore"], euro)),
        ("Rientro del condominio, scenario base",
         lambda a, t: f"{a.base.kpi.payback_investitore} anni" if a.base.kpi.payback_investitore else "oltre 25 anni"),
        ("In più rispetto al solo fotovoltaico", lambda a, t: intervallo(a.bande["valore_configurazione"], euro)),
    ]
    print("| | Gruppo di autoconsumatori | Comunità energetica |")
    print("|---|---|---|")
    for voce, valore in righe:
        print(f"| {voce} | {valore(risultati['gruppo'], 'gruppo')} | {valore(risultati['CER'], 'CER')} |")
    print()
    for tipo, a in risultati.items():
        print(f"{tipo}: prezzi {'; '.join(sorted({e.fonte_prezzi for e in a.esiti}))}; "
              f"requisiti condizionali: {a.report.condizionale}")


if __name__ == "__main__":
    main()
