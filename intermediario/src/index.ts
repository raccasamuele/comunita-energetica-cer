// Intermediario PVGIS per l'interfaccia web della CER (docs/web_architettura.md, sezione 4).
//
// Il motore cersim gira nel browser e chiede le serie orarie di PVGIS seriescalc; PVGIS non manda le intestazioni
// CORS, quindi le inoltra questo Worker. Sul dominio del sito risponde su /pvgis/seriescalc (stessa origine,
// niente CORS); su workers.dev su /seriescalc. Non è un proxy aperto: accetta solo GET con i parametri che
// cersim usa (cersim/pv.py, _parametri), negli intervalli ammessi, e li riscrive in forma canonica. Risponde con
// ore e potenze, come la cache su disco di cersim, e tiene le risposte per 90 giorni: in un KV se è collegato
// (PVGIS_CACHE), altrimenti nella cache di Cloudflare, che funziona solo con un dominio personalizzato.
// Inoltra anche la ricerca dell'indirizzo del passo 1 a Nominatim (GET /geo/cerca?q=…, src/indirizzo.ts).
// Non registra le richieste.

import {
  DURATA_CACHE_INDIRIZZI_S,
  luoghi,
  MAX_RISULTATI,
  NOMINATIM_URL,
  testoRicerca,
  turnoNominatim,
} from "./indirizzo.ts";

export const PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/seriescalc";
export const DURATA_CACHE_S = 90 * 24 * 3600;
const VERSIONE_CACHE = "v1"; // da cambiare se cambia la forma della risposta
const TIMEOUT_MS = 45_000;
const TIMEOUT_PVGIS_MS = 20_000; // per tentativo: di solito PVGIS risponde in 1–2 s
const ATTESE_PVGIS_MS = [400, 1_200]; // prima del secondo e del terzo tentativo
const MIN_ORE = 8_700; // un anno di PVGIS ha 8760 o 8784 ore
const PERCORSI = ["/seriescalc", "/pvgis/seriescalc"]; // workers.dev e route sul dominio del sito
const PERCORSO_INDIRIZZI = "/geo/cerca"; // uguale su workers.dev e sul dominio (route <sito>/geo/*)

/** Il minimo di KV che serve, così i test non dipendono dai tipi di Cloudflare. */
export interface Kv {
  get(chiave: string): Promise<string | null>;
  put(chiave: string, valore: string, opzioni?: { expirationTtl?: number }): Promise<void>;
}

export interface Env {
  /** Origini del sito ammesse, separate da virgole (per esempio https://cer.pages.dev). */
  ORIGINI: string;
  PVGIS_CACHE?: Kv;
}

export interface Contesto {
  waitUntil(promessa: Promise<unknown>): void;
}

interface Regola {
  min: number;
  max: number;
  intero?: boolean;
  decimali?: number; // arrotondamento: coordinate a 0,01°, come cersim
}

const NUMERICI: Record<string, Regola> = {
  lat: { min: 35, max: 48, decimali: 2 }, // Italia, come model.Configuration
  lon: { min: 6, max: 19, decimali: 2 },
  peakpower: { min: 1, max: 1 },
  loss: { min: 0, max: 50 },
  angle: { min: 0, max: 90 },
  aspect: { min: -180, max: 180 },
  pvcalculation: { min: 1, max: 1, intero: true },
  startyear: { min: 2021, max: 2023, intero: true }, // pv.ANNI_METEO
  endyear: { min: 2021, max: 2023, intero: true },
};
const ORDINE = [...Object.keys(NUMERICI), "outputformat"];
const NUMERO = /^-?\d{1,4}(\.\d{1,6})?$/;

/** Query canonica (ordine fisso, numeri normalizzati) oppure il motivo per cui non è ammessa. */
export function canonica(query: URLSearchParams): { query: string } | { errore: string } {
  const chiavi = [...query.keys()];
  const estranee = chiavi.filter((k) => !ORDINE.includes(k));
  if (estranee.length) return { errore: `parametri non ammessi: ${estranee.slice(0, 5).join(", ")}` };
  if (new Set(chiavi).size !== chiavi.length) return { errore: "parametri ripetuti" };
  const mancanti = ORDINE.filter((k) => !query.has(k));
  if (mancanti.length) return { errore: `mancano: ${mancanti.join(", ")}` };
  if (query.get("outputformat") !== "json") return { errore: "outputformat deve essere json" };

  const valori: Record<string, number> = {};
  for (const [nome, regola] of Object.entries(NUMERICI)) {
    const testo = query.get(nome)!;
    if (!NUMERO.test(testo)) return { errore: `${nome} non è un numero` };
    let x = Number(testo);
    if (regola.intero && !Number.isInteger(x)) return { errore: `${nome} deve essere intero` };
    if (regola.decimali !== undefined) x = Math.round(x * 10 ** regola.decimali) / 10 ** regola.decimali;
    if (x < regola.min || x > regola.max) return { errore: `${nome} fuori intervallo (${regola.min}–${regola.max})` };
    valori[nome] = Object.is(x, -0) ? 0 : x;
  }
  if (valori.startyear !== valori.endyear) return { errore: "startyear ed endyear devono coincidere" };
  const parti = Object.keys(NUMERICI).map((k) => [k, String(valori[k])]);
  return { query: new URLSearchParams([...parti, ["outputformat", "json"]]).toString() };
}

