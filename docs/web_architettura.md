# Interfaccia web: cersim nel browser con Pyodide

La CER passa dall'app Streamlit a un'interfaccia web con lo stesso stack e lo stesso stile del simulatore della
casa. Il motore resta `cersim`, lo stesso pacchetto Python dei test, e gira **nel browser** con
[Pyodide](https://pyodide.org) dentro un Web Worker. Tutto è gratuito: un sito statico su Cloudflare Pages,
pubblicato da GitHub, più un piccolo Worker di Cloudflare che fa da intermediario verso PVGIS. Non ci sono server
Python né servizi a pagamento. L'app Streamlit resta funzionante finché la nuova interfaccia non la sostituisce.

## 1. Prova di fattibilità (28/10/2026)

**Esito: il motore gira in Pyodide senza modifiche.** Ho simulato il caso di Torino di
`esempi/caso_studio_torino.py` (come CER: 14 contatori, 20 kWp, 3 anni meteo, 25 anni di progetto, banda di scenari
e sensibilità). Le bande escono **identiche a CPython**, al centesimo: energia condivisa da 15.890,3 a 17.095,03 kWh,
mediana 16.344,76 kWh; tariffa premio da 2.065,74 a 2.222,35 € all'anno. Anche il report PDF e quello Excel si
generano in Pyodide.

- Pyodide **314.0.7** (Python 3.14.2, pubblicato il 14/09/2026), fissato in `web/package.json`. Pacchetti di Pyodide:
  numpy 2.4.6, pandas 3.0.2, pydantic 2.12.5, pyyaml 6.0.3, tzdata 2025.3, requests 2.33.1. Per i report:
  matplotlib, Pillow e fonttools da Pyodide, fpdf2 e openpyxl (puro Python) da PyPI con `micropip`.
- Come rifarla: `cd web && npm install && npm run prova:pyodide`. Lo script (`web/prova/prova_pyodide.mjs`) gira in
  Node e prende le serie PVGIS dalla cache locale di cersim (`~/.cache/cersim/pvgis`). Una serie che manca diventa
  il profilo semplificato, come quando PVGIS non risponde. Per il primo caricamento a freddo va cancellata prima la
  cartella `web/node_modules/.pyodide-pacchetti`.

### Tempi

| Fase | Node, a freddo (due prove) | Browser (pannello Chromium, primo avvio) | CPython 3.12 |
|---|---|---|---|
| Avvio di Python | 2,7–4,4 s | | |
| Pacchetti del motore | 3,4–5,0 s | | |
| Import di cersim (315 kB di sorgenti) | 7,6–11,9 s | | 3,0 s |
| Motore pronto, in tutto | 14–21 s | **11 s** | |
| Prima analisi di Torino | 11,7–18,5 s | **6,9 s** | 5,7 s |
| Analisi successive | 9,6–13,6 s | 6,9–10,4 s | 5,0 s |
| Report PDF ed Excel (pacchetti compresi) | 4,6 s + 17,6 s | non provato | |

Pyodide è più lento di CPython: circa 1,2 volte nel browser, da 2 a 3 volte in Node. Conta l'esperienza:
- al primo accesso il motore è pronto in circa 11 secondi, mentre si compilano i passi 1–4, perché si carica subito
  in sottofondo;
- un'analisi completa dura 7–10 secondi, senza bloccare la pagina, perché gira nel Worker.

### Peso

| Cosa | Non compresso | Compresso (gzip) |
|---|---|---|
| Nucleo di Pyodide (`pyodide.asm.wasm`, `python_stdlib.zip`, JS, lock) | 13,5 MB | circa 7,5 MB |
| Pacchetti del motore (numpy, pandas, pydantic e dipendenze) | 9,4 MB | sono già ruote compresse |
| Sorgenti di cersim (`motore/cersim.json`) | 329 kB | 96 kB |
| Solo per i report: matplotlib, Pillow, fonttools, fpdf2, openpyxl | 8,6 MB | |
| Interfaccia (JS, CSS, font) | 0,3 MB | 0,1 MB |

Nel browser il primo avvio ha trasferito **16,8 MB**. Le visite successive usano la cache del browser: gli indirizzi
di Pyodide contengono la versione e non cambiano. La memoria di WebAssembly arriva a 280–340 MB: va bene su un
portatile, che è lo strumento d'uso (PRODUCT.md), meno su un telefono economico.

### Che cosa non gira e l'alternativa

| Parte | Problema in Pyodide | Alternativa |
|---|---|---|
| `requests.get` (PVGIS in `pv.py`, geocodifica in `geo.py`, edifici in `tetto.py`) | Python nel browser non apre connessioni; PVGIS, inoltre, non manda le intestazioni CORS | Le richieste le fa il JavaScript, tramite l'intermediario. Python riceve i dati già scaricati (`cersim/web.py` per PVGIS; geocodifica e tetto alle tappe 3 e 4). `requests` serve solo perché quei moduli lo importano: si può togliere rendendo l'import pigro (0,4 MB in meno) |
| Cache PVGIS su disco (`pv.py`) | Il file system di Pyodide è in memoria e si perde a ogni visita | Cache nel browser (Cache Storage) e cache dell'intermediario, vedi sotto |
| Report PDF ed Excel | Funzionano, ma costano 8,6 MB e una ventina di secondi | Caricarli solo quando si chiede il report |
| Streamlit (`app.py`) | Non serve: è l'interfaccia che si sostituisce | |

## 2. Struttura

```
comunita-energetica-cer/
  cersim/            motore Python (invariato), più cersim/web.py: ingresso per il browser
  tests/             pytest, anche per cersim/web.py (tests/test_web.py)
  app.py             app Streamlit attuale, finché serve
  web/               interfaccia web
    package.json     React 18.3.1, Vite 5.4.21, TypeScript 5.6.3, lucide-react 0.453.0, @fontsource/poppins 5.1.0, pyodide 314.0.7
    vite.config.ts   plugin "motore-cersim": impacchetta cersim/*.py e i dati YAML in motore/cersim.json
    prova/           prova di fattibilità in Node
    scripts/         sincronizza_stile.mjs: copia lo stile di Casa
    public/esempi/   torino.json, salvataggio del caso di Torino
    src/
      App.tsx        barra laterale con i 5 passi, intestazione con esempio, importa, esporta e nuovo; bozza e controllo
      bozza.ts       bozza in localStorage, nome del file di salvataggio, file in base64 per il motore
      passi/         Luogo.tsx, Membri.tsx, campi.tsx (numeri all'italiana, scelte), Passi.tsx (Impianti ed
                     Economia, da costruire), Risultati.tsx
      scheda/        la pagina del link per le famiglie (?modulo=famiglia): SchedaFamiglia.tsx, scheda.ts,
                     testi.json (scritto da python -m cersim.web)
      motore/        contratto.ts, worker.ts (Pyodide), client.ts (lato pagina), pvgis.ts (adattatore),
                     indirizzo.ts (ricerca dell'indirizzo tramite l'intermediario)
      stile/         casa.css (copia di Casa, non modificarla), cer.css (aggiunte della CER)
```

I sorgenti di cersim non si duplicano. Vite li legge dalla cartella `cersim/` del repository e li serve come un solo
JSON (`motore/cersim.json`), che il Worker scrive nel file system di Pyodide. Una modifica al motore vale quindi
subito per i test, per l'app Streamlit e per il sito.

`web/` si avvia con `npm install` e poi `npm run dev` (porta 5173, o quella indicata con `-- --port`).

## 3. Il motore nel Web Worker

Il Worker (`web/src/motore/worker.ts`) carica Pyodide dalla CDN jsDelivr, con l'indirizzo fissato alla versione
del pacchetto npm. Poi carica i pacchetti e i sorgenti, e importa `cersim.web`. La pagina parla con il Worker solo
per messaggi (`web/src/motore/contratto.ts`). Il progetto viaggia come testo: è il file di salvataggio del lavoro di
oggi (`ui_model.esporta_json`, `{"schema": 1, "configurazione": …, "parametri": …}`), quindi il sito legge anche i
lavori salvati dall'app Streamlit.

| Dalla pagina | Risposta del Worker | Che cosa fa |
|---|---|---|
| `{tipo: "avvia", sorgenti}` | `{tipo: "stato", fase}` più volte, poi `{tipo: "pronto", avvio}` | carica Python, pacchetti e cersim, una volta sola; `avvio` contiene versioni, tempi e MB scaricati |
| `{tipo: "richieste", id, progetto}` | `{tipo: "richieste", id, richieste}` | `cersim.web.richieste_pvgis`: le serie PVGIS che servono, `{chiave, parametri}` |
| `{tipo: "analizza", id, progetto, serie}` | `{tipo: "risultato", id, risultato, secondi}` | `cersim.web.analizza_web` con le serie scaricate (chiave → risposta di PVGIS) |
| `{tipo: "chiama", id, funzione, argomenti}` | `{tipo: "valore", id, valore}` | `cersim.web.chiama`: una delle `FUNZIONI` dei passi, con gli argomenti per nome in JSON (sotto) |
| `{tipo: "prepara_report", id}` | `{tipo: "report_pronto", id}` | carica i pacchetti dei report PDF ed Excel, una volta sola (sezione "I risultati e i report") |
| | `{tipo: "errore", id?, messaggio}` | errore del motore; i dati sbagliati, invece, tornano in `risultato.errore` |

Il risultato (versione del contratto 1) contiene:
- `ok`, `qualita` (A, B o C) e `fonti_pv`;
- le bande (minimo, mediana, massimo) di energia condivisa, tariffa premio, valorizzazione ARERA e VAN;
- i KPI dello scenario base;
- gli avvisi e i requisiti non supportati o da verificare.

Tutto è JSON semplice, senza oggetti Python. Una modifica che cambia il significato di un campo alza `CONTRATTO` in
`cersim/web.py`.

Il calcolo ha due tempi perché Python nel browser non può fare richieste di rete:
1. il motore dice quali serie gli servono;
2. la pagina le scarica;
3. il motore calcola.

Una serie che non arriva non blocca il calcolo: si usa il profilo semplificato e la qualità scende a C, come oggi
quando PVGIS non risponde.

### La bozza dei passi 1 e 2

Il sito tiene il lavoro in una **bozza** con le stesse tabelle dell'app Streamlit (`cersim.ui_model`), così la
logica resta in Python e non si riscrive in TypeScript (`Tabelle` in `contratto.ts`):
- `generale`: nome, tipo (`gruppo` o `CER`), indirizzo, coordinate, regione, data di costituzione;
- `punti`: una riga per contatore, con chiavi brevi (`punto`, `membro`, `tipo_soggetto`, `tipologia`, `kwh_annui`,
  `f1_kwh`, `f23_kwh`, `area`, `tensione`; `cersim.web.CAMPI_PUNTO`);
- `impianti`: le righe con le colonne di `ui_model`, dalla proposta o scritte a mano al passo 3;
- `curve`: per contatore, la curva oraria (`CurvaMisurata`) con la descrizione;
- `parametri` e `base`, il lavoro ricaricato, da cui si riprendono i campi che le tabelle non mostrano.

Le funzioni che il Worker chiama per nome (`cersim.web.FUNZIONI`):

| Funzione | Che cosa fa |
|---|---|
| `costanti()` | regioni, tipi di soggetto, tipologie e tensioni per i campi a scelta, consumo della famiglia tipo |
| `famiglie(n, inizio)` | righe di famiglie tipo (`ui_model.famiglie_tipo`) |
| `regione(nome)` | il nome della regione di cersim da come lo scrive OpenStreetMap (`geo.normalizza_regione`) |
| `progetto_da_tabelle(tabelle)` | il salvataggio (`configurazione_da_tabelle` ed `esporta_json`) con il riepilogo, oppure gli errori del passo 1 (`errori_luogo`) e delle tabelle (`errori`) |
| `tabelle_da_progetto(progetto)` | la bozza da un file salvato, anche dall'app Streamlit (`importa_json`, `tabelle_da_configurazione`) |
| `leggi_consumi(file)` | la curva oraria dai file del distributore o da un file `curva-consumi` del simulatore della casa, con gli avvisi |
| `leggi_schede(file, tabelle)` | le schede dei consumi ricevute dalle famiglie, unite alla tabella dei contatori (`guida.leggi_scheda`, `guida.unisci_schede`) |
| `costanti_impianti()` | forme del tetto, inclinazioni, m² per kWp, livelli di ombre, colonne della tabella degli impianti, foto aerea, termine della tariffa premio |
| `entrata_prevista(data_costituzione)` | l'entrata in esercizio proposta (`proposta.entrata_predefinita`) |
| `tetto(angoli, forma, piani, inclinazione, edifici)` | superficie, orientamento e, con gli edifici di OpenStreetMap, ombre e pianta del tetto disegnato (`tetto.tetto_disegnato`) |
| `richieste_proposta(tabelle, scelta)` | le serie PVGIS che servono alla proposta, come `richieste_pvgis` |
| `proposta(tabelle, scelta, serie)` | tre taglie commentate (`proposta.proponi`), la curva delle taglie provate e, per ogni taglia, la tabella degli impianti che ne esce |
| `costanti_economia(tipo)` | i valori predefiniti del passo 4 (`normativa.assunzioni_economiche`), mostrati come segnaposto |
| `leggi_prezzi(file, regione)` | i prezzi orari dai CSV dell'utente, uno per anno, per la zona della regione (`prices.prezzi_da_csv`) |
| `risultati(progetto, serie, prezzi)` | l'analisi del passo 5 (`analisi.analizza`) con testi, cifre, tabelle e dati dei grafici di `cersim.report`; resta in memoria |
| `dimensionamento(impianto)` | la curva del beneficio per diverse taglie, dall'analisi in memoria (`sizing.dimensiona`) |
| `report(formato)` | il report PDF o il file Excel dell'analisi in memoria (`report.report_pdf`, `report_excel`), in base64 |
| `scheda_pdf(configurazione, link)` | la scheda dei consumi da stampare per le famiglie (`report.scheda_famiglia_pdf`), in base64 |

### La scheda dei consumi per le famiglie

Al passo 2 chi coordina copia un link (`?modulo=famiglia&per=<nome della configurazione>`) e lo gira a famiglie e
attività. Il link apre una pagina a parte (`web/src/scheda/`), con che cosa serve, i propri consumi e un pulsante
che scarica un piccolo file JSON da rimandare: lo stesso formato `cersim-scheda-consumi` dell'app Streamlit.
Chi coordina carica le schede ricevute al passo 2 e la tabella si compila da sola.

La pagina è **leggera**: si apre subito, anche da telefono, e non avvia il motore Python, che costerebbe 17 MB e
qualche decina di secondi a chi scrive solo il consumo annuo. Il motore parte solo se si allegano i consumi ora per
ora, perché la forma media si ricava in Python (`leggi_consumi`). Per questo:
- testi, scelte e soglie della scheda stanno in `web/src/scheda/testi.json`, scritto da `python -m cersim.web`
  (dalla radice del progetto) a partire da `cersim.guida`; `tests/test_web.py` fallisce se il file non è più uguale;
- i controlli semplici (`guida.controlla`) sono ripetuti in `web/src/scheda/scheda.ts`, con gli stessi messaggi;
- quando chi coordina carica la scheda, il motore la ricontrolla tutta (`leggi_schede`).

La scheda da stampare in PDF (`report.scheda_famiglia_pdf`) la chiede chi coordina al passo 2 (`scheda_pdf`): usa i
pacchetti dei report, caricati la prima volta come al passo 5.

A ogni modifica la pagina salva la bozza nel `localStorage` del browser e, 0,3 secondi dopo, chiede al motore
`progetto_da_tabelle`: gli errori compaiono accanto ai passi e il passo Risultati calcola il salvataggio che ne
esce. "Esporta" scarica lo stesso salvataggio; "Importa" e "Esempio di Torino" passano da `tabelle_da_progetto`.
Prima che il motore sia pronto (circa 11 secondi al primo accesso) si può già scrivere: i controlli arrivano appena
è pronto.

### I risultati e i report

Il passo 4 tiene nella bozza (`Tabelle.parametri`) il riparto, obbligatorio, e i valori avanzati: vuoti valgono le
assunzioni economiche, che compaiono come segnaposto. I prezzi orari caricati (`leggi_prezzi`) stanno nella bozza
(`Tabelle.prezzi`, i valori orari di ogni anno) e non nel salvataggio, come nell'app Streamlit: i dati del GME sono
solo per uso personale.

Il passo 5 chiede le serie PVGIS come prima, poi `risultati`, che fa l'analisi completa e la presenta come l'app
Streamlit: la frase in cima, la qualità con le fonti dei prezzi, le cifre con il loro intervallo, "Come rendere la
stima più precisa" con il passo da cui si correggono, il confronto senza configurazione, i requisiti, i grafici
(giorno tipo per ogni mese, mese per mese, flussi di cassa, sensibilità, curva delle taglie), chi paga e chi riceve,
le avvertenze. Testi e tabelle li scrive `cersim.report`, gli stessi del report PDF; i grafici sono SVG semplici
(`web/src/passi/grafici.tsx`), ognuno con la tabella dei valori sotto *Mostra i dati*. L'analisi resta in memoria
nel Worker: curva delle taglie e report non la rifanno.

I report chiedono pacchetti che Pyodide non ha, fpdf2 2.8.9 e openpyxl 3.1.5 con defusedxml ed et_xmlfile: sono
wheel puri, che `vite.config.ts` scarica una volta da PyPI in `web/.pacchetti/`, controlla con l'hash di PyPI e mette
nel sito, in `motore/pacchetti/`, insieme ai caratteri Geist di `static/`. Solo quando si chiede un report il Worker
carica matplotlib dalla CDN di Pyodide e installa quei wheel con micropip dal sito stesso.

Prova del 29/10/2026 con l'esempio di Torino e un anno di prezzi orari: analisi in 10,7 s nel browser, qualità B,
16.345 kWh condivisi; curva delle taglie in 26 s; report PDF in 7 s compresa la prima installazione dei pacchetti
(203 kB), Excel in 1 s.

## 4. Adattatore PVGIS e intermediario

`web/src/motore/pvgis.ts` definisce una `SorgentePvgis` sostituibile:

- **cache locale**, solo in sviluppo: Vite serve i file della cache di cersim su `/pvgis-locale/<chiave>`, con la
  chiave controllata da un'espressione regolare, così non si esce dalla cartella;
- **intermediario**, quando c'è `VITE_PVGIS_INTERMEDIARIO` (nella build di produzione `./pvgis`, cioè lo stesso
  dominio del sito, da `web/.env.production`): `GET <intermediario>/seriescalc?<parametri>`, con le
  risposte tenute nel browser (Cache Storage `cersim-pvgis-v1`, una voce per serie): a ogni ricalcolo dello stesso
  progetto non si rifanno le richieste;
