// Passo 5: lo scenario calcolato nel browser e presentato come nell'app Streamlit (app.py, passo 5). Testi, cifre e
// tabelle li prepara il motore (cersim.web.risultati, da cersim.report); qui si mostrano, con i grafici in SVG. La
// curva delle taglie e i report PDF ed Excel usano l'analisi rimasta in memoria nel Worker.

import { useState } from "react";
import {
  AlertTriangle, ArrowLeft, CheckCircle2, Loader2, ShieldAlert, Upload,
} from "lucide-react";
import { Icon, type IconName } from "../ui/icons";
import { Brief, InfoTip, type MetodoId } from "../ui/info-tip";
import { Messaggi } from "../ui/issues";
import type { Motore } from "../motore/client";
import type { Dimensionamento, RisultatiCompleti, SeriePrezzi, TabellaDati } from "../motore/contratto";
import { avvisoSerieMancanti, scaricaSerie, sorgentePredefinita } from "../motore/pvgis";
import { euro, kwh, secondi } from "../formato";
import { scaricaBase64 } from "../bozza";
import { BarreImpilate, Linee, migliaia, Tornado } from "./grafici";
import { Scorrevole } from "../ui/scorrevole";

type Passo = "luogo" | "membri" | "impianti" | "economia";
const PASSI: Record<number, Passo> = { 1: "luogo", 2: "membri", 3: "impianti", 4: "economia" };
const MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
// i ruoli dei grafici dell'energia (cer.css), come i colori del report
const COLORE: Record<string, string> = {
  "Produzione FV": "var(--fv)", Consumi: "var(--consumi)", "Autoconsumo fisico": "var(--autoconsumo)", "Energia condivisa": "var(--condivisa)",
  "Condivisa (kWh)": "var(--condivisa)", "Immessa non condivisa (kWh)": "var(--immessa)", "Autoconsumo fisico (kWh)": "var(--autoconsumo)",
  "Configurazione (consolidato)": "var(--accent-strong)", Investitore: "var(--s4)",
};
const TONO = { ok: "ok", no: "bad", forse: "warn" } as const;
type Scheda = "giorno" | "mesi" | "cassa" | "sensibilita" | "taglie";

interface Esito {
  r: RisultatiCompleti;
  secondi: number;
  serie: string;
  avvisoPvgis: string | null;
  firma: string;
}

const colonna = (t: TabellaDati, nome: string) => {
  const j = t.colonne.indexOf(nome);
  return t.righe.map((r) => (typeof r[j] === "number" ? (r[j] as number) : null));
};
const intervallo = (min: number | null, max: number | null, f: (x: number | null) => string) =>
  min === null || max === null || min === max ? "un solo scenario" : `tra ${f(min)} e ${f(max)} negli scenari`;

/** Paragrafo della pagina tecnica per le quattro cifre principali, nell'ordine in cui il motore le restituisce. */
const METODO_CIFRE: (MetodoId | undefined)[] = ["condivisione-oraria", "tip-per-impianto", "van-consolidamento", "van-consolidamento"];