function originiAmmesse(env: Env): string[] {
  return (env.ORIGINI ?? "").split(",").map((o) => o.trim()).filter(Boolean);
}

/** PVGIS e Nominatim chiedono che l'applicazione si faccia riconoscere: nome e indirizzo del sito. */
function userAgent(env: Env): string {
  const sito = originiAmmesse(env)[0];
  return `cersim-intermediario/0.1 (simulatore CER${sito ? `; ${sito}` : ""})`;
}

function intestazioni(origine: string | null, ammessa: boolean, extra: Record<string, string> = {}): Headers {
  const h = new Headers({ "Content-Type": "application/json; charset=utf-8", "X-Content-Type-Options": "nosniff", ...extra });
  if (origine && ammessa) {
    h.set("Access-Control-Allow-Origin", origine);
    h.set("Vary", "Origin");
  }
  return h;
}

function risposta(stato: number, corpo: unknown, origine: string | null, ammessa: boolean, extra?: Record<string, string>) {
  return new Response(JSON.stringify(corpo), { status: stato, headers: intestazioni(origine, ammessa, extra) });
}

/** Ore e potenze della risposta di PVGIS, o null se la forma non è quella attesa. */
export function compatta(dati: unknown, query: string): string | null {
  const orarie = (dati as { outputs?: { hourly?: unknown } })?.outputs?.hourly;
  if (!Array.isArray(orarie) || orarie.length < MIN_ORE) return null;
  const time: string[] = [];
  const P: number[] = [];
  for (const ora of orarie as { time?: unknown; P?: unknown }[]) {
    if (typeof ora?.time !== "string" || typeof ora?.P !== "number" || !Number.isFinite(ora.P)) return null;
    time.push(ora.time);
    P.push(ora.P);
  }
  const parametri = Object.fromEntries(new URLSearchParams(query));
  return JSON.stringify({ fonte: "PVGIS 5.3", parametri, scaricato_il: new Date().toISOString(), time, P });
}

async function dallaCache(env: Env, chiave: string, url: string): Promise<string | null> {
  if (env.PVGIS_CACHE) return env.PVGIS_CACHE.get(chiave);
  if (typeof caches === "undefined") return null;
  const trovata = await (caches as unknown as { default: Cache }).default.match(url);
  return trovata ? trovata.text() : null;
}

