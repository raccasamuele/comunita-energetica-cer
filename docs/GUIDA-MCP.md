# Il simulatore CER negli agenti AI: guida all'installazione

Con questa guida un agente AI (Claude Code, Claude Desktop o un altro agente compatibile con MCP) può usare il
simulatore:
- crea un progetto dalla conversazione, o controlla un lavoro salvato dal sito o dall'app;
- legge i consumi dei contatori e i prezzi orari da file sul computer;
- propone la taglia del fotovoltaico per un tetto;
- calcola lo scenario completo, la curva delle taglie e il report PDF o Excel.

I calcoli sono quelli del sito, con lo stesso motore (`cersim`). Il server ricalca quello di Casa
(efficienza-energetica-casa, `docs/ecosistema/GUIDA-MCP.md`): stessi principi, stesse avvertenze dove valgono.

**Chiunque può installarlo**, sul proprio computer: il codice è in questo repository, con licenza MIT ([LICENSE](../LICENSE)). Prima di
installarlo leggi le avvertenze del §6.

## 1. Che cosa serve

- **Python 3.11 o più recente**, con le dipendenze del motore (`requirements.txt`). Non servono altre librerie: il
  protocollo MCP è scritto a mano, come in Casa.
- **Il repository**, perché il report PDF usa i caratteri in `static/`.
- **Internet per PVGIS**, la prima volta per ogni luogo e orientamento. Le serie restano nella cache di `cersim`
  (`~/.cache/cersim/pvgis`, o la cartella di `CERSIM_CACHE_DIR`) per 90 giorni, la stessa dell'app Streamlit. Senza
  rete il server usa la cache e, se manca, il modello semplificato (qualità C).

## 2. Installare

Dalla cartella del repository, con l'ambiente virtuale del [README](../README.md#provarlo):

```powershell
~/.venvs/cersim/Scripts/python -m pip install -e .
```

`-e` (modalità modificabile) tiene il motore collegato al repository: dopo un `git pull` il server usa la versione
nuova senza reinstallare. Crea anche il comando `cersim-mcp` nell'ambiente virtuale.

Il percorso completo di Python dell'ambiente è il `<python>` dei paragrafi seguenti. In PowerShell:
`(Resolve-Path ~/.venvs/cersim/Scripts/python.exe).Path`.

## 3. Collegarlo a Claude Code

```powershell
claude mcp add --scope user cer -- "<python>" -m cersim.mcp.server
claude mcp get cer
```

Deve dire `Status: ✔ Connected`. Senza `--scope user` il server vale solo nella cartella da cui si è dato il comando.

Opzioni, da aggiungere in fondo al comando:
- `--cache "<cartella>"`: un'altra cartella per la cache PVGIS;
- `--senza-rete`: non scarica da PVGIS (solo la cache, altrimenti il modello semplificato).

## 4. Collegarlo a Claude Desktop

### Con l'estensione (senza terminale)

Il modo più semplice, anche per chi non ha Python né il repository: il file **`cer-<versione>.mcpb`**, un'estensione
di Claude Desktop (formato MCPB). Contiene il motore, la scheda nella chat e i caratteri del report; le librerie
(numpy, pandas, …) le installa Claude Desktop con `uv` al primo avvio, per il sistema di chi lo usa (Windows, macOS,
Linux). Il primo avvio richiede internet e qualche decina di secondi.

1. Doppio clic sul file `.mcpb`, oppure trascinarlo nella finestra di Claude Desktop, oppure Impostazioni →
   Estensioni → «Installa estensione…».
2. Claude Desktop mostra nome, autore, strumenti e licenza: «Installa».
3. In una chat nuova il simulatore c'è (icona degli strumenti, voce «Simulatore CER»).

Se prima era collegato a mano (sotto), togliere il blocco `"cer"` da `claude_desktop_config.json`: altrimenti ci
sono due server con lo stesso nome.

Per creare il file, dalla cartella del repository:

```powershell
~/.venvs/cersim/Scripts/python estensione/crea_pacchetto.py
```

Scrive `dist/cer-<versione>.mcpb`. Per controllarlo: `npx @anthropic-ai/mcpb validate` sul `manifest.json`
estratto, oppure `npx @anthropic-ai/mcpb info dist/cer-<versione>.mcpb`. Il pacchetto non è firmato.

### A mano, dal repository

Per chi lavora sul codice: il server usa il repository, e dopo un `git pull` la versione nuova è già lì.
Impostazioni → Sviluppatore → «Modifica configurazione», poi accanto a quello che c'è già (per esempio `casa`):

```json
{
  "mcpServers": {
    "cer": {
      "command": "<python, con le barre rovesciate raddoppiate>",
      "args": ["-m", "cersim.mcp.server"]
    }
  }
}
```