export function Risultati({ motore, progetto, prezzi, impianti, erroriImpianti, vai, salva, salvataggio }: {
  motore: Motore;
  progetto: string | null;
  prezzi: Record<string, SeriePrezzi> | undefined;
  impianti: number;
  erroriImpianti: string[];
  vai: (passo: Passo) => void;
  salva: () => void;
  salvataggio: boolean;
}) {
  const [esito, setEsito] = useState<Esito | null>(null);
  const [errore, setErrore] = useState<string | null>(null);
  const [fase, setFase] = useState<string | null>(null);
  const firma = JSON.stringify([progetto, Object.values(prezzi ?? {}).map((s) => [s.anno, s.fonte, s.media])]);

  async function calcola() {
    if (!progetto) return;
    setErrore(null);
    try {
      setFase("Avvio del motore…");
      await motore.avvia();
      setFase("Dati di produzione…");
      const richieste = await motore.richieste(progetto);
      const sorgente = sorgentePredefinita();
      const serie = await scaricaSerie(richieste, sorgente);
      setFase("Simulo 25 anni ora per ora, con 3 anni meteo, 3 livelli di prezzo e 3 profili di consumo…");
      const t = performance.now();
      const r = await motore.chiama("risultati", { progetto, serie, prezzi: prezzi ?? null });
      setEsito({ r, firma, secondi: (performance.now() - t) / 1000, serie: `${Object.keys(serie).length} di ${richieste.length} serie PVGIS (${sorgente.nome})`,
        avvisoPvgis: avvisoSerieMancanti(Object.keys(serie).length, richieste.length, sorgente) });
    } catch (e) {
      setErrore(e instanceof Error ? e.message : String(e));
    } finally {
      setFase(null);
    }
  }

  const superato = esito !== null && esito.firma !== firma;
  const r = esito && !superato ? esito.r : null;

  return (
    <div className="dash">
      <div className="result-status">
        <p><strong>Dati: </strong><InfoTip text={r?.qualita?.testo ?? "qualità da calcolare"} label="Qualità dei dati">{r?.qualita?.spiegazione ?? "Curva completa: consumi misurati per quasi un anno, non una garanzia del risultato; B: bollette o curve calcolate; C: valori tipici o prezzi costanti. La qualità complessiva sarà indicata dopo il calcolo."} {r?.nota_intervalli}</InfoTip></p>
        <p><strong>Modello: </strong><InfoTip text="scenario preliminare, non una consulenza." label="Limiti dello scenario">Non è un preventivo né una verifica dei requisiti GSE. Confronta ipotesi su consumi, produzione e prezzi: requisiti e scelta finale vanno verificati con un professionista.</InfoTip></p>
      </div>
      <section className="panel">
        <div className="card-head">
          <h2>Calcolo dello scenario</h2>
          <button type="button" className="btn primary" onClick={() => void calcola()} disabled={fase !== null || !progetto || impianti === 0}>
            {fase ? <Loader2 size={16} /> : <Icon name="rapida" />} Calcola lo scenario
          </button>
        </div>
        <div className="toolbar report-actions no-print"><button type="button" className="btn" onClick={salva} disabled={salvataggio}><Upload size={16} /> Salva il progetto</button></div>
        <p className="muted">Il calcolo resta in questo browser.</p>
        <div aria-live="polite">
          {!progetto && erroriImpianti.length === 0 && (
            <div className="notice info"><AlertTriangle size={18} /><div>
              Mancano dati nei primi passi: completa il <button type="button" className="link" onClick={() => vai("luogo")}>passo 1</button> e
              il <button type="button" className="link" onClick={() => vai("membri")}>passo 2</button>.
            </div></div>
          )}
          {!progetto && erroriImpianti.length > 0 && (
            <div className="notice info"><AlertTriangle size={18} /><div>
              Da sistemare nella tabella degli impianti, al <button type="button" className="link" onClick={() => vai("impianti")}>passo 3</button>.
              <Messaggi titolo="Impianti da completare" messaggi={erroriImpianti} bloccanti />
            </div></div>
          )}
          {progetto && impianti === 0 && (
            <div className="notice info"><AlertTriangle size={18} /><div>
              Manca l'impianto fotovoltaico: disegna il tetto e scegli una taglia, oppure scrivi i dati di un preventivo, al{" "}
              <button type="button" className="link" onClick={() => vai("impianti")}>passo 3</button>.
            </div></div>
          )}
          {fase && <p role="status"><Loader2 size={14} /> {fase}</p>}
          {errore && <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{errore}</div></div>}
          {superato && (
            <div className="notice warn"><AlertTriangle size={18} /><div>I dati sono cambiati dopo l'ultimo calcolo: premi di nuovo <em>Calcola lo scenario</em> per vedere i risultati aggiornati.</div></div>
          )}
          {r && !r.ok && (
            <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>
              {r.errore ?? <>Questa configurazione non è supportata in questa versione:<ul>{(r.non_supportati ?? []).map((m) => <li key={m}>{m}</li>)}</ul></>}
              {r.errore?.includes("passo 4") && <> <button type="button" className="link" onClick={() => vai("economia")}>Vai al passo 4</button>.</>}
            </div></div>
          )}
        </div>
      </section>

      {r?.ok && esito && <Scenario r={r} esito={esito} motore={motore} vai={vai} />}
    </div>
  );
}