async function inCache(env: Env, chiave: string, url: string, corpo: string, durata = DURATA_CACHE_S): Promise<void> {
  if (env.PVGIS_CACHE) return env.PVGIS_CACHE.put(chiave, corpo, { expirationTtl: durata });
  if (typeof caches === "undefined") return;
  await (caches as unknown as { default: Cache }).default.put(
    url,
    new Response(corpo, { headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${durata}` } }),
  );
}

/** PVGIS ogni tanto rifiuta una richiesta (429 o 5xx, anche con tre richieste insieme) e poco dopo la accetta: si
 * riprova fino a tre volte. Gli altri errori, come un parametro che PVGIS non accetta, tornano subito. */
async function chiediPvgis(query: string, env: Env): Promise<Response> {
  for (let tentativo = 0; ; tentativo++) {
    const ultimo = tentativo === ATTESE_PVGIS_MS.length;
    try {
      const r = await fetch(`${PVGIS_URL}?${query}`, {
        headers: { Accept: "application/json", "User-Agent": userAgent(env) },
        signal: AbortSignal.timeout(TIMEOUT_PVGIS_MS),
      });
      if (r.ok || ultimo || (r.status !== 429 && r.status < 500)) return r;
    } catch (e) {
      if (ultimo) throw e;
    }
    await new Promise((fatto) => setTimeout(fatto, ATTESE_PVGIS_MS[tentativo]));
  }
}

/** GET /geo/cerca?q=…: i luoghi trovati da Nominatim, dalla cache se la stessa ricerca è già stata fatta. */
async function cercaIndirizzo(url: URL, env: Env, ctx: Contesto, origine: string | null, ammessa: boolean): Promise<Response> {
  const esito = testoRicerca(url.searchParams);
  if ("errore" in esito) return risposta(400, { errore: esito.errore }, origine, ammessa);
  const q = esito.q.toLowerCase();
  const chiave = `indirizzo:${VERSIONE_CACHE}:${q}`;
  const urlCache = `${url.origin}${url.pathname}?q=${encodeURIComponent(q)}&cache=${VERSIONE_CACHE}`;
  const durata = { "Cache-Control": `public, max-age=${DURATA_CACHE_INDIRIZZI_S}` };

  const salvata = await dallaCache(env, chiave, urlCache).catch(() => null);
  if (salvata) return new Response(salvata, { headers: intestazioni(origine, ammessa, { ...durata, "X-Cache": "HIT" }) });

  const attesa = turnoNominatim();
  if (attesa === null) return risposta(429, { errore: "troppe ricerche insieme: riprova tra qualche secondo" }, origine, ammessa, { "Retry-After": "5" });
  if (attesa > 0) await new Promise((r) => setTimeout(r, attesa));
  const query = new URLSearchParams({ q: esito.q, format: "jsonv2", addressdetails: "1", countrycodes: "it", limit: String(MAX_RISULTATI), "accept-language": "it" });
  let corpo: string;
  try {
    const nominatim = await fetch(`${NOMINATIM_URL}?${query}`, {
      headers: { Accept: "application/json", "User-Agent": userAgent(env) },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!nominatim.ok) return risposta(502, { errore: `Nominatim ha risposto ${nominatim.status}` }, origine, ammessa);
    const trovati = luoghi(await nominatim.json());
    if (!trovati) return risposta(502, { errore: "risposta di Nominatim non riconosciuta" }, origine, ammessa);
    corpo = JSON.stringify({ fonte: "OpenStreetMap Nominatim", licenza: "© OpenStreetMap contributors, ODbL", luoghi: trovati });
  } catch {
    return risposta(504, { errore: "Nominatim non risponde" }, origine, ammessa);
  }
  ctx.waitUntil(inCache(env, chiave, urlCache, corpo, DURATA_CACHE_INDIRIZZI_S).catch(() => undefined));
  return new Response(corpo, { headers: intestazioni(origine, ammessa, { ...durata, "X-Cache": "MISS" }) });
}

export default {
  async fetch(request: Request, env: Env, ctx: Contesto): Promise<Response> {
    const url = new URL(request.url);
    const origine = request.headers.get("Origin");
    const ammessa = origine !== null && originiAmmesse(env).includes(origine);
    if (origine !== null && !ammessa) return risposta(403, { errore: "origine non ammessa" }, origine, false);

    const indirizzi = url.pathname === PERCORSO_INDIRIZZI;
    if (!indirizzi && !PERCORSI.includes(url.pathname)) {
      return risposta(404, { errore: "solo /pvgis/seriescalc e /geo/cerca" }, origine, ammessa);
    }
    if (request.method === "OPTIONS") {
      const h = intestazioni(origine, ammessa, { "Access-Control-Allow-Methods": "GET", "Access-Control-Max-Age": "86400" });
      return new Response(null, { status: 204, headers: h });
    }
    if (request.method !== "GET") return risposta(405, { errore: "solo GET" }, origine, ammessa, { Allow: "GET, OPTIONS" });
    if (indirizzi) return cercaIndirizzo(url, env, ctx, origine, ammessa);

    const esito = canonica(url.searchParams);
    if ("errore" in esito) return risposta(400, { errore: esito.errore }, origine, ammessa);
    const chiave = `pvgis:${VERSIONE_CACHE}:${esito.query}`;
    const urlCache = `${url.origin}${url.pathname}?${esito.query}&cache=${VERSIONE_CACHE}`;
    const durata = { "Cache-Control": `public, max-age=${DURATA_CACHE_S}` };

    const salvata = await dallaCache(env, chiave, urlCache).catch(() => null);
    if (salvata) return new Response(salvata, { headers: intestazioni(origine, ammessa, { ...durata, "X-Cache": "HIT" }) });

    let corpo: string | null = null;
    try {
      const pvgis = await chiediPvgis(esito.query, env);
      if (!pvgis.ok) return risposta(502, { errore: `PVGIS ha risposto ${pvgis.status}` }, origine, ammessa);
      corpo = compatta(await pvgis.json(), esito.query);
    } catch {
      return risposta(504, { errore: "PVGIS non risponde" }, origine, ammessa);
    }
    if (!corpo) return risposta(502, { errore: "risposta di PVGIS non riconosciuta" }, origine, ammessa);
    ctx.waitUntil(inCache(env, chiave, urlCache, corpo).catch(() => undefined));
    return new Response(corpo, { headers: intestazioni(origine, ammessa, { ...durata, "X-Cache": "MISS" }) });
  },
};
