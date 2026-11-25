// Test della ricerca dell'indirizzo (GET /geo/cerca): Nominatim e KV finti, nessuna rete.

import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import intermediario, { type Env, type Kv } from "../src/index.ts";
import { azzeraTurni, luoghi, MAX_ATTESA_MS, MIN_INTERVALLO_MS, NOMINATIM_URL, testoRicerca, turnoNominatim } from "../src/indirizzo.ts";

const SITO = "https://cer.example.org";
const NOMINATIM = [
  {
    lat: "45.0703393", lon: "7.6869005", display_name: "Piazza Castello, Centro, Torino, Piemonte, 10122, Italia",
    address: { road: "Piazza Castello", city: "Torino", state: "Piemonte", country_code: "it" },
  },
  { lat: "41.9", lon: "12.49", display_name: "Piazza Castello, Roma, Lazio, Italia", address: { town: "Roma", state: "Lazio" } },
  { lat: "51.5", lon: "-0.12", display_name: "fuori dall'Italia", address: { state: "England" } },
];

class KvFinto implements Kv {
  dati = new Map<string, string>();
  ttl = new Map<string, number | undefined>();
  async get(k: string) { return this.dati.get(k) ?? null; }
  async put(k: string, v: string, o?: { expirationTtl?: number }) { this.dati.set(k, v); this.ttl.set(k, o?.expirationTtl); }
}

let chiamate: { url: string; ua: string | null }[] = [];
let rispostaNominatim: () => Response;
const fetchOriginale = globalThis.fetch;
beforeEach(() => {
  azzeraTurni();
  chiamate = [];
  rispostaNominatim = () => Response.json(NOMINATIM);
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    chiamate.push({ url: String(url), ua: new Headers(init?.headers).get("User-Agent") });
    return rispostaNominatim();
  }) as typeof fetch;
});
afterEach(() => {
  globalThis.fetch = fetchOriginale;
});

async function cerca(query: string, { origine = SITO as string | null, env = {} as Partial<Env>, base = "https://cer.example.org" } = {}) {
  const attese: Promise<unknown>[] = [];
  const r = await intermediario.fetch(
    new Request(`${base}/geo/cerca?${query}`, { headers: origine ? { Origin: origine } : {} }),
    { ORIGINI: SITO, ...env },
    { waitUntil: (p) => void attese.push(p) },
  );
  await Promise.all(attese);
  return r;
}

test("inoltra a Nominatim solo in Italia e risponde con i luoghi ridotti", async () => {
  const r = await cerca("q=Piazza%20Castello,%20Torino");
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("Access-Control-Allow-Origin"), SITO);
  const [chiamata] = chiamate;
  const url = new URL(chiamata.url);
  assert.equal(`${url.origin}${url.pathname}`, NOMINATIM_URL);
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    q: "Piazza Castello, Torino", format: "jsonv2", addressdetails: "1", countrycodes: "it", limit: "5", "accept-language": "it",
  });
  assert.equal(chiamata.ua, `cersim-intermediario/0.1 (simulatore CER; ${SITO})`);
  const corpo = await r.json();
  assert.match(corpo.licenza, /OpenStreetMap contributors/);
  assert.deepEqual(corpo.luoghi, [
    { descrizione: NOMINATIM[0].display_name, lat: 45.07034, lon: 7.6869, regione: "Piemonte", comune: "Torino" },
    { descrizione: NOMINATIM[1].display_name, lat: 41.9, lon: 12.49, regione: "Lazio", comune: "Roma" },
  ]);
});

test("la stessa ricerca, anche con maiuscole e spazi diversi, viene dalla cache per 30 giorni", async () => {
  const kv = new KvFinto();
  await cerca("q=Piazza Castello, Torino", { env: { PVGIS_CACHE: kv } });
  const seconda = await cerca("q=  piazza   castello, TORINO ", { env: { PVGIS_CACHE: kv } });
  assert.equal(seconda.headers.get("X-Cache"), "HIT");
  assert.equal(chiamate.length, 1);
  assert.equal([...kv.ttl.values()][0], 30 * 24 * 3600);
});

test("sul dominio del sito, dalla stessa origine, senza CORS", async () => {
  const r = await cerca("q=Via Roma 1, Torino", { origine: null });
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("Access-Control-Allow-Origin"), null);
  assert.equal((await cerca("q=Via Roma 1", { origine: "https://altro.example.com" })).status, 403);
});

test("le risposte sbagliate di Nominatim non finiscono in cache", async () => {
  const kv = new KvFinto();
  rispostaNominatim = () => new Response("occupato", { status: 503 });
  assert.equal((await cerca("q=Via Roma 1", { env: { PVGIS_CACHE: kv } })).status, 502);
  rispostaNominatim = () => Response.json({ errore: "forma diversa" });
  azzeraTurni();
  assert.equal((await cerca("q=Via Roma 1", { env: { PVGIS_CACHE: kv } })).status, 502);
  rispostaNominatim = () => { throw new TypeError("rete"); };
  azzeraTurni();
  assert.equal((await cerca("q=Via Roma 1", { env: { PVGIS_CACHE: kv } })).status, 504);
  assert.equal(kv.dati.size, 0);
});

for (const [caso, query, messaggio] of [
  ["senza testo", "", /solo il parametro q/],
  ["troppo corto", "q=ab", /da 3 a 200/],
  ["troppo lungo", `q=${"a".repeat(201)}`, /da 3 a 200/],
  ["altri parametri", "q=Via Roma&format=xml", /solo il parametro q/],
  ["parametro ripetuto", "q=Via Roma&q=Torino", /solo il parametro q/],
  ["caratteri di controllo", "q=Via%00Roma", /non ammessi/],
] as const) {
  test(`rifiuta: ${caso}`, async () => {
    const r = await cerca(query);
    assert.equal(r.status, 400);
    assert.match((await r.json()).errore, messaggio);
    assert.equal(chiamate.length, 0);
  });
}

test("al massimo una richiesta al secondo a Nominatim, e una coda breve", () => {
  assert.equal(turnoNominatim(1_000), 0);
  assert.equal(turnoNominatim(1_000), MIN_INTERVALLO_MS);
  assert.equal(turnoNominatim(1_500), 2 * MIN_INTERVALLO_MS - 500);
  let attesa: number | null = 0;
  while (attesa !== null && attesa <= MAX_ATTESA_MS) attesa = turnoNominatim(1_500);
  assert.equal(attesa, null);
});

test("luoghi e testo: casi limite", () => {
  assert.equal(luoghi({}), null);
  assert.deepEqual(luoghi([{ lat: "x", lon: "7", display_name: "a" }, { lat: "45", lon: "7" }]), []);
  assert.deepEqual(testoRicerca(new URLSearchParams("q=%20Via%20%20Roma%0A1%20")), { q: "Via Roma 1" });
});
