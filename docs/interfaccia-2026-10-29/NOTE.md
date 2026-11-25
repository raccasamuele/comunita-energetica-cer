# Interfaccia CER nella famiglia Casa

29–30 ottobre 2026 · ramo `feat/interfaccia-come-casa` · modifiche lasciate nel working tree, senza commit o push.

## Cosa è cambiato

| Prima | Dopo |
| --- | --- |
| Importa, Esporta, Nuovo e badge sempre nella barra | Durante i passi resta solo il titolo. Importa ed Esempio di Torino sono nell'ingresso |
| Esporta nella barra | «Salva il progetto» nei Risultati e nel piede laterale, con freccia verso l'alto; formato e controlli del motore invariati |
| Nuovo sempre accessibile | «Torna all'inizio» richiede conferma e conserva la bozza; dall'ingresso si può riprenderla o sostituirla con un nuovo progetto |
| Scenario preliminare ripetuto nell'interfaccia | Nei Risultati due righe: «Dati» e «Modello», con spiegazione su richiesta |
| Suggerimenti dei campi e introduzioni sempre estesi | `InfoTip` e `Brief` di Casa, con testi completi raggiungibili dal (?) |
| Liste di controlli ripetute, alcune troncate | Gruppi con titolo e conteggio, frasi comuni mostrate una volta e nomi delle righe in chip; errori aperti con `role="alert"` |
| Icone al tratto per passi, sezioni e indicatori | Illustrazioni clay trasparenti, nella stessa palette e con lo stesso materiale di Casa |
| Scheda famiglia nello stesso caricamento dell'app completa | L'app CER è un modulo separato. La scheda non carica motore o Leaflet all'apertura o durante la normale compilazione |

`npm.cmd run sincronizza-stile` è stato eseguito. `web/src/stile/casa.css` è una copia identica allo stile di Casa, verificata con SHA-256 (`3744ca57c62d9c7023d355f54732f7c53f2371e70eb72c5de224ae08212baefd`). Le aggiunte della CER stanno esclusivamente in `cer.css`.

I (?) hanno nome accessibile, `aria-expanded`, `aria-controls`, chiusura con Esc, clic esterno o spostamento del focus. Esc riporta il focus al pulsante. Il pannello resta nel viewport e scorre internamente se necessario. L'ultima parola della prosa e il comando sono uniti senza a capo. I campi mantengono `aria-describedby` anche con la spiegazione chiusa. I (?) delle opzioni di configurazione sono esterni alle etichette dei radio: aprirli non cambia la scelta.

Gli avvisi di privacy restano visibili nei punti pertinenti, con dettagli nel (?). Resta anche la dicitura «Dati GME solo per uso personale». Nessun testo del motore o dei report è stato modificato. Nei gruppi non si tagliano più le liste a 3, 5, 8 o 12 voci. I requisiti sono suddivisi in «Non ammessi», «Da verificare» e «Coerenti con i dati»; i primi restano aperti.

I `.notice` seguono il comportamento di Casa: blocchi normali, flex solo quando è presente un'icona funzionale, icona non comprimibile e contenuto con `min-width: 0`. Le intestazioni delle tabelle conservano le parole intere; su telefono scorre il contenitore della tabella. Tema chiaro fisso e Poppins locale conservati.

## File

- `web/src/App.tsx`: ingresso, navigazione, barra essenziale, azioni nel piede, privacy breve.
- `web/src/main.tsx`: caricamento separato dell'app completa.
- `web/src/passi/{Luogo,Membri,Impianti,Economia,Risultati}.tsx`: spiegazioni, icone, controlli e riepiloghi.
- `web/src/passi/campi.tsx`: suggerimenti nel (?) e descrizioni accessibili per campi e select.
- `web/src/scheda/SchedaFamiglia.tsx`: stessa famiglia visiva, testi brevi e import del client di calcolo solo quando si allegano file orari, come funzionalità facoltativa già esistente.
- `web/src/ui/{info-tip,icons,issues}.tsx`: componenti condivisi dell'interfaccia.
- `web/src/stile/{casa,cer}.css`, `web/public/icons/` e questa cartella di documentazione.

