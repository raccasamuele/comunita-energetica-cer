// Prova di fattibilità: il motore cersim in Pyodide, senza interfaccia.
//
//   cd web && npm install && npm run prova:pyodide
//
// Carica Pyodide (versione fissata in package.json), i pacchetti del motore e i sorgenti di cersim, poi simula il
// caso di Torino di esempi/caso_studio_torino.py come lo farebbe il Web Worker: prima chiede quali serie PVGIS
// servono, poi le passa già scaricate. Al posto dell'intermediario usa la cache locale di cersim
// (~/.cache/cersim/pvgis, o CERSIM_CACHE_DIR); una serie che manca diventa il profilo semplificato (qualità C).
// Infine prova report PDF ed Excel, con fpdf2 e openpyxl da PyPI tramite micropip. Stampa le misure in JSON.
// Per misurare il primo caricamento cancellare prima node_modules/.pyodide-pacchetti.

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide, version } from "pyodide";

const RADICE = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const PACCHETTI_PYODIDE = join(RADICE, "web", "node_modules", ".pyodide-pacchetti");
const MOTORE = ["numpy", "pandas", "pydantic", "pyyaml", "tzdata", "requests"];
const REPORT = ["matplotlib", "pillow", "fonttools", "micropip"];
const DA_PYPI = ["fpdf2", "openpyxl"];
const CACHE_PVGIS = process.env.CERSIM_CACHE_DIR
  ? join(process.env.CERSIM_CACHE_DIR, "pvgis")
  : join(homedir(), ".cache", "cersim", "pvgis");

const misure = { pyodide: version };
const ora = () => performance.now();
const secondi = (t) => Math.round(ora() - t) / 1000;
const mb = (byte) => Math.round(byte / 1e5) / 10;

function file(cartella, filtro) {
  return readdirSync(cartella, { withFileTypes: true }).flatMap((voce) => {
    const percorso = join(cartella, voce.name);
    if (voce.isDirectory()) return voce.name === "__pycache__" ? [] : file(percorso, filtro);
    return filtro.test(voce.name) ? [percorso] : [];
  });
}

/** Byte delle ruote di Pyodide caricate finora (dalla cartella in cui Node le scarica). */
function bytePacchetti(pyodide) {
  const lock = JSON.parse(readFileSync(join(RADICE, "web", "node_modules", "pyodide", "pyodide-lock.json"), "utf8"));
  return Object.keys(pyodide.loadedPackages)
    .map((nome) => lock.packages[nome]?.file_name)
    .filter((f) => f && existsSync(join(PACCHETTI_PYODIDE, f)))
    .reduce((s, f) => s + statSync(join(PACCHETTI_PYODIDE, f)).size, 0);
}

const nucleo = ["pyodide.asm.wasm", "pyodide.asm.mjs", "python_stdlib.zip", "pyodide-lock.json"]
  .map((f) => statSync(join(RADICE, "web", "node_modules", "pyodide", f)).size)
  .reduce((a, b) => a + b, 0);
misure.nucleo_mb = mb(nucleo);

let t = ora();
const pyodide = await loadPyodide({ packageCacheDir: PACCHETTI_PYODIDE });
misure.avvio_s = secondi(t);

t = ora();
await pyodide.loadPackage(MOTORE, { messageCallback: () => {} });
misure.pacchetti_motore_s = secondi(t);
misure.pacchetti_motore_mb = mb(bytePacchetti(pyodide));

t = ora();
const sorgenti = file(join(RADICE, "cersim"), /\.(py|yaml)$/);
for (const percorso of [...sorgenti, join(RADICE, "esempi", "caso_studio_torino.py")]) {
  const destinazione = "/home/pyodide/" + relative(RADICE, percorso).replaceAll("\\", "/");
  pyodide.FS.mkdirTree(dirname(destinazione));
  pyodide.FS.writeFile(destinazione, readFileSync(percorso));
}
misure.sorgenti_kb = Math.round(sorgenti.reduce((s, p) => s + statSync(p).size, 0) / 1000);
await pyodide.runPythonAsync(`
import sys
sys.path[:0] = ["/home/pyodide", "/home/pyodide/esempi"]
import cersim.web
`);
misure.import_cersim_s = secondi(t);

t = ora();
const richieste = JSON.parse(await pyodide.runPythonAsync(`
import json
from caso_studio_torino import tabelle
from cersim.ui_model import configurazione_da_tabelle, esporta_json
esito = configurazione_da_tabelle(*tabelle("CER"))
progetto = esporta_json(esito.config, {"quota_membri": 0.5})
json.dumps(cersim.web.richieste_pvgis(progetto))
`));
const serie = {};
for (const { chiave } of richieste) {
  const percorso = join(CACHE_PVGIS, chiave + ".json");
  if (existsSync(percorso)) serie[chiave] = JSON.parse(readFileSync(percorso, "utf8"));
}
misure.serie_pvgis = `${Object.keys(serie).length} di ${richieste.length} dalla cache locale`;
pyodide.globals.set("serie_json", JSON.stringify(serie));
const risultato = JSON.parse(await pyodide.runPythonAsync(`
json.dumps(cersim.web.analizza_web(progetto, json.loads(serie_json)))
`));
misure.analisi_s = secondi(t);

t = ora();
await pyodide.runPythonAsync(`cersim.web.analizza_web(progetto, json.loads(serie_json))`);
misure.seconda_analisi_s = secondi(t);
misure.risultato = {
  ok: risultato.ok,
  qualita: risultato.qualita,
  fonti_pv: risultato.fonti_pv,
  energia_condivisa_kwh: risultato.bande.energia_condivisa_kwh,
  tip_eur_anno: risultato.bande.tip_eur_anno,
};

// report: matplotlib e Pillow da Pyodide, fpdf2 e openpyxl (pure Python) da PyPI
t = ora();
const primaDelReport = bytePacchetti(pyodide);
await pyodide.loadPackage(REPORT, { messageCallback: () => {} });
for (const percorso of file(join(RADICE, "static"), /^Geist-.*\.ttf$/)) {
  pyodide.FS.mkdirTree("/home/pyodide/static");
  pyodide.FS.writeFile("/home/pyodide/static/" + relative(join(RADICE, "static"), percorso), readFileSync(percorso));
}
try {
  await pyodide.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(DA_PYPI)})
`);
  misure.pacchetti_report_s = secondi(t);
  misure.pacchetti_report_mb = mb(bytePacchetti(pyodide) - primaDelReport);
  t = ora();
  const [pdf, xlsx] = (await pyodide.runPythonAsync(`
from cersim.analisi import analizza
from cersim.economics import ParametriEconomici
from cersim.report import report_excel, report_pdf
params = ParametriEconomici(quota_membri=0.5)
analisi = analizza(esito.config, params, fetch_pv=cersim.web.fetch_da_serie(json.loads(serie_json)))
[len(report_pdf(analisi, params)), len(report_excel(analisi, params))]
`)).toJs();
  misure.report_s = secondi(t);
  misure.report = { pdf_kb: Math.round(pdf / 1000), excel_kb: Math.round(xlsx / 1000) };
} catch (e) {
  misure.report_errore = String(e).split("\n").slice(-3).join(" ");
}

misure.memoria_wasm_mb = mb(pyodide._module.HEAPU8.length);
console.log(JSON.stringify(misure, null, 2));
