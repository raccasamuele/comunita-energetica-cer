import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, relative, resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const RADICE = resolve(__dirname, "..");

/** Sorgenti del motore (cersim/*.py e i dati YAML) come un solo JSON {percorso: testo}: il Worker li scrive nel
 * file system di Pyodide. Niente da installare: sono gli stessi file dell'app Streamlit e dei test. */
function sorgentiCersim(): string {
  const file: Record<string, string> = {};
  const visita = (cartella: string) => {
    for (const voce of readdirSync(cartella, { withFileTypes: true })) {
      const percorso = join(cartella, voce.name);
      if (voce.isDirectory()) {
        if (voce.name !== "__pycache__") visita(percorso);
      } else if (/\.(py|yaml)$/.test(voce.name)) {
        file[relative(RADICE, percorso).replaceAll("\\", "/")] = readFileSync(percorso, "utf8");
      }
    }
  };
  visita(join(RADICE, "cersim"));
  return JSON.stringify(file);
}

/** Licenza e crediti del sito: la licenza MIT con i componenti e i dati di terzi (LICENZA.md) e il testo della licenza. */
function licenza(): string {
  return `${readFileSync(join(RADICE, "LICENZA.md"), "utf8")}\n\n---\n\n${readFileSync(join(RADICE, "LICENSE"), "utf8")}`;
}

const CHIAVE_PVGIS = /^pvgis_[-\d.]+_[-\d.]+_t[-\d.]+_a[-\d.]+_l[-\d.]+_\d{4}$/;

/** Pacchetti Python dei report PDF ed Excel che Pyodide non ha (cersim.report: fpdf2, openpyxl): wheel puri,
 * versioni come nell'ambiente di sviluppo, controllati con l'hash di PyPI. Si scaricano una volta in .pacchetti/ e il
 * sito li serve da sé, in motore/pacchetti/: il Worker li installa solo quando si chiede un report. */
const PACCHETTI_REPORT: { file: string; url: string; sha256: string }[] = [
  { file: "fpdf2-2.8.9-py3-none-any.whl", sha256: "6e1d94af6d6311950a23dec7fb5fc84b000203eb59aee8e76c1e701b12a14976",
    url: "https://files.pythonhosted.org/packages/41/16/42cc18bba1561692a235fd232b38947e54f059150065d43d631b57a0085a/fpdf2-2.8.9-py3-none-any.whl" },
  { file: "defusedxml-0.7.1-py2.py3-none-any.whl", sha256: "a352e7e428770286cc899e2542b6cdaedb2b4953ff269a210103ec58f6198a61",
    url: "https://files.pythonhosted.org/packages/07/6c/aa3f2f849e01cb6a001cd8554a88d4c77c5c1a31c95bdf1cf9301e6d9ef4/defusedxml-0.7.1-py2.py3-none-any.whl" },
  { file: "openpyxl-3.1.5-py2.py3-none-any.whl", sha256: "5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2",
    url: "https://files.pythonhosted.org/packages/c0/da/977ded879c29cbd04de313843e76868e6e13408a94ed6b987245dc7c8506/openpyxl-3.1.5-py2.py3-none-any.whl" },
  { file: "et_xmlfile-2.0.0-py3-none-any.whl", sha256: "7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa",
    url: "https://files.pythonhosted.org/packages/c1/8b/5fe2cc11fee489817272089c4203e679c63b570a5aaeb18d852ae3cbba6a/et_xmlfile-2.0.0-py3-none-any.whl" },
];
const CARTELLA_PACCHETTI = resolve(__dirname, ".pacchetti");
const FONT_REPORT = ["Geist-Regular.ttf", "Geist-SemiBold.ttf"]; // cersim.report.FONT, da static/

