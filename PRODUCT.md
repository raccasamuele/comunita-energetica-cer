# Product

## Register

product

## Users
Funzionari e sindaci di piccoli e medi comuni, amministratori di condominio, presidenti di associazioni che valutano una comunità energetica. Non sono tecnici dell'energia. Usano lo strumento in ufficio, di giorno, su un portatile, e spesso ne proiettano i risultati in consiglio comunale o in assemblea condominiale, davanti a persone che faranno domande sui numeri. Il compito: capire in mezz'ora se una CER o un gruppo di autoconsumatori ha senso, quanto vale, chi paga e chi ci guadagna, e portare a casa un riepilogo da discutere.

## Product Purpose
Simulatore open source (licenza MIT) che, da pochi dati di bolletta e un indirizzo, produce uno **scenario preliminare** di comunità energetica: energia condivisa ora per ora, contributi GSE secondo le regole verificate sulle fonti, flussi economici per soggetto, banda di incertezza e dimensionamento. Successo: un sindaco capisce il risultato senza spiegazioni, sa quali requisiti restano da verificare e non scambia mai una stima per un preventivo.

Fa parte di **Energia in chiaro** (nome deciso il 29/10/2026), la famiglia di simulatori che comprende anche quello della riqualificazione della casa ("Casa"). Il portale generale dei progetti è `raccasamuele.it`; i due simulatori stanno su `cer.` e `casa.`, sotto il titolo comune, con stesso aspetto, stesso modo di lavorare per passi, dati che passano da uno all'altro (la curva dei consumi di una casa con pompa di calore diventa i consumi di un membro). L'interfaccia web gira tutta nel browser: i dati dei contatori non lasciano il computer di chi la usa ([docs/web_architettura.md](docs/web_architettura.md)).

## Brand Personality
Affidabile, chiara, civica. Tono da servizio pubblico ben fatto: frasi semplici in italiano corrente, numeri sempre accompagnati da cosa significano e da quanto sono incerti, nessun entusiasmo promozionale. Deve dare la stessa fiducia di un buon ufficio tecnico comunale. L'aspetto è quello di Casa, un cruscotto pulito e luminoso; il tono resta questo.

## Anti-references
- Siti di vendita di pannelli solari e calcolatori "scopri quanto risparmi": colori accesi, promesse, numeri singoli senza incertezza.
- Cruscotti che mostrano una cifra grande senza banda né qualità dei dati, o che la presentano come un risultato certo.
- Effetti decorativi: card in vetro, gradienti, animazioni che non spiegano nulla. Le schede e i KPI di Casa vanno bene: servono a ordinare, non a stupire.
- Moduli della PA vecchio stile: muri di campi, gergo burocratico, errori incomprensibili.
- Cruscotti da trading scuri e densi di grafici. Dal 29/10/2026 CER e Casa usano solo il tema chiaro, anche con il sistema in tema scuro.

## Design Principles
1. **L'onestà prima dell'effetto.** Ogni numero mostra la sua banda e la qualità dei dati; ciò che non è verificato è detto chiaramente. Un KPI senza banda non si pubblica.
2. **Leggibile in proiezione.** Gerarchia netta, contrasti alti, pochi elementi per schermata: deve funzionare su uno schermo in una sala, anche nel tema chiaro con la luce accesa.
3. **Spiegare con le parole del lettore.** Prima la frase che un sindaco può ripetere, poi la cifra, poi il dettaglio tecnico.
4. **Familiarità come affordance.** Componenti e percorsi standard (passi nella barra laterale, schede, tabelle, pulsanti), gli stessi di Casa: chi ha usato uno dei due simulatori sa usare l'altro.
5. **Uno stile comune, un solo accento.** Token, componenti e temi di Casa; un solo colore d'accento per le azioni e lo stato, il resto neutro. Le differenze tra i due simulatori sono nei contenuti, non nell'aspetto.

## Accessibility & Inclusion
WCAG 2.1 AA in entrambi i temi: contrasto ≥ 4.5:1 per il testo (3:1 per testo grande e componenti), stato mai trasmesso dal solo colore (sempre anche testo o icona), grafici con palette distinguibile dai daltonici e legenda testuale, testo ridimensionabile, navigazione da tastiera con focus visibile, obiettivi di almeno 44 px, nessuna animazione decorativa.
