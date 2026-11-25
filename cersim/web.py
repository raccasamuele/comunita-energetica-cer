"""Ingresso del motore per l'interfaccia web: cersim gira nel browser con Pyodide, dentro un Web Worker.

Nel browser Python non apre connessioni, e PVGIS non manda le intestazioni CORS: le serie le scarica il codice
JavaScript, tramite un intermediario. Per questo il calcolo ha due tempi, senza rete né disco:

1. `richieste_pvgis(progetto)`: quali serie PVGIS servono, con la chiave e i parametri di ciascuna;
2. `analizza_web(progetto, serie)`: l'analisi con le serie già scaricate. Una serie che manca vale come PVGIS
   che non risponde: produzione dal modello semplificato, qualità C.

`progetto` è il file di salvataggio del lavoro (`ui_model.esporta_json`), come testo o dizionario; le uscite sono
dizionari pronti per JSON. Il contratto dei messaggi è in docs/web_architettura.md.

I passi dell'interfaccia (luogo, contatori, consumi ora per ora) usano le stesse tabelle dell'app Streamlit
(`ui_model`): le funzioni in `FUNZIONI` le traducono nel salvataggio e ritorno, e il Worker le chiama per nome con
`chiama`.
"""

import base64
import binascii
import io
import json
import math
from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
from pydantic import ValidationError

from cersim import __version__
from cersim.analisi import (
    Analisi,
    analizza,
    anno_rappresentativo,
    cassa_cumulata,
    chi_riceve_cosa,
    fonti_prezzi,
    giorno_tipo,
    mensile,
    nomi_leggibili,
    scenari_dimensionamento,
)
from cersim.curva_calcolata import leggi_curva_calcolata
from cersim.profilo import FORMATO as FORMATO_PROFILO, applica_scenario, esporta_profilo, leggi_profilo, sintesi
from cersim.economics import ParametriEconomici
from cersim.geo import REGIONI, normalizza_regione, zona_mercato
from cersim.guida import (
    CODICE_POD,
    COSA_SERVE,
    ETICHETTE_SOGGETTO_ATTIVITA,
    FORMATO,
    KWH_FAMIGLIA_TIPO,
    MAX_CONTATORI,
    MAX_TESTO,
    MODULO,
    PORTALE_CONSUMI,
    PRIVACY_SCHEDA,
    PROFILI,
    SCARTO_FASCE,
    SOGGETTI_ATTIVITA,
    TIPOLOGIE_ATTIVITA,
    TIPOLOGIE_ENTE,
    VERSIONE,
    leggi_scheda,
    unisci_schede,
)
from cersim.loads import qualita_consumi
from cersim.misure import curva_da_file, descrivi
from cersim.model import (MAX_KWH_ANNUI, MAX_PUNTI, BatteriaCasa, Configuration, ConnectionPoint, CurvaMisurata,
                          ProfiloPunto, Ruolo, Tensione, Tipologia)
from cersim.normativa import assunzioni_economiche, pacchetto_normativo
from cersim.proposta import QUOTA_PROVVISORIA, SceltaTetto, entrata_predefinita, nome_impianto, proponi, tabella_impianto
from cersim.prices import PriceSeries, anno_dei_prezzi, prezzi_da_csv
from cersim.pv import ANNI_METEO, PVProfile, _nome_cache, _parametri, parse_pvgis_hourly, synthetic_profile
from cersim.report import (
    COLORI_GRAFICI,
    NOTA_INTERVALLI,
    QUALITA,
    STATO_ETICHETTA,
    avvertenze,
    cifre,
    confronto,
    dati_da_migliorare,
    frase_confronto,
    frase_precisione,
    frase_sintesi,
    report_excel,
    report_pdf,
    requisiti,
    scheda_famiglia_pdf,
)
from cersim.simulate import pv_profiles_for
from cersim.sizing import dimensiona
from cersim.tetto import (
    ATTRIBUZIONE,
    FORME,
    FOTO_AEREA_ATTRIBUZIONE,
    FOTO_AEREA_URL,
    INCLINAZIONE,
    LIVELLI_OMBRE,
    M2_PER_KWP,
    disegno_svg,
    tetto_disegnato,
)
from cersim.timebase import year_index
from cersim.ui_model import (
    COLONNE_IMPIANTI,
    COLONNE_PUNTI,
    INVESTITORE_ESTERNO,
    SOLA_IMMISSIONE,
    TIPI_SOGGETTO,
    TIPOLOGIE,
    Generale,
    configurazione_da_tabelle,
    esporta_json,
    famiglie_tipo,
    importa_json,
    ombre_da_perdite,
    tabelle_da_configurazione,
    tipizza_impianti,
    tipizza_punti,
)

CONTRATTO = 1  # versione del contratto dei messaggi tra interfaccia e motore
PARAMETRI = ("quota_membri", "costo_evitabile_eur_kwh", "tasso_sconto", "regime_vendita",
             "om_assicurazione_quota_anno", "gestione_eur_anno", "costituzione_eur")


def _progetto(progetto: str | dict) -> tuple[Configuration, dict]:
    testo = progetto if isinstance(progetto, str) else json.dumps(progetto)
    return importa_json(testo)


def chiave_pvgis(params: dict) -> str:
    """Chiave di una serie PVGIS: la stessa del nome del file di cache di `cersim.pv`, senza estensione."""
    return _nome_cache(params).removesuffix(".json")


def richieste_pvgis(progetto: str | dict) -> list[dict]:
    """Serie PVGIS che servono all'analisi: `{"chiave", "parametri"}`, una per luogo, orientamento, perdite e anno
    meteo. `parametri` è la query di `seriescalc` da inoltrare all'intermediario così com'è."""
    config, _ = _progetto(progetto)
    return _richieste(config)


def _richieste(config: Configuration) -> list[dict]:
    richieste: dict[str, dict] = {}

    def registra(lat, lon, tilt, azimut, perdite, anno):
        params = _parametri(lat, lon, tilt, azimut, perdite, anno)
        richieste.setdefault(chiave_pvgis(params), params)
        return synthetic_profile(lat, lon, tilt, azimut, perdite, anno)  # segnaposto, non usato

    for anno in ANNI_METEO:
        pv_profiles_for(config, anno, fetch=registra)
    return [{"chiave": k, "parametri": p} for k, p in richieste.items()]


