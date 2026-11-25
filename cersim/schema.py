"""Schemi JSON pubblici del progetto CER: il file in ingresso e l'esito in uscita.

Servono a chi usa il motore da fuori (riga di comando, altri programmi, in futuro un server MCP per gli agenti AI):
dicono che forma hanno i dati senza leggere il codice.

- **Progetto** (`progetto-cer`, ingresso): è il file di salvataggio di sempre (`ui_model.esporta_json`,
  `{"schema": 1, "configurazione": …, "parametri": …}`), lo stesso che esportano l'app Streamlit e il sito. Lo schema
  si ricava dai modelli pydantic di `cersim.model`, con le descrizioni in italiano aggiunte qui.
- **Esito** (`esito-cer`, uscita): il risultato del passo 5 (`web.risultati`) con un'intestazione che dice formato,
  versione, motore e data del calcolo. I campi "stabili" sono descritti campo per campo; quelli di presentazione
  (frasi, tabelle dei grafici, colori) sono elencati ma possono cambiare forma senza cambiare versione.

Lo schema è necessario ma non sufficiente: le regole tra più campi (riferimenti tra membri, contatori e impianti,
somma delle fasce, regione riconosciuta…) le controlla solo il motore, con `cersim valida`.

`python -m cersim.schema` riscrive i file in `cersim/schemi/`; tests/test_schema.py controlla che siano aggiornati.
"""

import copy
import json
from datetime import date
from pathlib import Path

from cersim import __version__
from cersim.model import CELLE_CURVA, Configuration
from cersim.ui_model import LIMITI_PARAMETRI, REGIMI_VENDITA, VERSIONE_SCHEMA

CARTELLA = Path(__file__).parent / "schemi"
BASE_ID = "https://cer.raccasamuele.it/schemi/"  # ipotesi: indirizzo stabile, i file non sono ancora pubblicati lì
DIALETTO = "https://json-schema.org/draft/2020-12/schema"

FORMATO_ESITO = "esito-cer"
VERSIONE_ESITO = 1  # sale quando cambia in modo incompatibile un campo stabile dell'esito

NOME_PROGETTO = f"progetto-cer.v{VERSIONE_SCHEMA}.schema.json"
NOME_ESITO = f"esito-cer.v{VERSIONE_ESITO}.schema.json"

