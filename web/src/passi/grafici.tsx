// Grafici del passo 5 in SVG semplice, senza librerie: linee, barre impilate e il grafico a tornado della
// sensibilità. Ogni grafico ha la legenda, una descrizione per chi usa un lettore di schermo e la tabella dei valori
// sotto "Mostra i dati", al posto del "Mostra i dati" di Streamlit.

import type { ReactNode } from "react";
import { scriviNumero } from "./campi";
import { Scorrevole } from "../ui/scorrevole";

export interface Serie {
  nome: string;
  colore: string;
  valori: (number | null)[];
}

const L = 680, A = 270, SX = 64, DX = 16, SU = 14, GIU = 40;

function scala(min: number, max: number, da: number, a: number) {
  const ampiezza = max - min || 1;
  return (v: number) => da + ((v - min) / ampiezza) * (a - da);
}

/** Tre o quattro valori tondi per l'asse, compreso lo zero se è nell'intervallo. */
function tacche(min: number, max: number): number[] {
  const passo = 10 ** Math.floor(Math.log10(Math.max(Math.abs(max - min), 1e-9) / 3));
  const tondo = [1, 2, 5, 10].map((m) => m * passo).find((p) => (max - min) / p <= 5) ?? passo * 10;
  const fuori: number[] = [];
  for (let v = Math.ceil(min / tondo) * tondo; v <= max + 1e-9; v += tondo) fuori.push(Math.round(v / tondo) * tondo);
  return fuori;
}

function Legenda({ serie }: { serie: Serie[] }) {
  return (
    <div className="legend" aria-hidden="true">
      {serie.map((s) => <span key={s.nome}><i style={{ background: s.colore }} />{s.nome}</span>)}
    </div>
  );
}