Poi chiudere del tutto Claude Desktop (icona vicino all'orologio → «Esci») e riaprirlo. I log sono in
`%LOCALAPPDATA%\Claude\Logs\mcp-server-cer.log`.

### La scheda nella chat

Nella Chat di Claude Desktop e su claude.ai, con ogni strumento (tranne `esporta_progetto`) compare la scheda del
simulatore (MCP Apps, `ui://cer/scheda.html`), nello stile del sito:
- **scenario** (`analizza_scenario`): la frase di sintesi, le cifre con gli intervalli, poi le schede *Sintesi*
  (conviene costituire la configurazione? netto per membro), *Energia* (mese per mese), *Soldi* (cassa cumulata,
  sensibilità, chi paga e chi riceve), *Requisiti* e *Precisione*. I grafici si leggono anche con la tastiera e hanno
  la tabella dei numeri;
- **proposta** (`proponi_impianto`): le tre taglie affiancate e la curva del beneficio per potenza;
- **progetto**, **curva delle taglie**, **consumi**, **prezzi**, **report** e **valori predefiniti**: i dati
  principali.

I pulsanti («Analizza questa taglia», «Curva delle taglie», «Salva il report PDF», «Calcola lo scenario») scrivono la
richiesta nella chat e Claude la esegue; se il client non lo permette, la scheda mostra il testo da copiare. La
scheda non fa calcoli e non va in rete: mostra quello che lo strumento ha già detto a Claude. Le sessioni della
scheda Code e gli altri agenti vedono solo il testo, che contiene comunque tutto.

## 5. Come usarlo

| Si chiede | Strumento |
|---|---|
| «Che tipi di soggetto posso usare? Quanto costa costituire una CER?» | `valori_predefiniti` |
| «Controlla il lavoro in C:\…\cer.json» | `controlla_progetto` |
| «Simula un gruppo di autoconsumatori a Torino con 12 famiglie e il tetto del condominio» | `crea_progetto` |
| «Questi sono i consumi della famiglia 3: C:\…\letture.csv» | `leggi_consumi` |
| «Usa i prezzi orari del GME in C:\…\prezzi_2025.csv» | `leggi_prezzi` |
| «Il tetto è di 120 m², esposto a sud, inclinato di 20°: quanti kWp?» | `proponi_impianto` |
| «Conviene? Chi riceve cosa?» | `analizza_scenario` |
| «E con un impianto più grande o più piccolo?» | `dimensiona_impianto` |
| «Salvami il report in C:\…\scenario.pdf» | `scrivi_report` |
| «Dammi il file da aprire nel sito» | `esporta_progetto` |

- **Identificativi.** Ogni strumento restituisce un `progetto_id`, `consumi_id`, `prezzi_id` o `analisi_id` da passare
  ai successivi. Valgono finché il server è acceso: per conservarli, `esporta_progetto` e `scrivi_report`.
- **Il percorso è meglio del contenuto.** L'agente può anche incollare il contenuto del file del progetto, ma così
  il file intero passa dal servizio dell'agente.
- **Ogni risposta riporta la qualità dei dati, gli intervalli, le avvertenze e l'avvertenza finale.** Se l'agente li
  toglie, chiedili: sono parte del risultato.
- `proponi_impianto` e `analizza_scenario` scaricano da PVGIS e mandano l'avanzamento: la prima volta qualche secondo
  per serie, poi dalla cache.

## 6. Prima di installarlo: che cosa sapere

1. **Che cosa esce dal computer.** Il server gira sul computer, ma l'agente di solito no: quello che il server
   risponde arriva al servizio dell'agente (per Claude, ad Anthropic).
   - **Non escono:** il nome della configurazione, l'indirizzo, i codici POD (diventano `[omesso]`), le coordinate
     precise, i valori orari dei consumi e dei prezzi.
   - **Escono:** la regione, i nomi dei contatori e dei membri (servono a leggere «chi riceve cosa»: conviene usare
     nomi come «Famiglia 1»), i consumi annui, i risultati.
   - **Le eccezioni:** `esporta_progetto` restituisce il file intero, perché è fatto per essere salvato e aperto nel
     sito; i report di `scrivi_report` contengono tutti i dati, ma restano nel file sul computer.
2. **A PVGIS** (JRC, Commissione europea) escono le coordinate arrotondate a 0,01° (circa 1 km), l'orientamento e le
   perdite di ogni impianto, come dall'app Streamlit.
3. **Il server legge i file che l'agente gli indica**: progetti `.json` fino a 2 MB, consumi `.csv`/`.json` fino a
   20 MB, prezzi `.csv` fino a 5 MB. Rifiuta i percorsi di rete e di dispositivo di Windows (`\\server\…`,
   `\\?\…`). Gli errori non ripetono il percorso né il contenuto del file.
4. **Il server scrive un solo tipo di file:** il report di `scrivi_report`, nel percorso indicato, con l'estensione
   giusta e solo se il file non esiste (non sovrascrive). Scrive anche la cache PVGIS.
5. **I risultati sono una stima esplorativa**, non un preventivo né una consulenza legale o fiscale: i requisiti «da
   verificare» vanno controllati con il GSE.

## 7. Dopo un aggiornamento

```powershell
git pull
~/.venvs/cersim/Scripts/python -m pip install -r requirements.txt
```

Poi una sessione nuova dell'agente (per Claude Desktop, la chiusura completa). Ogni risposta riporta la versione del
motore. Con l'estensione: installare il file `.mcpb` nuovo, che sostituisce il vecchio.

## 8. Toglierlo

```powershell
claude mcp remove cer -s user
```

In Claude Desktop: con l'estensione, Impostazioni → Estensioni → «Simulatore CER» → «Disinstalla»; collegato a mano,
si toglie il blocco `"cer"` da `mcpServers` e si riavvia l'app.
