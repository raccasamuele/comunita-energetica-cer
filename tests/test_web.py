"""Ingresso del motore per l'interfaccia web (cersim/web.py): due tempi, nessuna rete, risultati in JSON."""

import base64
import json
from datetime import date
from functools import partial
from pathlib import Path

import pandas as pd
import pytest

from cersim import proposta, web
from cersim.pv import synthetic_profile
from cersim.ui_model import (Generale, configurazione_da_tabelle, esporta_json, famiglie_tipo, impianti_vuoti,
                             importa_json)
from cersim.web import (CONTRATTO, analizza_web, chiama, chiave_pvgis, costanti, famiglie, fetch_da_serie,
                        leggi_consumi, leggi_schede, progetto_da_tabelle, richieste_pvgis, tabelle_da_progetto,
                        scheda_per_il_sito)


def progetto(quota=0.5) -> str:
    generale = Generale("Prova", "gruppo", 45.07, 7.69, "Piemonte", data_costituzione=date(2027, 1, 1))
    impianti = impianti_vuoti()
    impianti.loc[0] = {"Impianto": "FV", "Punto": "Famiglia 1", "kWp moduli": 6.0, "kW inverter": 6.0,
                       "Inclinazione °": 25.0, "Orientamento °": 10.0, "Entrata in esercizio": date(2027, 4, 1),
                       "Investitore": "Famiglia 1"}
    esito = configurazione_da_tabelle(generale, famiglie_tipo(3, kwh=2700), impianti)
    assert esito.config is not None, esito.errori
    return esporta_json(esito.config, {} if quota is None else {"quota_membri": quota})


def risposta_pvgis(parametri: dict) -> dict:
    """Una risposta di PVGIS seriescalc (ore UTC, W per 1 kWp), costruita dal profilo semplificato."""
    p = synthetic_profile(parametri["lat"], parametri["lon"], parametri["angle"], parametri["aspect"],
                          parametri["loss"], parametri["startyear"])
    ore = p.kw_per_kwp.index.tz_convert("UTC")
    return {"outputs": {"hourly": [{"time": f"{t:%Y%m%d:%H}10", "P": round(v * 1000, 2)}
                                   for t, v in zip(ore, p.kw_per_kwp.to_numpy())]}}


def test_richieste_una_per_orientamento_e_anno_meteo():
    richieste = richieste_pvgis(progetto())
    assert [r["parametri"]["startyear"] for r in richieste] == [2021, 2022, 2023]
    r = richieste[-1]
    assert r["chiave"] == "pvgis_45.07_7.69_t25_a10_l14_2023" == chiave_pvgis(r["parametri"])
    assert r["parametri"]["outputformat"] == "json" and r["parametri"]["peakpower"] == 1
    assert json.loads(json.dumps(richieste)) == richieste  # passa per postMessage


def test_analisi_con_le_serie_scaricate():
    serie = {r["chiave"]: risposta_pvgis(r["parametri"]) for r in richieste_pvgis(progetto())}
    risultato = analizza_web(progetto(), serie, n_anni=3)
    assert risultato["contratto"] == CONTRATTO and risultato["ok"] and risultato["fonti_pv"] == ["PVGIS"]
    assert risultato["qualita"] == "C"  # famiglie tipo e prezzo costante
    banda = risultato["bande"]["energia_condivisa_kwh"]
    assert 0 < banda["minimo"] <= banda["mediana"] <= banda["massimo"]
    assert set(risultato["base"]) >= {"van_investitore", "van_consolidato", "contributi_primo_anno_intero"}
    json.dumps(risultato)


def test_serie_mancanti_o_illeggibili_danno_il_profilo_semplificato():
    risultato = analizza_web(progetto(), {}, n_anni=2)
    assert risultato["ok"] and risultato["fonti_pv"] == ["sintetico"] and risultato["qualita"] == "C"
    chiave = richieste_pvgis(progetto())[0]["chiave"]
    profilo = fetch_da_serie({chiave: {"outputs": {"hourly": "rotto"}}})(45.07, 7.69, 25.0, 10.0, 14.0, 2021)
    assert profilo.fonte == "sintetico"


