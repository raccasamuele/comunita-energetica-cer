# Design

Sistema visivo della CER. Strategia, utenti e principi sono in [PRODUCT.md](PRODUCT.md).

Dal 28/10/2026 la CER ha **lo stesso stile del simulatore della casa** ("Casa"), nell'interfaccia web in `web/`. I token e i componenti sono quelli di Casa, copiati senza modifiche in [web/src/stile/casa.css](web/src/stile/casa.css) (`npm run sincronizza-stile` li ricopia quando Casa li cambia). Le aggiunte della CER stanno in [web/src/stile/cer.css](web/src/stile/cer.css). L'app Streamlit (`app.py`) conserva il sistema precedente finché non viene ritirata (in fondo).

## Visual Theme
Cruscotto pulito e luminoso: schede bianche su fondo lavanda chiaro, un solo accento viola per azioni e stato, grafici in toni pieni ma non accesi. Tema chiaro fisso dal 29/10/2026, in CER e Casa (`data-theme="light"` in `index.html`): il tema scuro dello stile comune resta nel CSS ma non si attiva più con l'impostazione del sistema. Scena di riferimento invariata: un funzionario comunale di giorno, in ufficio o con i risultati proiettati in sala consiliare. Per questo, in proiezione si usa il tema chiaro.

## Colors
Valori di `casa.css`. Contrasti verificati WCAG 2.1 AA (testo ≥ 4.5:1, bordi dei controlli ≥ 3:1).

| Ruolo | Token | Chiaro | Scuro | Uso |
|---|---|---|---|---|
| Sfondo | `--bg` | `#f3f2f9` | `#14131b` | pagina |
| Superficie | `--surface` | `#ffffff` | `#1d1c27` | barra laterale, pannelli, KPI |
| Superficie tenue | `--surface-2` | `#f6f5fb` | `#24232f` | campi, schede interne, intestazioni delle tabelle |
| Testo | `--text` | `#1f1d2b` (14,9:1) | `#ecebf3` (15,6:1) | testo |
| Testo tenue | `--muted` | `#6b6880` (5,4:1 sul bianco, 4,8:1 sullo sfondo) | `#a19eb3` (6,5:1) | didascalie, etichette |
| Bordo dei controlli | `--control-line` | `#79758b` (4,4:1) | `#8c879f` (4,9:1) | campi e pulsanti |
| Accento | `--accent-strong` | `#7c3aed`, testo bianco 5,7:1 | `#c4b5fd`, testo `#120d21` 10,3:1 | pulsante principale, passo aperto, selezione |
| Testo d'accento | `--accent-text` | `#6230b8` (8,0:1) | `#c4b5fd` (9,1:1) | link, focus |
| Successo | `--ok-text` su `--ok-soft` | `#08664e` su `#e3f7f0` (6,2:1) | `#3ccf9f` su `#173a30` (6,3:1) | "Coerente con i dati" |
| Attenzione | `--warn-text` su `--warn-soft` | `#814800` su `#fff3df` (6,7:1) | `#f5b34c` su `#3a2e19` (7,2:1) | "Da verificare", "Scenario preliminare" |
| Errore | `--bad-text` su `--bad-soft` | `#a9212a` su `#fde8e8` (6,1:1) | `#ff7a7f` su `#3d2023` (5,8:1) | "Non ammesso" |
| Informazione | `--info-text` su `--info-soft` | `#174db5` su `#e8f0fe` (6,6:1) | | note |

Grafici dell'energia, con ruoli fissi in tutte le viste (`cer.css`, sui colori di serie di Casa):

| Ruolo | Token | Colore |
|---|---|---|
| produzione FV | `--fv` | `--s3` ambra |
| consumi | `--consumi` | `--s1` viola |
| autoconsumo | `--autoconsumo` | `--s2` verde |
| energia condivisa | `--condivisa` | `--s4` rosso corallo |
| immessa non condivisa | `--immessa` | `--line` |

Ogni serie ha anche la legenda testuale; il significato non è mai affidato al solo colore. Il report PDF va riallineato a questi valori quando si costruisce il report nel sito (tappa 5).

