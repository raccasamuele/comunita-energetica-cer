# Aggiornamento periodico dei dati — istruzioni per l'agente

Queste istruzioni le segue la routine trimestrale (Claude Code nel cloud) e chiunque faccia il controllo a mano. Valgono per questo repository; il sito Casa (efficienza-energetica-casa) ha un file gemello con le sue fonti.

## Regole che non si toccano

- **Mai su `main`, mai pubblicare.** Il push su `main` pubblica il sito. Si lavora su un ramo `aggiornamento-dati-AAAA-MM` e si apre una pull request verso `main`. Niente merge.
- **Le regole normative non si cambiano in automatico.** Formule, soglie, requisiti, termini e classificazione dei soggetti si toccano solo con un piano approvato da Samuele: la routine li segnala.
- **Nessun valore senza fonte.** Ogni numero cambiato porta atto o documento, data ed edizione nel file YAML (commento o campo fonte), in `docs/fonti_normative.md` e nel rapporto. Fonti primarie: GSE, ARERA, MASE, Gazzetta Ufficiale, JRC. Non bastano articoli, blog o associazioni.
- **Voci con `"automatico": false`**: non si cambia codice né dati. Si scrive solo il rapporto con la novità e cosa servirebbe fare.
- **Dati con licenza** (campo `licenza`): non si scaricano.
- **Lingua**: italiano semplice in rapporto, commit e pull request.

## Passi

1. **Voci da controllare.** `python aggiornamento/scadute.py` elenca le voci da controllare: quelle che scadono (`ultimo_controllo` + `frequenza_mesi`) prima della routine successiva, cioè entro `frequenza_routine_mesi` da oggi. Così una voce che scadrebbe fra un controllo e l'altro si guarda in anticipo, non con tre mesi di ritardo; elenca anche i pacchetti di dati (`cersim/data/*.yaml`) con il campo `scadenza` entro quattro mesi. Con `--tutte` elenca tutto. Se non c'è nulla, la routine si ferma senza aprire nulla.
2. **Per ogni voce da controllare**, seguendo `come_controllare`:
   - apri la fonte (`url` o ricerca del documento più recente sul sito dell'ente); leggi il documento originale, non un riassunto;
   - annota: atto, data, articolo o tabella, indirizzo, valore trovato, unità;
   - confronta con `valori` dell'inventario e con il file YAML.
3. **Esito per voce**
   - **Invariato**: aggiorna solo `ultimo_controllo` (data di oggi).
   - **Cambiato, `automatico: true`**: aggiorna il valore nel file YAML, la fonte, `docs/fonti_normative.md` e la voce dell'inventario (`valori`, `fonte`, `ultimo_controllo`). Per TRASE e BTAU si **aggiunge** l'anno nuovo, senza togliere i precedenti. Se la differenza supera `soglia_pct`, segnalala nel rapporto come **«da verificare a mano»**.
   - **Cambiato, `automatico: false`**: lascia codice e dati; aggiorna `ultimo_controllo` e descrivi nel rapporto la novità, l'atto e che cosa andrebbe rivisto.
   - **Fonte non raggiungibile**: non cambiare il valore; scrivi nel rapporto «fonte non raggiungibile» con la data. Se era già successo al controllo precedente (vedi l'ultimo rapporto in `docs/aggiornamenti/`), segnalalo come **«serve una fonte nuova»**.
4. **Pacchetti in scadenza.** Per ogni pacchetto con la scadenza entro quattro mesi: se i valori sono stati ricontrollati e sono ancora validi, proponi nel rapporto la nuova scadenza **senza cambiarla**; la decide Samuele. Il test `test_nessun_pacchetto_scade_entro_trenta_giorni` blocca la pubblicazione un mese prima.
5. **Controlli**: `pip install -r requirements.txt` e `pytest`; poi in `web/` `npm ci`, `npm run typecheck`, `npm run build`. Se un test fallisce per un valore cambiato, aggiorna il test solo se il nuovo comportamento è corretto e dillo nel rapporto. Se non sai perché fallisce, non forzare: scrivilo nel rapporto e apri comunque la pull request come bozza.
6. **Rapporto** in `docs/aggiornamenti/AAAA-MM.md` (formato sotto).
7. **Ramo, commit e pull request**: ramo `aggiornamento-dati-AAAA-MM` da `main`; un commit con messaggio «Aggiornamento dati AAAA-MM: …»; pull request verso `main` con titolo «Aggiornamento dati AAAA-MM» e nel testo il riassunto del rapporto (tre righe in cima: quante voci controllate, quante cambiate, quante da verificare a mano). Se nulla è cambiato e nessuna fonte manca, apri lo stesso la pull request con le sole date aggiornate: è la prova che il controllo è stato fatto.

## Formato del rapporto

```markdown
# Aggiornamento dati — AAAA-MM

Controllo del GG/MM/AAAA. Voci controllate: N. Cambiate: N. Da verificare a mano: N. Fonti non raggiungibili: N. Pacchetti in scadenza: N.

| Voce | Esito | Prima | Dopo | Fonte (atto, data) |
|---|---|---|---|---|
| arera-trase-btau | cambiato | TRASE 2026 11,90 €/MWh | + TRASE 2027 … €/MWh | ARERA, delibera …/2026/R/eel, tab. 3 |

## Dettagli
Per ogni voce cambiata o da verificare: cosa dice l'atto, da quando vale, effetto sul caso di studio (incentivo annuo della configurazione di esempio) prima e dopo.

## Pacchetti in scadenza
File, scadenza attuale, scadenza proposta e perché.

## Da decidere
Novità normative non applicate (`automatico: false`): che cosa cambierebbe nel simulatore.

## Controlli
Esito di pytest, typecheck e build.
```