# Descrizioni dei campi, per modello. tests/test_schema.py controlla che ogni voce corrisponda a un campo esistente.
DESCRIZIONI: dict[str, dict[str, str]] = {
    "Configuration": {
        "": "La configurazione: gruppo di autoconsumatori (un edificio) o comunità energetica rinnovabile (CER).",
        "nome": "Nome libero della configurazione, per i report.",
        "tipo": "\"gruppo\": autoconsumatori nello stesso edificio; \"CER\": comunità energetica rinnovabile.",
        "indirizzo": "Indirizzo indicativo, solo per i report.",
        "lat": "Latitudine in gradi decimali (WGS84). Il simulatore vale solo per l'Italia: tra 35 e 48.",
        "lon": "Longitudine in gradi decimali (WGS84). Il simulatore vale solo per l'Italia: tra 6 e 19.",
        "regione": "Regione italiana (per esempio \"Piemonte\"): decide la zona di mercato dei prezzi e la maggiorazione "
                   "della tariffa premio. Accetta anche varianti di scrittura comuni.",
        "members": "I membri: chi partecipa, con il tipo di soggetto che decide l'ammissibilità.",
        "connection_points": "I contatori (POD): l'unità del bilancio energetico. Un membro può averne più di uno.",
        "plants": "Gli impianti fotovoltaici, ognuno collegato a un contatore (al massimo uno per contatore).",
        "referente": "Identificativo del membro referente verso il GSE, se scelto.",
        "edificio_id_gruppo": "Per un gruppo di autoconsumatori: l'edificio comune. Obbligatorio se tipo è \"gruppo\".",
        "data_costituzione": "Data (prevista) di costituzione della configurazione, AAAA-MM-GG.",
    },
    "Member": {
        "": "Un membro della configurazione.",
        "id": "Identificativo univoco, usato dai contatori (titolare) e dagli impianti (investitore…). Lettere, cifre, "
              "_ . -. Non può essere un nome riservato (configurazione, GSE, mercato, fornitori, bolletta_evitata, terzo).",
        "nome": "Nome leggibile, per i report.",
        "tipo_soggetto": "Tipo giuridico: decide se il membro è ammesso e come si dividono le quote.",
    },
    "ConnectionPoint": {
        "": "Un contatore (punto di connessione, POD).",
        "id": "Identificativo univoco del contatore, usato dagli impianti.",
        "titolare": "Identificativo del membro titolare.",
        "ruolo": "\"bidirezionale\": preleva e immette; \"sola_immissione\": solo un impianto, senza consumi.",
        "codice_pod": "Codice POD, facoltativo: non serve al calcolo.",
        "tipologia_profilo": "Forma tipica dei consumi orari quando non c'è una curva oraria. Obbligatoria tranne che "
                             "per i contatori di sola immissione.",
        "kwh_annui": "Consumo annuo in kWh, dalla bolletta. Se mancano consumo, fasce e curva, solo per i domestici vale "
                     "la famiglia tipo ARERA (2700 kWh).",
        "fasce": "Consumo annuo per fascia oraria, dalla bolletta. Con kwh_annui la somma deve tornare entro il 5%.",
        "tensione": "Livello di tensione della connessione.",
        "lat": "Latitudine del contatore, se diversa da quella della configurazione.",
        "lon": "Longitudine del contatore, se diversa da quella della configurazione.",
        "area_convenzionale": "Area convenzionale GSE (cabina primaria). In una CER i membri devono stare nella stessa.",
        "edificio_id": "Edificio del contatore: in un gruppo deve coincidere con edificio_id_gruppo.",
        "curva_misurata": "Consumi orari (misurati o calcolati): se ci sono, prevalgono su kwh_annui, fasce e tipologia.",
        "batteria": "Batteria di casa dietro il contatore (dal profilo energetico): richiede un impianto sullo stesso "
                    "contatore.",
        "profilo": "Scenario del profilo energetico della casa da cui vengono curva e batteria, conservato per "
                   "riscaricarlo.",
    },
    "Fasce": {
        "": "Consumi annui per fascia, in kWh: F1/F2/F3 oppure F1/F23.",
        "f1": "kWh in fascia F1.",
        "f2": "kWh in fascia F2 (insieme a f3, in alternativa a f23).",
        "f3": "kWh in fascia F3 (insieme a f2, in alternativa a f23).",
        "f23": "kWh in fascia F2 + F3 (in alternativa a f2 e f3).",
    },
    "CurvaMisurata": {
        "": f"Forma media dei consumi orari: {CELLE_CURVA} valori in kWh, per tipo di giorno (feriale, sabato, festivo) "
            "× mese × ora civile. Si ricava dai file del distributore (cersim.misure) o dal formato curva-consumi "
            "(docs/formato_curva_consumi.md); non contiene il POD né le singole letture.",
        "ore": f"{CELLE_CURVA} valori in kWh, nell'ordine tipo di giorno × mese × ora.",
        "natura": "\"misurata\" (dai contatori) o \"calcolata\" (da un modello).",
        "giorni": "Giorni con misure. Solo per le curve misurate.",
        "dal": "Primo giorno delle misure. Solo per le curve misurate.",
        "al": "Ultimo giorno delle misure. Solo per le curve misurate.",
        "kwh_annui": "Stima del consumo annuo dalla forma media.",
        "fonte": "Da dove vengono i dati, testo libero.",
        "giorni_veri": "Giorni veri senza data, per non sottostimare i picchi: [cella, 24 valori in kWh].",
        "fv_sottratto_kwp": "kWp di fotovoltaico già tolti dai consumi: la curva sono prelievi, non consumi lordi.",
        "batteria_kwh": "Capacità della batteria di casa già considerata nei prelievi.",
    },
    "Plant": {
        "": "Un impianto fotovoltaico.",
        "id": "Identificativo univoco dell'impianto.",
        "nome": "Nome leggibile, per i report.",
        "connection_point": "Identificativo del contatore a cui è collegato.",
        "potenza_moduli_kwp": "Potenza dei moduli in kWp (lato continua).",
        "potenza_inverter_kw": "Potenza degli inverter in kW (lato alternata). Per il GSE conta il minore dei due.",
        "potenza_moduli_max_kwp": "Potenza massima installabile, per provare taglie diverse.",
        "tilt": "Inclinazione dei moduli in gradi (0 = orizzontale).",
        "azimut": "Orientamento in gradi, convenzione PVGIS: 0 = sud, 90 = ovest, -90 = est.",
        "azimut_2": "Orientamento della seconda falda, se i moduli sono divisi a metà su due falde.",
        "perdite_pct": "Perdite di sistema in percentuale, ombre comprese (PVGIS usa 14 come valore tipico).",
        "investitore": "Chi paga l'impianto: identificativo di un membro oppure \"terzo\".",
        "proprietario": "Proprietario, se diverso dall'investitore.",
        "produttore": "Produttore per il GSE, se diverso dal proprietario.",
        "data_entrata_esercizio": "Data (prevista) di entrata in esercizio, AAAA-MM-GG.",
        "data_inizio_periodo_incentivazione": "Inizio dei 20 anni di tariffa premio, se diverso dall'entrata in esercizio.",
        "data_decorrenza_servizio_cacer": "Decorrenza del servizio per l'autoconsumo diffuso, se diversa.",
        "data_decorrenza_vendita": "Decorrenza della vendita dell'energia, se diversa.",
        "nell_edificio": "Se l'impianto è nell'edificio (o nel condominio) della configurazione.",
        "contributo_capitale": "Contributo in conto capitale già concesso (per esempio PNRR), con gli estremi dell'atto.",
        "costo_preventivo_eur": "Costo complessivo da preventivo, IVA esclusa. Se manca si usano le assunzioni "
                                "economiche del motore.",
    },
}

