# Fonti normative verificate

Verifica del 15/10/2026 sui testi originali. Ogni regola implementata in `cersim` rimanda a questa pagina; i valori numerici sono in [`cersim/data/parametri_normativi.yaml`](../cersim/data/parametri_normativi.yaml).

## Documenti letti

| Sigla | Documento | Versione letta |
|---|---|---|
| **DM** | DM MASE 7 dicembre 2023, n. 414 (Decreto CACER) | testo pubblicato dal GSE ("Decreto CER.pdf") |
| **RO** | GSE, *Decreto CACER e TIAD – Regole operative*, Allegato 1 | **versione del 16 luglio 2025** |
| **TIAD** | ARERA, Allegato A alla delibera 727/2022/R/eel | testo 2022 (le grandezze usate sono riprese e aggiornate nelle RO) |
| **DM106** | DM MASE 15 marzo 2024, n. 106 (corrispettivi GSE) | tabella riportata dal GSE, pagina "Corrispettivi e tariffa" |
| **TIT** | ARERA, tariffa di trasmissione TRAS (periodo 2024–2027, delibera 615/2023/R/eel) | valori pubblicati da ARERA per 2024, 2025, 2026 |

## Regole confermate

### Tariffa premio (TIP)
- **Formula oraria** (RO §2.2.2.1.2, p. 40–41; DM Allegato 1):
  `TIP_h = { min[CAP; TPbase + max(0; 180 − Pz)] + FCzonale } × (1 − F)`
  con `Pz` = prezzo zonale orario.
