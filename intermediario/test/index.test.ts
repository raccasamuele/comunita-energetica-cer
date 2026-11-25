// Test dell'intermediario PVGIS con il test runner di Node: fetch verso PVGIS e KV finti, nessuna rete.

import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import intermediario, { canonica, PVGIS_URL, type Env, type Kv } from "../src/index.ts";

const SITO = "https://cer.example.org";
const BASE = "https://cersim-pvgis.example.workers.dev/seriescalc";
const VALIDA = {
  lat: "45.0703", lon: "7.6869", peakpower: "1", loss: "14", angle: "25", aspect: "10", pvcalculation: "1",
  startyear: "2023", endyear: "2023", outputformat: "json",
};

function pvgis(ore = 8760) {
  return { outputs: { hourly: Array.from({ length: ore }, (_, i) => ({ time: `2023${String(i).padStart(4, "0")}:0010`, P: i % 24 > 6 && i % 24 < 18 ? 500.5 : 0, G_i: 1 })) } };
}

class KvFinto implements Kv {
  dati = new Map<string, string>();
  ttl = new Map<string, number | undefined>();
  async get(k: string) { return this.dati.get(k) ?? null; }
  async put(k: string, v: string, o?: { expirationTtl?: number }) { this.dati.set(k, v); this.ttl.set(k, o?.expirationTtl); }
}

let chiamate: string[] = [];
let rispostaPvgis: () => Response;
const fetchOriginale = globalThis.fetch;
beforeEach(() => {
  chiamate = [];
  rispostaPvgis = () => Response.json(pvgis());
  globalThis.fetch = (async (url: string | URL | Request) => {
    chiamate.push(String(url));
    return rispostaPvgis();
  }) as typeof fetch;
});
afterEach(() => {
  globalThis.fetch = fetchOriginale;
});

async function chiedi(parametri: Record<string, string> = VALIDA, { origine = SITO as string | null, metodo = "GET", env = {} as Partial<Env>, percorso = BASE } = {}) {
  const attese: Promise<unknown>[] = [];
  const headers: Record<string, string> = origine ? { Origin: origine } : {};
  const r = await intermediario.fetch(
    new Request(`${percorso}?${new URLSearchParams(parametri)}`, { method: metodo, headers }),
    { ORIGINI: `${SITO}, http://127.0.0.1:5181`, ...env },
    { waitUntil: (p) => void attese.push(p) },
  );
  await Promise.all(attese);
  return r;
}

test("inoltra a PVGIS con la query canonica e risponde compatto con CORS", async () => {
  const r = await chiedi();
  assert.equal(r.status, 200);
  assert.equal(r.headers.get("Access-Control-Allow-Origin"), SITO);
  assert.equal(r.headers.get("Vary"), "Origin");
  assert.equal(r.headers.get("X-Cache"), "MISS");
  assert.deepEqual(chiamate, [`${PVGIS_URL}?lat=45.07&lon=7.69&peakpower=1&loss=14&angle=25&aspect=10&pvcalculation=1&startyear=2023&endyear=2023&outputformat=json`]);
  const corpo = await r.json();
  assert.equal(corpo.time.length, 8760);
  assert.equal(corpo.P[12], 500.5);
  assert.equal(corpo.parametri.lat, "45.07");
  assert.ok(!("outputs" in corpo)); // solo ore e potenze: un quinto del peso
});

test("la seconda richiesta viene dal KV, per 90 giorni", async () => {
  const kv = new KvFinto();
  await chiedi(VALIDA, { env: { PVGIS_CACHE: kv } });
  const seconda = await chiedi({ ...VALIDA, lat: "45.071" }, { env: { PVGIS_CACHE: kv } }); // stessa cella di 0,01°
  assert.equal(chiamate.length, 1);
  assert.equal(seconda.headers.get("X-Cache"), "HIT");
  assert.equal(seconda.headers.get("Access-Control-Allow-Origin"), SITO);
  assert.equal([...kv.ttl.values()][0], 90 * 24 * 3600);
});

test("le risposte sbagliate di PVGIS non finiscono in cache", async () => {
  const kv = new KvFinto();
  rispostaPvgis = () => new Response("errore", { status: 500 });
  assert.equal((await chiedi(VALIDA, { env: { PVGIS_CACHE: kv } })).status, 502);
  rispostaPvgis = () => Response.json(pvgis(100));
  assert.equal((await chiedi(VALIDA, { env: { PVGIS_CACHE: kv } })).status, 502);
  rispostaPvgis = () => { throw new TypeError("rete"); };
  assert.equal((await chiedi(VALIDA, { env: { PVGIS_CACHE: kv } })).status, 504);
  assert.equal(kv.dati.size, 0);
  assert.equal(chiamate.length, 3 + 1 + 3); // 500 e rete: tre tentativi; la risposta incompleta: uno
});