`cersim/`, `tests/`, `app.py`, `intermediario/`, `web/src/motore/`, `web/package.json`, lockfile e `web/index.html` invariati. Nessuna nuova dipendenza di prodotto.

## Icone

**13 icone riusate da Casa**, ciascuna a 48 e 96 px: `casa`, `localita`, `bolletta`, `risultati`, `report`, `verifica`, `clima`, `costi`, `solare`, `crescita`, `sensibilita`, `nome`, `rapida`.

**8 icone generate con ImageGen** in una sola chiamata e un foglio unico: `comunita`, `contatore`, `tetto-mappa`, `condivisa`, `riparto`, `economia-comunita`, `scheda-famiglia`, `ombre`.

Il [prompt integrale](icone/PROMPT.md) usa il foglio di Casa come riferimento: clay morbido, viola `#6d28d9`, lavanda, acqua `#0b7a5e`, ambra e azzurro, luce dall'alto a sinistra, niente testo. Il risultato ha alpha trasparente. [prepara_icone.py](icone/prepara_icone.py) rimuove piccole componenti isolate, ritaglia, centra e riduce; non disegna soggetti. Il PNG originale generato resta nella cartella di ImageGen; l'hash è nel manifest.

| Risorse WebP trasparenti | File | Minimo | Massimo | Totale |
| --- | ---: | ---: | ---: | ---: |
| Riusate da Casa | 26 | 1.560 B | 4.588 B | 68.328 B |
| Generate per la CER | 16 | 1.274 B | 5.974 B | 48.546 B |
| Totale | 42 | | **5.974 B** | **116.874 B** |

Tutte le 21 coppie hanno dimensioni 48/96 px, alpha e peso inferiore a 12.000 B. Nomi `nome.webp` e `nome-2x.webp`, senza `@`; `Icon` usa `srcSet`, dimensioni esplicite e semantica decorativa. Frecce, chiudi, spunte e notifiche funzionali restano vettoriali.

Il [foglio originale ridotto](icone/foglio-originale.webp) pesa **99.352 B**, sotto 200 KB; l'[anteprima](icone/anteprima.webp) **19.890 B**. Ritagli, hash, pesi e controlli sono in [asset.json](icone/asset.json). Immagini generate per il progetto, senza importare una famiglia illustrata di terzi.

## Verifiche

- `npm.cmd run typecheck`: **riuscito**.
- `npm.cmd run build`: **riuscito**, anche dopo le correzioni finali. Restano le consuete segnalazioni di Vite sui moduli Node esternalizzati da Pyodide; nessun errore di build.
- `git diff --check`: **riuscito**. Nessuna modifica nei percorsi del motore o dell'intermediario.
- Chromium isolato: **186 controlli, 29 viste**, [registro](verifica-browser.json). Ingresso, cinque passi, mappa, risultati Torino e scheda famiglia a 1400, 1024 e 375 px; risultati calcolati e relative tabelle controllati a tutte e tre le larghezze. Verificati assenza di overflow della pagina, parole intere nelle intestazioni, scorrimento interno delle tabelle, (?) uniti alla prosa, apertura e chiusura dei popover da tastiera e mouse, focus, salvataggio JSON e reimportazione, conferma/annullamento del ritorno all'ingresso, errori aperti e blocco del salvataggio con dati non validi.
- Leaflet non viene richiesto prima di «Apri la foto aerea»; il contenitore della mappa è stato controllato alle tre larghezze. La scheda famiglia si apre e salva senza richieste a Pyodide, al Worker, all'app CER o a Leaflet.
- Tutti i **42 WebP decodificati anche nel browser**. Verificati dimensioni, alpha e limite di peso; i contesti delle schermate usano densità 2 e selezionano le risorse `-2x.webp`.
- [Controlli di accessibilità](verifica-accessibilita.json): tema chiaro anche con preferenza di sistema scura; focus visibile di 2 px; otto coppie di contrasto conformi alle soglie AA (testo tenue su sfondo 4,82:1; link e (?) 7,97:1; bordo controlli 4,44:1). Non è un audit assistivo completo o una prova su un telefono fisico.