DESCRIZIONI_PARAMETRI = {
    "quota_membri": "Quota dei contributi GSE che va ai membri (0–1); il resto va a chi investe. Senza questa scelta "
                    "l'analisi economica non si calcola: il motore non ha un riparto \"consigliato\".",
    "costo_evitabile_eur_kwh": "Costo evitato in bolletta per ogni kWh autoconsumato, €/kWh. Vuoto: valore del motore.",
    "tasso_sconto": "Tasso di sconto reale per il VAN (0–0,2). Vuoto: valore del motore.",
    "regime_vendita": "Vendita dell'energia immessa: ritiro dedicato GSE (\"RID\") o sul mercato.",
    "om_assicurazione_quota_anno": "Manutenzione e assicurazione all'anno, come quota del costo dell'impianto (0–0,1).",
    "gestione_eur_anno": "Costi di gestione della configurazione, € all'anno.",
    "costituzione_eur": "Costi di costituzione della configurazione, €.",
}


def _descrivi(schema: dict) -> dict:
    for modello, campi in DESCRIZIONI.items():
        nodo = schema if modello == "Configuration" else schema["$defs"][modello]
        for campo, testo in campi.items():
            (nodo if campo == "" else nodo["properties"][campo])["description"] = testo
    return schema


def _parametri() -> dict:
    proprieta = {}
    for chiave, (_, minimo, massimo) in LIMITI_PARAMETRI.items():
        proprieta[chiave] = {"type": ["number", "null"], "minimum": minimo, "maximum": massimo}
    proprieta["regime_vendita"] = {"enum": [*REGIMI_VENDITA, None]}
    for chiave, testo in DESCRIZIONI_PARAMETRI.items():
        proprieta[chiave]["description"] = testo
    return {"type": "object", "description": "Scelte economiche dello scenario. Le chiavi sconosciute si ignorano.",
            "properties": proprieta}