def _orarie(dati: dict) -> tuple[list[str], list[float]]:
    """Ore e potenze da una risposta di PVGIS (`outputs.hourly`) o da un file della cache di `cersim.pv`."""
    if "outputs" in dati:
        orarie = dati["outputs"]["hourly"]
        return [h["time"] for h in orarie], [h["P"] for h in orarie]
    return dati["time"], dati["P"]


def fetch_da_serie(serie: dict[str, dict]) -> Callable[..., PVProfile]:
    """Adattatore per `analisi.analizza(fetch_pv=...)`: prende i profili dalle serie già scaricate invece che dalla
    rete. Una serie mancante o illeggibile dà il profilo semplificato (qualità C), come quando PVGIS non risponde."""

    def fetch(lat, lon, tilt, azimut, perdite_pct, year) -> PVProfile:
        dati = serie.get(chiave_pvgis(_parametri(lat, lon, tilt, azimut, perdite_pct, year)))
        if dati is not None:
            try:
                tempi, potenze = _orarie(dati)
                return PVProfile(kw_per_kwp=parse_pvgis_hourly(tempi, potenze, year), year=year, fonte="PVGIS",
                                 qualita="B", cache_hit=True)
            except (KeyError, TypeError, ValueError):
                pass
        return synthetic_profile(lat, lon, tilt, azimut, perdite_pct, year)

    return fetch


def _parametri_economici(parametri: dict) -> ParametriEconomici | None:
    if parametri.get("quota_membri") is None:
        return None
    return ParametriEconomici(**{k: parametri[k] for k in PARAMETRI if parametri.get(k) is not None})


def _numero(x) -> float | None:
    return round(float(x), 2) if x is not None and math.isfinite(x) else None


def analizza_web(progetto: str | dict, serie: dict[str, dict], *, n_anni: int | None = None) -> dict:
    """Analisi del progetto con le serie PVGIS date (chiave → risposta di PVGIS). Errori dei dati e configurazioni
    non supportate tornano come testo nel risultato, non come eccezioni."""
    try:
        config, parametri = _progetto(progetto)
    except ValueError as e:
        return {"contratto": CONTRATTO, "ok": False, "errore": str(e)}
    params = _parametri_economici(parametri)
    if params is None:
        return {"contratto": CONTRATTO, "ok": False,
                "errore": "Scegli quanta parte dei contributi va ai membri: senza questa scelta lo scenario non si "
                          "calcola."}
    analisi = analizza(config, params, fetch_pv=fetch_da_serie(serie), n_anni=n_anni)
    risultato = {
        "contratto": CONTRATTO,
        "motore": __version__,
        "ok": analisi.supportata,
        "supportata": analisi.supportata,
        "non_supportati": analisi.report.non_supportati,
        "da_verificare": analisi.report.da_verificare,
        "qualita": analisi.qualita,
        "economia_disabilitata": analisi.economia_disabilitata,
        "fonti_pv": sorted({p.fonte for profili in analisi.pv.values() for p in profili.values()}),
        "bande": {nome: {"minimo": _numero(b.minimo), "mediana": _numero(b.mediana), "massimo": _numero(b.massimo)}
                  for nome, b in analisi.bande.items()},
        "avvisi": analisi.avvisi[:50],
    }
    if analisi.base is not None:
        k = analisi.base.kpi
        risultato["base"] = {
            "van_investitore": _numero(k.van_investitore), "van_consolidato": _numero(k.van_consolidato),
            "tir_investitore": _numero(k.tir_investitore), "payback_investitore": k.payback_investitore,
            "contributi_primo_anno_intero": {n: _numero(v) for n, v in k.contributi_primo_anno_intero.items()},
        }
    return risultato


# --- passi 1 e 2: le tabelle dell'interfaccia e il salvataggio ---------------------------------
# Il sito tiene una bozza con le stesse tabelle dell'app Streamlit: i dati generali, una riga per contatore (con chiavi
# brevi, qui sotto), gli impianti con le colonne di `ui_model`, le curve orarie per contatore, i parametri economici e
# il lavoro ricaricato (`base`), da cui si riprendono i campi che le tabelle non mostrano.

CAMPI_PUNTO = {"punto": "Punto", "membro": "Membro", "tipo_soggetto": "Tipo soggetto",
               "tipologia": "Tipologia consumo", "kwh_annui": "kWh annui", "f1_kwh": "F1 kWh", "f23_kwh": "F23 kWh",
               "area": "Area convenzionale GSE", "tensione": "Tensione"}
MAX_FILE_CONSUMI = 40  # per esempio tre anni di file mensili di e-distribuzione


def costanti() -> dict:
    """Elenchi per i campi a scelta, presi dal motore così l'interfaccia non li ripete."""
    return {"contratto": CONTRATTO, "motore": __version__, "regioni": list(REGIONI),
            "tipi_soggetto": list(TIPI_SOGGETTO), "tipologie": list(TIPOLOGIE), "tensioni": [t.value for t in Tensione],
            "kwh_famiglia_tipo": KWH_FAMIGLIA_TIPO, "max_contatori": MAX_PUNTI}


def _json(v):
    """Valore di una cella in forma JSON: vuoti come null, date come testo ISO, numeri come float."""
    if v is None or isinstance(v, str):
        return v
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return float(v)


def _righe_punti(df: pd.DataFrame) -> list[dict]:
    return [{campo: _json(r.get(colonna)) for campo, colonna in CAMPI_PUNTO.items()} for r in df.to_dict("records")]


def _tabella_punti(righe: list[dict]) -> pd.DataFrame:
    return tipizza_punti(pd.DataFrame([{colonna: r.get(campo) for campo, colonna in CAMPI_PUNTO.items()}
                                       for r in righe], columns=COLONNE_PUNTI))