La build iniziale presente prima delle modifiche aveva `index-BznraqKV.js` da **266.469 B**. Ora l'ingresso principale è **170.028 B** (55.605 B gzip); aggiungendo il modulo dell'app completa (**92.385 B**) e il client (**1.940 B**), il totale è **264.353 B**, circa **2,1 KB in meno** del precedente file principale. Worker e mappa restano separati; nessuna crescita oltre il vincolo di circa 30 KB.

### Ambiente e limiti verificabili

La prova usa il server di sviluppo sulla porta **5182**. Come per Casa, il sandbox Windows impedisce a esbuild di leggere directory superiori: build e typecheck sono stati lanciati dalla mappatura temporanea `R:` della stessa cartella. Per il server è stata usata la configurazione locale ignorata da Git `web/.verifica-ui/interfaccia.vite.mjs`, che importa quella del prodotto e aggiunge soltanto `preserveSymlinks` per Vite/esbuild e `server.watch: null`. La configurazione del prodotto non cambia.

La rete del sandbox blocca la CDN di Pyodide. Solo nel contesto di prova, le richieste alla CDN sono state soddisfatte con gli **stessi file Pyodide e wheel già presenti in `web/node_modules/pyodide` e `.pyodide-pacchetti`**. Non sono stati simulati il Worker, le risposte di cersim o i risultati. Le serie PVGIS sono arrivate dalla cache locale, attraverso il server Vite come descritto nel README. Il caso Torino si è calcolato correttamente: 16.345 kWh condivisi nel valore centrale e beneficio della configurazione di 16.589 € (4.445–30.165 € negli scenari).

**`pytest` non verificato:** il Python accessibile restituisce `No module named pytest`. Non c'è una `.venv` del repository; il Python di sistema non è eseguibile dal sandbox. Il tentativo di installare i pacchetti di verifica in una cartella locale ignorata è stato bloccato dalla rete (`WinError 10013` su PyPI). Non è quindi corretto dichiarare la suite Python verde: rimane da eseguire `pytest` dalla radice nell'ambiente abituale prima del commit.

Non verificati con rete reale: ortofoto Esri, ricerca dell'indirizzo, richieste Overpass e collegamento alla CDN pubblica. La mappa e i relativi controlli si aprono, ma la disponibilità delle immagini esterne non è attestata. Proposta di nuove taglie, curva di dimensionamento e download PDF/Excel non rieseguiti in questa prova; i loro calcoli e generatori sono invariati.

Lo [script browser](verifica-browser.cjs) si lancia dalla radice con il server attivo: `node docs/interfaccia-2026-10-29/verifica-browser.cjs`. Usa Playwright già presente per le prove locali; `PLAYWRIGHT_MODULE` permette di indicare un'altra installazione, senza aggiungerlo alle dipendenze di prodotto.

## Schermate

Sette JPEG di viewport, tra 33 e 122 KB: [ingresso 1400](1400-ingresso.jpg), [ingresso 375](375-ingresso.jpg), [risultati 1400](1400-risultati.jpg), [risultati 375](375-risultati.jpg), [impianti 375](375-impianti.jpg), [famiglia 1400](1400-famiglia.jpg), [famiglia 375](375-famiglia.jpg). Immagini a dimensione CSS, senza intere pagine molto lunghe.

Il server sulla porta 5182 è stato chiuso alla fine. Nessun processo preesistente non identificato come parte di questa prova è stato terminato.