def schema_progetto() -> dict:
    """Schema JSON del file di progetto (ingresso), dai modelli di `cersim.model`."""
    configurazione = _descrivi(Configuration.model_json_schema())
    definizioni = configurazione.pop("$defs")
    definizioni["Configuration"] = configurazione
    return {
        "$schema": DIALETTO,
        "$id": BASE_ID + NOME_PROGETTO,
        "title": "Progetto CER",
        "description": "Il file di progetto di cersim: lo stesso che esportano l'app e il sito (\"Esporta\"). "
                       "Lo schema controlla la forma; le regole tra campi le controlla `cersim valida`.",
        "type": "object",
        "required": ["schema", "configurazione"],
        "properties": {
            "schema": {"const": VERSIONE_SCHEMA, "description": "Versione del formato del progetto."},
            "configurazione": {"$ref": "#/$defs/Configuration"},
            "parametri": _parametri(),
        },
        "$defs": definizioni,
    }


_NUMERO = {"type": ["number", "null"]}
_TESTI = {"type": "array", "items": {"type": "string"}}
_BANDA = {"type": ["object", "null"], "description": "Intervallo sugli scenari: minimo, mediana, massimo.",
          "properties": {"minimo": _NUMERO, "mediana": _NUMERO, "massimo": _NUMERO},
          "required": ["minimo", "mediana", "massimo"]}
_TABELLA = {"type": "object", "properties": {"colonne": _TESTI, "righe": {"type": "array", "items": {"type": "array"}}},
            "required": ["colonne", "righe"]}
_PRESENTAZIONE = "Campo di presentazione: può cambiare forma senza cambiare versione."


