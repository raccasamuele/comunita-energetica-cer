# Cosa manca da fare

Stato al 25/11/2026. Il piano completo è in [PLAN.md](PLAN.md).

## Dove siamo

| Tappa | Stato |
|---|---|
| 1. Motore fisico (bilancio orario, PVGIS, consumi, requisiti) | Fatta, nel commit `5d14b11` |
| 2. Euro (TIP, CACV, ledger, VAN, scenari, dimensionamento) | Fatta, nel commit `5d14b11` |
| 3. Interfaccia web (app Streamlit in 5 passi) | Fatta e ridisegnata (`ca25e2f`); nuovo aspetto il 24/10 (`0a01da4`): blu petrolio, passi numerati, cifre in riquadri; verifica di accessibilità il 24/10 |
| 3b. Proposta dell'impianto sul tetto | Fatta: tetto disegnato sulla foto aerea, tre taglie, due falde a est e a ovest; per la comunità energetica un tetto alla volta su edifici diversi (commit `db793cc`–`df5187e`) |
| 4. Report, validazione, pubblicazione | In corso: report PDF ed Excel, README e caso studio fatti; mancano prezzi orari nell'app pubblica, curve misurate e validazione |
| 5. Agenti AI | Fatta: schema JSON del progetto e CLI `cersim` (24/11), server MCP `cersim-mcp` (24/11); scheda nella chat ed estensione per Claude Desktop in revisione (PR #7); [docs/GUIDA-MCP.md](docs/GUIDA-MCP.md). Installato e provato sul PC di Samuele il 25/11, PVGIS compreso |

Test: 473, tutti verdi il 25/11/2026.

## Cose che dipendono dall'autore

Richiedono account, contatti o decisioni dell'autore.

1. **Token ENTSO-E.** Chiunque può chiederlo: registrazione su https://transparency.entsoe.eu/ (*Sign In*, poi *Register*), conferma via email, poi un'email a transparency@entsoe.eu con oggetto "RESTful API access" e nel testo l'indirizzo della registrazione. Dopo la conferma: *My Account*, poi genera il token. Serve per l'aggiornamento annuale dei prezzi in locale.
2. **Autorizzazione del GME.** Per usare i prezzi orari nell'app pubblica serve un consenso scritto: i prezzi del giorno prima non sono tra i dati liberi di ENTSO-E e le condizioni del GME ne permettono solo l'uso privato. Il GME prevede la richiesta di licenze d'uso (§15 delle condizioni). La richiesta è da inviare.
3. **Repository pubblico**: questo. Il codice è open source con licenza **MIT** dal 24/11/2026, come Casa ([LICENZA.md](LICENZA.md)); la storia dello sviluppo precedente resta nel repository privato di lavoro.
4. **Account Streamlit Community Cloud** per pubblicare l'app di prova, solo per invitati. Da verificare: secondo il forum il piano gratuito consente una sola app privata.
5. **Un esperto esterno** (docente PoliTo o professionista CER) che controlli un caso CER e un caso di gruppo condominiale. È la condizione per rendere l'app pubblica.

## Da fare nel codice

### Prossimo passo
- ~~Consumi misurati~~: lettore fatto il 23/10 per Portale Consumi e e-distribuzione (sito e app), con i formati ricostruiti da fonti pubbliche ([docs/consumi_misurati.md](docs/consumi_misurati.md)); caricamento al passo 2 e nella scheda delle famiglie; qualità A con tre quarti dei consumi misurati. **Resta la prova con un file reale** di ciascun tipo: il portale mostra solo le forniture intestate a chi entra, quindi deve scaricarlo il titolare del contratto.
- ~~Sistemazione dell'interfaccia~~: fatta il 23/10 (Prima di iniziare riordinata, pulsanti Avanti, termini tecnici in riquadri chiusi, risultati con la frase in cima, "Come rendere la stima più precisa"), controllata anche su telefono.
- ~~Nuovo aspetto~~: fatto il 24/10 (palette blu petrolio, passi numerati, pannello bianco, tre riquadri in cima ai Risultati; regole in [DESIGN.md](DESIGN.md)). Corretto anche lo schema del tetto al passo 3, che non si vedeva perché `st.html` toglie gli SVG.
- ~~Ponte dei consumi, lato CER~~: fatto il 28/10. Formato `curva-consumi` versione 1 ([docs/formato_curva_consumi.md](docs/formato_curva_consumi.md)), lettore con validazione in `cersim/curva_calcolata.py`, caricamento al passo 2 accanto ai file del distributore; la curva calcolata vale qualità B, mai A. **Resta l'esportazione dal simulatore della casa**, da fare su quel progetto seguendo il documento del formato.
- Poi il resto della Tappa 4.

### Interfaccia web con Pyodide
- ~~Prova di fattibilità, architettura, scheletro di `web/`~~: fatti il 28/10 ([docs/web_architettura.md](docs/web_architettura.md)). Il motore gira nel browser con risultati identici a CPython; pronto in circa 11 s al primo accesso, analisi di Torino in circa 7 s.
- ~~Intermediario PVGIS~~: fatto il 29/10 ([intermediario/](intermediario/README.md)): Worker di Cloudflare con parametri controllati, CORS solo per il sito, cache di 90 giorni (KV o cache di Cloudflare), Cache Storage nel browser; provato in locale con PVGIS vero. **Non ancora pubblicato.**
- ~~Passi 1 e 2 del sito~~: fatti il 29/10 (luogo con la ricerca dell'indirizzo tramite l'intermediario, tabella dei contatori, famiglie tipo, consumi ora per ora anche dal simulatore della casa, bozza nel browser, importa ed esporta). La logica resta in Python (`cersim/web.py`, `FUNZIONI`). Lo stesso giorno la scheda dei consumi per le famiglie: link, pagina leggera senza motore (che parte solo per i file orari) e raccolta delle schede al passo 2. La scheda da stampare in PDF è arrivata il 24/11.
- ~~Passo 3 del sito~~: fatto il 29/10 (tetto disegnato sulla foto aerea, ombre dagli edifici vicini di OpenStreetMap, proposta delle tre taglie, tabella degli impianti). La logica resta in Python (`cersim/web.py`).
- ~~Passi 4 e 5 del sito~~: fatti il 29/10 (riparto, prezzi orari per uso personale, valori avanzati; risultati completi con grafici, requisiti, sensibilità, curva delle taglie, report PDF ed Excel generati nel browser).
- **Prossima tappa**: chiusura del sito e ritiro dell'app Streamlit, in [docs/chiusura_sito.md](docs/chiusura_sito.md). Il 24/11: scheda per le famiglie da stampare in PDF al passo 2; verifica axe-core del sito a 1280 e 320 px senza violazioni (corretti la gerarchia dei titoli e la barra dei passi su telefono). Restano le prove manuali (lettore di schermo, axe con il motore acceso, proiezione, stampa), *Prima di iniziare* nel sito e le quattro fasi del ritiro.
- **Casa e CER**: un portale generale su `raccasamuele.it`, con Casa e CER sotto un titolo comune su `casa.` e `cer.` (deciso il 29/10). Da fare: il titolo comune e la barra di navigazione comune; il pulsante "Porta nella CER" in Casa.
- **Pubblicato il 29/10** su https://cer.raccasamuele.it (Worker `cer-sito`, commit `b73746c`): sito, PVGIS e ricerca dell'indirizzo provati dal vivo. Gli aggiornamenti si pubblicano a mano (intermediario/README.md).
- **Dominio**: intermediario e sito sono pronti per un dominio proprio: `cer.<dominio>` per il sito, le route `cer.<dominio>/pvgis/*` e `cer.<dominio>/geo/*` per l'intermediario, niente KV né CORS. Passi in docs/web_architettura.md, sezione 6: comprare il dominio, aggiungerlo a Cloudflare, collegare Pages, `SITO=cer.<dominio> npm run deploy`.
- ~~Contatto per le licenze commerciali~~: non serve più con la licenza MIT (24/11).
- ~~Citazione di OpenStreetMap~~: «© OpenStreetMap contributors» c'era già sotto la pianta degli edifici vicini e nella ricerca dell'indirizzo, nel report PDF ed Excel dal 24/11. Il 25/11 è diventata un collegamento a openstreetmap.org/copyright (come chiedono le linee guida della OSM Foundation), compare anche accanto alla scelta delle ombre stimate, fuori dal riquadro chiuso, e nel piè di pagina del sito con PVGIS ed Esri.

### Tappa 4: report e pubblicazione
- ~~Report PDF, export Excel e pulsanti di download nell'app~~: fatti (`84ea6d0`, `5ff66e1`).
- **Prezzi reali nell'app**: connettore ENTSO-E (con token, solo uso personale finché non arriva l'autorizzazione GME) e uno script per l'aggiornamento annuale dei prezzi.
- ~~Caso studio Torino e README completo~~: fatti il 23/10 ([docs/caso_studio_torino.md](docs/caso_studio_torino.md)).

