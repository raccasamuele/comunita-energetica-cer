"""Scenario preliminare completo per un condominio a Torino: energia, euro, chi riceve cosa.

    python esempi/condominio_torino.py                         # prezzo costante (qualità C)
    python esempi/condominio_torino.py --prezzi prezzi.csv --anno-prezzi 2024
                                                               # prezzi orari tuoi (formato in cersim/prices.py)

Il file dei prezzi NON è incluso: le condizioni del GME ne consentono solo l'uso
personale. Con un file reale si aggiunge lo scenario "prezzi recenti"
(prezzi di quell'anno con il meteo 2023).
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cersim.economics import ESCLUSIONI, ParametriEconomici  # noqa: E402
from cersim.eligibility import check  # noqa: E402
from cersim.model import Configuration, ConnectionPoint, Fasce, Member, Plant  # noqa: E402
from cersim.prices import prezzi_da_csv  # noqa: E402
from cersim.pv import ANNI_METEO  # noqa: E402
from cersim.scenari import Scenario, bande, esegui_scenari, qualita_complessiva, scenari_standard, sensibilita  # noqa: E402
from cersim.simulate import pv_profiles_for  # noqa: E402
from cersim.sizing import dimensiona  # noqa: E402

argomenti = argparse.ArgumentParser()
argomenti.add_argument("--prezzi", help="CSV di prezzi orari (uso personale)")
argomenti.add_argument("--anno-prezzi", type=int, help="anno del file dei prezzi")
argomenti.add_argument("--quota-membri", type=float, default=0.5, help="scenario di riparto: quota del netto ai membri")
args = argomenti.parse_args()

famiglie = [Member(id=f"fam{i:02d}", nome=f"Famiglia {i}", tipo_soggetto="persona_fisica") for i in range(1, 13)]
membri = famiglie + [
    Member(id="negozio", nome="Panetteria", tipo_soggetto="pmi"),
    Member(id="condominio", nome="Condominio Via Esempio 1", tipo_soggetto="condominio"),
]
consumi = [1800, 2200, 2700, 2700, 3100, 3500, 2400, 1600, 2900, 3300, 2000, 2600]
punti = [
    ConnectionPoint(id=f"pod_{m.id}", titolare=m.id, tipologia_profilo="domestico", kwh_annui=kwh,
                    fasce=Fasce(f1=round(kwh * 0.33), f23=round(kwh * 0.67)), edificio_id="via_esempio_1")
    for m, kwh in zip(famiglie, consumi)
] + [
    ConnectionPoint(id="pod_negozio", titolare="negozio", tipologia_profilo="ufficio_commerciale", kwh_annui=14000,
                    fasce=Fasce(f1=8400, f23=5600), edificio_id="via_esempio_1"),
    ConnectionPoint(id="pod_condominio", titolare="condominio", tipologia_profilo="pa_municipio", kwh_annui=4500,
                    fasce=Fasce(f1=2000, f23=2500), edificio_id="via_esempio_1"),
]
impianti = [
    Plant(id="fv_tetto", nome="FV tetto", connection_point="pod_condominio", potenza_moduli_kwp=20,
          potenza_inverter_kw=18, potenza_moduli_max_kwp=35, tilt=25, azimut=10, investitore="condominio",
          data_entrata_esercizio=date(2027, 4, 1)),
]
config = Configuration(
    nome="Condominio Via Esempio 1", tipo="gruppo", lat=45.0703, lon=7.6869, regione="Piemonte",
    members=membri, connection_points=punti, plants=impianti, edificio_id_gruppo="via_esempio_1",
    data_costituzione=date(2027, 1, 15),
)
params = ParametriEconomici(quota_membri=args.quota_membri)

report = check(config)
pv = {anno: pv_profiles_for(config, anno) for anno in ANNI_METEO}
prezzi, recenti = {}, ()
if args.prezzi:
    prezzi[args.anno_prezzi] = prezzi_da_csv(args.prezzi, "NORD", args.anno_prezzi)
    recenti = (args.anno_prezzi,) if args.anno_prezzi not in ANNI_METEO else ()
scenari = scenari_standard(anni_prezzi_recenti=recenti)
esiti = esegui_scenari(config, report, params, pv, prezzi, scenari)
qualita = qualita_complessiva(config, pv, esiti)


def euro(x):
    return f"{x:>10,.0f} €".replace(",", ".")


print("=" * 78)
print("SCENARIO PRELIMINARE — non è uno studio di fattibilità")
print(f"{config.nome} · gruppo di autoconsumatori · 20 kWp · qualità dati: {qualita}")
print("=" * 78)
print(f"Requisiti: {report.stato_configurazione.value}" + ("  (contributi condizionali)" if report.condizionale else ""))

print(f"\nBanda degli scenari ({len(esiti)} scenari: meteo 2021–2023 × livello prezzi basso/base/alto"
      + (f" + prezzi {recenti[0]}" if recenti else "") + ")")
print(f"{'':32}{'minimo':>12}{'mediana':>12}{'massimo':>12}")
for nome, b in bande(esiti).items():
    print(f"{nome:32}{b.minimo:>12,.0f}{b.mediana:>12,.0f}{b.massimo:>12,.0f}".replace(",", "."))

base = next(e for e in esiti if e.scenario == Scenario(2023, 2023, "base"))
k = base.kpi
print(f"\nScenario base (meteo 2023, prezzo medio 110 €/MWh, riparto {params.quota_membri:.0%} ai membri):")
print(f"  VAN investitore (condominio) {euro(k.van_investitore)}   VAN consolidato {euro(k.van_consolidato)}")
tir = f"{k.tir_investitore:.1%}" if k.tir_investitore is not None else "non definito"
print(f"  TIR investitore {tir}   payback {k.payback_investitore} anni (attualizzato {k.payback_attualizzato_investitore})")

print(f"\nChi riceve cosa nel {base.ledger.anno_inizio + 1} (primo anno intero):")
for voce, importo in sorted(k.contributi_primo_anno_intero.items(), key=lambda v: -v[1]):
    print(f"  {voce:38}{euro(importo)}")
famiglie_euro = [k.euro_anno_per_membro[m.id] for m in famiglie]
print(f"  → ogni famiglia riceve tra {min(famiglie_euro):.0f} e {max(famiglie_euro):.0f} €/anno dal riparto")

print("\nSensibilità del VAN consolidato (scenario base):")
for v in sensibilita(config, report, params, pv, prezzi, base.scenario):
    print(f"  {v.parametro:34} {v.variazione:>18}  {euro(v.van_consolidato_basso)} … {euro(v.van_consolidato_alto)}")

print("\nDimensionamento dell'impianto sul tetto (scenari base dei 3 anni meteo):")
dim = dimensiona(config, "fv_tetto", params, pv, prezzi, [Scenario(a, a, "base") for a in ANNI_METEO], n_punti=6)
print(f"{'kWp':>8}{'VAN consolidato':>18}{'VAN investitore':>18}{'% condivisa':>13}")
for p in dim.curva:
    nota = "  (investitore in perdita)" if p.investitore_in_perdita else ""
    print(f"{p.potenza_moduli_kwp:>8.1f}{euro(p.van_consolidato_mediano):>18}{euro(p.van_investitore_mediano):>18}"
          f"{p.quota_condivisa_su_immessa:>13.0%}{nota}")
print(f"  {dim.dicitura}")

avvisi = sorted({a for e in esiti for a in e.ledger.avvisi} | set(base.energia.manifest["avvisi"]))
print("\nAvvisi:")
for a in avvisi + base.ledger.contributi_esclusi:
    print(f"  - {a}")
print("  - Valori pre-imposte. Esclusi: " + ", ".join(ESCLUSIONI))