## Typography
**Poppins** (OFL, da `@fontsource/poppins`, servito dal sito senza richieste esterne), pesi 400, 500 e 600. Fallback `Segoe UI`, `system-ui`. Testo di base 14 px; titolo del passo 1.45 rem, titoli 1.15 / 1 rem, peso 600. Cifre tabulari nei KPI e nelle tabelle. Righe di testo al massimo 72 caratteri.

## Components
Quelli di Casa, con gli stessi nomi di classe:

- **Barra laterale:** marchio (quadrato in accento con il sole) e nome, con sopra il titolo comune con Casa, "Energia in chiaro", piccolo e in testo d'accento (`.famiglia`; anche nella testata della scheda per le famiglie e nel titolo della pagina), poi i 5 passi con icona Lucide, nome e numero: Luogo, Membri e consumi, Impianti, Economia, Risultati. Il passo aperto è in accento tenue (`aria-current="step"`). In fondo c'è lo stato del motore di calcolo. Su telefono la barra diventa una riga di passi scorrevole.
- **Intestazione:** titolo del passo (riceve il focus quando si cambia passo), "Passo N di 5", a destra la pillola "Scenario preliminare" in tono attenzione e gli strumenti (esempio, importa, esporta).
- **Pannello:** scheda bianca con raggio 18 px e ombra leggera; dentro, schede tenui senza ombra.
- **KPI:** una riga di 4 riquadri nel passo Risultati (2 sotto i 1280 px, 1 sotto i 520 px). Ognuno ha l'etichetta, il valore centrale, la riga "tra X e Y negli scenari" e un'icona in tono. Il riquadro della qualità dei dati è sempre presente.
- **Pulsanti:** principale pieno in accento, uno per schermata ("Calcola", "Avanti"); secondari bianchi con bordo. Altezza minima di 44 px. Icone Lucide, mai emoji.
- **Avanti e Indietro:** in fondo a ogni passo, "Indietro" a sinistra e il pulsante principale con il nome del passo successivo a destra.
- **Etichette di stato:** pillole con testo e icona (`badge ok / warn / bad / info`).
- **Avvisi:** riquadri `notice`, con icona e testo, su fondo tenuto nel tono; `role="alert"` per gli errori.
- **Valori avanzati:** in un riquadro chiuso (`details.advanced`).
- **Frase di sintesi:** prima dei numeri, una frase che un sindaco può ripetere.
- **Piede:** "scenario preliminare, non un preventivo", il calcolo che resta nel browser, © dell'autore, uso libero del sito anche per lavoro, codice non modificabile senza permesso, link alle condizioni d'uso.

## Layout
Griglia con la barra laterale di 248 px e il contenuto fino a 1440 px; sotto gli 860 px una colonna sola. Il passo Risultati è un cruscotto (KPI, poi schede su una griglia di 12 colonne); gli altri passi stanno in un pannello unico. Nessun gradiente, nessuna animazione decorativa, un solo livello di ombra.

## Accessibility
- Pagina in italiano (`lang="it"`).
- Focus visibile di 2 px in testo d'accento; il titolo del passo riceve il focus al cambio di passo.
- Obiettivi di almeno 44 px; tutto si usa da tastiera.
- Stato sempre anche in testo; ogni grafico ha la didascalia che dice che cosa mostra.
- Nessuno scorrimento orizzontale a 375 px.
- Contrasti AA verificati nei due temi (tabella sopra). Dopo ogni sincronizzazione dello stile vanno ricontrollati.

## Copy
Italiano corrente, frasi brevi, niente gergo dove esiste una parola comune ("beneficio netto" accanto a VAN). Niente trattini lunghi.

## App Streamlit (fino al ritiro)
`app.py` conserva il sistema precedente: neutri grigio ardesia, accento blu petrolio `#1f5f6b`, carattere Geist da `static/`, passi numerati in alto, valori in [.streamlit/config.toml](.streamlit/config.toml) e nel blocco `STILE` di `app.py`. Usano gli stessi valori anche il report PDF (`cersim/report.py`) e lo schema del tetto. Non si aggiorna più: le novità dell'interfaccia vanno nel sito.