function Dati({ intestazione, righe, formato }: { intestazione: string[]; righe: (string | number | null)[][]; formato: (v: number) => string }) {
  return (
    <details className="advanced dati-grafico">
      <summary>Mostra i dati</summary>
      <Scorrevole className="table-wrap" etichetta="Dati del grafico">
        <table className="data">
          <thead><tr>{intestazione.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
          <tbody>
            {righe.map((r, i) => (
              <tr key={i}>{r.map((v, j) => <td key={j}>{typeof v === "number" && j > 0 ? formato(v) : v ?? "–"}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </Scorrevole>
    </details>
  );
}

function Figura({ descrizione, didascalia, children }: { descrizione: string; didascalia?: ReactNode; children: ReactNode }) {
  return (
    <figure className="chart grafico">
      {children}
      <figcaption className="small muted">{didascalia ?? descrizione}</figcaption>
    </figure>
  );
}

/** Il disegno, che sul telefono scorre di lato invece di rimpicciolire le scritte. */
function Disegno({ children }: { children: ReactNode }) {
  return (
    <>
      <Scorrevole className="grafico-scroll" etichetta="Grafico">{children}</Scorrevole>
      <p className="scorri small muted">Scorri il grafico di lato per vedere tutti i valori.</p>
    </>
  );
}

export function Linee({ x, serie, formato, etichettaX, descrizione, didascalia, zero = false }: {
  x: (number | string)[];
  serie: Serie[];
  formato: (v: number) => string;
  etichettaX: string;
  descrizione: string;
  didascalia?: ReactNode;
  zero?: boolean;
}) {
  const tutti = serie.flatMap((s) => s.valori.filter((v): v is number => v !== null));
  if (tutti.length === 0) return null;
  const min = Math.min(zero ? 0 : Infinity, ...tutti), max = Math.max(zero ? 0 : -Infinity, ...tutti);
  const sx = scala(0, x.length - 1, SX, L - DX), sy = scala(min, max, A - GIU, SU);
  const ogni = Math.max(1, Math.ceil(x.length / 8));
  return (
    <Figura descrizione={descrizione} didascalia={didascalia}>
      <Legenda serie={serie} />
      <Disegno><svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label={descrizione}>
        {tacche(min, max).map((t) => (
          <g key={t}>
            <line x1={SX} x2={L - DX} y1={sy(t)} y2={sy(t)} className={t === 0 ? "asse-zero" : "griglia"} />
            <text x={SX - 6} y={sy(t) + 4} textAnchor="end">{formato(t)}</text>
          </g>
        ))}
        {x.map((v, i) => (i % ogni === 0 || i === x.length - 1) && (
          <text key={i} x={sx(i)} y={A - 22} textAnchor={i === x.length - 1 ? "end" : i === 0 ? "start" : "middle"}>{v}</text>
        ))}
        <text x={L - DX} y={A - 4} textAnchor="end" className="titolo-asse">{etichettaX}</text>
        {serie.map((s) => (
          <polyline key={s.nome} fill="none" stroke={s.colore} strokeWidth={2.2}
            points={s.valori.map((v, i) => (v === null ? null : `${sx(i)},${sy(v)}`)).filter(Boolean).join(" ")} />
        ))}
      </svg></Disegno>
      <Dati intestazione={[etichettaX, ...serie.map((s) => s.nome)]} formato={formato}
        righe={x.map((v, i) => [v, ...serie.map((s) => s.valori[i])])} />
    </Figura>
  );
}

export function BarreImpilate({ categorie, serie, formato, descrizione, didascalia }: {
  categorie: string[];
  serie: Serie[];
  formato: (v: number) => string;
  descrizione: string;
  didascalia?: ReactNode;
}) {
  const totali = categorie.map((_, i) => serie.reduce((t, s) => t + Math.max(0, s.valori[i] ?? 0), 0));
  const max = Math.max(...totali, 1);
  const sy = scala(0, max, A - GIU, SU);
  const passo = (L - SX - DX) / categorie.length, larga = passo * 0.62;
  return (
    <Figura descrizione={descrizione} didascalia={didascalia}>
      <Legenda serie={serie} />
      <Disegno><svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label={descrizione}>
        {tacche(0, max).map((t) => (
          <g key={t}>
            <line x1={SX} x2={L - DX} y1={sy(t)} y2={sy(t)} className="griglia" />
            <text x={SX - 6} y={sy(t) + 4} textAnchor="end">{formato(t)}</text>
          </g>
        ))}
        {categorie.map((c, i) => {
          let sotto = 0;
          const x = SX + i * passo + (passo - larga) / 2;
          return (
            <g key={c}>
              {serie.map((s) => {
                const v = Math.max(0, s.valori[i] ?? 0);
                const y0 = sy(sotto), y1 = sy(sotto + v);
                sotto += v;
                return <rect key={s.nome} x={x} y={y1} width={larga} height={Math.max(0, y0 - y1)} fill={s.colore} />;
              })}
              <text x={x + larga / 2} y={A - 22} textAnchor="middle">{c}</text>
            </g>
          );
        })}
      </svg></Disegno>
      <Dati intestazione={["Mese", ...serie.map((s) => s.nome)]} formato={formato}
        righe={categorie.map((c, i) => [c, ...serie.map((s) => s.valori[i])])} />
    </Figura>
  );
}

/** Ogni barra parte dal valore dello scenario base e arriva al valore con il parametro basso o alto. */
export function Tornado({ base, voci, formato, descrizione, didascalia, colori }: {
  base: number;
  voci: { parametro: string; variazione: string; basso: number | null; alto: number | null }[];
  formato: (v: number) => string;
  descrizione: string;
  didascalia?: ReactNode;
  colori: { basso: string; alto: string };
}) {
  const valori = voci.flatMap((v) => [v.basso, v.alto]).filter((v): v is number => v !== null);
  if (valori.length === 0) return null;
  const sx0 = 200, riga = 42, altezza = SU + voci.length * riga + GIU;
  const min = Math.min(base, ...valori), max = Math.max(base, ...valori);
  const sx = scala(min, max, sx0, L - DX - 8);
  return (
    <Figura descrizione={descrizione} didascalia={didascalia}>
      <div className="legend" aria-hidden="true">
        <span><i style={{ background: colori.basso }} />valore basso</span>
        <span><i style={{ background: colori.alto }} />valore alto</span>
      </div>
      <Disegno><svg viewBox={`0 0 ${L} ${altezza}`} role="img" aria-label={descrizione}>
        {tacche(min, max).map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={SU} y2={altezza - GIU} className="griglia" />
            <text x={sx(t)} y={altezza - 18} textAnchor="middle">{formato(t)}</text>
          </g>
        ))}
        {voci.map((v, i) => {
          const y = SU + i * riga;
          return (
            <g key={v.parametro}>
              <text x={sx0 - 8} y={y + 16} textAnchor="end" className="etichetta-tornado">{v.parametro}</text>
              <text x={sx0 - 8} y={y + 32} textAnchor="end">{v.variazione}</text>
              {([["basso", v.basso], ["alto", v.alto]] as const).map(([chi, val]) => val === null ? null : (
                <rect key={chi} x={Math.min(sx(base), sx(val))} y={y + 8} height={20}
                  width={Math.max(1, Math.abs(sx(val) - sx(base)))} fill={colori[chi]} opacity={0.9} />
              ))}
            </g>
          );
        })}
        <line x1={sx(base)} x2={sx(base)} y1={SU - 4} y2={altezza - GIU} className="asse-zero" />
      </svg></Disegno>
      <Dati intestazione={["Parametro", "Variazione", "Valore basso", "Valore alto"]} formato={formato}
        righe={voci.map((v) => [v.parametro, v.variazione, v.basso, v.alto])} />
    </Figura>
  );
}

export const migliaia = (v: number) => scriviNumero(v);