### Dalla revisione del 16/10/2026
Tutto corretto tranne i consumi misurati (sopra): termine TIP 31/12/2027; oneri RID a scaglioni (DM 24/12/2014); risultati invalidati quando cambiano i dati; più anni di prezzi e qualità B raggiungibile; nomi riservati nel ledger; vendita negativa; TIR nascosto con qualità C; "non investire" e contributo escluso nel dimensionamento; salva/ricarica senza perdite; costi da preventivo; varianti dei consumi (più di giorno / più la sera) nella banda; confronto con il solo fotovoltaico; etichetta "Coerente con i dati".

### Verifiche ancora aperte (docs/fonti_normative.md)
- ~~Costo calcolato sulla potenza nominale GSE~~: deciso il 23/10, la stima del costo usa i kWp dei moduli (`base_potenza: DC`); fasce della tariffa premio e limite di 1 MW restano sulla potenza GSE.
- ~~Valori BTAU 2025–2026~~: verificati il 02/11 sulla delibera ARERA 575/2025/R/eel (0,073 e 0,068 c€/kWh), già nel pacchetto normativo.
- Classificazione di condominio ed enti del terzo settore ai fini dell'esenzione F e della quota eccedentaria: ricontrollata il 25/11. Nessuna fonte ufficiale tratta il condominio: il punto delle parti comuni resta non esente da F (l'elenco delle RO è chiuso) e non impresa ai fini della quota eccedentaria; gli ETS esenti da F, di natura sconosciuta per la quota eccedentaria. **Ipotesi dichiarate** in [docs/fonti_normative.md](docs/fonti_normative.md), da far confermare al GSE o all'esperto.
- Ripartizione dell'energia condivisa tra impianti con la stessa data di entrata in esercizio: ricontrollata il 25/11, né le RO né la FAQ GSE del 29/09/2025 trattano il caso. Resta in proporzione alle immissioni, **ipotesi dichiarata**; un quesito al GSE se capita in un caso reale.
- Rinnovo del pacchetto normativo prima della scadenza del 30/04/2027.