- **nessuna**, in produzione senza intermediario: produzione stimata, qualità C.

L'intermediario è un Worker di Cloudflare in [intermediario/](../intermediario/README.md):
- accetta solo `GET /seriescalc` con i parametri che usa cersim: `lat`, `lon`, `peakpower`, `loss`, `angle`,
  `aspect`, `pvcalculation`, `startyear`, `endyear`, `outputformat`. Li controlla negli intervalli ammessi (Italia,
  1 kWp, anni 2021–2023, formato JSON), arrotonda le coordinate a 0,01° e li riscrive in forma canonica. Così non
  diventa un proxy aperto e richieste quasi uguali condividono la cache;
- inoltra a `https://re.jrc.ec.europa.eu/api/v5_3/seriescalc`. Sul dominio del sito risponde su
  `/pvgis/seriescalc`: il browser lo chiama dalla stessa origine, senza CORS. Su `workers.dev`, invece, mette
  `Access-Control-Allow-Origin` solo per le origini in `ORIGINI`. Le richieste da altre origini ricevono 403;
  quelle senza origine (stessa origine o curl) sono servite senza intestazioni CORS;
- risponde con ore e potenze, nella stessa forma della cache su disco di cersim, che `cersim.web` legge già: 177 kB
  invece degli 824 kB di PVGIS;
