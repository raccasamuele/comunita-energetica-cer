/// <reference lib="webworker" />
// Il motore cersim in Pyodide, fuori dal thread dell'interfaccia: un'analisi dura secondi e non deve bloccare la
// pagina. Nessuna rete da Python: le serie PVGIS arrivano già scaricate nel messaggio "analizza".

import { loadPyodide, version, type PyodideInterface } from "pyodide";
import type { AlMotore, DaMotore, RichiestaPvgis, Risultato } from "./contratto";

const INDICE_PYODIDE = `https://cdn.jsdelivr.net/pyodide/v${version}/full/`;
const PACCHETTI = ["numpy", "pandas", "pydantic", "pyyaml", "tzdata", "requests"];

let motore: Promise<PyodideInterface> | null = null;
let baseMotore = ""; // la cartella motore/ del sito, da cui arrivano anche i file dei report
let pacchettiReport: Promise<void> | null = null;
const invia = (messaggio: DaMotore) => self.postMessage(messaggio);
const secondi = (da: number) => Math.round(performance.now() - da) / 1000;

function megabyteScaricati(): number {
  const voci = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
  // transferSize è 0 per le risposte da cache o da un'altra origine senza Timing-Allow-Origin: si usa il corpo
  const byte = voci.reduce((s, v) => s + (v.transferSize || v.encodedBodySize || 0), 0);
  return Math.round(byte / 1e5) / 10;
}

async function avvia(sorgenti: string): Promise<PyodideInterface> {
  let t = performance.now();
  invia({ tipo: "stato", fase: "Avvio di Python" });
  const py = await loadPyodide({ indexURL: INDICE_PYODIDE });
  const python_s = secondi(t);

  t = performance.now();
  invia({ tipo: "stato", fase: "Pacchetti di calcolo" });
  await py.loadPackage(PACCHETTI, { messageCallback: () => {} });
  const pacchetti_s = secondi(t);

  t = performance.now();
  invia({ tipo: "stato", fase: "Motore cersim" });
  baseMotore = new URL(".", sorgenti).href;
  const risposta = await fetch(sorgenti);
  if (!risposta.ok) throw new Error(`Sorgenti del motore non disponibili (HTTP ${risposta.status})`);
  const file = (await risposta.json()) as Record<string, string>;
  for (const [percorso, testo] of Object.entries(file)) {
    const destinazione = `/home/pyodide/${percorso}`;
    py.FS.mkdirTree(destinazione.slice(0, destinazione.lastIndexOf("/")));
    py.FS.writeFile(destinazione, testo);
  }
  await py.runPythonAsync("import sys, json\nsys.path.insert(0, '/home/pyodide')\nimport cersim, cersim.web");
  const versione = String(py.runPython("cersim.__version__"));
  invia({
    tipo: "pronto",
    avvio: { motore: versione, pyodide: version, python_s, pacchetti_s, cersim_s: secondi(t), scaricati_mb: megabyteScaricati() },
  });
  return py;
}

/** Solo per i report PDF ed Excel (cersim.report): matplotlib dalla CDN di Pyodide, fpdf2 e openpyxl dal sito
 * (motore/pacchetti/, vite.config.ts) e i caratteri Geist in static/, dove li cerca cersim. Una volta sola. */
async function preparaReport(py: PyodideInterface): Promise<void> {
  const elenco = (await (await fetch(new URL("report.json", baseMotore))).json()) as { pacchetti: string[]; font: string[] };
  await py.loadPackage(["matplotlib", "micropip"], { messageCallback: () => {} });
  const indirizzi = elenco.pacchetti.map((f) => new URL(`pacchetti/${f}`, baseMotore).href);
  const spazio = py.toPy({ indirizzi });
  try {
    await py.runPythonAsync(["import micropip", "await micropip.install(indirizzi, deps=False)"].join("\n"), { globals: spazio });
  } finally {
    spazio.destroy();
  }
  py.FS.mkdirTree("/home/pyodide/static");
  for (const f of elenco.font) {
    const r = await fetch(new URL(`font/${f}`, baseMotore));
    if (!r.ok) throw new Error(`Carattere ${f} non disponibile (HTTP ${r.status})`);
    py.FS.writeFile(`/home/pyodide/static/${f}`, new Uint8Array(await r.arrayBuffer()));
  }
}

/** Esegue `codice` con le variabili date e restituisce l'ultima espressione, che deve essere un testo JSON. */
function json<T>(py: PyodideInterface, codice: string, variabili: Record<string, string>): T {
  const spazio = py.toPy({ ...variabili, json: py.pyimport("json"), cersim: py.pyimport("cersim") });
  try {
    return JSON.parse(String(py.runPython(codice, { globals: spazio }))) as T;
  } finally {
    spazio.destroy();
  }
}

self.onmessage = async (evento: MessageEvent<AlMotore>) => {
  const m = evento.data;
  try {
    if (m.tipo === "avvia") {
      motore ??= avvia(m.sorgenti);
      await motore;
      return;
    }
    if (!motore) throw new Error("Il motore non è ancora avviato");
    const py = await motore;
    if (m.tipo === "prepara_report") {
      pacchettiReport ??= preparaReport(py).catch((e: unknown) => {
        pacchettiReport = null; // si può riprovare
        throw e;
      });
      await pacchettiReport;
      invia({ tipo: "report_pronto", id: m.id });
    } else if (m.tipo === "chiama") {
      const valore = json<unknown>(py, "cersim.web.chiama(funzione, argomenti)", { funzione: m.funzione, argomenti: m.argomenti });
      invia({ tipo: "valore", id: m.id, valore });
    } else if (m.tipo === "richieste") {
      const richieste = json<RichiestaPvgis[]>(py, "json.dumps(cersim.web.richieste_pvgis(progetto))", { progetto: m.progetto });
      invia({ tipo: "richieste", id: m.id, richieste });
    } else {
      const t = performance.now();
      const risultato = json<Risultato>(
        py,
        "json.dumps(cersim.web.analizza_web(progetto, json.loads(serie)))",
        { progetto: m.progetto, serie: JSON.stringify(m.serie) },
      );
      invia({ tipo: "risultato", id: m.id, risultato, secondi: secondi(t) });
    }
  } catch (e) {
    if (m.tipo === "avvia") motore = null; // si può riprovare
    invia({ tipo: "errore", id: "id" in m ? m.id : undefined, messaggio: e instanceof Error ? e.message : String(e) });
  }
};
