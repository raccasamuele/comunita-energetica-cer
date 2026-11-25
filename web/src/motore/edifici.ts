// Edifici vicini al tetto del passo 3, per stimare le ombre: il browser chiede a Overpass di OpenStreetMap la stessa
// cosa di cersim (cersim/tetto.py, scarica_edifici), cioè le sagome `building` entro 150 m con altezza, piani e forma
// del tetto. Overpass manda le intestazioni CORS e una POST di modulo non chiede il permesso preliminare, quindi non
// serve l'intermediario: e passando da Cloudflare non funziona, perché Overpass divide i posti in coda per indirizzo
// IP e quelli dei Worker sono condivisi da moltissimi siti (prova dal vivo del 29/10/2026). Esce solo il punto del
// tetto, arrotondato a circa 10 metri; la risposta va al motore, che ne legge le sagome (tetto.edifici_da_osm).

// server pubblici di Overpass, in ordine: il primo è il principale, il secondo è un'alternativa volontaria
const OVERPASS_URL = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.private.coffee/api/interpreter",
];
const RAGGIO_M = 150; // come tetto.RAGGIO_M
// i server pubblici sono spesso pieni: il 29/10/2026 overpass-api.de ha risposto dopo 33–55 s anche a domande
// piccole (è la coda, non il lavoro), e le alternative non hanno risposto. Intanto la pagina resta usabile.
// Il primo server ha il tempo di quelle risposte; se resta appeso, il secondo ha ancora 30 s invece di 10.
const TIMEOUT_MS = 60_000; // per server
const TEMPO_MS = 90_000; // in tutto, poi si rinuncia: chi aspetta sceglie le ombre a mano

/** La domanda per Overpass, uguale a quella di cersim, con il punto arrotondato a 0,0001°. */
export function domandaOverpass(lat: number, lon: number): string {
  const attorno = `(around:${RAGGIO_M},${lat.toFixed(4)},${lon.toFixed(4)})`;
  return `[out:json][timeout:15];(way["building"]${attorno};relation["building"]${attorno};);out geom;`;
}

/** Gli elementi di Overpass attorno al tetto, da passare al motore; un errore leggibile se nessun server risponde. */
export async function edificiVicini(lat: number, lon: number): Promise<unknown[]> {
  const corpo = new URLSearchParams({ data: domandaOverpass(lat, lon) }).toString();
  const fine = Date.now() + TEMPO_MS;
  for (const server of OVERPASS_URL) {
    const resta = fine - Date.now();
    if (resta < 1_000) break;
    try {
      const r = await fetch(server, {
        method: "POST",
        body: corpo,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        signal: AbortSignal.timeout(Math.min(TIMEOUT_MS, resta)),
      });
      if (!r.ok) continue; // pieno (429, 504) o rifiuta: il prossimo
      const elementi = ((await r.json()) as { elements?: unknown })?.elements;
      if (Array.isArray(elementi)) return elementi;
    } catch {
      // non risponde in tempo o la rete manca: il prossimo
    }
  }
  throw new Error("OpenStreetMap non risponde in questo momento");
}