- **TPbase / CAP** per potenza dell'impianto: ≤ 200 kW → 80 / 120 €/MWh; 200–600 kW → 70 / 110; > 600 kW → 60 / 100.
- **Il tetto (CAP) si applica prima della correzione geografica**: al Nord, ≤ 200 kW, la TIP massima è 130 €/MWh.
- **FCzonale** (solo FV): +10 €/MWh Nord (Emilia-Romagna, Friuli-Venezia Giulia, Liguria, Lombardia, Piemonte, Trentino-Alto Adige, Valle d'Aosta, Veneto); +4 €/MWh Centro (Lazio, Marche, Toscana, Umbria, Abruzzo); 0 altrove. ✔ coincide con `geo.REGIONI`.
- **Durata**: 20 anni dalla **data di entrata in esercizio commerciale** (DM art. 4 c. 3), al netto delle fermate per forza maggiore. ✔ `data_inizio_periodo_incentivazione`.
- **Termine di accesso**: il Titolo II (TIP) "si applica fino al trentesimo giorno successivo alla data del raggiungimento di un contingente di potenza incentivata pari a 5 GW, e comunque non oltre il 31 dicembre 2027" (DM art. 1 c. 2). Un impianto che entra in esercizio dopo il 31/12/2027 non accede alla TIP (CACV invariato). ✔ `eligibility._termine_accesso_tip`. Al 16/10/2026 la proroga al 2030 è solo richiesta dalle associazioni; contingente usato ~0,5 GW (ago. 2026). Da verificare: se il termine riguarda l'entrata in esercizio o la presentazione della richiesta.
- **EACI oraria** = min(Σ immissioni ai fini della condivisione, Σ prelievi ai fini della condivisione) sui punti della configurazione (RO p. 40). ✔ `simulate.py`.

### Attribuzione dell'energia condivisa tra impianti
- RO, Appendice A (definizioni di energia autoconsumata e condivisa): può essere suddivisa per impianto/UP **"a partire dalle immissioni degli impianti di produzione entrati prima in esercizio"**. ✔ già implementato.
- **A parità di data** le RO non dicono nulla: `cersim` ripartisce in proporzione alle immissioni. **Ipotesi dichiarata.**
  Ricontrollato il 25/11/2026: anche la FAQ del GSE KB0016870 (aggiornata il 29/09/2025, sull'energia condivisa
  incentivabile con più impianti a tariffe diverse) descrive solo la priorità per data di entrata in esercizio, fino
  all'energia immessa di ciascun impianto, e non tratta la parità di data; nemmeno la guida Unioncamere sulle CER
  (giugno 2025). Resta un'ipotesi: la ripartizione proporzionale non cambia il totale della configurazione, cambia solo
  quanto si attribuisce a ciascun impianto (e quindi a chi investe) quando gli impianti hanno tariffe o investitori
  diversi. Da chiedere al GSE con un quesito se un caso reale ha due impianti con la stessa data.

### Fattore F (contributo in conto capitale)
- F varia linearmente da 0 (nessun contributo) a 0,5 (contributo pari al 40% dell'investimento) "nella generalità dei casi" (DM All. 1 §3; RO p. 41). `cersim` usa il valore dell'atto di concessione.
- **Non si applica** all'EACI afferente a punti di prelievo di **enti territoriali, enti religiosi, enti del terzo settore e di protezione ambientale e persone fisiche** (RO p. 41). Nota: il DM originale non citava le persone fisiche; la versione 2025 delle RO sì, con ricalcolo retroattivo del 2024.
- Con almeno un punto esente e almeno un impianto con contributo, l'EACI si divide in esente / non esente; **l'energia dei punti esenti va prioritariamente agli impianti con contributo** (RO p. 41).

### Quota eccedentaria (55% / 45%)
- Due insiemi di impianti: solo TIP / TIP + contributo in capitale (RO §2.2.2.1.3, p. 42).
- `%EACI,ecc,j = max[0; EACI_j / Eimmessa_j − soglia_j]`, soglia 55% (solo TIP) o 45% (con contributo); verifica **annuale**.
- Importo eccedentario: `C_ecc = Σ_j %EACI,ecc,j × C_ACI,j`. Va destinato a **consumatori diversi dalle imprese** e/o a **finalità sociali** sul territorio (DM art. 3 c. 2 lett. g).

### Corrispettivo di valorizzazione (CACV)
- **CER** (RO §2.2.2.2.2, p. 45): `CACV = CUAf,a × EACV`, con `CUAf,a = TRASE` (parte variabile della tariffa di trasmissione per le utenze BT).
- **Gruppo di autoconsumatori**: `CACV = CUAf,a × EACV + CUAf,b × EACVC + Σ_h Σ_i (EACVC,i × cPR,i × Pz)`, con `CUAf,b` = valore più elevato della componente variabile di distribuzione BTAU e `EACVC` = energia autoconsumata con i soli impianti dell'edificio o condominio.
- **Perdite evitate cPR**: 2,6% per impianti connessi in BT, 1,2% in MT (RO p. 46). Per i livelli di tensione misti le RO partono dagli impianti al livello più basso: `cersim` usa la tensione del punto dell'impianto (semplificazione; i casi condominiali sono tutti in BT).
- **Durata**: 20 anni; al termine "il Contratto può essere tacitamente rinnovato annualmente in relazione alle sole parti afferenti alla valorizzazione" (RO p. 35). ✔ TIP 20 anni, CACV fino all'orizzonte.

### Ritiro dedicato (RID)
- L'energia immessa resta nella disponibilità del produttore (DM art. 4 c. 2). Il ritiro da parte del GSE segue l'Allegato A della delibera ARERA 280/07 (RO §2.2.2.3).
- Oneri amministrativi del RID (verificati il 16/10/2026): DM MiSE 24/12/2014, tabella 3 del documento GSE "Tariffe per la copertura degli oneri sostenuti dal GSE", richiamato dalla pagina GSE "Tariffe e copertura del servizio" del Ritiro Dedicato. Solare: 0,70 €/kW fino a 20 kW, 0,65 €/kW da 20 a 200 kW, 0,60 €/kW oltre, a scaglioni progressivi sulla potenza nominale, massimale 10.000 €/anno; esenti gli impianti fino a 3 kW; dovuta per intero se la convenzione è valida anche un solo giorno dell'anno. Esempi: 19 kW → 13,3 €; 100 kW → 66 €. ✔ `Rid.onere_annuo`. Sostituisce la regola dello 0,5% del controvalore (delibera 280/07), non più in vigore dal 2015.

### Corrispettivi GSE per costi gestionali (DM106)
- Dovuti su base annua dai beneficiari della tariffa, trattenuti dalle somme erogate (RO §2.2.2.5).
- Per impianto: P ≤ 3 kW → 0; 3 < P ≤ 20 kW → 15 €/anno; 20 < P ≤ 1000 kW → 15 €/anno + 1 €/kW sulla sola potenza oltre i 20 kW (DM106, Allegato 1 lett. a): 100 kW → 95 €/anno.

### Decorrenze (RO §2.2.1.1–2.2.1.2)
- Il servizio decorre dall'entrata in esercizio se la richiesta arriva entro 120 giorni; altrimenti dal giorno dopo la richiesta, **perdendo i contributi del periodo intermedio**. Per CER e gruppi non può precedere la costituzione. ✔ tre date per impianto.

### Valori TRASE / BTAU
- TRASE (BT altri usi): **1,057 c€/kWh nel 2024**, **1,189 nel 2025**, **1,190 nel 2026** (ARERA, TIT). Il valore 2024 coincide con i 10,57 €/MWh indicati dal GSE.
- BTAU (massimo, quota energia della distribuzione BT altri usi, tariffe BTA1–BTA6): **0,065 c€/kWh nel 2024**, **0,073 nel 2025**, **0,068 nel 2026**. Fonte: tabelle TIT allegate alla [delibera ARERA 575/2025/R/eel](https://www.arera.it/atti-e-provvedimenti/dettaglio/25/575-25), Tabella 3, consultate il 2 novembre 2026. Il valore 2024 coincide con gli 0,65 €/MWh indicati dal GSE.
- Gli anni futuri usano **l'ultimo valore verificato, congelato in termini reali** (ipotesi dichiarata e in sensibilità).

## Fonti dei dati di prezzo — vincolo di licenza

Le *Condizioni generali di utilizzo* del sito GME (lette il 15/10/2026):
- §5: licenza **personale**, "per uso meramente informativo e di carattere privato", con citazione della fonte;
- §6: vietato pubblicare, riprodurre o distribuire i contenuti per finalità economiche senza consenso scritto;
- §6 bis: **vietata l'estrazione automatizzata** (crawler, bot, scraper) senza autorizzazione scritta, salvo organismi di ricerca per ricerca scientifica.

Conseguenze per `cersim`:
- **nessun file GME nel repository** e nessun download automatico dal sito GME;
- `cersim.prices` legge un file di prezzi orari fornito dall'utente (per uso personale) oppure usa un prezzo costante (qualità `C`);
- per l'app pubblica serve una fonte con licenza compatibile: ENTSO-E da sola non basta (vedi sotto) → **autorizzazione scritta del GME**. **Aperto.**
- **ENTSO-E Transparency Platform** (verificato il 15/10/2026 su *Terms of Use* del 29/03/2023 e *List of data available for free re-use* del 18/10/2023):
  - i dati si possono usare "per qualsiasi scopo" citando la piattaforma come fonte (§3.1), ma senza ledere i diritti del proprietario originario dei dati; in caso di rischio serve il suo consenso preventivo;
  - solo i dati della lista sono riutilizzabili liberamente con licenza **CC-BY 4.0**: la lista **non comprende i prezzi del giorno prima** (Regolamento 543/2013, art. 12.1.d). Per i prezzi italiani il proprietario originario è il GME, le cui condizioni li limitano all'uso privato;
  - conclusione: con il token ENTSO-E i prezzi si possono usare **per studio e analisi personali** (anche per l'aggiornamento annuale in locale); **per l'app pubblica o il repository serve comunque un'autorizzazione scritta del GME** (le condizioni GME, §15, prevedono la richiesta di licenze d'uso). Valutazione non legale: in caso di dubbio chiedere a un legale o direttamente al GME.
- Da ottobre 2025 il mercato del giorno prima europeo usa prodotti quartorari: per gli anni recenti il prezzo orario va ricavato come media dei quattro quarti d'ora (TIP e condivisa restano orarie).

### Condominio ed enti del terzo settore (fattore F e quota eccedentaria)
Ricontrollato il 25/11/2026 sulle fonti disponibili: RO del 16/07/2025 p. 41 (letta il 15/10), DM art. 3 c. 2 lett. g,
FAQ GSE, guida e scheda Unioncamere sulle CER (2025), caso d'uso condominiale delle Camere di commercio.
- **Fattore F, condominio.** L'elenco dei soggetti esenti delle RO è chiuso (enti territoriali, enti religiosi, enti
  del terzo settore e di protezione ambientale, persone fisiche) e **il condominio non c'è**. Nessuna fonte letta lo
  aggiunge. `cersim` tratta i punti di prelievo del condominio (le parti comuni) come **non esenti**: è la lettura
  testuale, e la più prudente (riduce la tariffa). Non si estende al condominio l'esenzione dei condòmini persone
  fisiche: i loro punti di prelievo sono esenti, quello delle parti comuni no. **Ipotesi dichiarata**, da confermare
  con il GSE.
- **Fattore F, terzo settore.** Gli enti del terzo settore sono esenti come categoria, senza distinguere chi svolge
  attività d'impresa: `cersim` li tratta come esenti.
- **Quota eccedentaria, condominio.** Il DM la destina ai «consumatori diversi dalle imprese» e/o a finalità sociali,
  senza definire «impresa». Il condominio non svolge attività economica e non è un'impresa: `cersim` lo conta fra i
  destinatari ammessi. **Ipotesi dichiarata.**
- **Quota eccedentaria, terzo settore.** Un ente del terzo settore può essere un'impresa sociale o svolgere attività
  commerciale in modo prevalente: nessuna fonte letta dice come trattarlo. `cersim` lo considera **di natura
  sconosciuta**: nella verifica della quota eccedentaria (`economics._verifica_eccedenza`) quello che riceve non conta
  fra le somme date a non-imprese, e il risultato avvisa che per alcuni membri non è noto se siano imprese.
- I valori sono in [`classificazione_soggetti.yaml`](../cersim/data/classificazione_soggetti.yaml); restano da far
  confermare a un esperto esterno o al GSE.

## Ancora aperto
- Fonte dei prezzi per l'app pubblica (licenza).
- Conferma del GSE o dell'esperto sulle tre ipotesi sopra (condominio e fattore F, condominio e quota eccedentaria,
  impianti con la stessa data); terzo settore che svolge attività d'impresa.
- Rinnovo del pacchetto normativo prima della scadenza del 30/04/2027 (valori TIT 2027, eventuali nuove RO, proroga del
  termine del 31/12/2027).