def schema_esito() -> dict:
    """Schema JSON dell'esito dell'analisi (uscita)."""
    return {
        "$schema": DIALETTO,
        "$id": BASE_ID + NOME_ESITO,
        "title": "Esito dell'analisi CER",
        "description": "Il risultato di `cersim analizza`: lo stesso del passo Risultati del sito, con l'intestazione. "
                       "Gli euro sono valori reali; gli intervalli vengono dagli scenari di meteo e prezzi. "
                       "Scenario preliminare, non uno studio di fattibilità.",
        "type": "object",
        "required": ["formato", "versione", "motore", "ok"],
        "properties": {
            "formato": {"const": FORMATO_ESITO},
            "versione": {"const": VERSIONE_ESITO, "description": "Versione del formato dell'esito."},
            "motore": {"type": "string", "description": "Versione di cersim che ha calcolato."},
            "contratto": {"type": "integer", "description": "Versione del contratto dei messaggi con il sito."},
            "calcolato_il": {"type": "string", "format": "date"},
            "progetto": {
                "type": "object", "description": "Riassunto del progetto analizzato.",
                "properties": {"nome": {"type": "string"}, "tipo": {"enum": ["CER", "gruppo"]},
                               "membri": {"type": "integer"}, "contatori": {"type": "integer"},
                               "impianti": {"type": "integer"}},
            },
            "ok": {"type": "boolean", "description": "true se l'analisi è completa. Con false si legge `errore` oppure "
                                                     "`non_supportati`."},
            "errore": {"type": "string", "description": "Perché l'analisi non si è fatta (dati non validi, riparto "
                                                        "mancante, bilanci incoerenti)."},
            "non_supportati": {**_TESTI, "description": "Casi che il motore non sa calcolare: con questi ok è false."},
            "da_verificare": {**_TESTI, "description": "Requisiti che il motore non può controllare dai dati."},
            "economia_disabilitata": {"type": ["string", "null"], "description": "Se c'è, l'analisi economica è "
                                      "spenta (per esempio parametri normativi scaduti) e restano i soli dati di energia."},
            "qualita": {"type": "object", "description": "Qualità complessiva dei dati: A (misure e PVGIS), B, C "
                        "(stime).", "properties": {"lettera": {"enum": ["A", "B", "C"]}, "testo": {"type": "string"},
                                                   "tono": {"type": "string"}, "spiegazione": {"type": "string"}}},
            "fonti_pv": {**_TESTI, "description": "Da dove viene la produzione: \"PVGIS\" o \"sintetico\" (modello "
                                                  "semplificato, qualità C)."},
            "fonti_prezzi": _TESTI,
            "impianti": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"},
                                                                                       "nome": {"type": "string"}}}},
            "bande": {"type": "object", "additionalProperties": _BANDA,
                      "description": "Indicatori principali come intervalli sugli scenari, per nome."},
            "cifre": {"type": "array", "description": "Le cifre principali, con unità e spiegazione.", "items": {
                "type": "object", "required": ["voce", "valore", "unita"],
                "properties": {"voce": {"type": "string"}, "valore": _NUMERO, "minimo": _NUMERO, "massimo": _NUMERO,
                               "unita": {"type": "string"}, "significato": {"type": "string"}}}},
            "per_membro": {"type": "array", "description": "Beneficio netto all'anno per membro, in €.", "items": {
                "type": "object", "properties": {"membro": {"type": "string"}, "netto": _NUMERO}}},
            "requisiti": {"type": "array", "description": "Requisiti normativi e il loro stato.", "items": {
                "type": "object", "properties": {"nome": {"type": "string"}, "stato": {"type": "string"},
                                                 "tono": {"type": "string"}, "motivo": {"type": "string"}}}},
            "avvertenze": {**_TESTI, "description": "Avvertenze da leggere insieme ai numeri."},
            "precisione": {"type": "object", "description": "Che cosa migliorare per un risultato più preciso.",
                           "properties": {"frase": {"type": "string"}, "voci": {"type": "array"}}},
            "sensibilita": {"type": "object", "description": "VAN della configurazione al variare dei parametri."},
            "cassa": {**_TABELLA, "description": "Cassa cumulata per anno."},
            "chi_riceve": {"type": "object", "description": "Chi riceve che cosa nell'anno rappresentativo."},
            "confronto": {"type": "object", "description": "Confronto con lo stesso impianto senza configurazione."},
            "frase": {"type": "array", "description": _PRESENTAZIONE},
            "nota_intervalli": {"type": "string", "description": _PRESENTAZIONE},
            "giorno_tipo": {"type": "object", "description": _PRESENTAZIONE},
            "mensile": {**_TABELLA, "description": _PRESENTAZIONE},
            "colori": {"type": "object", "description": _PRESENTAZIONE},
        },
    }


def esito(risultato: dict, config: Configuration | None = None, oggi: date | None = None) -> dict:
    """L'esito con l'intestazione, dal risultato di `web.risultati` e dalla configurazione analizzata."""
    testa: dict = {"formato": FORMATO_ESITO, "versione": VERSIONE_ESITO, "motore": __version__,
                   "calcolato_il": (oggi or date.today()).isoformat()}
    if config is not None:
        testa["progetto"] = {"nome": config.nome, "tipo": config.tipo.value, "membri": len(config.members),
                             "contatori": len(config.connection_points), "impianti": len(config.plants)}
    return testa | copy.deepcopy(risultato)


def schemi() -> dict[str, dict]:
    return {NOME_PROGETTO: schema_progetto(), NOME_ESITO: schema_esito()}


def testo(schema: dict) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":  # python -m cersim.schema: riscrive i file degli schemi
    CARTELLA.mkdir(exist_ok=True)
    for nome, schema in schemi().items():
        (CARTELLA / nome).write_text(testo(schema), encoding="utf-8", newline="\n")
        print(f"Scritto cersim/schemi/{nome}")