- tiene le risposte 90 giorni, la stessa scadenza della cache di cersim, così PVGIS riceve una sola richiesta per
  luogo, orientamento e anno. Le tiene in un **KV** se è collegato (gratuito: 1 GB, 1.000 scritture al giorno),
  altrimenti nella cache di Cloudflare (`caches.default`), che però funziona solo con un dominio personalizzato e
  non su `workers.dev`. Le risposte sbagliate non si tengono.

  Con un dominio proprio basta la cache di Cloudflare, con due limiti rispetto al KV. Primo, è separata per
  data center: la prima richiesta da ciascuno arriva fino a PVGIS. Secondo, Cloudflare può togliere prima dei
  90 giorni le risposte usate di rado. Per questo progetto va bene, perché ogni browser tiene già le sue serie;
- non registra le richieste.

Prova del 29/10/2026, con l'intermediario in locale (`npm run locale`, lo stesso codice in Node) e il sito in
sviluppo:
- le 3 serie del caso di Torino sono arrivate da PVGIS vero con le stesse bande della cache locale;
- PVGIS ha risposto in 1,3 s, la cache dell'intermediario in 4 ms;
- un secondo calcolo non ha fatto richieste: le serie erano in Cache Storage.

La build per Cloudflare (`cf deploy --dry-run`) pesa 6,2 KiB. Il Worker non è ancora pubblicato.

