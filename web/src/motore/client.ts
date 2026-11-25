// Lato interfaccia del motore: un solo Worker per la pagina, richieste con id e promesse.

import type { AlMotore, Avvio, DaMotore, Funzioni, RichiestaPvgis, Risultato } from "./contratto";

type Attesa = { risolvi: (m: DaMotore) => void; rifiuta: (e: Error) => void };
type SenzaId<T> = T extends unknown ? Omit<T, "id"> : never;

export class Motore {
  private worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  private attese = new Map<number, Attesa>();
  private prossimo = 1;
  private avvio: Promise<Avvio> | null = null;
  private suAvvio: Attesa | null = null;

  constructor(private suStato: (fase: string) => void) {
    this.worker.onmessage = (e: MessageEvent<DaMotore>) => this.ricevi(e.data);
    this.worker.onerror = (e) => this.fallisci(new Error(e.message || "Il motore si è interrotto"));
  }

  private ricevi(m: DaMotore) {
    if (m.tipo === "stato") return this.suStato(m.fase);
    if (m.tipo === "pronto") {
      this.suAvvio?.risolvi(m);
      this.suAvvio = null;
      return;
    }
    const attesa = m.id !== undefined ? this.attese.get(m.id) : undefined;
    if (attesa && m.id !== undefined) {
      this.attese.delete(m.id);
      if (m.tipo === "errore") attesa.rifiuta(new Error(m.messaggio));
      else attesa.risolvi(m);
    } else if (m.tipo === "errore") {
      this.fallisci(new Error(m.messaggio));
    }
  }

  private fallisci(errore: Error) {
    this.suAvvio?.rifiuta(errore);
    this.suAvvio = null;
    this.avvio = null;
    for (const a of this.attese.values()) a.rifiuta(errore);
    this.attese.clear();
  }

  private invia(m: AlMotore) {
    this.worker.postMessage(m);
  }

  /** Carica Python, i pacchetti e cersim (una volta sola); i sorgenti sono il JSON della build. */
  avvia(): Promise<Avvio> {
    this.avvio ??= new Promise<DaMotore>((risolvi, rifiuta) => {
      this.suAvvio = { risolvi, rifiuta };
      this.invia({ tipo: "avvia", sorgenti: new URL("motore/cersim.json", document.baseURI).href });
    }).then((m) => (m as Extract<DaMotore, { tipo: "pronto" }>).avvio);
    return this.avvio;
  }

  private chiedi(m: SenzaId<Extract<AlMotore, { id: number }>>): Promise<DaMotore> {
    const id = this.prossimo++;
    return new Promise((risolvi, rifiuta) => {
      this.attese.set(id, { risolvi, rifiuta });
      this.invia({ ...m, id } as AlMotore);
    });
  }

  async richieste(progetto: string): Promise<RichiestaPvgis[]> {
    await this.avvia();
    const m = await this.chiedi({ tipo: "richieste", progetto });
    return (m as Extract<DaMotore, { tipo: "richieste" }>).richieste;
  }

  async analizza(progetto: string, serie: Record<string, unknown>): Promise<{ risultato: Risultato; secondi: number }> {
    await this.avvia();
    const m = (await this.chiedi({ tipo: "analizza", progetto, serie })) as Extract<DaMotore, { tipo: "risultato" }>;
    return { risultato: m.risultato, secondi: m.secondi };
  }

  /** Carica i pacchetti dei report PDF ed Excel (la prima volta, qualche secondo). */
  async preparaReport(): Promise<void> {
    await this.avvia();
    await this.chiedi({ tipo: "prepara_report" });
  }

  /** Una funzione di cersim.web (FUNZIONI), con gli argomenti per nome; aspetta che il motore sia pronto. */
  async chiama<F extends keyof Funzioni>(funzione: F, argomenti: Funzioni[F]["argomenti"]): Promise<Funzioni[F]["risultato"]> {
    await this.avvia();
    const m = (await this.chiedi({ tipo: "chiama", funzione, argomenti: JSON.stringify(argomenti) })) as Extract<DaMotore, { tipo: "valore" }>;
    return m.valore as Funzioni[F]["risultato"];
  }
}
