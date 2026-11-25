// L'intermediario in Node, per provare il sito in locale con PVGIS vero, senza account Cloudflare:
//
//   npm run locale                       # http://127.0.0.1:8787/seriescalc e /geo/cerca
//   ORIGINI=http://127.0.0.1:5181 npm run locale
//
// Un KV in memoria fa da cache finché il processo resta acceso. Per la prova nel runtime di Cloudflare: npm run dev.

import { createServer } from "node:http";
import intermediario, { type Kv } from "../src/index.ts";

const PORTA = Number(process.env.PORTA ?? 8787);
const memoria = new Map<string, string>();
const kv: Kv = { get: async (k) => memoria.get(k) ?? null, put: async (k, v) => void memoria.set(k, v) };
const env = { ORIGINI: process.env.ORIGINI ?? "http://127.0.0.1:5181,http://localhost:5181", PVGIS_CACHE: kv };

createServer(async (req, res) => {
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) if (typeof v === "string") headers.set(k, v);
  const risposta = await intermediario.fetch(
    new Request(`http://127.0.0.1:${PORTA}${req.url}`, { method: req.method, headers }),
    env,
    { waitUntil: () => {} },
  );
  res.writeHead(risposta.status, Object.fromEntries(risposta.headers));
  res.end(Buffer.from(await risposta.arrayBuffer()));
}).listen(PORTA, "127.0.0.1", () =>
  console.log(`Intermediario su http://127.0.0.1:${PORTA}: PVGIS su /seriescalc, indirizzi su /geo/cerca`),
);