Il piano gratuito dei Workers basta: 100.000 richieste al giorno, e un'analisi ne fa al massimo 3 per orientamento.
Lo stesso Worker inoltra la ricerca dell'indirizzo (sotto). Gli edifici vicini al tetto, invece, il browser li chiede
direttamente a Overpass (sezione "Il tetto").

### Ricerca dell'indirizzo

Il passo 1 cerca l'indirizzo con **Nominatim** di OpenStreetMap, attraverso lo stesso Worker
(`intermediario/src/indirizzo.ts`, `web/src/motore/indirizzo.ts`):
- `GET /geo/cerca?q=<indirizzo>`, uguale su `workers.dev` e sul dominio del sito (route `cer.<dominio>/geo/*`). Il
  sito ricava l'indirizzo da `VITE_PVGIS_INTERMEDIARIO`: con `./pvgis` cerca su `./geo/cerca`;
- accetta solo il parametro `q`, da 3 a 200 caratteri, e inoltra con `countrycodes=it`, al massimo 5 risultati e
  uno User-Agent con il nome del progetto e l'indirizzo del sito, come chiede la policy di Nominatim;
- risponde con descrizione, coordinate, regione e comune dei luoghi in Italia, e la licenza dei dati (© OpenStreetMap
  contributors, ODbL), che il sito mostra accanto al risultato. La regione la riconduce ai nomi di cersim il motore
  (`regione`);