def test_la_cache_di_cersim_vale_come_serie():
    parametri = richieste_pvgis(progetto())[0]["parametri"]
    pvgis = risposta_pvgis(parametri)["outputs"]["hourly"]
    cache = {"time": [h["time"] for h in pvgis], "P": [h["P"] for h in pvgis]}
    profilo = fetch_da_serie({chiave_pvgis(parametri): cache})(45.07, 7.69, 25.0, 10.0, 14.0, 2021)
    assert profilo.fonte == "PVGIS" and isinstance(profilo.kw_per_kwp, pd.Series)


@pytest.mark.parametrize("contenuto, messaggio", [
    ("non json", "JSON valido"),
    (json.dumps({"schema": 99}), "non è un salvataggio"),
    (progetto(quota=None), "quanta parte dei contributi"),
])
def test_errori_come_testo(contenuto, messaggio):
    risultato = analizza_web(contenuto, {})
    assert risultato["ok"] is False and messaggio in risultato["errore"]


# --- passi 1 e 2: tabelle della bozza ↔ salvataggio -----------------------------------------------
RADICE = Path(__file__).resolve().parents[1]
TORINO = (RADICE / "web" / "public" / "esempi" / "torino.json").read_text(encoding="utf-8")
LUOGO = {"nome": "Prova", "tipo": "gruppo", "indirizzo": "Via Roma 1, Torino", "lat": 45.07, "lon": 7.69,
         "regione": "Piemonte", "data_costituzione": "2027-01-15"}


def bozza(**cambi) -> dict:
    return {"generale": dict(LUOGO), "punti": famiglie(2), "impianti": [], "curve": {}, "parametri": {}, **cambi}


def file_(percorso: Path) -> dict:
    return {"nome": percorso.name, "base64": base64.b64encode(percorso.read_bytes()).decode()}


def test_costanti_dal_motore():
    c = costanti()
    assert c["regioni"][0] == "Piemonte" and len(c["regioni"]) == 20
    assert "Persona fisica" in c["tipi_soggetto"] and "Famiglia" in c["tipologie"] and c["tensioni"] == ["BT", "MT"]
    assert c["kwh_famiglia_tipo"] == 2700 and c["contratto"] == CONTRATTO


def test_famiglie_tipo_come_righe():
    righe = famiglie(2, inizio=5)
    assert [r["punto"] for r in righe] == ["Famiglia 5", "Famiglia 6"]
    assert righe[0] == {"punto": "Famiglia 5", "membro": "Famiglia 5", "tipo_soggetto": "Persona fisica",
                        "tipologia": "Famiglia", "kwh_annui": None, "f1_kwh": None, "f23_kwh": None, "area": None,
                        "tensione": "BT"}
    with pytest.raises(ValueError, match="da 1 a 100"):
        famiglie(0)


def test_progetto_senza_impianti_con_riepilogo():
    esito = progetto_da_tabelle(bozza(parametri={"quota_membri": 0.5, "estraneo": 1}))
    assert esito["ok"] and esito["errori"] == [] and esito["errori_luogo"] == []
    config, parametri = importa_json(esito["progetto"])
    assert config.tipo.value == "gruppo" and config.data_costituzione == date(2027, 1, 15) and not config.plants
    assert parametri == {"quota_membri": 0.5}
    assert esito["riepilogo"] == {"membri": 2, "contatori": 2, "kwh_annui": 5400, "famiglie_tipo": 2,
                                  "qualita_consumi": {"A": 0, "B": 0, "C": 2}}


@pytest.mark.parametrize("cambi, messaggio", [
    ({"lat": 52.5}, "latitudine"),
    ({"lon": None}, "longitudine"),
    ({"regione": "Baviera"}, "regione"),
    ({"tipo": "condominio"}, "che cosa vuoi simulare"),
    ({"data_costituzione": "15/01/2027"}, "data di costituzione"),
])
def test_errori_del_luogo(cambi, messaggio):
    esito = progetto_da_tabelle(bozza(generale={**LUOGO, **cambi}))
    assert not esito["ok"] and messaggio in " ".join(esito["errori_luogo"]).lower()