def famiglie(n: int, inizio: int = 1, kwh: float | None = None) -> list[dict]:
    """Righe per N famiglie tipo, numerate da `inizio`."""
    if not 1 <= int(n) <= 100:
        raise ValueError("Si possono aggiungere da 1 a 100 famiglie alla volta")
    return _righe_punti(famiglie_tipo(int(n), inizio=int(inizio), kwh=kwh))


def regione(nome: str) -> dict:
    """Nome canonico della regione (per esempio dalla ricerca dell'indirizzo), o null se non è riconosciuta."""
    try:
        return {"regione": normalizza_regione(str(nome))}
    except ValueError:
        return {"regione": None}


def _coordinata(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        return None
    return float(v)


def _generale(g: dict) -> tuple[Generale | None, list[str]]:
    """Dati del passo 1, controllati con messaggi da mostrare accanto ai campi."""
    errori = []
    nome = str(g.get("nome") or "").strip()
    if len(nome) > 120:
        errori.append("Il nome è troppo lungo: al massimo 120 caratteri")
    tipo = g.get("tipo")
    if tipo not in ("gruppo", "CER"):
        errori.append("Scegli che cosa vuoi simulare: gruppo di autoconsumatori o comunità energetica")
    indirizzo = str(g.get("indirizzo") or "").strip() or None
    if indirizzo and len(indirizzo) > 300:
        errori.append("L'indirizzo è troppo lungo: al massimo 300 caratteri")
    lat, lon = _coordinata(g.get("lat")), _coordinata(g.get("lon"))
    if lat is None or not 35 <= lat <= 48:
        errori.append("La latitudine deve essere tra 35 e 48: il simulatore vale per l'Italia")
    if lon is None or not 6 <= lon <= 19:
        errori.append("La longitudine deve essere tra 6 e 19: il simulatore vale per l'Italia")
    nome_regione = regione(g.get("regione") or "")["regione"]
    if nome_regione is None:
        errori.append("Scegli la regione")
    costituzione = None
    if g.get("data_costituzione"):
        try:
            costituzione = date.fromisoformat(str(g["data_costituzione"]))
        except ValueError:
            errori.append("La data di costituzione non è valida")
    if errori:
        return None, errori
    return Generale(nome=nome, tipo=tipo, lat=lat, lon=lon, regione=nome_regione, indirizzo=indirizzo,
                    data_costituzione=costituzione), []


def _riepilogo(config: Configuration) -> dict:
    """Quanti membri e contatori, il consumo totale e la qualità dei consumi di ogni contatore."""
    punti = [cp for cp in config.connection_points if cp.ruolo is not Ruolo.SOLA_IMMISSIONE]
    qualita = {"A": 0, "B": 0, "C": 0}
    for cp in punti:
        qualita[qualita_consumi(cp)] += 1
    return {"membri": len(config.members), "contatori": len(punti),
            "kwh_annui": round(sum(cp.kwh_effettivi for cp in punti)),
            "famiglie_tipo": sum(cp.kwh_da_default for cp in punti), "qualita_consumi": qualita}


def progetto_da_tabelle(tabelle: dict) -> dict:
    """Salvataggio (`ui_model.esporta_json`) dalle tabelle della bozza, con il riepilogo; oppure gli errori, separati
    tra il passo 1 (`errori_luogo`) e le tabelle (`errori`). Gli impianti possono mancare: arrivano al passo 3."""
    generale, errori_luogo = _generale(tabelle.get("generale") or {})
    righe = tabelle.get("punti") or []
    if len(righe) > MAX_PUNTI:
        return {"ok": False, "errori_luogo": errori_luogo, "errori": [f"Al massimo {MAX_PUNTI} contatori"]}
    errori: list[str] = []
    try:
        base = Configuration.model_validate(tabelle["base"]) if tabelle.get("base") else None
        voci = (tabelle.get("curve") or {}).items()
        curve = {str(k): CurvaMisurata.model_validate(v["curva"]) for k, v in voci}
        batterie = {str(k): BatteriaCasa.model_validate(v["batteria"]) for k, v in voci if v.get("batteria")}
        profili = {str(k): ProfiloPunto.model_validate(v["profilo"]) for k, v in voci if v.get("profilo")}
    except (ValidationError, KeyError, TypeError, AttributeError) as e:
        return {"ok": False, "errori_luogo": errori_luogo, "errori": [f"Bozza non valida: {e}"]}
    esito = None
    if generale is not None:
        impianti = tipizza_impianti(pd.DataFrame(tabelle.get("impianti") or [], columns=COLONNE_IMPIANTI))
        esito = configurazione_da_tabelle(generale, _tabella_punti(righe), impianti, base=base, curve=curve,
                                          batterie=batterie, profili=profili)
        errori = esito.errori
    if esito is None or esito.config is None:
        # gli errori degli impianti si mostrano al passo 3, gli altri al passo 2
        return {"ok": False, "errori_luogo": errori_luogo,
                "errori": [e for e in errori if not e.startswith("Impianto '")],
                "errori_impianti": [e for e in errori if e.startswith("Impianto '")]}
    parametri = {k: v for k, v in (tabelle.get("parametri") or {}).items() if k in PARAMETRI}
    return {"ok": True, "errori_luogo": [], "errori": [], "errori_impianti": [],
            "progetto": esporta_json(esito.config, parametri), "riepilogo": _riepilogo(esito.config)}


def _curva(curva: CurvaMisurata, batteria: BatteriaCasa | None = None, profilo: ProfiloPunto | None = None) -> dict:
    """La voce di un contatore nelle curve della bozza: la curva e, dal profilo energetico, batteria e scenario."""
    voce = {"curva": curva.model_dump(mode="json"), "descrizione": descrivi(curva), "calcolata": not curva.misurata}
    if batteria is not None:
        voce["batteria"] = batteria.model_dump(mode="json")
    if profilo is not None:
        voce["profilo"] = profilo.model_dump(mode="json")
    return voce


def tabelle_da_progetto(progetto: str) -> dict:
    """Bozza dal file di salvataggio (anche dell'app Streamlit); se il file non va, l'errore come testo."""
    try:
        config, parametri = importa_json(progetto)
    except ValueError as e:
        return {"ok": False, "errore": str(e)}
    generale, punti, impianti = tabelle_da_configurazione(config)
    return {"ok": True, "tabelle": {
        "generale": {"nome": generale.nome, "tipo": generale.tipo, "indirizzo": generale.indirizzo or "",
                     "lat": generale.lat, "lon": generale.lon, "regione": generale.regione,
                     "data_costituzione": _json(generale.data_costituzione)},
        "punti": _righe_punti(punti),
        "impianti": [{k: _json(v) for k, v in r.items()} for r in impianti.to_dict("records")],
        "curve": {cp.id: _curva(cp.curva_misurata, cp.batteria, cp.profilo)
                  for cp in config.connection_points if cp.curva_misurata},
        "parametri": parametri,
        "base": config.model_dump(mode="json"),
    }}


def _e_profilo(contenuto: bytes) -> bool:
    try:
        return json.loads(contenuto.decode("utf-8-sig")).get("formato") == FORMATO_PROFILO
    except (ValueError, AttributeError, RecursionError):
        return False


def _impianto_dal_profilo(impianto: dict, punto: str, data_costituzione: str | None) -> dict:
    """La riga del passo 3 per il FV di casa: investitore e, per un FV esistente, la data li indica l'utente."""
    return {"Impianto": nome_impianto_casa(punto), "Punto": punto, "kWp moduli": impianto["kwp"],
            "kW inverter": impianto["kwp"], "Inclinazione °": impianto["inclinazione"],
            "Orientamento °": impianto["orientamento"], "Ombre %": ombre_da_perdite(impianto["perdite_pct"]),
            "Entrata in esercizio": None if impianto["esistente"] else entrata_prevista(data_costituzione)["entrata"],
            "esistente": impianto["esistente"]}


def nome_impianto_casa(punto: str) -> str:
    return f"FV di casa ({punto})"[:120]


def leggi_consumi(file: list[dict], scenario: str | None = None, conta_fv: bool = True,
                  data_costituzione: str | None = None, contatore: str = "") -> dict:
    """Curva oraria di un contatore dai file scelti, ognuno `{"nome", "base64"}`: i CSV del distributore (anche più
    mesi insieme), un solo file `curva-consumi` del simulatore della casa (docs/formato_curva_consumi.md) oppure un
    profilo energetico (docs/formato_profilo_energetico.md). Per il profilo, senza `scenario` si restituiscono gli
    scenari da scegliere; con lo scenario, la curva, la batteria di casa e la riga dell'impianto da aggiungere."""
    if not file:
        return {"ok": False, "errore": "Scegli almeno un file"}
    if len(file) > MAX_FILE_CONSUMI:
        return {"ok": False, "errore": f"Al massimo {MAX_FILE_CONSUMI} file alla volta"}
    try:
        contenuti = [(str(f["nome"]), base64.b64decode(f["base64"], validate=True)) for f in file]
    except (KeyError, TypeError, binascii.Error):
        return {"ok": False, "errore": "File non leggibili"}
    calcolati = [c for nome, c in contenuti if nome.lower().endswith(".json")]
    if len(contenuti) == 1 and calcolati and _e_profilo(calcolati[0]):
        try:
            profilo = leggi_profilo(calcolati[0])
            if scenario is None:
                return {"ok": True, "scegli": True, "scenari": sintesi(profilo),
                        "comune": profilo.comune.nome if profilo.comune else None,
                        "descrizione": profilo.descrizione, "avvisi": profilo.avvisi[:20]}
            a = applica_scenario(profilo, str(scenario), bool(conta_fv))
        except ValueError as e:
            return {"ok": False, "errore": str(e)}
        return {"ok": True, **_curva(a.curva, a.batteria, a.profilo), "avvisi": a.avvisi[:20],
                "impianto": _impianto_dal_profilo(a.impianto, contatore, data_costituzione) if a.impianto else None}
    try:
        if calcolati and len(contenuti) > 1:
            raise ValueError("Il file del simulatore della casa va caricato da solo, senza altri file")
        curva, avvisi = leggi_curva_calcolata(calcolati[0]) if calcolati else curva_da_file([c for _, c in contenuti])
    except ValueError as e:
        return {"ok": False, "errore": str(e)}
    return {"ok": True, **_curva(curva), "avvisi": avvisi[:20]}


# --- la scheda dei consumi delle famiglie (cersim.guida) ---------------------------------------
# La pagina del link per le famiglie è leggera e non avvia il motore, salvo per i file orari: i suoi testi e le sue
# soglie sono una copia di `scheda_per_il_sito()` in web/src/scheda/testi.json (tests/test_web.py la confronta), e
# la scheda ricevuta si ricontrolla qui con `leggi_scheda`.

MAX_SCHEDE = 200


def scheda_per_il_sito() -> dict:
    """Testi, scelte e soglie della scheda dei consumi, per web/src/scheda/testi.json."""
    return {
        "formato": FORMATO, "versione": VERSIONE, "modulo": MODULO, "max_contatori": MAX_CONTATORI,
        "max_testo": MAX_TESTO, "scarto_fasce": SCARTO_FASCE, "max_kwh": MAX_KWH_ANNUI,
        "kwh_famiglia_tipo": KWH_FAMIGLIA_TIPO,
        "cosa_serve": [{"cosa": v.cosa, "dove": v.dove} for v in COSA_SERVE["famiglia"].voci[:2]],
        "portale_consumi": PORTALE_CONSUMI, "codice_pod": CODICE_POD, "privacy": PRIVACY_SCHEDA,
        "profili": [{"etichetta": k, "tipo_soggetto": s, "tipologia": t} for k, (s, t) in PROFILI.items()],
        "soggetti_attivita": [{"valore": s, "etichetta": ETICHETTE_SOGGETTO_ATTIVITA[s]} for s in SOGGETTI_ATTIVITA],
        "tipologie_attivita": TIPOLOGIE_ATTIVITA, "tipologie_ente": TIPOLOGIE_ENTE,
    }


def leggi_schede(file: list[dict], tabelle: dict) -> dict:
    """Le schede ricevute (`{"nome", "base64"}`) unite alla tabella dei contatori della bozza: una scheda rimandata
    aggiorna le righe di chi l'ha mandata (`guida.unisci_schede`). Restituisce le righe e le curve aggiornate e i
    messaggi per chi coordina; le schede sbagliate si saltano, con il motivo."""
    schede, messaggi = [], []
    nome_cfg = str((tabelle.get("generale") or {}).get("nome") or "").strip()[:MAX_TESTO]
    for f in file[:MAX_SCHEDE]:
        nome = str(f.get("nome") or "scheda") if isinstance(f, dict) else "scheda"
        try:
            scheda = leggi_scheda(base64.b64decode(f["base64"], validate=True))
        except (KeyError, TypeError, binascii.Error):
            messaggi.append(f"{nome}: file non leggibile")
            continue
        except ValueError as e:
            messaggi.append(f"{nome}: {e}")
            continue
        schede.append(scheda)
        if scheda.configurazione and nome_cfg and scheda.configurazione != nome_cfg:
            messaggi.append(f"{nome}: la scheda era per '{scheda.configurazione}'. Aggiunta lo stesso.")
    curve = {str(k): CurvaMisurata.model_validate(v["curva"]) for k, v in (tabelle.get("curve") or {}).items()}
    punti = _tabella_punti(tabelle.get("punti") or [])
    if schede:
        punti, unione = unisci_schede(punti, schede, curve=curve)
        messaggi = unione + messaggi
    return {"lette": len(schede), "punti": _righe_punti(punti), "curve": {k: _curva(c) for k, c in curve.items()},
            "messaggi": messaggi}


# --- passo 3: il tetto disegnato, la proposta delle tre taglie e la tabella degli impianti ---------------
# Come nell'app Streamlit (app.py, _proposta_impianto): il tetto si disegna sulla foto aerea, il motore ne ricava
# superficie e orientamento (`tetto.tetto_disegnato`), poi prova diverse taglie (`proposta.proponi`). Gli edifici
# vicini per le ombre li scarica la pagina tramite l'intermediario (Overpass), le serie PVGIS pure: la proposta ha
# gli stessi due tempi dell'analisi (`richieste_proposta`, poi `proposta` con le serie).


def scarica_profilo(voce: dict, ha_impianto: bool) -> dict:
    """Il profilo energetico di un contatore dalla sua voce nelle curve della bozza; oppure l'errore come testo."""
    try:
        cp = ConnectionPoint(id="contatore", titolare="membro", tipologia_profilo=Tipologia.DOMESTICO,
                             curva_misurata=CurvaMisurata.model_validate(voce["curva"]),
                             batteria=BatteriaCasa.model_validate(voce["batteria"]) if voce.get("batteria") else None,
                             profilo=ProfiloPunto.model_validate(voce["profilo"]) if voce.get("profilo") else None)
        return {"ok": True, "profilo": esporta_profilo(cp, bool(ha_impianto))}
    except (ValidationError, ValueError, KeyError, TypeError, AttributeError) as e:
        return {"ok": False, "errore": str(e).replace("Il contatore contatore", "Il contatore")}


def costanti_impianti() -> dict:
    """Elenchi e valori del passo 3, presi dal motore così l'interfaccia non li ripete."""
    return {"forme": list(FORME), "inclinazione": INCLINAZIONE, "m2_per_kwp": M2_PER_KWP,
            "livelli_ombre": [{"etichetta": e, "pct": p} for e, p in LIVELLI_OMBRE],
            "sola_immissione": SOLA_IMMISSIONE, "investitore_esterno": INVESTITORE_ESTERNO,
            "colonne": COLONNE_IMPIANTI, "foto_aerea_url": FOTO_AEREA_URL,
            "foto_aerea_attribuzione": FOTO_AEREA_ATTRIBUZIONE, "attribuzione_osm": ATTRIBUZIONE,
            "quota_provvisoria": QUOTA_PROVVISORIA,
            "termine_tip": pacchetto_normativo().tip.termine_accesso_entrata_esercizio.isoformat()}


def entrata_prevista(data_costituzione: str | None = None) -> dict:
    """Entrata in esercizio proposta: qualche mese dopo la costituzione, o da oggi."""
    try:
        costituzione = date.fromisoformat(data_costituzione) if data_costituzione else None
    except ValueError:
        costituzione = None
    return {"entrata": entrata_predefinita(costituzione).isoformat()}


def tetto(angoli: list, forma: str = "a falde", piani: int | None = None, inclinazione: float | None = None,
          edifici: list[dict] | None = None) -> dict:
    """Superficie, orientamento e ombre del tetto disegnato (angoli `[lon, lat]`). Con gli edifici di OpenStreetMap
    (`edifici`, gli elementi di Overpass) anche le ombre stimate e la pianta in SVG; senza, solo il disegno."""
    if forma not in FORME:
        return {"ok": False, "errore": "Scegli il tipo di tetto"}
    try:
        t = tetto_disegnato(angoli, forma=forma, piani=int(piani) if piani else None, inclinazione=inclinazione,
                            elementi_osm=edifici)
    except (ValueError, TypeError, IndexError) as e:
        return {"ok": False, "errore": str(e) if isinstance(e, ValueError) else "Disegno del tetto non leggibile"}
    con_vicini = edifici is not None
    return {
        "ok": True, "lat": round(t.lat, 6), "lon": round(t.lon, 6), "area_terra_m2": round(t.area_terra_m2, 1),
        "superficie_utile_m2": round(t.superficie_utile_m2, 1), "azimut": round(t.azimut), "est_ovest": t.est_ovest,
        "ombre_pct": round(t.ombre_pct, 1) if con_vicini else None,
        "ombre_pct_due_falde": (round(t.ombre_pct_due_falde, 1)
                                if con_vicini and t.ombre_pct_due_falde is not None else None),
        "vicini": len(t.vicini), "note": t.note, "svg": disegno_svg(t) if con_vicini else None,
    }


def _scelta(s: dict, tipo: str) -> SceltaTetto:
    """La scelta del tetto e di chi paga, come la manda la pagina. Solleva ValueError con un messaggio leggibile."""
    nomi = {"kwp_max": "kWp installabili", "inclinazione": "inclinazione", "azimut": "orientamento",
            "azimut_2": "orientamento della seconda falda", "ombre_pct": "ombre"}

    def numero(chiave, minimo, massimo):
        x = _coordinata(s.get(chiave))
        if x is None or not minimo <= x <= massimo:
            raise ValueError(f"Controlla il valore di {nomi[chiave]}: deve essere tra {minimo} e {massimo}")
        return x

    punto, investitore = str(s.get("punto") or "").strip(), str(s.get("investitore") or "").strip()
    if not punto or not investitore:
        raise ValueError("Scegli il contatore a cui si collega l'impianto e chi lo paga")
    try:
        entrata = date.fromisoformat(str(s.get("entrata")))
    except ValueError:
        raise ValueError("Indica la data prevista di entrata in esercizio") from None
    azimut_2 = None if s.get("azimut_2") is None else numero("azimut_2", -180, 180)
    return SceltaTetto(kwp_max=round(numero("kwp_max", 0, 5000), 1), inclinazione=numero("inclinazione", 0, 90),
                       azimut=numero("azimut", -180, 180), ombre_pct=numero("ombre_pct", 0, 40), punto=punto,
                       investitore=investitore, entrata=entrata, azimut_2=azimut_2, nome=nome_impianto(tipo, punto))


def _dati_proposta(tabelle: dict, scelta: dict) -> tuple[Generale, pd.DataFrame, SceltaTetto, pd.DataFrame | None,
                                                         dict[str, CurvaMisurata]]:
    generale, errori = _generale(tabelle.get("generale") or {})
    if generale is None:
        raise ValueError("Prima completa il passo 1: " + "; ".join(errori))
    s = _scelta(scelta, generale.tipo)
    curve = {str(k): CurvaMisurata.model_validate(v["curva"]) for k, v in (tabelle.get("curve") or {}).items()}
    # nel condominio c'è un solo tetto e la proposta lo sostituisce; nella comunità gli altri impianti restano
    altri = (tipizza_impianti(pd.DataFrame(tabelle.get("impianti") or [], columns=COLONNE_IMPIANTI))
             if generale.tipo == "CER" else None)
    return generale, _tabella_punti(tabelle.get("punti") or []), s, altri, curve


def richieste_proposta(tabelle: dict, scelta: dict) -> dict:
    """Serie PVGIS che servono alla proposta (come `richieste_pvgis`), o l'errore se i dati non bastano."""
    try:
        generale, punti, s, altri, curve = _dati_proposta(tabelle, scelta)
        esito = configurazione_da_tabelle(generale, punti, tabella_impianto(s, max(s.kwp_max, 1), altri), curve=curve)
    except (ValueError, ValidationError, KeyError, TypeError) as e:
        return {"ok": False, "errore": str(e)}
    if esito.config is None:
        return {"ok": False, "errore": "Prima completa i dati: " + "; ".join(esito.errori)}
    return {"ok": True, "richieste": _richieste(esito.config)}


def _righe_impianti(df: pd.DataFrame) -> list[dict]:
    return [{k: _json(v) for k, v in r.items()} for r in df.to_dict("records")]


def proposta(tabelle: dict, scelta: dict, serie: dict[str, dict]) -> dict:
    """Tre taglie commentate per il tetto (`proposta.proponi`), con le serie PVGIS già scaricate. Per ogni taglia
    anche la tabella degli impianti che ne risulta, da usare con "Usa questa taglia"."""
    try:
        generale, punti, s, altri, curve = _dati_proposta(tabelle, scelta)
        parametri = tabelle.get("parametri") or {}
        provvisoria = parametri.get("quota_membri") is None
        params = _parametri_economici({**parametri, "quota_membri": QUOTA_PROVVISORIA} if provvisoria else parametri)
        p = proponi(generale, punti, s, params, _prezzi(tabelle.get("prezzi")), quota_provvisoria=provvisoria,
                    altri=altri, curve=curve, fetch_pv=fetch_da_serie(serie))
    except (ValueError, ValidationError, KeyError, TypeError) as e:
        return {"ok": False, "errore": str(e)}
    return {
        "ok": True, "qualita": p.qualita, "quota_membri": p.quota_membri, "quota_provvisoria": p.quota_provvisoria,
        "investitore": p.investitore, "nessuna_conviene": p.nessuna_conviene, "note": p.note,
        "opzioni": [{
            "nome": o.nome, "kwp": round(o.punto.potenza_moduli_kwp, 1), "costo": _numero(o.punto.costo_eur),
            "van_minimo": _numero(o.punto.van_consolidato_min), "van_mediana": _numero(o.punto.van_consolidato_mediano),
            "van_massimo": _numero(o.punto.van_consolidato_max), "euro_anno_membri": _numero(o.punto.euro_anno_membri),
            "commento": o.commento, "conviene_a_entrambi": o.conviene_a_entrambi,
            "impianti": _righe_impianti(tabella_impianto(s, o.punto.potenza_moduli_kwp, altri)),
        } for o in p.opzioni],
        "curva": [{"kwp": round(q.potenza_moduli_kwp, 1), "minimo": _numero(q.van_consolidato_min),
                   "mediana": _numero(q.van_consolidato_mediano), "massimo": _numero(q.van_consolidato_max)}
                  for q in p.curva],
    }


# --- passi 4 e 5: economia, risultati completi, curva delle taglie e report ----------------------------------
# Come nell'app Streamlit (app.py, passi 4 e 5). I prezzi orari caricati dall'utente restano nella bozza del browser,
# non nel salvataggio (i dati del GME sono solo per uso personale): viaggiano come valori orari dell'anno. L'ultima
# analisi resta in memoria nel Worker, così curva delle taglie e report non la rifanno.

MAX_FILE_PREZZI = 6
_ultima: dict = {}  # {"chiave", "analisi", "params", "prezzi"}: l'ultima analisi calcolata


def costanti_economia(tipo: str = "gruppo") -> dict:
    """Valori predefiniti del passo 4, per i segnaposto dei campi (normativa.assunzioni_economiche)."""
    ipotesi = assunzioni_economiche()
    tipo = tipo if tipo in ("gruppo", "CER") else "gruppo"
    return {
        "prezzi_medi": ipotesi.prezzi.media_eur_mwh,
        "costo_evitabile_eur_kwh": ipotesi.bolletta.costo_evitabile_eur_kwh,
        "tasso_sconto": ipotesi.finanza.tasso_sconto_reale,
        "om_assicurazione_quota_anno": ipotesi.impianto.om_quota_capex_anno + ipotesi.impianto.assicurazione_quota_capex_anno,
        "gestione_eur_anno": ipotesi.configurazione.gestione_eur_anno[tipo],
        "costituzione_eur": ipotesi.configurazione.costituzione_eur[tipo],
    }


def _serie_prezzi(s: PriceSeries) -> dict:
    return {"anno": s.year, "zona": s.zona, "fonte": s.fonte, "qualita": s.qualita, "media": round(s.media, 2),
            "valori": [round(float(v), 3) for v in s.eur_mwh.to_numpy()]}


def _prezzi(prezzi: dict | None) -> dict[int, PriceSeries]:
    """I prezzi della bozza (`leggi_prezzi`) come serie del motore. Solleva ValueError se non tornano."""
    fuori = {}
    for voce in (prezzi or {}).values():
        anno = int(voce["anno"])
        indice = year_index(anno)
        if len(voce["valori"]) != len(indice):
            raise ValueError(f"Prezzi del {anno} incompleti: carica di nuovo il file al passo 4")
        fuori[anno] = PriceSeries(pd.Series(voce["valori"], index=indice, dtype=float, name="eur_mwh"), anno,
                                  str(voce["zona"]), str(voce["fonte"]), str(voce.get("qualita") or "B"))
    return fuori


def leggi_prezzi(file: list[dict], regione: str) -> dict:
    """Prezzi orari dai CSV dell'utente (`{"nome", "base64"}`, uno per anno), per la zona della regione."""
    if not file:
        return {"ok": False, "errori": ["Scegli almeno un file"], "prezzi": {}}
    serie: dict[int, PriceSeries] = {}
    errori = []
    for f in file[:MAX_FILE_PREZZI]:
        nome = str(f.get("nome") or "prezzi.csv")
        try:
            dati = base64.b64decode(f["base64"], validate=True)
            anno = anno_dei_prezzi(io.BytesIO(dati))
            contenuto = io.BytesIO(dati)
            contenuto.name = nome
            s = prezzi_da_csv(contenuto, zona_mercato(regione, anno), anno)
            if s.year in serie:
                raise ValueError(f"c'è già un file per il {s.year}")
            serie[s.year] = s
        except (KeyError, TypeError, binascii.Error):
            errori.append(f"{nome}: file non leggibile")
        except (ValueError, pd.errors.ParserError) as e:
            errori.append(f"{nome}: {e}")
    return {"ok": bool(serie), "errori": errori, "prezzi": {str(a): _serie_prezzi(s) for a, s in sorted(serie.items())}}


def _tabella(df: pd.DataFrame) -> dict:
    """Una tabella pandas in JSON: colonne e righe, con i numeri arrotondati."""
    return {"colonne": [str(c) for c in df.columns],
            "righe": [[_numero(v) if isinstance(v, int | float | np.floating) else str(v) for v in r]
                      for r in df.itertuples(index=False)]}


def _banda(b) -> dict | None:
    return None if b is None else {"minimo": _numero(b.minimo), "mediana": _numero(b.mediana), "massimo": _numero(b.massimo)}


def _presenta(analisi: Analisi) -> dict:
    """Tutto ciò che il passo 5 mostra, già pronto: testi e tabelle di cersim.report, dati dei grafici."""
    rep = analisi.report
    fuori = {"contratto": CONTRATTO, "motore": __version__, "ok": analisi.supportata,
             "non_supportati": rep.non_supportati, "da_verificare": rep.da_verificare}
    if not analisi.supportata:
        return fuori
    if analisi.dati_incoerenti:
        return {"contratto": CONTRATTO, "ok": False, "errore": analisi.economia_disabilitata}
    nomi = nomi_leggibili(analisi.config)
    testo_q, tono_q, spiegazione_q = QUALITA[analisi.qualita]
    yr = anno_rappresentativo(analisi.energia_base)
    fuori |= {
        "economia_disabilitata": analisi.economia_disabilitata,
        "frase": [[t, g] for t, g in frase_sintesi(analisi)],
        "qualita": {"lettera": analisi.qualita, "testo": testo_q, "tono": tono_q, "spiegazione": spiegazione_q},
        "nota_intervalli": NOTA_INTERVALLI,
        "fonti_prezzi": [] if analisi.economia_disabilitata else fonti_prezzi(analisi),
        "fonti_pv": sorted({p.fonte for profili in analisi.pv.values() for p in profili.values()}),
        "precisione": {"frase": frase_precisione(analisi),
                       "voci": [{"cosa": m.cosa, "perche": m.perche, "passo": m.passo} for m in dati_da_migliorare(analisi)]},
        "requisiti": [{"nome": n, "stato": STATO_ETICHETTA[s][0], "tono": STATO_ETICHETTA[s][1], "motivo": m}
                      for n, s, m in requisiti(analisi, tutti=False)],
        "giorno_tipo": {"anno": yr.year, "mesi": [_tabella(giorno_tipo(yr, mese).reset_index()) for mese in range(1, 13)]},
        "mensile": _tabella(mensile(yr).reset_index(names="mese")),
        "colori": COLORI_GRAFICI,
        "avvertenze": avvertenze(analisi),
        "impianti": [{"id": p.id, "nome": p.nome} for p in analisi.config.plants],
        "bande": {k: _banda(b) for k, b in analisi.bande.items()},
    }
    if analisi.economia_disabilitata or analisi.base is None:
        return fuori
    base = analisi.base
    fuori |= {
        "cifre": [{"voce": c.voce, "valore": _numero(c.valore), "minimo": _numero(c.minimo), "massimo": _numero(c.massimo),
                   "unita": c.unita, "significato": c.significato} for c in cifre(analisi, nomi)],
        "confronto": {"frase": frase_confronto(analisi),
                      "righe": [{"voce": v, "banda": _banda(b), "descrizione": d} for v, b, d in confronto(analisi)]},
        "cassa": _tabella(cassa_cumulata(base).reset_index()),
        "sensibilita": {"base": _numero(base.kpi.van_consolidato), "anno_meteo": base.scenario.anno_meteo,
                        "voci": [{"parametro": v.parametro, "variazione": v.variazione,
                                  "basso": _numero(v.van_consolidato_basso), "alto": _numero(v.van_consolidato_alto)}
                                 for v in analisi.sensibilita]},
        "chi_riceve": {"anno": anno_rappresentativo(base.energia).year, **_tabella(chi_riceve_cosa(base, nomi))},
        "per_membro": [{"membro": nomi.get(m, m), "netto": _numero(v)} for m, v in base.kpi.euro_anno_per_membro.items()],
    }
    return fuori


def risultati(progetto: str | dict, serie: dict[str, dict], prezzi: dict | None = None, *,
              n_anni: int | None = None, fetch_pv: Callable[..., PVProfile] | None = None) -> dict:
    """L'analisi del passo 5 (`analisi.analizza`) con le serie PVGIS e i prezzi della bozza, presentata come
    nell'app Streamlit. Resta in memoria per `dimensionamento` e `report`. Fuori dal browser `fetch_pv` può prendere
    il posto delle serie (per esempio `pv.pv_profile`, che scarica da PVGIS con la cache)."""
    try:
        config, parametri = _progetto(progetto)
        serie_prezzi = _prezzi(prezzi)
    except (ValueError, KeyError, TypeError) as e:
        return {"contratto": CONTRATTO, "ok": False, "errore": str(e)}
    params = _parametri_economici(parametri)
    if params is None:
        return {"contratto": CONTRATTO, "ok": False,
                "errore": "Scegli quanta parte dei contributi va ai membri, al passo 4: senza questa scelta lo scenario "
                          "non si calcola."}
    analisi = analizza(config, params, serie_prezzi, fetch_pv=fetch_pv or fetch_da_serie(serie), n_anni=n_anni)
    _ultima.clear()
    _ultima.update(analisi=analisi, params=params, prezzi=serie_prezzi)
    return _presenta(analisi)


def _analisi_in_memoria() -> tuple[Analisi, ParametriEconomici, dict]:
    if not _ultima or not _ultima["analisi"].supportata or _ultima["analisi"].economia_disabilitata:
        raise ValueError("Calcola prima lo scenario")
    return _ultima["analisi"], _ultima["params"], _ultima["prezzi"]


def dimensionamento(impianto: str, *, n_punti: int = 8) -> dict:
    """Curva del beneficio per diverse taglie di un impianto dell'ultima analisi (`sizing.dimensiona`)."""
    try:
        analisi, params, prezzi = _analisi_in_memoria()
        if impianto not in {p.id for p in analisi.config.plants}:
            raise ValueError("Impianto sconosciuto")
        dim = dimensiona(analisi.config, impianto, params, analisi.pv, prezzi, scenari_dimensionamento(analisi),
                         n_punti=n_punti)
    except ValueError as e:
        return {"ok": False, "errore": str(e)}
    return {"ok": True, "dicitura": dim.dicitura,
            "curva": [{"kwp": round(float(q.potenza_moduli_kwp), 1), "configurazione": _numero(q.van_consolidato_mediano),
                       "investitore": _numero(q.van_investitore_mediano)} for q in dim.curva]}


def report(formato: str) -> dict:
    """Il report PDF o il file Excel dell'ultima analisi, in base64. Chiede fpdf2, matplotlib e openpyxl, che il
    Worker carica solo per questo, e i caratteri Geist in static/."""
    try:
        analisi, params, _ = _analisi_in_memoria()
        if formato == "pdf":
            dati, nome = report_pdf(analisi, params), "scenario_cer.pdf"
        elif formato == "xlsx":
            dati, nome = report_excel(analisi, params), "scenario_cer.xlsx"
        else:
            raise ValueError("Formato sconosciuto")
    except (ValueError, FileNotFoundError, ImportError) as e:
        return {"ok": False, "errore": str(e)}
    return {"ok": True, "nome": nome, "base64": base64.b64encode(dati).decode()}


def scheda_pdf(configurazione: str | None = None, link: str | None = None) -> dict:
    """La scheda dei consumi da stampare o girare alle famiglie (`report.scheda_famiglia_pdf`), in base64. Come
    `report`, chiede fpdf2 e i caratteri Geist, che il Worker carica con i pacchetti dei report."""
    try:
        dati = scheda_famiglia_pdf((configurazione or "").strip() or None, link or None)
    except (ValueError, FileNotFoundError, ImportError) as e:
        return {"ok": False, "errore": str(e)}
    return {"ok": True, "nome": "scheda_consumi.pdf", "base64": base64.b64encode(dati).decode()}


FUNZIONI: dict[str, Callable[..., object]] = {f.__name__: f for f in (
    costanti, famiglie, regione, progetto_da_tabelle, tabelle_da_progetto, leggi_consumi, leggi_schede, scarica_profilo,
    costanti_impianti, entrata_prevista, tetto, richieste_proposta, proposta,
    costanti_economia, leggi_prezzi, risultati, dimensionamento, report, scheda_pdf)}


def chiama(nome: str, argomenti: str) -> str:
    """Per il Worker: una delle `FUNZIONI`, con gli argomenti per nome in un JSON; il risultato in JSON."""
    if nome not in FUNZIONI:
        raise ValueError(f"Funzione del motore sconosciuta: {nome}")
    return json.dumps(FUNZIONI[nome](**json.loads(argomenti)), ensure_ascii=False)


TESTI_SCHEDA = "web/src/scheda/testi.json"

if __name__ == "__main__":  # python -m cersim.web: riscrive i testi della scheda per il sito, dalla radice del progetto
    with open(TESTI_SCHEDA, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(scheda_per_il_sito(), ensure_ascii=False, indent=2) + "\n")
    print(f"Scritto {TESTI_SCHEDA}")