- tiene le risposte 30 giorni, nella stessa cache delle serie PVGIS; la chiave è il testo cercato in minuscolo;
- al massimo una richiesta al secondo a Nominatim da ogni istanza del Worker, con una coda di 5 secondi al massimo
  (poi risponde 429). Le istanze in data center diversi non si coordinano: va bene finché le ricerche sono poche.
  Con molto traffico servirebbe un Durable Object o un servizio di geocodifica a pagamento;
- il sito cerca solo quando si preme Cerca (niente completamento automatico, vietato da Nominatim). Senza
  intermediario, in sviluppo, la ricerca è spenta e la posizione si scrive a mano.

Prova del 29/10/2026 con l'intermediario locale: "Piazza Castello, Torino" → Piazza Castello, Torino, Piemonte,
45,0711 e 7,6871.

### Il tetto: foto aerea ed edifici vicini

Il passo 3 fa come l'app Streamlit (`app.py`, `_proposta_impianto`):
- la **foto aerea** è quella di Esri (`tetto.FOTO_AEREA_URL`), mostrata con Leaflet 1.9.4
  (`web/src/passi/MappaTetto.tsx`), che si scarica solo quando si preme *Apri la foto aerea*. Il tetto si disegna con
  un clic per angolo; superficie e orientamento li calcola il motore (`tetto`). Senza mouse si scrivono a mano;