def test_errori_della_tabella_dei_contatori():
    righe = famiglie(2)
    righe[1]["tipo_soggetto"] = None
    righe.append({"punto": "Bar", "membro": "Bar", "tipo_soggetto": "PMI", "tipologia": "Ufficio / negozio",
                  "f1_kwh": 100.0})
    esito = progetto_da_tabelle(bozza(punti=righe))
    assert not esito["ok"] and esito["errori_luogo"] == []
    assert any("tipo di soggetto" in e for e in esito["errori"]) and any("F1 sia F23" in e for e in esito["errori"])
    assert "Aggiungi almeno un punto" in progetto_da_tabelle(bozza(punti=[]))["errori"][0]


def test_salvataggio_ricaricato_e_riesportato_uguale():
    caricato = tabelle_da_progetto(TORINO)
    assert caricato["ok"]
    tabelle = json.loads(json.dumps(caricato["tabelle"]))  # passa per postMessage e per la bozza nel browser
    assert tabelle["generale"]["tipo"] == "CER" and len(tabelle["punti"]) == 14
    assert tabelle["impianti"][0]["Entrata in esercizio"] == "2027-04-01"
    esito = progetto_da_tabelle(tabelle)
    assert esito["ok"], esito["errori"]
    assert json.loads(esito["progetto"]) == json.loads(TORINO)


def test_file_che_non_e_un_salvataggio():
    assert "JSON valido" in tabelle_da_progetto("non json")["errore"]
    assert tabelle_da_progetto(json.dumps({"schema": 99}))["ok"] is False


def test_consumi_dal_simulatore_della_casa():
    letta = leggi_consumi([file_(RADICE / "esempi" / "curva_consumi_esempio.json")])
    assert letta["ok"] and letta["calcolata"] and "calcolati" in letta["descrizione"]
    tabelle = bozza(curve={"Famiglia 1": letta})
    esito = progetto_da_tabelle(json.loads(json.dumps(tabelle)))
    assert esito["ok"] and esito["riepilogo"]["qualita_consumi"] == {"A": 0, "B": 1, "C": 1}
    config, _ = importa_json(esito["progetto"])
    assert config.connection_points[0].curva_misurata.kwh_annui == letta["curva"]["kwh_annui"]
    ricaricato = tabelle_da_progetto(esito["progetto"])["tabelle"]
    assert list(ricaricato["curve"]) == ["Famiglia_1"] and ricaricato["curve"]["Famiglia_1"]["calcolata"]


def test_consumi_dal_distributore_e_file_sbagliati():
    letta = leggi_consumi([file_(RADICE / "esempi" / "letture_esempio_sintetico.csv")])
    assert letta["ok"] and not letta["calcolata"] and letta["curva"]["natura"] == "misurata"
    insieme = [file_(RADICE / "esempi" / "curva_consumi_esempio.json"),
               file_(RADICE / "esempi" / "letture_esempio_sintetico.csv")]
    assert "da solo" in leggi_consumi(insieme)["errore"]
    assert leggi_consumi([{"nome": "a.csv", "base64": "non base64!"}])["errore"] == "File non leggibili"
    assert leggi_consumi([])["ok"] is False


def test_chiama_solo_le_funzioni_ammesse():
    assert json.loads(chiama("regione", json.dumps({"nome": "Sicily"}))) == {"regione": "Sicilia"}
    assert json.loads(chiama("regione", json.dumps({"nome": "Baviera"}))) == {"regione": None}
    with pytest.raises(ValueError, match="sconosciuta"):
        chiama("analizza", "{}")


# --- la scheda dei consumi delle famiglie -----------------------------------------------------------
def scheda_dal_sito(membro="Rossi, interno 3", contatori=None, per="Prova") -> dict:
    """Una scheda come la scrive la pagina del link nel sito (web/src/scheda/scheda.ts)."""
    return {"formato": "cersim-scheda-consumi", "versione": 1, "configurazione": per, "compilata_il": "2026-10-29",
            "membro": membro, "tipo_soggetto": "Persona fisica",
            "contatori": contatori or [{"nome": "Contatore", "tipologia": "Famiglia", "kwh_annui": 3100,
                                        "f1_kwh": 1000, "f23_kwh": 2100, "tensione": "BT", "curva": None}]}


def file_json(nome: str, dati) -> dict:
    testo = dati if isinstance(dati, str) else json.dumps(dati)
    return {"nome": nome, "base64": base64.b64encode(testo.encode()).decode()}


