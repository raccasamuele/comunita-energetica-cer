import { bindings, defineConfig } from "cf/config";
import * as entrypoint from "./src/index.ts" with { type: "cf-worker" };

declare const process: { env: Record<string, string | undefined> }; // la configurazione si legge in Node

// Due modi di pubblicare (intermediario/README.md):
// - SITO=cer.tuonome.it: un solo Worker sul dominio personalizzato del sito. Serve i file del sito (web/dist, vedi
//   vite.config.ts) e risponde lui su /pvgis/* e /geo/* (ricerca dell'indirizzo): stessa origine, niente CORS,
//   cache di Cloudflare funzionante; l'indirizzo workers.dev si spegne. È la "nuova Pages" su Workers.
// - senza SITO: solo l'intermediario su <nome>.<sottodominio>.workers.dev, con ORIGINI per il CORS e, se c'è, il KV
//   PVGIS_KV_ID (su workers.dev la cache di Cloudflare non funziona).
const sito = process.env.SITO;
const origini = process.env.ORIGINI ?? (sito ? `https://${sito}` : "http://127.0.0.1:5181,http://localhost:5181");

export default defineConfig({
  worker: {
    name: sito ? "cer-sito" : "cersim-pvgis",
    compatibilityDate: "2026-10-06",
    entrypoint,
    workersDev: !sito,
    domains: sito ? [sito] : undefined,
    // le richieste che non sono dell'intermediario vanno ai file del sito; un percorso sconosciuto dà index.html
    assets: sito ? { notFoundHandling: "single-page-application", runWorkerFirst: ["/pvgis/*", "/geo/*"] } : undefined,
    env: {
      ORIGINI: bindings.text(origini),
      PVGIS_CACHE: process.env.PVGIS_KV_ID ? bindings.kv({ id: process.env.PVGIS_KV_ID }) : false,
    },
  },
});