- gli **edifici vicini** per le ombre il browser li chiede **direttamente** a Overpass di OpenStreetMap
  (`web/src/motore/edifici.ts`), con la stessa domanda di cersim (edifici entro 150 m dal centro del tetto,
  arrotondato a 0,0001°, circa 10 m). Overpass manda le intestazioni CORS e una POST di modulo non chiede il permesso
  preliminare. Prova tre server pubblici uno dopo l'altro, 80 secondi al massimo per server e 90 in tutto (il
  29/10 overpass-api.de ha risposto dopo 33–55 s anche a domande piccole: è la coda); intanto la pagina resta
  usabile. Se nessuno risponde, la pagina lo dice e le ombre si scelgono a mano. La risposta va al motore (`tetto`).

  All'inizio la domanda passava dall'intermediario, come la ricerca dell'indirizzo, ma dal vivo non è mai arrivata
  (504 dopo 58 s, due volte), mentre dal computer di sviluppo lo stesso server rispondeva in 33–40 s. Overpass divide
  i posti in coda per indirizzo IP, e quelli dei Worker di Cloudflare sono condivisi da moltissimi siti: dal browser
  ogni persona usa i propri, come faceva il server dell'app Streamlit;
- la **proposta** ha i due tempi dell'analisi: `richieste_proposta`, poi la pagina scarica le serie PVGIS e
  `proposta` prova diverse taglie su 3 anni meteo e 3 livelli di prezzo. "Usa questa taglia" mette nella bozza la
  tabella degli impianti che ne esce; nella comunità energetica il disegno si azzera per il tetto successivo, e la
  proposta dopo tiene conto degli impianti già scelti.

Prova del 29/10/2026 con l'intermediario locale e l'esempio di Torino:
- disegno di 177 m² in pianta, 66 m² utili, circa 12 kWp;
- Overpass ha risposto in 33 s (il 29/10 i server pubblici erano molto carichi: anche 40 s, con gli altri due
  server muti);
- proposta: Prudente 8,6 kWp, Intermedia 10,3 kWp, Consigliata 12 kWp. Con le serie già in cache, 20,5 s nel
  browser contro 18 s in CPython;
- con la taglia consigliata il passo Risultati ha calcolato 12.455 kWh condivisi all'anno.

## 5. Privacy

- **I dati dei contatori restano nel browser.** Consumi, curve misurate o calcolate, membri e impianti si elaborano
  nel Worker e non vanno a nessun server. Il lavoro si salva come file JSON scaricato, come oggi; la bozza resta
  nel `localStorage` di quel browser, finché non si preme "Nuovo" o si cancellano i dati del sito.
- **Che cosa esce:**
  - verso PVGIS, tramite l'intermediario, le coordinate arrotondate a 0,01° (circa 1 km), l'orientamento e le perdite
    dell'impianto, come fa già l'app Streamlit;
  - verso Nominatim, tramite l'intermediario e solo quando si preme Cerca, il testo dell'indirizzo. L'intermediario
    tiene la risposta 30 giorni, senza sapere chi l'ha chiesta;
  - verso Esri, quando si apre la foto aerea, le richieste delle immagini della zona che si guarda, direttamente dal
    browser, come nell'app Streamlit;
  - verso Overpass, direttamente dal browser e solo quando si preme *Stima le ombre*, il centro del tetto
    arrotondato a circa 10 m, con l'indirizzo IP di chi usa il sito. Il disegno del tetto resta nel browser.