async function scaricaPacchettiReport(): Promise<void> {
  mkdirSync(CARTELLA_PACCHETTI, { recursive: true });
  for (const p of PACCHETTI_REPORT) {
    const percorso = join(CARTELLA_PACCHETTI, p.file);
    const hash = (b: Buffer) => createHash("sha256").update(b).digest("hex");
    if (existsSync(percorso) && hash(readFileSync(percorso)) === p.sha256) continue;
    const risposta = await fetch(p.url);
    if (!risposta.ok) throw new Error(`${p.file}: PyPI ha risposto ${risposta.status}`);
    const dati = Buffer.from(await risposta.arrayBuffer());
    if (hash(dati) !== p.sha256) throw new Error(`${p.file}: hash diverso da quello atteso`);
    writeFileSync(percorso, dati);
  }
}

/** L'elenco per il Worker (motore/report.json): quali wheel installare e quali caratteri scrivere in static/. */
function elencoReport(): string {
  return JSON.stringify({ pacchetti: PACCHETTI_REPORT.map((p) => p.file), font: FONT_REPORT });
}

/** I file dei report serviti dal sito: i pacchetti e i caratteri, con il loro percorso nella build. */
function fileReport(): { nome: string; percorso: string }[] {
  return [
    ...PACCHETTI_REPORT.map((p) => ({ nome: `motore/pacchetti/${p.file}`, percorso: join(CARTELLA_PACCHETTI, p.file) })),
    ...FONT_REPORT.map((f) => ({ nome: `motore/font/${f}`, percorso: join(RADICE, "static", f) })),
  ];
}

/** Il motore servito in sviluppo e scritto nella build; in sviluppo anche la cache PVGIS locale di cersim al posto
 * dell'intermediario, che arriverà con il Worker di Cloudflare. */
function motoreCersim(): Plugin {
  const cachePvgis = join(process.env.CERSIM_CACHE_DIR ?? join(homedir(), ".cache", "cersim"), "pvgis");
  return {
    name: "motore-cersim",
    buildStart: scaricaPacchettiReport,
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? "/", "http://locale");
        if (url.pathname === "/motore/report.json") {
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(elencoReport());
          return;
        }
        const report = fileReport().find((f) => url.pathname === `/${f.nome}`);
        if (report) {
          res.setHeader("Content-Type", "application/octet-stream");
          res.end(readFileSync(report.percorso));
          return;
        }
        if (url.pathname === "/motore/cersim.json") {
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          res.end(sorgentiCersim());
          return;
        }
        if (url.pathname === "/licenza.txt") {
          res.setHeader("Content-Type", "text/plain; charset=utf-8");
          res.end(licenza());
          return;
        }
        if (url.pathname.startsWith("/pvgis-locale/")) {
          const chiave = decodeURIComponent(url.pathname.slice("/pvgis-locale/".length));
          const percorso = join(cachePvgis, `${chiave}.json`);
          if (!CHIAVE_PVGIS.test(chiave) || !existsSync(percorso)) {
            res.statusCode = 404;
            res.end();
            return;
          }
          res.setHeader("Content-Type", "application/json");
          res.end(readFileSync(percorso));
          return;
        }
        next();
      });
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "motore/cersim.json", source: sorgentiCersim() });
      this.emitFile({ type: "asset", fileName: "licenza.txt", source: licenza() });
      this.emitFile({ type: "asset", fileName: "motore/report.json", source: elencoReport() });
      for (const f of fileReport()) this.emitFile({ type: "asset", fileName: f.nome, source: readFileSync(f.percorso) });
    },
  };
}

export default defineConfig({
  plugins: [react(), motoreCersim()],
  base: "./",
  worker: { format: "es" },
  // vite preview si comporta come il dominio del sito: /pvgis e /geo vanno all'intermediario (npm run locale)
  preview: {
    proxy: {
      "/pvgis": process.env.PVGIS_LOCALE ?? "http://127.0.0.1:8787",
      "/geo": process.env.PVGIS_LOCALE ?? "http://127.0.0.1:8787",
    },
  },
  optimizeDeps: { exclude: ["pyodide"] },
});
