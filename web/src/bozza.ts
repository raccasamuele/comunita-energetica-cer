// La bozza del lavoro resta in questo browser (localStorage), così una pagina ricaricata riparte da dove si era.
// Non va a nessun server; per portarla altrove si esporta il file di salvataggio (cersim.ui_model.esporta_json).

import type { Tabelle } from "./motore/contratto";

const CHIAVE = "cersim:bozza:v1";

export function bozzaVuota(): Tabelle {
  return {
    generale: { nome: "", tipo: "gruppo", indirizzo: "", lat: 45.07, lon: 7.69, regione: "Piemonte", data_costituzione: null },
    punti: [],
    impianti: [],
    curve: {},
    parametri: {},
    base: null,
  };
}

/** La bozza salvata, o null se non c'è o non si legge (navigazione privata, dati cancellati, formato vecchio). */
export function leggiBozza(): Tabelle | null {
  try {
    const testo = window.localStorage.getItem(CHIAVE);
    if (!testo) return null;
    const dati = JSON.parse(testo) as { versione?: number; tabelle?: Tabelle };
    const t = dati.versione === 1 ? dati.tabelle : undefined;
    if (!t?.generale || !Array.isArray(t.punti) || !Array.isArray(t.impianti)) return null;
    return { ...bozzaVuota(), ...t };
  } catch {
    return null;
  }
}

/** Salva la bozza; false se il browser non lo permette o lo spazio non basta (molte curve orarie). */
export function salvaBozza(tabelle: Tabelle): boolean {
  try {
    window.localStorage.setItem(CHIAVE, JSON.stringify({ versione: 1, salvata: new Date().toISOString(), tabelle }));
    return true;
  } catch {
    return false;
  }
}

export function cancellaBozza() {
  try {
    window.localStorage.removeItem(CHIAVE);
  } catch {
    // niente da cancellare
  }
}

/** Nome del file di salvataggio dal nome della configurazione. */
export function nomeFile(nome: string): string {
  const base = nome.normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return `${(base || "configurazione").slice(0, 60)}.json`;
}

/** Contenuto di un file come base64, per passarlo al motore. */
export async function base64(file: File): Promise<string> {
  const byte = new Uint8Array(await file.arrayBuffer());
  let testo = "";
  for (let i = 0; i < byte.length; i += 0x8000) testo += String.fromCharCode(...byte.subarray(i, i + 0x8000));
  return btoa(testo);
}

/** Scarica un file arrivato dal motore in base64 (report, scheda da stampare). */
export function scaricaBase64(dati: string, nome: string, tipo: string) {
  const byte = Uint8Array.from(atob(dati), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([byte], { type: tipo }));
  Object.assign(document.createElement("a"), { href: url, download: nome }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
