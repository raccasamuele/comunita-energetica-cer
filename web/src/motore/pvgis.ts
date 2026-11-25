// Adattatore PVGIS sostituibile: chi scarica le serie che il motore chiede (`RichiestaPvgis`).
// - In sviluppo, senza intermediario: la cache PVGIS locale di cersim, servita da Vite (/pvgis-locale/<chiave>).
// - Con VITE_PVGIS_INTERMEDIARIO: il Worker di Cloudflare che inoltra la query a PVGIS e aggiunge le intestazioni
//   CORS (PVGIS non le manda). Il browser non chiama mai PVGIS direttamente.
// Una serie che non arriva non blocca: il motore usa il profilo semplificato e la qualità scende a C.

import type { RichiestaPvgis } from "./contratto";

export interface SorgentePvgis {
  nome: string;
  scarica(richiesta: RichiestaPvgis): Promise<unknown | null>;
}

/** Quanto si aspetta una serie: PVGIS di solito risponde in pochi secondi, ma a volte resta appeso. Dopo, la serie
 * manca e il motore usa il profilo semplificato: meglio un risultato di qualità C subito che un calcolo fermo. */
export const TIMEOUT_PVGIS_MS = 45_000;

async function json(url: string): Promise<unknown | null> {
  try {
    const risposta = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_PVGIS_MS) });
    return risposta.ok ? await risposta.json() : null;
  } catch {
    return null;
  }
}

export const cacheLocale: SorgentePvgis = {
  nome: "cache PVGIS locale (sviluppo)",
  scarica: (r) => json(`./pvgis-locale/${encodeURIComponent(r.chiave)}`),
};

export function intermediario(base: string): SorgentePvgis {
  return {
    nome: "PVGIS tramite intermediario",
    scarica: (r) => {
      const query = new URLSearchParams(Object.entries(r.parametri).map(([k, v]) => [k, String(v)]));
      return json(`${base.replace(/\/$/, "")}/seriescalc?${query}`);
    },
  };
}

export const nessuna: SorgentePvgis = { nome: "nessuna: produzione stimata", scarica: async () => null };

const CACHE_BROWSER = "cersim-pvgis-v1";

/** Tiene nel browser (Cache Storage) le serie già scaricate: a ogni ricalcolo non si rifanno le richieste. Senza
 * Cache Storage (navigazione privata, pagina non sicura) scarica e basta. */
export function conCacheBrowser(sorgente: SorgentePvgis): SorgentePvgis {
  return {
    nome: sorgente.nome,
    async scarica(r) {
      const chiave = `https://pvgis.cersim.invalid/${encodeURIComponent(r.chiave)}`;
      let cache: Cache | null = null;
      try {
        cache = await caches.open(CACHE_BROWSER);
        const salvata = await cache.match(chiave);
        if (salvata) return await salvata.json();
      } catch {
        cache = null;
      }
      const dati = await sorgente.scarica(r);
      if (dati !== null && cache) {
        await cache.put(chiave, new Response(JSON.stringify(dati), { headers: { "Content-Type": "application/json" } })).catch(() => undefined);
      }
      return dati;
    },
  };
}

export function sorgentePredefinita(): SorgentePvgis {
  const base = import.meta.env.VITE_PVGIS_INTERMEDIARIO as string | undefined;
  if (base) return conCacheBrowser(intermediario(base));
  return import.meta.env.DEV ? cacheLocale : nessuna;
}

/** Scarica tutte le serie richieste, in parallelo; quelle mancanti restano fuori. */
export async function scaricaSerie(richieste: RichiestaPvgis[], sorgente: SorgentePvgis): Promise<Record<string, unknown>> {
  const voci = await Promise.all(richieste.map(async (r) => [r.chiave, await sorgente.scarica(r)] as const));
  return Object.fromEntries(voci.filter(([, dati]) => dati !== null));
}

/** Avviso da mostrare quando PVGIS non ha dato tutte le serie (lento, fuori servizio o rete assente); null se ci
 * sono tutte. Con la sorgente «nessuna» (sito senza intermediario) non si avvisa: la stima è voluta. */
export function avvisoSerieMancanti(arrivate: number, richieste: number, sorgente: SorgentePvgis): string | null {
  if (arrivate >= richieste || sorgente === nessuna) return null;
  const quante = arrivate === 0 ? "nessuna delle" : `${richieste - arrivate} delle`;
  return `PVGIS non ha risposto in tempo per ${quante} ${richieste} serie di produzione: per quelle il calcolo usa una ` +
    "stima semplificata e la qualità dei risultati scende. Di solito è un rallentamento passeggero: riprova fra " +
    "qualche minuto, le serie già arrivate restano nel browser.";
}