- **CDN:** il primo caricamento scarica Pyodide e i pacchetti da cdn.jsdelivr.net, che vede l'indirizzo IP ma nessun
  dato del progetto. Se si vuole evitarlo, i file si possono servire da Pages: nessun file supera il limite di 25 MiB
  (`pyodide.asm.wasm` pesa 9,6 MB), ma servono un passo di copia nella build e il controllo del numero di file.
- Niente cookie, niente statistiche di visita, niente account.

## 6. Pubblicazione gratuita

### Dominio (consigliato)

Un dominio tuo, per esempio `tuonome.it`, con un sottodominio per progetto:

| Indirizzo | Cosa c'è |
|---|---|
| `tuonome.it` | il portale generale dei tuoi progetti |
| `casa.tuonome.it` | il simulatore della casa |
| `cer.tuonome.it` | il sito della CER: file statici del Worker `cer-sito` |
| `cer.tuonome.it/pvgis/*` e `/geo/*` | l'intermediario: PVGIS e ricerca dell'indirizzo, nello stesso Worker |

**Casa e CER sotto un titolo comune** (deciso il 29/10/2026). Il dominio scelto è `raccasamuele.it`, che sarà il
portale generale dei progetti. Casa e CER, che trattano lo stesso tema, stanno sotto un titolo comune, con lo stesso
stile e una navigazione comune che porta dall'uno all'altro. Restano due siti, su `casa.` e `cer.`, in due
repository: Casa resta leggera e Pyodide si scarica solo entrando nella CER. Il ponte dei consumi passa per il
file `curva-consumi` (Casa lo esporta, la CER lo carica al passo 2); più avanti potrà diventare un pulsante "Porta
nella CER" che apre `cer.` e passa la curva senza file. Il titolo comune e la barra di navigazione sono da fare.

Così il sito e l'intermediario hanno la stessa origine (niente CORS), la cache di Cloudflare funziona (niente
KV) e gli indirizzi sono più credibili di `….pages.dev`. Passi, nell'ordine:

