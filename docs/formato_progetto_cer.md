# Formato del progetto CER e dell'esito

Due file JSON fanno da contratto tra il motore e chi lo usa da fuori: la riga di comando `cersim`, altri programmi e,
più avanti, un server MCP per gli agenti AI.

| | Che cos'è | Versione | Schema |
|---|---|---|---|
| **Progetto** (ingresso) | il file di salvataggio che esportano il sito e l'app | `"schema": 1` | [`cersim/schemi/progetto-cer.v1.schema.json`](../cersim/schemi/progetto-cer.v1.schema.json) |
| **Esito** (uscita) | il risultato dell'analisi, come al passo Risultati | `"formato": "esito-cer", "versione": 1` | [`cersim/schemi/esito-cer.v1.schema.json`](../cersim/schemi/esito-cer.v1.schema.json) |

Gli schemi seguono JSON Schema 2020-12. Si stampano con `cersim schema progetto` e `cersim schema esito`; i file in
`cersim/schemi/` si rigenerano con `python -m cersim.schema` e un test controlla che siano aggiornati.

## Il progetto

```json
{
  "schema": 1,
  "configurazione": {
    "nome": "Condominio Via Esempio 1, Torino", "tipo": "CER",
    "lat": 45.0703, "lon": 7.6869, "regione": "Piemonte",
    "members": [{"id": "Famiglia_1", "nome": "Famiglia 1", "tipo_soggetto": "persona_fisica"}, "…"],
    "connection_points": [{"id": "Famiglia_1", "titolare": "Famiglia_1", "tipologia_profilo": "domestico",
                           "kwh_annui": 1800, "area_convenzionale": "AC-ESEMPIO"}, "…"],
    "plants": [{"id": "FV_tetto", "nome": "FV sul tetto", "connection_point": "Condominio",
                "potenza_moduli_kwp": 30, "potenza_inverter_kw": 30, "investitore": "Condominio",
                "data_entrata_esercizio": "2027-06-01"}]
  },
  "parametri": {"quota_membri": 0.5}
}
```

Un esempio completo è [`web/public/esempi/torino.json`](../web/public/esempi/torino.json). Lo schema descrive ogni
campo in italiano; in breve:

- `configurazione`: tipo (`gruppo` o `CER`), luogo in Italia, membri, contatori e impianti. I contatori hanno i consumi
  in uno di questi modi, dal più preciso: `curva_misurata` (forma oraria, dai file del distributore o dal formato
  [curva-consumi](formato_curva_consumi.md)), `fasce`, `kwh_annui`, oppure niente (solo domestici: famiglia tipo ARERA).
- `parametri`: le scelte economiche. Serve almeno `quota_membri`: senza, l'analisi economica non parte, perché il
  motore non ha un riparto "consigliato". Dalla riga di comando si può dare con `--parametro quota_membri=0.5`.
- I prezzi orari del GME **non** stanno nel progetto (i dati sono per solo uso personale): si passano a parte con
  `--prezzi`, come nel sito restano nella bozza del browser.

Lo schema controlla la forma (tipi, intervalli, valori ammessi, campi sconosciuti). Le regole tra più campi le
controlla solo il motore: riferimenti tra membri, contatori e impianti, fasce che tornano con il consumo annuo,
regione riconosciuta, un impianto per contatore, edificio del gruppo. Per questo `cersim valida` è il controllo che fa
fede.

## L'esito

È lo stesso dizionario che il sito mostra al passo Risultati (`web.risultati`), con un'intestazione:

```json
{
  "formato": "esito-cer", "versione": 1, "motore": "0.2.0", "calcolato_il": "2026-11-24",
  "progetto": {"nome": "Condominio Via Esempio 1, Torino", "tipo": "CER", "membri": 14, "contatori": 14, "impianti": 1},
  "ok": true,
  "qualita": {"lettera": "B", "…": "…"},
  "cifre": [{"voce": "Energia condivisa all'anno", "valore": 17654.57, "minimo": 17220.58, "massimo": 18220.38,
             "unita": "kWh", "significato": "…"}, "…"],
  "per_membro": [{"membro": "Famiglia 1", "netto": 40.7}, "…"],
  "bande": {"…": {"minimo": 0, "mediana": 0, "massimo": 0}},
  "requisiti": ["…"], "da_verificare": ["…"], "avvertenze": ["…"]
}
```

- Con `"ok": false` c'è `errore` (dati non validi, riparto mancante, bilanci che non tornano) oppure `non_supportati`
  (casi che il motore non sa calcolare).
- **Campi stabili**: intestazione, `ok`, `errore`, `non_supportati`, `da_verificare`, `economia_disabilitata`,
  `qualita`, `fonti_pv`, `fonti_prezzi`, `impianti`, `bande`, `cifre`, `per_membro`, `requisiti`, `avvertenze`. Se uno
  di questi cambia in modo incompatibile, `versione` sale.
- **Campi di presentazione**: `frase`, `nota_intervalli`, `giorno_tipo`, `mensile`, `colori` (e la forma interna di
  `sensibilita`, `cassa`, `chi_riceve`, `confronto`, `precisione`) servono al sito e possono cambiare senza cambiare
  versione. Lo schema li elenca senza fissarne il contenuto.
- Gli euro sono valori reali; i minimi e massimi vengono dagli scenari di meteo e prezzi. È uno scenario preliminare,
  non uno studio di fattibilità.

## La riga di comando

```bash
cersim valida PROGETTO                    # 0 se il progetto si può calcolare, 1 altrimenti
cersim analizza PROGETTO [-o ESITO]       # esito-cer su standard output o nel file
        [--senza-rete] [--prezzi CSV …] [--parametro chiave=valore …] [--anni N]
cersim report PROGETTO -o scenario.pdf    # o .xlsx; stesse opzioni di analizza
cersim schema progetto|esito
```

`PROGETTO` può essere `-` per leggere dallo standard input. Le uscite JSON vanno su standard output, i messaggi per
le persone su standard error. Codici di uscita: 0 tutto bene, 1 dati non validi o analisi non riuscita, 2 comando
scritto male.

## Ipotesi di questa prima versione

Da confermare o cambiare prima di considerare il formato definitivo:

1. **Il progetto resta il salvataggio di oggi** (`"schema": 1`), senza un formato nuovo: così i file già esportati dal
   sito e dall'app funzionano subito. Le chiavi restano quelle del codice (`members`, `connection_points`, `plants`
   in inglese, il resto in italiano).
2. **L'esito ha una versione sua** (`esito-cer` 1), separata dal `contratto` dei messaggi con il sito, ed è lo stesso
   risultato del sito con l'intestazione: un solo formato per sito, riga di comando e futuro MCP.
3. **Stabili e di presentazione**: la divisione tra campi stabili e di presentazione dell'esito è una prima proposta.
4. **Indirizzo degli schemi**: il `$id` punta a `https://cer.raccasamuele.it/schemi/…`, ma i file non sono ancora
   pubblicati lì.
5. **PVGIS dalla riga di comando**: `analizza` scarica le serie da PVGIS con la cache locale (come l'app Streamlit) e,
   se la rete non risponde, usa il modello semplificato (qualità C) senza fermarsi; `--senza-rete` lo usa sempre.
6. **Il report PDF** cerca i caratteri Geist in `static/` accanto al pacchetto: funziona dalla copia del repository
   (anche installata con `pip install -e .`), non da un pacchetto installato altrove.