def test_i_testi_della_scheda_nel_sito_sono_quelli_del_motore():
    nel_sito = json.loads((RADICE / "web" / "src" / "scheda" / "testi.json").read_text(encoding="utf-8"))
    assert nel_sito == json.loads(json.dumps(scheda_per_il_sito())), "rigenera con: python -m cersim.web"


def test_schede_ricevute_aggiunte_e_aggiornate():
    tabelle = bozza()
    letto = leggi_schede([file_json("rossi.json", scheda_dal_sito()), file_json("altro.json", "non json"),
                          file_json("bianchi.json", scheda_dal_sito("Bianchi", per="Un'altra"))], tabelle)
    assert letto["lette"] == 2
    assert [r["punto"] for r in letto["punti"]] == ["Famiglia 1", "Famiglia 2", "Rossi, interno 3", "Bianchi"]
    assert letto["punti"][2]["kwh_annui"] == 3100 and letto["punti"][2]["f23_kwh"] == 2100
    assert letto["messaggi"][0].startswith("Contatori aggiunti: 2")
    assert any("altro.json" in m for m in letto["messaggi"])
    assert any("era per 'Un'altra'" in m for m in letto["messaggi"])
    # la stessa famiglia rimanda la scheda: aggiorna la sua riga, con la curva misurata allegata
    curva = leggi_consumi([file_(RADICE / "esempi" / "letture_esempio_sintetico.csv")])["curva"]
    rimandata = scheda_dal_sito(contatori=[{"nome": "Contatore", "tipologia": "Famiglia", "kwh_annui": 2900,
                                            "f1_kwh": None, "f23_kwh": None, "tensione": "BT", "curva": curva}])
    secondo = leggi_schede([file_json("rossi.json", rimandata)], {**tabelle, "punti": letto["punti"]})
    assert len(secondo["punti"]) == 4 and secondo["punti"][2]["kwh_annui"] == 2900
    assert list(secondo["curve"]) == ["Rossi, interno 3"] and not secondo["curve"]["Rossi, interno 3"]["calcolata"]
    assert progetto_da_tabelle({**tabelle, "punti": secondo["punti"], "curve": secondo["curve"]})["ok"]


def test_scheda_con_fasce_incoerenti_rifiutata():
    sbagliata = scheda_dal_sito(contatori=[{"nome": "Contatore", "tipologia": "Famiglia", "kwh_annui": 3000,
                                            "f1_kwh": 100, "f23_kwh": 200, "tensione": "BT", "curva": None}])
    letto = leggi_schede([file_json("s.json", sbagliata)], bozza())
    assert letto["lette"] == 0 and "molto diverso" in letto["messaggi"][0]


# --- passo 3: tetto, proposta delle tre taglie, impianti --------------------------------------------
ANGOLI = [[7.68982, 45.06988], [7.69018, 45.06988], [7.69018, 45.07012], [7.68982, 45.07012]]  # circa 28 × 27 m


def scelta(**cambi) -> dict:
    return {"kwp_max": 20.0, "inclinazione": 20, "azimut": 0, "azimut_2": None, "ombre_pct": 5, "punto": "Famiglia 1",
            "investitore": "Famiglia 1", "entrata": "2027-05-01", **cambi}


def test_costanti_e_entrata_del_passo_3():
    c = web.costanti_impianti()
    assert c["forme"] == ["piano", "a falde"] and c["m2_per_kwp"]["a falde"] == 5.5
    assert c["livelli_ombre"][0] == {"etichetta": "Nessuna ombra importante", "pct": 0.0}
    assert c["colonne"][0] == "Impianto" and c["termine_tip"] == "2027-12-31"
    assert web.entrata_prevista("2027-01-15") == {"entrata": "2027-05-01"}
    assert date.fromisoformat(web.entrata_prevista(None)["entrata"]).day == 1
    json.dumps(c)