function Scenario({ r, esito, motore, vai }: { r: RisultatiCompleti; esito: Esito; motore: Motore; vai: (p: Passo) => void }) {
  const cifre = r.cifre ?? [];
  const formatoCifra = (u: string) => (u === "€" ? euro : kwh);
  return (
    <>
      <section className="panel">
        {r.economia_disabilitata && <div className="notice bad" role="alert"><ShieldAlert size={18} /><div>{r.economia_disabilitata}</div></div>}
        {esito.avvisoPvgis && <div className="notice warn"><ShieldAlert size={18} /><div>{esito.avvisoPvgis}</div></div>}
        <p className="sintesi frase-risultato">{(r.frase ?? []).map(([t, g], i) => (g ? <strong key={i}>{t}</strong> : <span key={i}>{t}</span>))}</p>
        <details className="advanced">
          <summary>Dettagli tecnici del calcolo</summary>
          <ul className="elenco small">
            <li>Calcolo in {secondi(esito.secondi)}, motore cersim {r.motore}.</li>
            <li>Produzione: {esito.serie}{r.fonti_pv?.length ? `, fonte ${r.fonti_pv.join(", ")}` : ""}.</li>
            {(r.fonti_prezzi ?? []).length > 0 && <li>Prezzi: {[...new Set(r.fonti_prezzi)].join("; ")}.</li>}
          </ul>
        </details>
      </section>

      {cifre.length > 0 && (
        <>
          <section className="kpis" aria-label="Cifre principali">
            {cifre.slice(0, 4).map((c, i) => {
              const f = formatoCifra(c.unita);
              const icona: IconName = (["condivisa", "solare", "economia-comunita", "comunita"] as const)[i] ?? "risultati";
              return (
                <div key={c.voce} className="kpi">
                  <div className="top"><span className="k"><InfoTip text={c.voce} label={c.voce} method={METODO_CIFRE[i]}>{c.significato}</InfoTip></span><span className={`kpi-icon tone-${["accent", "ok", "info", "warn"][i]}`}><Icon name={icona} size={28} /></span></div>
                  <div className="v">{f(c.valore)}</div>
                  <div className="d">{intervallo(c.minimo, c.massimo, f)}</div>
                </div>
              );
            })}
          </section>
          {cifre.length > 4 && <section className="panel">
            <Scorrevole className="table-wrap" etichetta="Altre cifre">
              <table className="data cifre">
                <caption className="sr-only">Altre cifre dello scenario</caption>
                <thead><tr><th scope="col">Indicatore</th><th scope="col">Valore centrale</th><th scope="col">Intervallo degli scenari</th><th scope="col">Che cosa significa</th></tr></thead>
                <tbody>
                  {cifre.slice(4).map((c) => {
                    const f = formatoCifra(c.unita);
                    return (
                      <tr key={c.voce}>
                        <td>{c.voce}</td><td className="num">{f(c.valore)}</td>
                        <td className="num">{c.minimo === c.massimo ? "" : `${f(c.minimo)} – ${f(c.massimo)}`}</td>
                        <td className="significato">{c.significato}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Scorrevole>
          </section>}
        </>
      )}

      {r.precisione && (
        <section className="panel" aria-labelledby="t-precisione">
          <h3 id="t-precisione">Come rendere la stima più precisa</h3>
          <p className="sintesi">{r.precisione.frase}</p>
          <ol className="migliorare">
            {r.precisione.voci.map((m) => (
              <li key={m.cosa}>
                <div><strong><InfoTip text={m.cosa} label={m.cosa}>{m.perche}</InfoTip></strong></div>
                {m.passo !== null && PASSI[m.passo] && (
                  <button type="button" className="btn small ghost" onClick={() => vai(PASSI[m.passo!])}><ArrowLeft size={14} /> Vai al passo {m.passo}</button>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {!r.economia_disabilitata && <Report motore={motore} />}

      {r.confronto && (
        <section className="panel" aria-labelledby="t-confronto">
          <h3 id="t-confronto">Conviene costituire la configurazione?</h3>
          <p className="sintesi">{r.confronto.frase}</p>
          <Scorrevole className="table-wrap" etichetta="Confronto delle alternative">
            <table className="data cifre">
              <thead><tr><th scope="col">Alternativa</th><th scope="col">Beneficio netto su 25 anni</th><th scope="col">Intervallo degli scenari</th><th scope="col">Che cosa comprende</th></tr></thead>
              <tbody>
                {r.confronto.righe.map((c) => (
                  <tr key={c.voce}>
                    <td>{c.voce}</td><td className="num">{euro(c.banda?.mediana ?? 0)}</td>
                    <td className="num">{!c.banda || c.banda.minimo === c.banda.massimo ? "" : `${euro(c.banda.minimo)} – ${euro(c.banda.massimo)}`}</td>
                    <td className="significato">{c.descrizione}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scorrevole>
        </section>
      )}

      <section className="panel" aria-labelledby="t-requisiti">
        <h3 id="t-requisiti"><span className="section-icon"><Icon name="verifica" /></span>Requisiti</h3>
        {(["no", "forse", "ok"] as const).map((tono) => {
          const gruppo = (r.requisiti ?? []).filter((q) => q.tono === tono);
          if (!gruppo.length) return null;
          const titolo = `${{ no: "Non ammessi", forse: "Da verificare", ok: "Coerenti con i dati" }[tono]} (${gruppo.length})`;
          const elenco = <ul className={tono === "no" ? "requisiti" : "issue-chips"}>{gruppo.map((q) => <li key={q.nome}>{tono === "no"
            ? <><span className={`badge ${TONO[tono]}`}>{q.stato}</span><span><strong>{q.nome}</strong>. {q.motivo}</span></>
            : <span><InfoTip text={q.nome} label={q.nome}>{q.stato}. {q.motivo}</InfoTip></span>}</li>)}</ul>;
          return tono === "no" ? <div key={tono} className="notice bad issue-errors" role="alert"><strong>{titolo}</strong>{elenco}</div>
            : <details key={tono} className="issue-summary"><summary>{titolo}</summary>{elenco}</details>;
        })}
        {(r.da_verificare ?? []).length > 0 && (
          <Messaggi titolo="Da verificare con un professionista" messaggi={r.da_verificare!} />
        )}
      </section>

      <Energia r={r} motore={motore} />

      {r.chi_riceve && (
        <section className="panel" aria-labelledby="t-chi-riceve">
          <h3 id="t-chi-riceve"><span className="section-icon"><Icon name="riparto" /></span>Chi paga e chi riceve</h3>
          <p className="small muted">Scenario base, anno {r.chi_riceve.anno}.</p>
          <details className="fold">
            <summary>Flussi voce per voce ({r.chi_riceve.righe.length})</summary>
            <Scorrevole className="table-wrap" etichetta="Flussi voce per voce">
              <table className="data">
                <thead><tr>{r.chi_riceve.colonne.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
                <tbody>{r.chi_riceve.righe.map((riga, i) => <tr key={i}>{riga.map((v, j) => <td key={j}>{typeof v === "number" ? euro(v) : v}</td>)}</tr>)}</tbody>
              </table>
            </Scorrevole>
          </details>
          <Scorrevole className="table-wrap per-membro" etichetta="Netto per membro">
            <table className="data">
              <thead><tr><th scope="col">Membro</th><th scope="col">Netto nell'anno</th></tr></thead>
              <tbody>{(r.per_membro ?? []).map((m) => <tr key={m.membro}><td>{m.membro}</td><td>{euro(m.netto)}</td></tr>)}</tbody>
            </table>
          </Scorrevole>
          <p className="small muted">
            <Brief label="Netto per membro" method="riparto-netto">{"Netto per membro: quota dei contributi, risparmio in bolletta e vendite, meno i costi sostenuti. Per chi investe comprende anche la sua quota e le spese dell'impianto."}</Brief>
          </p>
        </section>
      )}

      <section className="panel" aria-labelledby="t-avvertenze">
        <h3 id="t-avvertenze"><span className="section-icon"><Icon name="verifica" /></span>Avvertenze</h3>
        <Messaggi titolo="Ipotesi e avvertenze" messaggi={r.avvertenze ?? []} />
      </section>
    </>
  );
}

/** "Porta i risultati in assemblea": report PDF ed Excel dell'ultima analisi, preparati nel Worker. */
function Report({ motore }: { motore: Motore }) {
  const [fase, setFase] = useState<string | null>(null);
  const [errore, setErrore] = useState<string | null>(null);

  async function scarica(formato: "pdf" | "xlsx") {
    setErrore(null);
    try {
      setFase("Carico i pacchetti dei report (la prima volta, qualche secondo)…");
      await motore.preparaReport();
      setFase(formato === "pdf" ? "Preparo il report PDF…" : "Preparo il file Excel…");
      const r = await motore.chiama("report", { formato });
      if (!r.ok) {
        setErrore(r.errore);
        return;
      }
      scaricaBase64(r.base64, r.nome, formato === "pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    } catch (e) {
      setErrore(e instanceof Error ? e.message : String(e));
    } finally {
      setFase(null);
    }
  }

  return (
    <section className="panel" aria-labelledby="t-report">
      <h3 id="t-report"><span className="section-icon"><Icon name="report" /></span>Porta i risultati in assemblea</h3>
      <div className="toolbar">
        <button type="button" className="btn" disabled={fase !== null} onClick={() => void scarica("pdf")}
          title="3 o 4 pagine da proiettare o stampare: cifre con intervallo, requisiti, grafici, chi paga e chi riceve, ipotesi e avvertenze">
          <Icon name="report" /> Scarica il report PDF
        </button>
        <button type="button" className="btn" disabled={fase !== null} onClick={() => void scarica("xlsx")}
          title="Riepilogo, per membro, flussi di cassa anno per anno, tutti i movimenti e manifest">
          <Icon name="risultati" /> Scarica i dati in Excel
        </button>
      </div>
      <div aria-live="polite">
        {fase && <p className="small" role="status"><Loader2 size={14} /> {fase}</p>}
        {errore && <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{errore}</div></div>}
      </div>
      <p className="small muted">Report dell'ultimo scenario calcolato qui.</p>
    </section>
  );
}

function Energia({ r, motore }: { r: RisultatiCompleti; motore: Motore }) {
  const economia = !r.economia_disabilitata && !!r.cassa;
  const schede: [Scheda, string][] = [["giorno", "Giorno tipo"], ["mesi", "Mese per mese"],
    ...(economia ? [["cassa", "Flussi di cassa"], ["sensibilita", "Sensibilità"], ["taglie", "Dimensionamento"]] as [Scheda, string][] : [])];
  const [scheda, setScheda] = useState<Scheda>("giorno");
  const [mese, setMese] = useState(6);

  const giorno = r.giorno_tipo?.mesi[mese - 1];
  const serieGiorno = giorno ? giorno.colonne.filter((c) => c !== "ora").map((c) => ({ nome: c, colore: COLORE[c] ?? "var(--s5)", valori: colonna(giorno, c) })) : [];
  const descrizioneGiorno = giorno ? `Energia media ora per ora in un giorno di ${MESI[mese - 1]}. ` + serieGiorno.map((s) => {
    const max = Math.max(...s.valori.map((v) => v ?? 0));
    return `${s.nome}: massimo ${max.toLocaleString("it-IT", { maximumFractionDigits: 1 })} kWh alle ${s.valori.indexOf(max)}`;
  }).join("; ") + "." : "";
  const kwhBreve = (v: number) => v.toLocaleString("it-IT", { maximumFractionDigits: 1 });

  return (
    <section className="panel" aria-labelledby="t-energia">
      <h3 id="t-energia"><span className="section-icon"><Icon name="condivisa" /></span>Come si comporta l'energia</h3>
      <div className="seg schede-grafici" role="group" aria-label="Grafico da mostrare">
        {schede.map(([id, etichetta]) => (
          <button key={id} type="button" aria-pressed={scheda === id} onClick={() => setScheda(id)}>{etichetta}</button>
        ))}
      </div>

      {scheda === "giorno" && giorno && (
        <>
          <div className="field mese">
            <label htmlFor="mese-giorno">Mese: {MESI[mese - 1]}</label>
            <input id="mese-giorno" type="range" min={1} max={12} value={mese} onChange={(e) => setMese(Number(e.target.value))} aria-valuetext={MESI[mese - 1]} />
          </div>
          <Linee x={colonna(giorno, "ora").map((v) => v ?? 0)} serie={serieGiorno} formato={kwhBreve} etichettaX="ora del giorno"
            descrizione={descrizioneGiorno} didascalia={`Energia media per ora in un giorno di ${MESI[mese - 1]}, in kWh.`} />
        </>
      )}
      {scheda === "mesi" && r.mensile && (
        <BarreImpilate categorie={r.mensile.righe.map((riga) => String(riga[0]))} formato={migliaia}
          serie={r.mensile.colonne.slice(1).map((c) => ({ nome: c, colore: COLORE[c] ?? "var(--s5)", valori: colonna(r.mensile!, c) }))}
          descrizione={`Energia di ogni mese del ${r.giorno_tipo?.anno ?? ""}, in kWh: condivisa, immessa e non condivisa, autoconsumo fisico.`} />
      )}
      {scheda === "cassa" && r.cassa && (
        <Linee x={colonna(r.cassa, "anno").map((v) => String(v ?? ""))} formato={migliaia} etichettaX="anno" zero
          serie={r.cassa.colonne.slice(1).map((c) => ({ nome: c, colore: COLORE[c] ?? "var(--s5)", valori: colonna(r.cassa!, c) }))}
          descrizione="Euro cumulati anno per anno, non attualizzati, per la configurazione e per chi investe."
          didascalia="Euro cumulati, non attualizzati. Sotto lo zero l'investimento non è ancora ripagato." />
      )}
      {scheda === "sensibilita" && r.sensibilita && r.sensibilita.base !== null && (
        <Tornado base={r.sensibilita.base} voci={r.sensibilita.voci} formato={migliaia} colori={{ basso: "var(--s5)", alto: "var(--s3)" }}
          descrizione="Beneficio netto della configurazione in euro con ogni parametro al valore basso e al valore alto."
          didascalia={<>Le barre partono da {euro(r.sensibilita.base)}, lo scenario base (meteo {r.sensibilita.anno_meteo}, prezzo base). In alto i
            parametri che contano di più. Le cifre in cima sono mediane di tutti gli scenari: possono differire di poco.</>} />
      )}
      {scheda === "taglie" && <Taglie impianti={r.impianti ?? []} motore={motore} />}
    </section>
  );
}

function Taglie({ impianti, motore }: { impianti: { id: string; nome: string }[]; motore: Motore }) {
  const [impianto, setImpianto] = useState(impianti[0]?.id ?? "");
  const [curva, setCurva] = useState<Dimensionamento | null>(null);
  const [inCalcolo, setInCalcolo] = useState(false);

  async function calcola() {
    setInCalcolo(true);
    try {
      setCurva(await motore.chiama("dimensionamento", { impianto }));
    } catch (e) {
      setCurva({ ok: false, errore: e instanceof Error ? e.message : String(e) });
    } finally {
      setInCalcolo(false);
    }
  }

  return (
    <>
      <div className="cerca">
        <div className="field">
          <label htmlFor="taglie-impianto">Impianto da dimensionare</label>
          <select id="taglie-impianto" value={impianto} onChange={(e) => { setImpianto(e.target.value); setCurva(null); }}>
            {impianti.map((p) => <option key={p.id} value={p.id}>{p.nome}</option>)}
          </select>
        </div>
        <button type="button" className="btn" onClick={() => void calcola()} disabled={inCalcolo || !impianto}>
          {inCalcolo ? <Loader2 size={16} /> : <CheckCircle2 size={16} />} Calcola la curva
        </button>
      </div>
      {inCalcolo && <p className="small" role="status"><Loader2 size={14} /> Provo diverse taglie: circa mezzo minuto…</p>}
      {!curva && !inCalcolo && <p className="small muted">La curva prova diverse taglie dell'impianto, fino al massimo installabile sul tetto.</p>}
      {curva && !curva.ok && <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{curva.errore}</div></div>}
      {curva?.ok && (
        <Linee x={curva.curva.map((q) => `${q.kwp.toLocaleString("it-IT")} kWp`)} formato={migliaia} etichettaX="taglia" zero
          serie={[
            { nome: "Beneficio della configurazione", colore: "var(--accent-strong)", valori: curva.curva.map((q) => q.configurazione) },
            { nome: "Beneficio di chi investe", colore: "var(--s4)", valori: curva.curva.map((q) => q.investitore) },
          ]}
          descrizione="Beneficio netto su 25 anni, in euro, per ogni taglia provata."
          didascalia={`Beneficio netto su 25 anni, in euro. ${curva.dicitura}`} />
      )}
    </>
  );
}