1. **Comprare il dominio** (circa 10–15 € all'anno). Lo compri tu: da Cloudflare, se vende quell'estensione, o
   da un altro venditore, per esempio Aruba o Register.it.
2. **Aggiungerlo a Cloudflare** come zona, nel piano gratuito. Se è comprato altrove, si cambiano i nameserver
   presso il venditore con quelli che indica Cloudflare. L'attivazione richiede da qualche minuto a un giorno.
3. **Sito e intermediario insieme:** `npm run build` in `web/`, poi `SITO=cer.tuonome.it npm run deploy` in
   `intermediario/` ([intermediario/README.md](../intermediario/README.md)). Si pubblica un solo Worker con i file
   del sito (*static assets*) sul dominio personalizzato `cer.tuonome.it`: Cloudflare crea record DNS e
   certificato. Le richieste a `/pvgis/…` e `/geo/…` vanno al codice, tutte le altre ai file. `cf` non pubblica
   i progetti Pages "classici" e indica questa strada, la nuova Pages su Workers.
4. **Fatto il 29/10/2026** per `raccasamuele.it`: zona attiva, Worker `cer-sito` su `cer.raccasamuele.it`
   (commit `b73746c`). Gli aggiornamenti per ora si pubblicano a mano, ripetendo il passo 3 su un commit.
5. **Indirizzo di contatto**, facoltativo: con l'inoltro email gratuito di Cloudflare (Email Routing) un
   indirizzo come `cer@tuonome.it` arriva alla tua casella. Con la licenza MIT (dal 24/11/2026) non servono più
   licenze commerciali.
6. **Casa** va su `casa.tuonome.it` allo stesso modo: un Worker con i suoi file statici.

### Sito e intermediario

- **Sito:** il repository GitHub è collegato a Cloudflare Pages. Impostazioni della build:
  - cartella radice `web`;
  - comando `npm ci && npm run build`;
  - cartella di uscita `dist`.

  Il plugin di Vite legge `../cersim`, che Pages ha perché clona tutto il repository. Ogni push su `main` pubblica,
  ogni ramo ha un'anteprima. Il piano gratuito ha 500 build al mese, 20.000 file e 25 MiB per file.
- **Variabili della build:**
  - `VITE_PVGIS_INTERMEDIARIO`: indirizzo del Worker. Con il dominio non serve: la build usa `./pvgis`
    (`web/.env.production`);
- **Intermediario:** il Worker di `intermediario/`, nel piano gratuito, pubblicato con la CLI `cf` e la
  configurazione `cloudflare.config.ts` (non Wrangler). I passi sono in
  [intermediario/README.md](../intermediario/README.md): accesso, KV facoltativo, `ORIGINI` con l'indirizzo del
  sito, `npm run deploy`. Nulla è ancora pubblicato.
- I test sono tre:
  - `pytest` per il motore;
  - `npm run typecheck` e `npm run build` per il sito;
  - `npm test` e `npm run typecheck` per l'intermediario.

  Si possono aggiungere al workflow `.github/workflows/tests.yml`.

## 7. Licenza

Dal 24/11/2026 il codice è **open source con licenza [MIT](../LICENSE)**, come Casa; i componenti e i dati di terzi
sono elencati in [LICENZA.md](../LICENZA.md). Fino al 29/10/2026 era AGPL-3.0, poi PolyForm Strict 1.0.0 con un
permesso aggiuntivo per il sito ufficiale.

- Chiunque può usare, modificare e ridistribuire il codice, anche per scopi commerciali, conservando l'avviso di
  copyright. Con Pyodide i sorgenti di cersim arrivano comunque nel browser (`motore/cersim.json`).
- Il piede del sito mostra il copyright e il link a licenza e crediti (`licenza.txt`), che la build genera da
  `LICENZA.md` e `LICENSE`. I `package.json` dichiarano `"license": "MIT"`.
- I componenti di terzi sono compatibili con la MIT e sono elencati in LICENZA.md: Pyodide (MPL-2.0), i pacchetti
  Python (BSD, MIT, Apache-2.0, LGPL per fpdf2), il font Poppins (OFL), le icone Lucide (ISC). Il sito serve anche,
  senza modificarli, i wheel di fpdf2 (LGPL-3.0), openpyxl ed et_xmlfile (MIT), defusedxml (PSF), i caratteri Geist
  (OFL) e la libreria Leaflet (BSD-2) della mappa del passo 3.
- La licenza del codice non cambia le condizioni dei dati: PVGIS con la fonte citata, OpenStreetMap con
  l'attribuzione ODbL, la foto aerea secondo i termini di Esri, i prezzi del GME solo per uso privato.

## 8. Stile comune con Casa

`web/src/stile/casa.css` è una copia **identica** di `src/styles.css` del simulatore della casa: token, tema
chiaro e scuro, barra laterale, card, KPI, campi, tabelle. Le aggiunte della CER (i ruoli dei grafici dell'energia,
pochi elementi) stanno in `cer.css`. Quando Casa cambia i token:

```
npm run sincronizza-stile -- "<cartella del progetto Casa>"
```

Poi si controllano contrasti e pagine. Più avanti i token comuni potranno stare in un pacchetto condiviso tra i due
progetti. Le regole di stile sono in [DESIGN.md](../DESIGN.md).

## 9. Tappe successive

1. ~~Prova di fattibilità, architettura, scheletro di `web/`~~ (28/10/2026).
2. ~~Intermediario PVGIS su Cloudflare Workers, con cache e test; Cache Storage nel browser; collegamento al
   sito~~ (29/10/2026). Resta la pubblicazione, insieme al sito.
3. ~~Passi 1 e 2: luogo con la ricerca dell'indirizzo (Nominatim tramite l'intermediario), tabella dei contatori,
   famiglie tipo, consumi ora per ora dai file del distributore e dal simulatore della casa; bozza nel browser,
   importa ed esporta in JSON; Risultati calcolano la bozza~~ (29/10/2026). Provati nel browser con l'intermediario
   locale: ricerca vera, file `curva-consumi`, esportazione e reimportazione, Torino con le stesse bande. Lo stesso
   giorno la **scheda dei consumi per le famiglie**: il link, la pagina leggera e la raccolta delle schede al passo
   2. Il 24/11 la scheda da stampare in PDF. Resta:
   - il **titolo comune e la navigazione** tra Casa e CER (sezione 6).
4. ~~Passo 3: tetto dalla foto aerea, ombre dagli edifici vicini (Overpass, chiesto dal browser), proposta delle
   tre taglie e tabella degli impianti~~ (29/10/2026). La proposta di Torino impiega circa 20 s nel Worker.
5. ~~Passi 4 e 5: economia, risultati completi con grafici, requisiti e sensibilità, report PDF ed Excel con i
   pacchetti caricati a richiesta~~ (29/10/2026).
6. Revisione dell'accessibilità (WCAG 2.1 AA) e prova in proiezione; poi l'app Streamlit si ritira. Verifica axe-core
   del 24/11 e piano del ritiro in [chiusura_sito.md](chiusura_sito.md).

Miglioramenti possibili per i tempi:
- import pigro di `requests`;
- sorgenti precompilati (`.pyc` in uno zip) per accorciare l'import di cersim;
- il motore avviato già nella prima schermata, come fa già lo scheletro.
