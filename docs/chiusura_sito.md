# Chiusura del sito e ritiro dell'app Streamlit

Stato al 24/11/2026. Riguarda la tappa 6 di [web_architettura.md](web_architettura.md#9-tappe-successive): revisione
dell'accessibilità, scheda delle famiglie da stampare, ritiro di `app.py`.

## 1. Fatto in questo giro

### Scheda per le famiglie da stampare in PDF

Al passo 2, nel riquadro *Raccogli i consumi con un link*, il pulsante **Scheda da stampare (PDF)** scarica un
foglio A4 con che cosa serve, dove trovarlo, il link (cliccabile) e una tabella da compilare a mano. È la stessa
scheda dell'app Streamlit (`cersim.report.scheda_famiglia_pdf`), chiamata dal Worker con la nuova funzione
`cersim.web.scheda_pdf` (in `FUNZIONI`). Usa fpdf2 e i caratteri Geist, quindi la prima volta carica i pacchetti
dei report come il passo 5 (qualche secondo). La pagina leggera della famiglia non cambia: non avvia il motore.

Test: `tests/test_web.py::test_scheda_da_stampare_per_le_famiglie`.

### Revisione dell'accessibilità (WCAG 2.1 AA)

axe-core 4.10.2 (regole `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`, `best-practice`) sul sito costruito
(`npm run build`, `vite preview`), a 1280 e 320 px di larghezza, su ingresso, i cinque passi con tutti i riquadri
`<details>` aperti e la scheda della famiglia. Prima: 9 violazioni in 2 regole; dopo: **nessuna violazione e nessun
caso da rivedere**. Corretti:

| Problema | Criterio | Correzione |
|---|---|---|
| Ai passi 1–4 il titolo del passo è `h1` e le sezioni erano `h3`: manca il livello 2 | 1.3.1 | Sezioni `h2`, sottotitoli `h3` (anche le tre taglie del passo 3); l'aspetto resta quello di prima con tre regole in `cer.css`, `casa.css` non cambia |
| A 320 px, prima di iniziare, la barra dei passi scorre di lato ma ha solo pulsanti spenti: non si raggiunge con la tastiera | 2.1.1 | La barra prende il focus (`tabIndex=0`) finché il progetto non è iniziato |
| Il link *Anteprima della scheda* apre una nuova scheda senza dirlo | 3.2.5 (AAA, buona pratica) | Testo nascosto "(si apre in una nuova scheda)" |

Controllati con la tastiera: ordine del Tab nell'ingresso e nella scheda della famiglia, anello di focus visibile
(2 px, pieno) su tutti i comandi, focus sul titolo del passo dopo il cambio di passo, nessuno scorrimento
orizzontale della pagina a 320 px (equivale allo zoom al 400% su 1280 px).

**Limite di questa verifica**: nell'ambiente di prova la CDN di Pyodide era bloccata, quindi il motore non partiva.
Sono state controllate le schermate vuote e gli stati d'errore, non i Risultati calcolati, la tabella dei contatori
piena, la proposta delle tre taglie e i grafici. La verifica di ottobre sull'app Streamlit li copriva; sul sito
vanno ripetuti (sezione 3).

## 2. Piano di ritiro di `app.py`

Il sito fa già tutto quello che fa l'app, con il motore nel browser e la stessa logica Python. Il ritiro è sicuro
perché nessun modulo di `cersim` dipende da Streamlit e nessuna funzione di `cersim` è usata solo da `app.py` tranne
alcune utilità elencate sotto.

### Cosa manca al sito rispetto all'app

1. **"Prima di iniziare"**: l'app ha *Come funziona*, *Che cosa tenere a portata di mano* e il riquadro *Tutti i
   dati che servono e dove trovarli* (`cersim.guida.COSA_SERVE` per chi coordina, famiglie, attività e parti comuni,
   più `PORTALE_CONSUMI` e `CODICE_POD`). L'ingresso del sito ha solo la frase del percorso. Da portare, con i testi
   esportati da `cersim.web` come già per la scheda (`testi.json`).
2. **Video "Come disegnare il tetto"** (`static/video_tetto.mp4`, 1,8 MB): il sito ha solo i passi scritti. Da
   decidere se metterlo in `web/public/` o farne a meno.
3. **Manifest tecnico** nei Risultati (l'app mostra `analisi.energia_base.manifest` in JSON): il sito mostra tempo
   di calcolo, versione del motore e fonti; il manifest completo è già nel report Excel. Basta così.

### Fasi

**Fase 0, condizioni per partire.** Le prove manuali della sezione 3 sono fatte e i due punti mancanti sopra sono
chiusi (o il video è scartato).

**Fase 1, avviso (reversibile).** In cima ad `app.py` un riquadro: "Questa versione non sarà più aggiornata: usa
cer.raccasamuele.it", con il link. Se l'app è pubblicata su Streamlit Community Cloud, si lascia così per qualche
settimana e poi si spegne dal pannello. Il README presenta il sito come interfaccia principale.

**Fase 2, test.** Nove test usano `streamlit.testing.AppTest` su `app.py`. Prima di togliere l'app si spostano su
`cersim.web` (stesse funzioni chiamate dal Worker) oppure si eliminano se il caso è già coperto:

| Test | Cosa controlla | Dove va |
|---|---|---|
| `test_analisi_app.py::test_app_si_avvia_e_calcola_l_esempio` | Torino dal salvataggio ai risultati | già coperto da `test_web.py::test_risultati_completi_curva_e_report`: si toglie |
| `test_curva_calcolata.py::test_app_con_una_curva_calcolata` | curva `curva-consumi` al passo 2 fino al calcolo | `leggi_consumi` + `progetto_da_tabelle` + `risultati` in `test_web.py` |
| `test_misure.py::test_app_calcola_con_le_curve_misurate` | file del distributore fino al calcolo, qualità A | come sopra, con `esempi/letture_esempio_sintetico.csv` |
| `test_guida.py::test_modulo_famiglia_nell_app` | `?modulo=famiglia` | `test_web.py` controlla già `testi.json`; il comportamento della pagina va in una prova Playwright di `web/` |
| `test_guida.py::test_prima_di_iniziare_e_link_nell_app` | testi di *Prima di iniziare* e link | dopo il punto 1 sopra, controllo dei testi esportati |
| `test_guida.py::test_percorso_con_i_pulsanti_avanti` | navigazione Avanti | prova Playwright di `web/` |
| `test_proposta.py::test_passo_3_guidato_nell_app`, `test_passo_3_con_le_falde_a_est_e_a_ovest`, `test_passo_3_per_una_comunita_energetica` | proposta del tetto dall'interfaccia | `richieste_proposta` + `proposta` in `test_web.py` (c'è già `test_proposta_in_due_tempi`: si aggiungono due falde e CER con più edifici) |

Per le prove Playwright c'è già `docs/interfaccia-2026-10-29/verifica-browser.cjs` da trasformare in uno script di
`web/` (`npm run verifica`), con la CDN di Pyodide servita da una cache locale come fa già lo script.

**Fase 3, rimozione.** Prima un tag `ultima-app-streamlit` sul commit di partenza, così l'app resta recuperabile.
Poi in un solo commit:
- si tolgono `app.py` e `static/video_tetto.mp4` (se non serve al sito);
- da `requirements.txt` e da `pyproject.toml` si tolgono `streamlit`, `folium`, `streamlit-folium` e l'extra `app`
  (`dev` resta con `pytest`);
- si **tengono** in `cersim` `geo.geocode`, `tetto.scarica_edifici`, `tetto.link_google_earth` e le utilità della
  scheda (`guida.crea_scheda`, `link_famiglie`, `nome_file`): oggi le usa solo l'app, ma servono a chi usa `cersim`
  da Python senza browser, in particolare al futuro server MCP per gli agenti, che non ha l'intermediario né
  Overpass dal browser;
- il formato di salvataggio non cambia (`cersim.ui_model.esporta_json`): i file salvati con l'app si aprono nel sito
  con *Importa*.

**Fase 4, documenti.** README (righe su `streamlit run`, tabella dei file, pubblicazione su share.streamlit.io),
PLAN.md e COSA_MANCA.md (tappa 3), commenti in `cersim/web.py` che rimandano ad `app.py` (righe 13, 233, 382, 508,
650, 777: diventano rimandi a `web/src/passi/`), DESIGN.md dove parla dell'aspetto Streamlit, LICENZA.md se cita
l'app.

## 3. Prove manuali

Non si possono fare in modo automatico; servono una persona e i dispositivi veri.

1. **Lettore di schermo**: NVDA con Firefox o Chrome su Windows e VoiceOver con Safari su Mac (anche iPhone per la
   scheda della famiglia). Un percorso intero: ingresso, esempio di Torino, cinque passi, calcolo, download del
   report. Controllare che si sentano i titoli dei passi, i messaggi del motore (`aria-live`), gli errori
   (`role="alert"`), le spiegazioni (?) e la tabella dei contatori riga per riga.
2. **Verifica axe con il motore acceso** (sul sito pubblicato o in locale con la CDN raggiungibile): Risultati
   calcolati con tutti i grafici, passo 2 con 13 righe, passo 3 con la mappa aperta e la proposta delle tre taglie,
   passo 4 con i prezzi caricati. Lo script di questa verifica si può rilanciare puntandolo all'indirizzo giusto.
3. **Prova in proiezione**: Risultati e report PDF su un proiettore vero (o un televisore) in una stanza illuminata,
   da 4–5 metri: leggibilità delle cifre, dei colori dei grafici (giallo e verde) e delle didascalie tenui.
4. **Stampa della scheda per le famiglie**: stampare il PDF su una stampante vera in bianco e nero, compilare la
   tabella a penna (le righe sono abbastanza alte?), provare il link stampato con la fotocamera di un telefono (il
   link è lungo: valutare un codice QR).
5. **Telefono vero**: la scheda della famiglia su un telefono Android e un iPhone, con zoom del sistema al massimo e
   testo grande.
6. **Mappa del tetto con la tastiera**: Leaflet si sposta con le frecce, ma il disegno dei vertici richiede il mouse
   o il tocco. Verificare che l'alternativa (inserire superficie e orientamento a mano) basti a chi non usa il mouse.
7. **File reali dei distributori**: un file del Portale Consumi e uno di e-distribuzione scaricati dal titolare del
   contratto (già in COSA_MANCA.md).
