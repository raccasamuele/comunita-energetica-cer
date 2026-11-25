// Ricerca dell'indirizzo per il passo 1 del sito (docs/web_architettura.md, sezione 4): inoltra a Nominatim di
// OpenStreetMap, che chiede di identificare l'applicazione, al massimo una richiesta al secondo e niente
// completamento automatico (il sito cerca solo quando si preme Cerca). Qui le parti senza rete: il testo ammesso e
// la risposta ridotta a descrizione, coordinate, regione e comune.

export const NOMINATIM_URL = "https://nominatim.openstreetmap.org/search";
export const DURATA_CACHE_INDIRIZZI_S = 30 * 24 * 3600;
export const MIN_INTERVALLO_MS = 1_100; // poco più di un secondo tra due richieste a Nominatim
export const MAX_ATTESA_MS = 5_000; // oltre, la ricerca si rifiuta invece di accodarla
export const MAX_RISULTATI = 5;
const CONTROLLO = /[\u0000-\u001f\u007f]/;

/** Testo cercato, ripulito: solo il parametro `q`, da 3 a 200 caratteri, senza caratteri di controllo. */
export function testoRicerca(query: URLSearchParams): { q: string } | { errore: string } {
  const chiavi = [...query.keys()];
  if (chiavi.length !== 1 || chiavi[0] !== "q") return { errore: "serve solo il parametro q" };
  const q = query.get("q")!.replace(/\s+/g, " ").trim();
  if (CONTROLLO.test(q)) return { errore: "caratteri non ammessi" };
  if (q.length < 3 || q.length > 200) return { errore: "l'indirizzo deve avere da 3 a 200 caratteri" };
  return { q };
}

export interface Luogo {
  descrizione: string;
  lat: number;
  lon: number;
  regione: string | null; // come la scrive OpenStreetMap: il motore la riconduce ai nomi di cersim
  comune: string | null;
}

const testo = (v: unknown, max: number) => (typeof v === "string" && v.trim() ? v.trim().slice(0, max) : null);

/** I luoghi in Italia della risposta di Nominatim (`format=jsonv2`, `addressdetails=1`), o null se la forma non è
 * quella attesa. */
export function luoghi(dati: unknown): Luogo[] | null {
  if (!Array.isArray(dati)) return null;
  const trovati: Luogo[] = [];
  for (const voce of dati.slice(0, MAX_RISULTATI) as Record<string, unknown>[]) {
    const lat = Number(voce?.lat);
    const lon = Number(voce?.lon);
    const descrizione = testo(voce?.display_name, 300);
    if (!descrizione || !(lat >= 35 && lat <= 48 && lon >= 6 && lon <= 19)) continue; // come model.Configuration
    const a = (voce.address ?? {}) as Record<string, unknown>;
    trovati.push({
      descrizione,
      lat: Math.round(lat * 1e5) / 1e5,
      lon: Math.round(lon * 1e5) / 1e5,
      regione: testo(a.state, 80),
      comune: testo(a.city ?? a.town ?? a.village ?? a.municipality, 80),
    });
  }
  return trovati;
}

let prossimoTurno = 0;

/** Attesa prima della prossima richiesta a Nominatim da questa istanza del Worker, o null se la coda è troppo
 * lunga. Le istanze in data center diversi non si coordinano: va bene finché le ricerche sono poche. */
export function turnoNominatim(adesso = Date.now()): number | null {
  const attesa = Math.max(0, prossimoTurno - adesso);
  if (attesa > MAX_ATTESA_MS) return null;
  prossimoTurno = Math.max(adesso, prossimoTurno) + MIN_INTERVALLO_MS;
  return attesa;
}

/** Solo per i test. */
export function azzeraTurni() {
  prossimoTurno = 0;
}