def test_tetto_disegnato_con_e_senza_edifici_vicini():
    t = web.tetto(ANGOLI, "a falde", 4, 20)
    assert t["ok"] and 700 < t["area_terra_m2"] < 800 and t["superficie_utile_m2"] > 0
    assert t["ombre_pct"] is None and t["svg"] is None  # senza edifici: solo il disegno
    alto = {"type": "way", "tags": {"building": "yes", "building:levels": "12"},
            "geometry": [{"lat": 45.0698, "lon": 7.6899}, {"lat": 45.0698, "lon": 7.6902},
                         {"lat": 45.0696, "lon": 7.6902}, {"lat": 45.0696, "lon": 7.6899}, {"lat": 45.0698, "lon": 7.6899}]}
    con = web.tetto(ANGOLI, "a falde", 4, 20, edifici=[alto])
    assert con["ok"] and con["vicini"] == 1 and con["ombre_pct"] > 0 and con["svg"].startswith("<svg")
    assert not web.tetto(ANGOLI[:2], "a falde")["ok"]
    assert "non sembra un tetto" in web.tetto([[7.6, 45.0], [7.7, 45.0], [7.7, 45.1]], "piano")["errore"]
    assert web.tetto(ANGOLI, "a cupola")["errore"] == "Scegli il tipo di tetto"


def test_errori_degli_impianti_separati_da_quelli_dei_contatori():
    esito = progetto_da_tabelle(bozza(impianti=[{"Impianto": "FV", "Punto": "Famiglia 1", "kWp moduli": 6.0}]))
    assert not esito["ok"] and esito["errori"] == []
    assert esito["errori_impianti"] == ["Impianto 'FV': scegli chi paga l'impianto (investitore)"]


def test_proposta_in_due_tempi(monkeypatch):
    # meno taglie e anni per tenere il test rapido: la logica è quella di cersim.proposta
    monkeypatch.setattr(web, "proponi", partial(proposta.proponi, n_punti=3, n_anni=3))
    tabelle = bozza(parametri={"quota_membri": 0.5})
    richieste = web.richieste_proposta(tabelle, scelta())
    assert richieste["ok"] and [r["parametri"]["startyear"] for r in richieste["richieste"]] == [2021, 2022, 2023]
    serie = {r["chiave"]: risposta_pvgis(r["parametri"]) for r in richieste["richieste"]}
    p = json.loads(chiama("proposta", json.dumps({"tabelle": tabelle, "scelta": scelta(), "serie": serie})))
    assert p["ok"] and not p["quota_provvisoria"] and len(p["opzioni"]) >= 2
    assert "Consigliata" in {o["nome"] for o in p["opzioni"]} and len(p["curva"]) >= 3
    riga = p["opzioni"][0]["impianti"]
    assert len(riga) == 1 and riga[0]["Impianto"] == "FV tetto" and riga[0]["Entrata in esercizio"] == "2027-05-01"
    assert riga[0]["kWp moduli"] == p["opzioni"][0]["kwp"] and riga[0]["Ombre %"] == 5.0
    # la tabella che ne esce è un progetto valido
    assert progetto_da_tabelle({**tabelle, "impianti": riga})["ok"]


def test_proposta_con_dati_che_non_bastano():
    assert "contatore" in web.richieste_proposta(bozza(), scelta(punto=""))["errore"]
    assert "orientamento" in web.proposta(bozza(), scelta(azimut=270), {})["errore"]
    assert "passo 1" in web.proposta(bozza(generale={**LUOGO, "lat": None}), scelta(), {})["errore"]
    assert "1 kWp" in web.proposta(bozza(), scelta(kwp_max=0.5), {})["errore"]


# --- passi 4 e 5: economia, risultati completi, curva delle taglie e report -------------------------
def csv_prezzi(anno=2024, zona="NORD") -> str:
    ore = pd.date_range(f"{anno}-01-01", f"{anno + 1}-01-01", freq="h", tz="Europe/Rome", inclusive="left")
    valori = [80 + 40 * ((t.hour - 13) ** 2 / 169) for t in ore]  # più bassi nelle ore di sole
    return "inizio," + zona + "\n" + "\n".join(f"{t.isoformat()},{v:.2f}" for t, v in zip(ore, valori))


def test_costanti_economia_per_tipo():
    gruppo, cer = web.costanti_economia("gruppo"), web.costanti_economia("CER")
    assert gruppo["prezzi_medi"] == {"basso": 80.0, "base": 110.0, "alto": 140.0}
    assert cer["costituzione_eur"] > 0 and 0 < cer["tasso_sconto"] < 0.2
    assert web.costanti_economia("altro") == gruppo


