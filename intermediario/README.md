# Intermediario PVGIS

Worker di Cloudflare, nel piano gratuito, che inoltra a PVGIS `seriescalc` le richieste del sito della CER. Il
motore cersim gira nel browser e PVGIS non manda le intestazioni CORS. Perché e come è fatto: sezione 4 di
[docs/web_architettura.md](../docs/web_architettura.md).

- Risponde su `/pvgis/seriescalc` quando sta sul dominio del sito e su `/seriescalc` su `workers.dev`.
- Accetta solo richieste GET con i parametri che usa cersim (`cersim/pv.py`), controllati: Italia, anni meteo
  2021–2023, 1 kWp, `outputformat=json`. Coordinate arrotondate a 0,01°. Tutto il resto risponde 400, 403, 404 o
  405.
- Sul dominio del sito il browser lo chiama dalla stessa origine, quindi non serve CORS. Su `workers.dev` il CORS
  vale solo per le origini in `ORIGINI`. Una richiesta da un'altra origine riceve 403.
- Risponde con ore e potenze (`time`, `P`), come la cache su disco di cersim: circa 177 kB invece di 824 kB.
- Cache di 90 giorni: in un KV se c'è `PVGIS_KV_ID`, altrimenti nella cache di Cloudflare, che funziona solo con un
  dominio personalizzato. Le risposte sbagliate di PVGIS non si tengono.
- Inoltra anche la ricerca dell'indirizzo del passo 1 a Nominatim di OpenStreetMap: `GET /geo/cerca?q=…`, solo il
  testo (da 3 a 200 caratteri), solo l'Italia, al massimo 5 luoghi, una richiesta al secondo per istanza, risposte
  in cache per 30 giorni (`src/indirizzo.ts`). Sul dominio del sito risponde sulla route `cer.<dominio>/geo/*`.
- Non registra le richieste.

```
npm install
npm test            # test con il test runner di Node, senza rete
npm run locale      # l'intermediario in Node su http://127.0.0.1:8787, con PVGIS vero e cache in memoria
npm run typecheck   # tipi di Cloudflare e TypeScript
npm run build       # build del Worker (cf build)
```

Per provare il sito con l'intermediario locale, avviare prima `npm run locale` qui. Poi, in `web/`:
- come sul dominio del sito: `npm run build && npm run preview -- --port 5182`. `vite preview` manda `/pvgis` a
  `http://127.0.0.1:8787`, come farà la route di Cloudflare;
- in sviluppo: `VITE_PVGIS_INTERMEDIARIO=http://127.0.0.1:8787 npm run dev -- --port 5181`, con il CORS per le
  origini predefinite `http://127.0.0.1:5181` e `http://localhost:5181`.

## Pubblicazione

Si usa la CLI `cf`, con la configurazione in `cloudflare.config.ts`, non Wrangler. La macchina di sviluppo è già
collegata all'account (`cf auth whoami`). Prima di ogni pubblicazione conviene `cf deploy --dry-run`, che
costruisce e mostra le binding senza mandare nulla. `cf` non pubblica i progetti Pages "classici": per un sito
statico indica un Worker con *static assets*, la nuova Pages su Workers.

**Con un dominio tuo (in uso: `cer.raccasamuele.it`).** Il dominio deve essere una zona del tuo account
Cloudflare (sezione 6 di docs/web_architettura.md). Si pubblica **un solo Worker, `cer-sito`**, che serve i file
del sito e risponde lui su `/pvgis/*` e `/geo/*`:

```
cd ../web && npm ci && npm run build
cd ../intermediario && SITO=cer.raccasamuele.it npm run deploy
```

La configurazione mette il Worker sul dominio personalizzato `SITO` (Cloudflare crea record DNS e certificato),
prende come file del sito `../web/dist` (`vite.config.ts`, `publicDir`; un'altra cartella con `SITO_DIST=`) e
manda al codice solo `/pvgis/*` e `/geo/*` (`assets.runWorkerFirst`). Tutto il resto lo servono i file statici,
senza consumare richieste del Worker, con `index.html` per i percorsi sconosciuti. Spegne `workers.dev`, dove la
cache di Cloudflare non funziona. Non servono KV né CORS, e il sito non ha bisogno di variabili: nella build di
produzione cerca l'intermediario in `./pvgis` (`web/.env.production`).

**Pubblicazione automatica da GitHub** (dal 29/10/2026). A ogni push su `main` il workflow
`.github/workflows/pubblica.yml` lancia pytest, typecheck e build del sito e i test dell'intermediario; se passano,
pubblica `cer-sito` con `npx cf deploy` e `SITO=cer.raccasamuele.it`. Il sito si aggiorna quindi con il merge in
`main`, non dai rami di lavoro. Servono, in GitHub, *Settings → Secrets and variables → Actions*:
- il segreto `CLOUDFLARE_API_TOKEN`: un token creato dal titolare dell'account in Cloudflare, *My Profile → API
  Tokens → Create Token*, modello *Edit Cloudflare Workers*, limitato all'account e alla zona `raccasamuele.it`;
- la variabile `CLOUDFLARE_ACCOUNT_ID`, l'identificativo dell'account (non è un segreto).

Senza il token il workflow salta la pubblicazione con un avviso. Si può rilanciare a mano da *Actions → pubblica →
Run workflow*.

A mano, conviene pubblicare un commit, non la cartella di lavoro: `git archive <commit> | tar -x -C <cartella
vuota>`, poi i due comandi sopra in quella cartella.

Prima pubblicazione: 29/10/2026, commit `b73746c`, Worker `cer-sito` su `cer.raccasamuele.it`. La cache di
Cloudflare è separata per data center: dalla stessa macchina le richieste passavano sia da Monaco sia da Parigi,
con una cache per ciascuno.

Seconda pubblicazione: 29/10/2026, commit `5965318` (scheda dei consumi per le famiglie, titolo comune "Energia in
chiaro"), versione del Worker `4c6a8951`.

**Senza dominio.** Solo l'intermediario, senza il sito: il Worker `cersim-pvgis` risponde su
`https://cersim-pvgis.<sottodominio>.workers.dev`, e serve un namespace KV per la cache:

```
ORIGINI=https://<progetto>.pages.dev PVGIS_KV_ID=<id del namespace> npm run deploy
```

Il sito, pubblicato altrove, va costruito con `VITE_PVGIS_INTERMEDIARIO=https://cersim-pvgis.<sottodominio>.workers.dev`.

Versioni fissate, uscite insieme a metà ottobre 2026: `cf` 1.0.0-beta.17, `@cloudflare/vite-plugin`
2.0.0-beta.sha-67fa336fd, `vite` 8.3.4, TypeScript 7.0.2. `cf` è ancora in beta: comandi e configurazione possono
cambiare.
