// Il ponte da Casa: il pulsante «Porta nella CER» del simulatore della casa apre questo sito con il profilo energetico
// della casa nel frammento dell'indirizzo, `#profilo-casa=z.<dati>` (JSON compresso con deflate-raw, poi base64url) oppure
// `#profilo-casa=j.<dati>` (JSON non compresso, per i browser senza CompressionStream). Il frammento non arriva mai al
// server: i dati passano da un sito all'altro dentro il browser. Formato descritto in docs/formato_profilo_energetico.md.
// Qui solo la lettura e i controlli di forma; il contenuto lo valida il motore come per un file caricato a mano.

export const CHIAVE_PONTE = "profilo-casa";
/** Lunghezza massima del frammento: un profilo vero compresso sta sotto i 30 kB. */
export const MAX_FRAMMENTO = 2_000_000;
/** Dimensione massima del JSON decompresso, come per i file dei consumi letti a mano (50 MB). */
export const MAX_JSON = 50_000_000;

export type Arrivo = { nome: string; testo: string } | { errore: string };

const FORMATI = new Map<unknown, string>([
  ["profilo-energetico", "profilo-energetico_casa.json"],
  ["curva-consumi", "curva-consumi_casa.json"],
]);

/** I dati dopo `#profilo-casa=`, oppure null se il frammento non viene da Casa. */
export function datiDelPonte(hash: string): string | null {
  const prefisso = `#${CHIAVE_PONTE}=`;
  return hash.startsWith(prefisso) ? hash.slice(prefisso.length) : null;
}

function daBase64url(testo: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]*$/.test(testo)) throw new Error("caratteri non validi");
  const b64 = testo.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((testo.length + 3) % 4);
  const binario = atob(b64);
  const byte = new Uint8Array(binario.length);
  for (let i = 0; i < binario.length; i++) byte[i] = binario.charCodeAt(i);
  return byte;
}

async function decomprimi(byte: Uint8Array): Promise<Uint8Array> {
  const flusso = new Blob([byte]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  const lettore = flusso.getReader();
  const pezzi: Uint8Array[] = [];
  let totale = 0;
  for (;;) {
    const { done, value } = await lettore.read();
    if (done) break;
    totale += value.length;
    if (totale > MAX_JSON) {
      await lettore.cancel();
      throw new Error("troppo grande");
    }
    pezzi.push(value);
  }
  const tutto = new Uint8Array(totale);
  let pos = 0;
  for (const p of pezzi) {
    tutto.set(p, pos);
    pos += p.length;
  }
  return tutto;
}

/**
 * Legge il profilo arrivato da Casa nel frammento dell'indirizzo. Restituisce null se il frammento non è del ponte,
 * il file da dare al passo 2 se è leggibile, un errore da mostrare altrimenti.
 */
export async function leggiArrivo(hash: string): Promise<Arrivo | null> {
  const dati = datiDelPonte(hash);
  if (dati === null) return null;
  const sbagliato = { errore: "Il profilo arrivato da Casa non si legge: scaricalo da Casa e caricalo al passo 2." };
  if (dati.length > MAX_FRAMMENTO) return { errore: "Il profilo arrivato da Casa è troppo grande: scaricalo da Casa e caricalo al passo 2." };
  const [tipo, corpo] = [dati.slice(0, 2), dati.slice(2)];
  try {
    let byte = daBase64url(corpo);
    if (tipo === "z.") {
      if (typeof DecompressionStream !== "function") {
        return { errore: "Questo browser non sa leggere il profilo arrivato da Casa: scaricalo da Casa e caricalo al passo 2." };
      }
      byte = await decomprimi(byte);
    } else if (tipo !== "j.") return sbagliato;
    if (byte.length > MAX_JSON) return sbagliato;
    const testo = new TextDecoder("utf-8", { fatal: true }).decode(byte);
    const json: unknown = JSON.parse(testo);
    const formato = json && typeof json === "object" && !Array.isArray(json) ? (json as { formato?: unknown }).formato : undefined;
    const nome = FORMATI.get(formato);
    return nome ? { nome, testo } : sbagliato;
  } catch {
    return sbagliato;
  }
}