def test_prezzi_orari_letti_e_riusati():
    letti = web.leggi_prezzi([file_json("prezzi_2024.csv", csv_prezzi())], "Piemonte")
    assert letti["ok"] and letti["errori"] == []
    s = letti["prezzi"]["2024"]
    assert s["zona"] == "NORD" and len(s["valori"]) == 8784 and 80 < s["media"] < 130
    assert web._prezzi(json.loads(json.dumps(letti["prezzi"])))[2024].media == pytest.approx(s["media"], abs=0.01)
    doppio = web.leggi_prezzi([file_json("a.csv", csv_prezzi()), file_json("b.csv", csv_prezzi())], "Piemonte")
    assert "c'è già un file per il 2024" in doppio["errori"][0]
    sbagliato = web.leggi_prezzi([file_json("x.csv", "data,prezzo\n2024-01-01,10")], "Piemonte")
    assert not sbagliato["ok"] and sbagliato["errori"][0].startswith("x.csv:")
    with pytest.raises(ValueError, match="incompleti"):
        web._prezzi({"2024": {**s, "valori": s["valori"][:100]}})


def test_risultati_completi_curva_e_report():
    serie = {r["chiave"]: risposta_pvgis(r["parametri"]) for r in richieste_pvgis(progetto())}
    prezzi = web.leggi_prezzi([file_json("p.csv", csv_prezzi())], "Piemonte")["prezzi"]
    r = json.loads(chiama("risultati", json.dumps({"progetto": progetto(), "serie": serie, "prezzi": prezzi, "n_anni": 3})))
    assert r["ok"] and r["contratto"] == CONTRATTO and r["economia_disabilitata"] is None
    assert any(g for _, g in r["frase"]) and r["qualita"]["lettera"] in "ABC"
    assert any("file utente p.csv" in f for f in r["fonti_prezzi"])
    assert r["cifre"][0]["unita"] == "kWh" and r["cifre"][0]["minimo"] <= r["cifre"][0]["valore"] <= r["cifre"][0]["massimo"]
    assert len(r["giorno_tipo"]["mesi"]) == 12 and r["giorno_tipo"]["mesi"][5]["colonne"][0] == "ora"
    assert len(r["mensile"]["righe"]) == 12 and r["cassa"]["colonne"][0] == "anno"
    assert r["requisiti"] and r["sensibilita"]["voci"] and r["per_membro"] and r["avvertenze"]
    assert r["confronto"]["righe"] and r["chi_riceve"]["righe"]
    d = web.dimensionamento(r["impianti"][0]["id"], n_punti=3)
    assert d["ok"] and len(d["curva"]) >= 2 and d["dicitura"]
    json.dumps(d)
    assert web.dimensionamento("sconosciuto")["errore"] == "Impianto sconosciuto"
    pdf, xlsx = web.report("pdf"), web.report("xlsx")
    assert base64.b64decode(pdf["base64"])[:4] == b"%PDF" and pdf["nome"] == "scenario_cer.pdf"
    assert base64.b64decode(xlsx["base64"])[:2] == b"PK"
    assert web.report("docx")["errore"] == "Formato sconosciuto"


def test_risultati_senza_riparto_o_senza_analisi():
    assert "passo 4" in web.risultati(progetto(quota=None), {})["errore"]
    web._ultima.clear()
    assert web.dimensionamento("fv")["errore"] == "Calcola prima lo scenario"
    assert web.report("pdf")["errore"] == "Calcola prima lo scenario"


def test_scheda_da_stampare_per_le_famiglie():
    link = "https://cer.raccasamuele.it/?modulo=famiglia&per=Via%20Roma%201"
    r = json.loads(chiama("scheda_pdf", json.dumps({"configurazione": " Via Roma 1 ", "link": link})))
    assert r["ok"] and r["nome"] == "scheda_consumi.pdf"
    pdf = base64.b64decode(r["base64"])
    assert pdf.startswith(b"%PDF") and link.encode() in pdf  # il link è cliccabile nel PDF
    senza = web.scheda_pdf(None, None)  # su carta soltanto, senza nome della configurazione
    assert senza["ok"] and base64.b64decode(senza["base64"]).startswith(b"%PDF")
