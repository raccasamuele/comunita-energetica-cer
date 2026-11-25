// La scheda dei consumi che una famiglia o un'attività compila dal link e manda a chi coordina (cersim.guida).
// La pagina è leggera e non avvia il motore Python, salvo per i file orari: per questo i controlli semplici sono
// ripetuti qui, con gli stessi messaggi di `guida.controlla`. Testi e soglie vengono da testi.json, che si rigenera
// con `python -m cersim.web` e che tests/test_web.py confronta con il motore. Quando chi coordina carica la scheda,
// il motore la ricontrolla tutta (`cersim.web.leggi_schede`).

import testi from "./testi.json";
import type { ConsumiOrari } from "../motore/contratto";

export { testi };

export interface ContatoreScheda {
  nome: string;
  tipologia: string | null;
  kwh_annui: number | null;
  f1_kwh: number | null;
  f23_kwh: number | null;
  tensione: "BT" | "MT";
  curva: ConsumiOrari | null; // facoltativa: forma media dei consumi misurati, senza POD
}

export interface Scheda {
  membro: string;
  tipo_soggetto: string | null;
  contatori: ContatoreScheda[];
  configurazione: string | null; // a chi è destinata, dal link
}

const migliaia = (x: number) => x.toLocaleString("it-IT", { maximumFractionDigits: 0, useGrouping: "always" });

function numero(valore: number | null, nome: string, errori: string[]): number | null {
  if (valore == null) return null;
  if (!Number.isFinite(valore)) {
    errori.push(`${nome}: serve un numero`);
    return null;
  }
  if (valore < 0 || valore > testi.max_kwh) {
    errori.push(`${nome}: valore fuori scala`);
    return null;
  }
  return valore;
}

/** Errori in italiano, comprensibili da chi compila; lista vuota = scheda pronta. Come `guida.controlla`. */
export function controlla(s: Scheda): string[] {
  const errori: string[] = [];
  if (!s.membro.trim()) errori.push("Scrivi il nome con cui vuoi comparire");
  else if (s.membro.length > testi.max_testo) errori.push(`Il nome è troppo lungo (massimo ${testi.max_testo} caratteri)`);
  if (!s.tipo_soggetto) errori.push("Scegli che tipo di soggetto sei");
  if (s.contatori.length < 1 || s.contatori.length > testi.max_contatori) errori.push(`Indica da 1 a ${testi.max_contatori} contatori`);
  const nomi = s.contatori.map((c) => c.nome.trim());
  if (new Set(nomi).size !== nomi.length) errori.push("Dai un nome diverso a ogni contatore");
  s.contatori.forEach((c, i) => {
    const chi = s.contatori.length > 1 ? `Contatore ${i + 1}` : "Contatore";
    if (!c.nome.trim() || c.nome.length > testi.max_testo) errori.push(`${chi}: scrivi un nome breve`);
    if (!c.tipologia) errori.push(`${chi}: scegli il tipo di consumo`);
    const kwh = numero(c.kwh_annui, `${chi}, consumo annuo`, errori);
    const f1 = numero(c.f1_kwh, `${chi}, F1`, errori);
    const f23 = numero(c.f23_kwh, `${chi}, F2+F3`, errori);
    if ((f1 === null) !== (f23 === null)) {
      errori.push(`${chi}: indica sia F1 sia F2+F3, oppure lascia vuote tutte e due`);
    } else if (f1 !== null && f23 !== null && kwh) {
      const somma = f1 + f23;
      if (Math.abs(somma - kwh) > testi.scarto_fasce * kwh) {
        errori.push(
          `${chi}: F1 più F2+F3 fa ${migliaia(somma)} kWh, molto diverso dal consumo annuo di ${migliaia(kwh)} kWh. ` +
            "Forse sono i consumi di una sola bolletta: usa i consumi dell'anno oppure lascia vuote le fasce.",
        );
      }
    }
  });
  return errori;
}

/** Il file da mandare, nel formato di `guida.crea_scheda`. */
export function creaScheda(s: Scheda, oggi = new Date()): string {
  const data = `${oggi.getFullYear()}-${String(oggi.getMonth() + 1).padStart(2, "0")}-${String(oggi.getDate()).padStart(2, "0")}`;
  return JSON.stringify(
    {
      formato: testi.formato,
      versione: testi.versione,
      configurazione: s.configurazione,
      compilata_il: data,
      membro: s.membro.trim(),
      tipo_soggetto: s.tipo_soggetto,
      contatori: s.contatori.map((c) => ({
        nome: c.nome.trim(),
        tipologia: c.tipologia,
        kwh_annui: c.kwh_annui,
        f1_kwh: c.f1_kwh,
        f23_kwh: c.f23_kwh,
        tensione: c.tensione,
        curva: c.curva?.curva ?? null,
      })),
    },
    null,
    2,
  );
}

/** Nome del file, come `guida.nome_file`. */
export function nomeFileScheda(membro: string): string {
  const base = membro.normalize("NFKD").replace(/[^\x00-\x7f]/g, "").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase().slice(0, 40);
  return `consumi_${base || "scheda"}.json`;
}

/** Il link da girare a famiglie e attività, come `guida.link_famiglie`: questa pagina con ?modulo=famiglia. */
export function linkFamiglie(configurazione: string): string {
  const url = new URL(window.location.pathname, window.location.origin);
  const parametri = new URLSearchParams({ modulo: testi.modulo });
  if (configurazione.trim()) parametri.set("per", configurazione.trim().slice(0, testi.max_testo));
  url.search = parametri.toString();
  return url.href;
}

/** Il modulo da aprire, dal parametro ?modulo= dell'indirizzo. */
export const apreLaScheda = () => new URLSearchParams(window.location.search).get("modulo") === testi.modulo;
