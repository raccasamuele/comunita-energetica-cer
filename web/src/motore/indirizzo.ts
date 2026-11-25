// Ricerca dell'indirizzo del passo 1: il browser chiede all'intermediario (GET /geo/cerca), che inoltra a Nominatim
// di OpenStreetMap (intermediario/src/indirizzo.ts). Si cerca solo quando si preme Cerca: niente completamento
// automatico, come chiede Nominatim. L'intermediario sta accanto a quello di PVGIS: con `./pvgis` sul dominio del
// sito la ricerca è `./geo/cerca`, con un indirizzo workers.dev è `<indirizzo>/geo/cerca`.

export interface LuogoTrovato {
  descrizione: string;
  lat: number;
  lon: number;
  regione: string | null; // come la scrive OpenStreetMap: il motore la riconduce ai nomi di cersim
  comune: string | null;
}

export function indirizzoRicerca(): string | null {
  const base = import.meta.env.VITE_PVGIS_INTERMEDIARIO as string | undefined;
  if (!base) return null;
  return `${base.replace(/\/$/, "").replace(/\/pvgis$/, "") || "."}/geo/cerca`;
}

/** I luoghi trovati, al massimo cinque; un errore leggibile se la ricerca non riesce. */
export async function cercaIndirizzo(testo: string): Promise<{ luoghi: LuogoTrovato[]; licenza: string }> {
  const url = indirizzoRicerca();
  if (!url) throw new Error("ricerca non disponibile in questa versione del sito");
  let risposta: Response;
  try {
    risposta = await fetch(`${url}?${new URLSearchParams({ q: testo })}`, { signal: AbortSignal.timeout(20_000) });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError")
      throw new Error("il servizio di ricerca è lento in questo momento: riprova fra poco, oppure inserisci a mano regione e coordinate");
    throw new Error("il servizio di ricerca non risponde: controlla la connessione, oppure inserisci a mano regione e coordinate");
  }
  const corpo = (await risposta.json().catch(() => null)) as { luoghi?: LuogoTrovato[]; licenza?: string; errore?: string } | null;
  if (!risposta.ok || !corpo?.luoghi) throw new Error(corpo?.errore ?? `il servizio di ricerca ha risposto ${risposta.status}`);
  return { luoghi: corpo.luoghi, licenza: corpo.licenza ?? "© OpenStreetMap contributors" };
}
