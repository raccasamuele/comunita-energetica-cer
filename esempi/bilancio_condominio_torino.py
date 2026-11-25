"""Bilancio energetico di un condominio a Torino (Tappa 1: solo energia, niente euro).

12 famiglie + 1 negozio + parti comuni, FV da 20 kWp sul tetto collegato al
POD condominiale, come gruppo di autoconsumatori. Usa PVGIS (rete) per i tre
anni meteo 2021–2023 e mostra la banda degli scenari.

    python esempi/bilancio_condominio_torino.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cersim.eligibility import check  # noqa: E402
from cersim.model import Configuration, ConnectionPoint, Fasce, Member, Plant  # noqa: E402
from cersim.pv import ANNI_METEO  # noqa: E402
from cersim.simulate import pv_profiles_for, simulate_project  # noqa: E402

famiglie = [Member(id=f"fam{i:02d}", nome=f"Famiglia {i}", tipo_soggetto="persona_fisica") for i in range(1, 13)]
membri = famiglie + [
    Member(id="negozio", nome="Panetteria", tipo_soggetto="pmi"),
    Member(id="condominio", nome="Condominio Via Esempio 1", tipo_soggetto="condominio"),
]
consumi_famiglie = [1800, 2200, 2700, 2700, 3100, 3500, 2400, 1600, 2900, 3300, 2000, 2600]
punti = [
    ConnectionPoint(id=f"pod_{m.id}", titolare=m.id, tipologia_profilo="domestico", kwh_annui=kwh,
                    fasce=Fasce(f1=round(kwh * 0.33), f23=round(kwh * 0.67)), edificio_id="via_esempio_1")
    for m, kwh in zip(famiglie, consumi_famiglie)
] + [
    ConnectionPoint(id="pod_negozio", titolare="negozio", tipologia_profilo="ufficio_commerciale", kwh_annui=14000,
                    edificio_id="via_esempio_1"),
    ConnectionPoint(id="pod_condominio", titolare="condominio", tipologia_profilo="pa_municipio", kwh_annui=4500,
                    edificio_id="via_esempio_1"),
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

report = check(config)
print(f"Configurazione: {report.stato_configurazione.value}  (condizionale: {report.condizionale})")
for voce in report.da_verificare:
    print(f"  da verificare: {voce}")

righe = []
for anno_meteo in ANNI_METEO:
    profili = pv_profiles_for(config, anno_meteo)
    risultato = simulate_project(config, report, profili, anno_meteo, n_years=2)
    totali = risultato.anni[1].totali()  # 2028, primo anno intero
    righe.append((anno_meteo, profili["fv_tetto"], totali, risultato.manifest))

print("\nPrimo anno intero (2028), un anno meteo per scenario:")
print(f"{'meteo':>6} {'fonte':>9} {'kWh/kWp':>8} {'produz.':>8} {'autocons.':>9} {'condivisa':>9} {'% cond/imm':>10} {'copertura':>9}")
for anno, prof, t, _ in righe:
    print(f"{anno:>6} {prof.fonte:>9} {prof.producibilita_kwh_kwp:>8.0f} {t['produzione_kwh']:>8.0f} "
          f"{t['autoconsumo_fisico_kwh']:>9.0f} {t['EACV_kwh']:>9.0f} {t['quota_condivisa_su_immessa']:>10.1%} "
          f"{t['copertura_consumi']:>9.1%}")

condivise = sorted(t["EACV_kwh"] for _, _, t, _ in righe)
print(f"\nBanda degli scenari, energia condivisa: {condivise[0]:.0f} – {condivise[1]:.0f} – {condivise[2]:.0f} kWh "
      "(minimo – mediana – massimo)")
manifest = righe[-1][3]
print(f"Qualità dati: {manifest['qualita_complessiva']}  |  controlli bilancio: {manifest['controlli_bilancio']}")
for avviso in manifest["avvisi"]:
    print(f"  avviso: {avviso}")