test("un rifiuto passeggero di PVGIS si riprova, un parametro rifiutato no", async () => {
  let volte = 0;
  rispostaPvgis = () => (++volte === 1 ? new Response("occupato", { status: 503 }) : Response.json(pvgis()));
  const r = await chiedi();
  assert.equal(r.status, 200);
  assert.equal(chiamate.length, 2);
  chiamate = [];
  rispostaPvgis = () => new Response("parametro non valido", { status: 400 });
  assert.equal((await chiedi()).status, 502);
  assert.equal(chiamate.length, 1);
});

for (const [caso, cambio, messaggio] of [
  ["manca un parametro", { outputformat: undefined }, /mancano: outputformat/],
  ["parametro estraneo", { browser: "1" }, /non ammessi: browser/],
  ["fuori dall'Italia", { lat: "52.5" }, /lat fuori intervallo/],
  ["anno non previsto", { startyear: "2019", endyear: "2019" }, /startyear fuori intervallo/],
  ["anni diversi", { endyear: "2022" }, /coincidere/],
  ["non numerico", { loss: "1e3" }, /loss non è un numero/],
  ["NaN", { angle: "NaN" }, /angle non è un numero/],
  ["anno non intero", { startyear: "2023.5", endyear: "2023.5" }, /intero/],
  ["potenza diversa da 1", { peakpower: "2" }, /peakpower fuori intervallo/],
  ["formato csv", { outputformat: "csv" }, /json/],
] as const) {
  test(`rifiuta: ${caso}`, async () => {
    const parametri: Record<string, string> = { ...VALIDA };
    for (const [k, v] of Object.entries(cambio)) {
      if (v === undefined) delete parametri[k];
      else parametri[k] = v;
    }
    const r = await chiedi(parametri);
    assert.equal(r.status, 400);
    assert.match((await r.json()).errore, messaggio);
    assert.equal(chiamate.length, 0);
  });
}

test("sul dominio del sito: /pvgis/seriescalc, stessa origine e senza CORS", async () => {
  const kv = new KvFinto();
  // una GET dalla stessa origine non manda l'intestazione Origin
  const prima = await chiedi(VALIDA, { origine: null, percorso: "https://cer.esempio.it/pvgis/seriescalc", env: { PVGIS_CACHE: kv } });
  assert.equal(prima.status, 200);
  assert.equal(prima.headers.get("Access-Control-Allow-Origin"), null);
  assert.equal((await prima.json()).time.length, 8760);
  const seconda = await chiedi(VALIDA, { origine: null, percorso: "https://cer.esempio.it/pvgis/seriescalc", env: { PVGIS_CACHE: kv } });
  assert.equal(seconda.headers.get("X-Cache"), "HIT");
  assert.equal(chiamate.length, 1);
});

test("parametri ripetuti", () => {
  const q = new URLSearchParams(VALIDA);
  q.append("lat", "40");
  assert.deepEqual(canonica(q), { errore: "parametri ripetuti" });
});

test("origini, metodi e percorsi", async () => {
  const estranea = await chiedi(VALIDA, { origine: "https://altro.example.com" });
  assert.equal(estranea.status, 403);
  assert.equal(estranea.headers.get("Access-Control-Allow-Origin"), null);

  const senzaOrigine = await chiedi(VALIDA, { origine: null }); // curl o un test: si serve, ma senza CORS
  assert.equal(senzaOrigine.status, 200);
  assert.equal(senzaOrigine.headers.get("Access-Control-Allow-Origin"), null);

  const preflight = await chiedi(VALIDA, { metodo: "OPTIONS" });
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get("Access-Control-Allow-Methods"), "GET");

  assert.equal((await chiedi(VALIDA, { metodo: "POST" })).status, 405);
  assert.equal((await chiedi(VALIDA, { percorso: "https://cersim-pvgis.example.workers.dev/pvgis/altro" })).status, 404);
  assert.equal((await chiedi(VALIDA, { percorso: "https://cersim-pvgis.example.workers.dev/altro" })).status, 404);
  assert.equal(chiamate.length, 1);
});