### Qualità e robustezza
- ~~**Accessibilità**~~: verifica WCAG 2.1 AA fatta il 24/10 con axe-core 4.10 su tutti i passi, i grafici dei Risultati e il modulo per le famiglie (nessuna violazione rimasta), più prove a mano con la tastiera e a 720 e 320 px di larghezza (zoom al 200% e al 400%). Corretti: lingua della pagina (era inglese) e nomi accessibili di Streamlit in italiano; barra laterale chiusa ancora raggiungibile con il Tab; ancore dei titoli che prendevano il focus restando invisibili; didascalie a 2,6–4,4:1 portate a 6,3:1; anello di focus uniforme; gerarchia dei titoli (titoli nascosti per ogni passo); focus sulla scheda del nuovo passo dopo *Avanti*; alternativa testuale del grafico "Giorno tipo"; tabella delle cifre e requisiti senza scorrimento orizzontale a 320 px. Restano:
  - **prova con un lettore di schermo vero** (NVDA su Windows, VoiceOver su Mac): finora solo controlli della semantica e dei nomi accessibili;
  - le **tabelle modificabili** del passo 2 e 3 (`st.data_editor`, una griglia disegnata su canvas) si usano con la tastiera ma sono poco leggibili dai lettori di schermo: il modulo per le famiglie è l'alternativa accessibile per inserire i consumi;
  - alcuni testi interni di Streamlit restano in inglese (il nome del pulsante di caricamento file, le descrizioni automatiche degli assi dei grafici).
- **Vista da telefono**: controllata a 375 e 320 px il 24/10; la tabella delle cifre diventa a blocchi sotto i 560 px.
- ~~**Configurazioni grandi**~~: ottimizzati il 25/11 i profili di consumo (forma della tipologia e rumore di ogni contatore calcolati una volta sola invece che per ogni anno), il libro dei movimenti e i controlli del bilancio, con risultati identici al centesimo. Analisi completa in Python: 60 contatori 5 s (prima 8), 120 contatori 9 s (prima 15), 200 contatori 16 s (prima 24). Nel browser (Pyodide) circa il doppio.
- ~~**Messaggi d'errore** per i casi limite~~: fatti il 25/11. File di prezzi: vuoto, Excel, UTF-16, non di testo, file grezzo del GME, colonne mancanti, data o prezzo sbagliato (con il numero di riga), prezzi in €/kWh, valori fuori scala; ora si accettano anche «;» e la virgola decimale di Excel in italiano. Servizi esterni: PVGIS aspetta al massimo 45 s per serie, poi il sito avvisa che per quelle serie usa la stima semplificata; la ricerca dell'indirizzo aspetta 20 s e suggerisce di inserire regione e coordinate a mano.

## Versione 2 (fuori dalla prima versione, per scelta)
- Curve di consumo reali scaricate da e-distribuzione (oggi profili sintetici: è la principale incertezza del modello).
- Batterie e accumulo.
- Autoconsumatore individuale a distanza.
- Impianti esistenti e potenziamenti, più impianti sullo stesso contatore, impianti oltre 1 MW.
- Verifica automatica della cabina primaria.
- Più investitori con contratti personalizzati, ottimizzazione di più impianti insieme.
- Fiscalità (IVA, imposte sui contributi, detrazioni).
