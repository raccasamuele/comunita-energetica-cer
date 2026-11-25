// Passo 3: il tetto disegnato sulla foto aerea, la proposta di tre taglie e la tabella degli impianti, come nell'app
// Streamlit (app.py, _proposta_impianto). Superficie, orientamento, ombre e taglie li calcola il motore
// (cersim.web.tetto e proposta); qui si raccolgono le scelte e si mostrano i risultati. Ogni valore si può correggere.

import { CreditiOsm } from "../ui/crediti-osm";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, Check, CheckCircle2, Eraser, Loader2, Plus, Undo2, X,
} from "lucide-react";
import { Icon } from "../ui/icons";
import { Brief, InfoTip } from "../ui/info-tip";
import { Messaggi } from "../ui/issues";
import type { Motore } from "../motore/client";
import type {
  CostantiImpianti, EsitoProgetto, EsitoProposta, EsitoTetto, OpzioneProposta, RigaImpianto, SceltaTetto, Tabelle,
} from "../motore/contratto";
import { edificiVicini } from "../motore/edifici";
import { avvisoSerieMancanti, scaricaSerie, sorgentePredefinita } from "../motore/pvgis";
import { euro } from "../formato";
import type { Angolo } from "./MappaTetto";
import { Campo, CampoNumero, Scelta, scriviNumero } from "./campi";
import { Scorrevole } from "../ui/scorrevole";

const MappaTetto = lazy(() => import("./MappaTetto"));

/** Lo stato del passo 3 che non sta nella bozza: il disegno e le scelte del tetto. Lo tiene App, così resta quando
 * si cambia passo. I valori null valgono "quello che viene dal disegno". */
export interface StatoTetto {
  mappaAperta: boolean;
  angoli: Angolo[];
  chiuso: boolean;
  forma: string;
  piani: number | null;
  inclinazione: number | null;
  azimut: number | null;
  dueFalde: boolean | null;
  superficie: number | null;
  ombre: string | null; // l'etichetta del livello scelto: null è il primo, la stima se c'è
  edifici: unknown[] | null;
  punto: string | null;
  investitore: string | null;
  entrata: string | null;
  proposta: { firma: string; esito: EsitoProposta } | null;
}

export const tettoIniziale = (): StatoTetto => ({
  mappaAperta: false, angoli: [], chiuso: false, forma: "a falde", piani: null, inclinazione: null, azimut: null,
  dueFalde: null, superficie: null, ombre: null, edifici: null, punto: null, investitore: null, entrata: null, proposta: null,
});

/** Disegno nuovo: si riparte dai valori del disegno e senza ombre né proposta. */
const senzaDisegno = (s: StatoTetto): StatoTetto => ({
  ...s, angoli: [], chiuso: false, azimut: null, dueFalde: null, superficie: null, ombre: null, edifici: null, proposta: null,
});

// come cersim.tetto.est_ovest e falda_opposta: servono anche per l'orientamento corretto a mano
const EST_OVEST_GRADI = 45;
const estOvest = (azimut: number) => Math.abs(Math.abs(azimut) - 90) <= EST_OVEST_GRADI;
const faldaOpposta = (azimut: number) => (azimut > 0 ? azimut - 180 : azimut + 180);
const DIREZIONI: [number, string][] = [[-180, "nord"], [-135, "nord-est"], [-90, "est"], [-45, "sud-est"], [0, "sud"],
  [45, "sud-ovest"], [90, "ovest"], [135, "nord-ovest"], [180, "nord"]];
const direzione = (az: number) => DIREZIONI.reduce((a, b) => (Math.abs(b[0] - az) < Math.abs(a[0] - az) ? b : a))[1];
const linkEarth = (lat: number, lon: number) => `https://earth.google.com/web/@${lat.toFixed(6)},${lon.toFixed(6)},250a,350d,35y,0h,60t,0r`;
const kwp = (x: number) => `${scriviNumero(x, 1)} kWp`;
const QUALITA = { A: "dati misurati", B: "dati da bolletta", C: "dati tipici: proposta esplorativa" } as const;

export function Impianti(props: {
  tabelle: Tabelle;
  aggiorna: (f: (t: Tabelle) => Tabelle) => void;
  costanti: CostantiImpianti | null;
  esito: EsitoProgetto | null;
  motore: Motore;
  stato: StatoTetto;
  cambia: (f: (s: StatoTetto) => StatoTetto) => void;
}) {
  const { tabelle, aggiorna, costanti, motore, stato, cambia } = props;
  const g = tabelle.generale;
  const cer = g.tipo === "CER";
  const [tetto, setTetto] = useState<EsitoTetto | null>(null);
  const [fase, setFase] = useState<string | null>(null);
  const [erroreProposta, setErroreProposta] = useState<string | null>(null);
  const [avvisoPvgis, setAvvisoPvgis] = useState<string | null>(null);
  const [erroreOmbre, setErroreOmbre] = useState<string | null>(null);
  const [impostato, setImpostato] = useState<string | null>(null);
  const [entrataPrevista, setEntrataPrevista] = useState<string | null>(null);

  // superficie e orientamento dal disegno, appena il tetto è chiuso o cambiano forma, piani, inclinazione ed edifici
  const inclinazione = stato.inclinazione ?? costanti?.inclinazione[stato.forma] ?? 20;
  useEffect(() => {
    if (!stato.chiuso || stato.angoli.length < 3) {
      setTetto(null);
      return;
    }
    let valido = true;
    motore
      .chiama("tetto", { angoli: stato.angoli, forma: stato.forma, piani: stato.piani, inclinazione, edifici: stato.edifici })
      .then((t) => valido && setTetto(t))
      .catch((e: unknown) => valido && setTetto({ ok: false, errore: e instanceof Error ? e.message : String(e) }));
    return () => {
      valido = false;
    };
  }, [motore, stato.angoli, stato.chiuso, stato.forma, stato.piani, inclinazione, stato.edifici]);

  useEffect(() => {
    motore.chiama("entrata_prevista", { data_costituzione: g.data_costituzione }).then((r) => setEntrataPrevista(r.entrata)).catch(() => undefined);
  }, [motore, g.data_costituzione]);

  const disegnato = tetto?.ok ? tetto : null;
  const azimut = stato.azimut ?? disegnato?.azimut ?? 0;
  const possibiliDueFalde = stato.forma === "a falde" && estOvest(azimut);
  const dueFalde = possibiliDueFalde && (stato.dueFalde ?? true);
  const azimut2 = dueFalde ? faldaOpposta(azimut) : null;
  // anche con l'orientamento corretto a mano: le due falde coprono tutta la pianta disegnata
  const daDisegno = disegnato ? disegnato.superficie_utile_m2 * (dueFalde ? 2 : 1) : null;
  const superficie = stato.superficie ?? (daDisegno !== null ? Math.round(daDisegno) : null);
  const m2PerKwp = costanti?.m2_per_kwp[stato.forma] ?? 5.5;
  const kwpMax = superficie ? superficie / m2PerKwp : 0;

  const stimate = disegnato && stato.edifici
    ? (dueFalde && disegnato.est_ovest ? disegnato.ombre_pct_due_falde : disegnato.ombre_pct)
    : null;
  const livelli = [
    ...(stimate !== null ? [{ etichetta: `Stimate dagli edifici vicini: ${scriviNumero(stimate, 1)}%`, pct: stimate }] : []),
    ...(costanti?.livelli_ombre ?? []),
  ];
  const sceltaOmbre = livelli.find((l) => l.etichetta === stato.ombre) ?? livelli[0];
  const ombre = sceltaOmbre?.pct ?? 0;

  // contatore e chi paga: di solito il condominio, oppure il Comune in una comunità energetica (se non c'è, il condominio)
  const etichette = tabelle.punti.map((r) => r.punto).filter((p): p is string => !!p?.trim());
  const membri = [...new Set(tabelle.punti.map((r) => r.membro).filter((m): m is string => !!m?.trim()))];
  const ospiti = cer ? ["Ente territoriale (es. Comune)", "Condominio"] : ["Condominio"];
  const condominio = ospiti.map((o) => tabelle.punti.find((r) => r.tipo_soggetto === o)?.membro).find(Boolean) ?? null;
  const puntoCondominio = tabelle.punti.find((r) => r.membro === condominio)?.punto ?? null;
  const punto = stato.punto && etichette.includes(stato.punto) ? stato.punto : puntoCondominio ?? etichette[0] ?? null;
  const investitore = stato.investitore && membri.includes(stato.investitore) ? stato.investitore : condominio ?? membri[0] ?? null;
  const entrata = stato.entrata ?? entrataPrevista;

  const scelta: SceltaTetto | null = superficie && punto && investitore && entrata
    ? { kwp_max: Math.round(kwpMax * 10) / 10, inclinazione, azimut, azimut_2: azimut2, ombre_pct: ombre, punto, investitore, entrata }
    : null;
  // la proposta vale per questi dati: se cambiano, va rifatta
  const firma = useMemo(() => JSON.stringify({
    scelta, generale: g, punti: tabelle.punti, parametri: tabelle.parametri, impianti: cer ? tabelle.impianti : null,
    curve: Object.entries(tabelle.curve).map(([k, c]) => [k, c.descrizione]),
  }), [scelta, g, tabelle.punti, tabelle.parametri, tabelle.impianti, tabelle.curve, cer]);

  async function stimaOmbre() {
    if (!disegnato) return;
    setErroreOmbre(null);
    setFase("ombre");
    try {
      const edifici = await edificiVicini(disegnato.lat, disegnato.lon);
      cambia((s) => ({ ...s, edifici, ombre: null }));
    } catch (e) {
      setErroreOmbre(`${e instanceof Error ? e.message : String(e)}: scegli tu il livello di ombre, aiutandoti con la vista 3D di Google Earth.`);
    } finally {
      setFase(null);
    }
  }

  async function proponi() {
    if (!scelta) return;
    setErroreProposta(null);
    setAvvisoPvgis(null);
    setImpostato(null);
    try {
      setFase("Dati di produzione…");
      const r = await motore.chiama("richieste_proposta", { tabelle, scelta });
      if (!r.ok) {
        setErroreProposta(r.errore);
        return;
      }
      const sorgente = sorgentePredefinita();
      const serie = await scaricaSerie(r.richieste, sorgente);
      setAvvisoPvgis(avvisoSerieMancanti(Object.keys(serie).length, r.richieste.length, sorgente));
      setFase("Provo diverse taglie su 3 anni di meteo e 3 livelli di prezzo: circa un minuto, di più su un computer lento…");
      const esito = await motore.chiama("proposta", { tabelle, scelta, serie });
      if (!esito.ok) setErroreProposta(esito.errore);
      cambia((s) => ({ ...s, proposta: esito.ok ? { firma, esito } : null }));
    } catch (e) {
      setErroreProposta(e instanceof Error ? e.message : String(e));
    } finally {
      setFase(null);
    }
  }

  function usa(o: OpzioneProposta) {
    aggiorna((t) => ({ ...t, impianti: o.impianti }));
    // nella comunità energetica si passa al tetto del prossimo edificio
    cambia((s) => (cer ? senzaDisegno(s) : s));
    setImpostato(`${o.nome}, ${kwp(o.kwp)}`);
  }

  const proposta = stato.proposta?.esito.ok ? stato.proposta.esito : null;
  const superata = stato.proposta !== null && stato.proposta.firma !== firma;

  return (
    <>
      <p className="sintesi">
        <InfoTip text="Disegna il tetto per confrontare tre taglie e i benefici." label="Tetti e impianti">Il confronto riguarda chi paga e i membri. {cer && "Nella comunità energetica aggiungi un tetto alla volta: ogni proposta tiene conto degli impianti già scelti. "}La scelta finale si conferma con un installatore.</InfoTip>
      </p>

      <section className="section" aria-labelledby="t-tetto">
        <h2 id="t-tetto"><span className="section-icon"><Icon name="tetto-mappa" /></span>Il tetto</h2>
        <details className="advanced">
          <summary>Come disegnare il tetto, passo per passo</summary>
          <ol className="elenco">
            <li>Premi <strong>Apri la foto aerea</strong>: la mappa si apre sull'indirizzo del passo 1. Se il tetto non è al
              centro, trascina la mappa e ingrandisci con la rotellina o con il tasto <strong>+</strong>.</li>
            <li>Clicca sugli angoli del tetto, uno dopo l'altro, seguendo il bordo. Se sbagli, <strong>Togli l'ultimo
              angolo</strong>.</li>
            <li>Per chiudere clicca di nuovo sul primo angolo oppure premi <strong>Chiudi il tetto</strong>: sotto la mappa
              compaiono superficie e orientamento.</li>
            <li>Con <strong>Guarda in 3D su Google Earth</strong> controlli se edifici o alberi più alti stanno a sud, est o
              ovest del tetto: servono a scegliere quanta ombra c'è.</li>
          </ol>
          <p className="small muted">Senza mouse puoi saltare il disegno: scrivi superficie e orientamento nei campi qui sotto.</p>
        </details>

        {!stato.mappaAperta ? (
          <div className="toolbar">
            <button type="button" className="btn" onClick={() => cambia((s) => ({ ...s, mappaAperta: true }))}
              disabled={g.lat == null || g.lon == null || !costanti}>
              <Icon name="tetto-mappa" /> Apri la foto aerea
            </button>
          </div>
        ) : (
          <>
            <Suspense fallback={<p className="muted" role="status"><Loader2 size={14} /> Apertura della mappa…</p>}>
              <MappaTetto lat={g.lat ?? 45.07} lon={g.lon ?? 7.69} angoli={stato.angoli} chiuso={stato.chiuso}
                urlFoto={costanti!.foto_aerea_url} attribuzione={costanti!.foto_aerea_attribuzione}
                aggiungi={(a) => cambia((s) => ({ ...senzaDisegno(s), angoli: [...s.angoli, a] }))}
                chiudi={() => cambia((s) => ({ ...s, chiuso: true }))} />
            </Suspense>
            <div className="toolbar">
              <button type="button" className="btn small" disabled={stato.chiuso || stato.angoli.length === 0}
                onClick={() => cambia((s) => ({ ...senzaDisegno(s), angoli: s.angoli.slice(0, -1) }))}>
                <Undo2 size={16} /> Togli l'ultimo angolo
              </button>
              <button type="button" className="btn small" disabled={stato.chiuso || stato.angoli.length < 3}
                onClick={() => cambia((s) => ({ ...s, chiuso: true }))}>
                <Check size={16} /> Chiudi il tetto
              </button>
              <button type="button" className="btn small" disabled={stato.angoli.length === 0} onClick={() => cambia(senzaDisegno)}>
                <Eraser size={16} /> Cancella il disegno
              </button>
              {g.lat != null && g.lon != null && (
                <a className="btn small ghost" href={linkEarth(disegnato?.lat ?? g.lat, disegnato?.lon ?? g.lon)} target="_blank" rel="noopener">
                  <Icon name="localita" /> Guarda in 3D su Google Earth
                </a>
              )}
            </div>
            <p className="small muted">
              {stato.chiuso ? "Tetto chiuso." : stato.angoli.length === 0 ? "Clicca sul primo angolo del tetto." :
                stato.angoli.length < 3 ? "Clicca sull'angolo successivo." : "Clicca sul primo angolo per chiudere, oppure premi Chiudi il tetto."}{" "}
              <InfoTip text="Esri riceve la zona che guardi." label="Privacy della foto aerea">Le immagini arrivano da Esri. Il disegno resta nel browser.</InfoTip>
            </p>
          </>
        )}
        {tetto && !tetto.ok && <div className="notice warn" role="alert"><AlertTriangle size={18} /><div>{tetto.errore}</div></div>}

        <div className="grid">
          <fieldset className="scelte stretta">
            <legend>Tipo di tetto</legend>
            {(costanti?.forme ?? ["piano", "a falde"]).map((f) => (
              <label key={f} className="scelta">
                <input type="radio" name="forma-tetto" checked={stato.forma === f}
                  onChange={() => cambia((s) => ({ ...s, forma: f, inclinazione: null, superficie: null }))} />
                <span><strong>{f === "piano" ? "Piano" : "A falde"}</strong></span>
              </label>
            ))}
          </fieldset>
          <Campo id="tetto-piani" etichetta="Piani dell'edificio" suggerimento="Per stimare le ombre">
            <CampoNumero id="tetto-piani" valore={stato.piani} min={1} max={40} descrittoDa="tetto-piani-aiuto"
              onChange={(v) => cambia((s) => ({ ...s, piani: v }))} />
          </Campo>
          <Campo id="tetto-incl" etichetta="Inclinazione dei moduli, gradi" suggerimento={stato.forma === "piano" ? "File inclinate e distanziate" : undefined}>
            <CampoNumero id="tetto-incl" valore={inclinazione} min={0} max={60} descrittoDa="tetto-incl-aiuto"
              onChange={(v) => cambia((s) => ({ ...s, inclinazione: v, superficie: null }))} />
          </Campo>
        </div>

        <div className="grid">
          <Campo id="tetto-sup" etichetta="Superficie utile del tetto, m²"
            suggerimento="Libera da ostacoli. Dal disegno: metà del tetto a falde (tutto con due falde), il 60% se piano">
            <CampoNumero id="tetto-sup" valore={superficie} min={0} max={20_000} descrittoDa="tetto-sup-aiuto"
              onChange={(v) => cambia((s) => ({ ...s, superficie: v }))} />
          </Campo>
          <Campo id="tetto-az" etichetta="Orientamento, gradi"
            suggerimento={`0 = sud, -90 = est, 90 = ovest. Moduli rivolti verso ${direzione(azimut)}${azimut2 !== null ? ` e verso ${direzione(azimut2)}, metà per falda` : ""}`}>
            <CampoNumero id="tetto-az" valore={azimut} min={-180} max={180} descrittoDa="tetto-az-aiuto"
              onChange={(v) => cambia((s) => ({ ...s, azimut: v, superficie: null }))} />
          </Campo>
          <div className="field">
            <span className="label-statico">Potenza installabile</span>
            <div className="installabili">
              {superficie ? <>
                <strong>Circa {scriviNumero(kwpMax)} kWp</strong>
                <span className="small muted">tra {scriviNumero(kwpMax * 0.8)} e {scriviNumero(kwpMax * 1.2)} kWp{dueFalde ? " sulle due falde" : ""}, da verificare con un installatore</span>
              </> : <span className="small muted">Disegna il tetto o scrivi la superficie</span>}
              {disegnato && <span className="small muted">Tetto disegnato: {scriviNumero(disegnato.area_terra_m2)} m² in pianta.</span>}
            </div>
          </div>
        </div>
        {possibiliDueFalde && (
          <label className="interruttore">
            <input type="checkbox" checked={dueFalde} onChange={(e) => cambia((s) => ({ ...s, dueFalde: e.target.checked, superficie: null }))} />
            <span>
              <strong>Usa entrambe le falde (est e ovest)</strong>
              <span className="small muted"> Rendono quasi uguali, circa l'85–90% di una falda a sud: usarle tutte e due
                raddoppia i kWp e la produzione dura di più al mattino e alla sera. Metà dei moduli va su ogni falda.</span>
            </span>
          </label>
        )}

        <fieldset className="scelte">
          <legend>Ombre sul tetto: energia persa in un anno per edifici e alberi vicini</legend>
          {livelli.map((l) => (
            <label key={l.etichetta} className="scelta">
              <input type="radio" name="ombre" checked={l === sceltaOmbre}
                onChange={() => cambia((s) => ({ ...s, ombre: l.etichetta }))} />
              <span><strong>{l.etichetta}</strong></span>
            </label>
          ))}
          {stimate !== null && <p className="small"><CreditiOsm cosa="Ombre stimate dalle sagome degli edifici:" /></p>}
        </fieldset>
        <div className="toolbar">
          <button type="button" className="btn small" onClick={() => void stimaOmbre()} disabled={!disegnato || fase !== null}
            title="Usa le altezze degli edifici su OpenStreetMap. Alberi e camini non sono considerati">
            {fase === "ombre" ? <Loader2 size={16} /> : <Icon name="ombre" />} Stima le ombre dagli edifici vicini
          </button>
          {fase === "ombre" && <span className="small muted" role="status">Chiedo a OpenStreetMap gli edifici vicini: spesso ci vuole più di mezzo minuto, intanto puoi continuare…</span>}
        </div>
        <p className="small muted"><InfoTip text="Overpass riceve solo la posizione del tetto." label="Privacy degli edifici vicini">I server pubblici Overpass, che leggono i dati di OpenStreetMap, ricevono coordinate arrotondate a circa 10 m e il tuo indirizzo IP. Le altezze servono a stimare le ombre; alberi e camini non sono considerati.</InfoTip></p>
        {erroreOmbre && <div className="notice warn" role="alert"><AlertTriangle size={18} /><div>{erroreOmbre}</div></div>}
        {disegnato?.svg && (
          <details className="advanced">
            <summary>Gli edifici vicini sulla mappa</summary>
            <img className="pianta" alt="Pianta del tetto disegnato e degli edifici vicini" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(disegnato.svg)}`} />
            <p className="small muted">
              In colore il tetto disegnato, in grigio scuro gli edifici più alti che possono fare ombra. {disegnato.note.join(" ")}{" "}
              <CreditiOsm cosa="Sagome degli edifici:" />
            </p>
          </details>
        )}
      </section>

      <section className="section" aria-labelledby="t-chi">
        <h2 id="t-chi"><span className="section-icon"><Icon name="costi" /></span>Dove si collega e chi paga</h2>
        <div className="grid">
          <Campo id="tetto-punto" etichetta="Collegato al contatore"
            suggerimento="Qui l'energia si usa subito; quella immessa è condivisa se gli altri membri la consumano nella stessa ora">
            <Scelta id="tetto-punto" valore={punto} opzioni={etichette} vuota={etichette.length ? undefined : "Prima aggiungi i contatori al passo 2"}
              onChange={(v) => cambia((s) => ({ ...s, punto: v }))} />
          </Campo>
          <Campo id="tetto-investitore" etichetta="Chi paga l'impianto">
            <Scelta id="tetto-investitore" valore={investitore} opzioni={membri} onChange={(v) => cambia((s) => ({ ...s, investitore: v }))} />
          </Campo>
          <Campo id="tetto-entrata" etichetta="Entrata in esercizio prevista"
            suggerimento={costanti ? `La tariffa premio spetta agli impianti in esercizio entro il ${new Date(costanti.termine_tip).toLocaleDateString("it-IT")}` : undefined}>
            <input id="tetto-entrata" type="date" value={entrata ?? ""} aria-describedby="tetto-entrata-aiuto"
              onChange={(e) => cambia((s) => ({ ...s, entrata: e.target.value || null }))} />
          </Campo>
        </div>
        <div className="toolbar">
          <button type="button" className="btn primary" onClick={() => void proponi()} disabled={!scelta || fase !== null}>
            {fase && fase !== "ombre" ? <Loader2 size={16} /> : <Icon name="solare" />} Proponi tre taglie
          </button>
        </div>
        <div aria-live="polite">
          {!scelta && <p className="small muted">Indica superficie del tetto, contatore, chi paga e data per avere la proposta.</p>}
          {fase && fase !== "ombre" && <p role="status"><Loader2 size={14} /> {fase}</p>}
          {erroreProposta && <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{erroreProposta}</div></div>}
          {avvisoPvgis && <div className="notice warn" role="status"><AlertTriangle size={18} /><div>{avvisoPvgis}</div></div>}
          {impostato && (
            <div className="notice ok" role="status">
              <CheckCircle2 size={18} />
              <div>Impianto impostato: {impostato}. Controlla i dati qui sotto, poi vai al passo 4{cer ? " oppure disegna il tetto di un altro edificio" : ""}.</div>
            </div>
          )}
          {superata && proposta && (
            <div className="notice warn"><AlertTriangle size={18} /><div>Hai cambiato i dati dopo la proposta: premi di nuovo <em>Proponi tre taglie</em> quando hai finito.</div></div>
          )}
        </div>
        {proposta && !superata && <LaProposta proposta={proposta} usa={usa} />}
      </section>

      <TabellaImpianti {...props} entrataPrevista={entrataPrevista} />
    </>
  );
}

function LaProposta({ proposta, usa }: { proposta: Extract<EsitoProposta, { ok: true }>; usa: (o: OpzioneProposta) => void }) {
  return (
    <>
      <p className="small">
        <span className={`badge ${proposta.qualita === "C" ? "warn" : proposta.qualita === "A" ? "ok" : "info"}`}>Qualità {proposta.qualita}</span>{" "}
        <span className="muted">{QUALITA[proposta.qualita]}. Ogni cifra è un intervallo tra lo scenario peggiore e il migliore.</span>
      </p>
      <div className="opzioni-box"><div className="opzioni">
        {proposta.opzioni.map((o) => (
          <article key={o.nome} className={`opzione${o.nome === "Consigliata" ? " consigliata" : ""}`} aria-labelledby={`op-${o.nome}`}>
            <h3 id={`op-${o.nome}`}>{o.nome === "Consigliata" ? <span className="badge ok">Consigliata</span> : o.nome}</h3>
            <p className="taglia">{kwp(o.kwp)}</p>
            <p>
              Costo stimato <strong>{euro(o.costo)}</strong><br />
              Beneficio su 25 anni {euro(o.van_minimo)} – {euro(o.van_massimo)}<br />
              Ai membri circa {euro(o.euro_anno_membri)} all'anno
            </p>
            <p className="small muted">{o.commento}</p>
            {!o.conviene_a_entrambi && <p className="small muted">Con il riparto attuale non conviene a tutti e due: vedi il passo 4.</p>}
            <button type="button" className="btn" onClick={() => usa(o)}><Check size={16} /> Usa questa taglia</button>
          </article>
        ))}
      </div></div>
      <GraficoProposta proposta={proposta} />
      <Messaggi titolo="Ipotesi della proposta" messaggi={proposta.note} />
    </>
  );
}

/** Il beneficio complessivo per ogni taglia provata: la linea è la mediana, la fascia va dal minimo al massimo. */
function GraficoProposta({ proposta }: { proposta: Extract<EsitoProposta, { ok: true }> }) {
  const punti = proposta.curva.filter((q) => q.mediana !== null && q.minimo !== null && q.massimo !== null);
  if (punti.length < 2) return null;
  const L = 640, A = 240, sx = 56, dx = 16, su = 16, giu = 34;
  const x0 = Math.min(...punti.map((q) => q.kwp)), x1 = Math.max(...punti.map((q) => q.kwp));
  const y0 = Math.min(0, ...punti.map((q) => q.minimo!)), y1 = Math.max(...punti.map((q) => q.massimo!));
  const x = (v: number) => sx + ((v - x0) / (x1 - x0 || 1)) * (L - sx - dx);
  const y = (v: number) => su + (1 - (v - y0) / (y1 - y0 || 1)) * (A - su - giu);
  const fascia = [...punti.map((q) => `${x(q.kwp)},${y(q.massimo!)}`), ...[...punti].reverse().map((q) => `${x(q.kwp)},${y(q.minimo!)}`)].join(" ");
  const linea = punti.map((q) => `${x(q.kwp)},${y(q.mediana!)}`).join(" ");
  const tacche = y0 < 0 ? [y0, 0, y1] : [y0, (y0 + y1) / 2, y1];
  return (
    <figure className="grafico-proposta">
      <Scorrevole className="grafico-scroll" etichetta="Grafico delle taglie"><svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label="Beneficio complessivo su 25 anni per ogni taglia provata">
        {tacche.map((t) => (
          <g key={t}>
            <line x1={sx} x2={L - dx} y1={y(t)} y2={y(t)} className="griglia" />
            <text x={sx - 6} y={y(t) + 4} textAnchor="end">{euro(Math.round(t / 1000) * 1000)}</text>
          </g>
        ))}
        {y0 < 0 && <line x1={sx} x2={L - dx} y1={y(0)} y2={y(0)} className="zero" />}
        <polygon points={fascia} className="fascia" />
        <polyline points={linea} className="mediana" />
        {proposta.opzioni.map((o) => {
          const q = punti.reduce((a, b) => (Math.abs(b.kwp - o.kwp) < Math.abs(a.kwp - o.kwp) ? b : a));
          return (
            <g key={o.nome}>
              <circle cx={x(o.kwp)} cy={y(q.mediana!)} r={5} className="punto" />
              <text x={x(o.kwp)} y={y(q.mediana!) - 10} className="etichetta"
                textAnchor={x(o.kwp) > L - 70 ? "end" : x(o.kwp) < sx + 40 ? "start" : "middle"}>{o.nome}</text>
            </g>
          );
        })}
        <text x={sx} y={A - 8}>{kwp(x0)}</text>
        <text x={L - dx} y={A - 8} textAnchor="end">{kwp(x1)}</text>
      </svg></Scorrevole>
      <figcaption className="small muted">
        Beneficio su 25 anni: la linea è la mediana, la fascia va dal minimo al massimo degli scenari. Costo stimato al
        massimo di riferimento del DM 414/2023, da sostituire con un preventivo.
      </figcaption>
    </figure>
  );
}

type Colonna = { nome: string; etichetta: string; tipo: "testo" | "numero" | "data" | "punto" | "investitore"; min?: number; max?: number; decimali?: number; rara?: boolean };
const COLONNE: Colonna[] = [
  { nome: "Impianto", etichetta: "Impianto", tipo: "testo" },
  { nome: "Punto", etichetta: "Collegato al contatore", tipo: "punto" },
  { nome: "kWp moduli", etichetta: "kWp moduli", tipo: "numero", min: 0.5, max: 5000, decimali: 1 },
  { nome: "kW inverter", etichetta: "kW inverter", tipo: "numero", min: 0.5, max: 5000, decimali: 1 },
  { nome: "kWp max installabili", etichetta: "kWp max sul tetto", tipo: "numero", min: 0.5, max: 5000, decimali: 1 },
  { nome: "Inclinazione °", etichetta: "Inclinazione °", tipo: "numero", min: 0, max: 90 },
  { nome: "Orientamento °", etichetta: "Orientamento °", tipo: "numero", min: -180, max: 180 },
  { nome: "Seconda falda °", etichetta: "Seconda falda °", tipo: "numero", min: -180, max: 180, rara: true },
  { nome: "Ombre %", etichetta: "Ombre %", tipo: "numero", min: 0, max: 40, decimali: 1 },
  { nome: "Entrata in esercizio", etichetta: "Entrata in esercizio", tipo: "data" },
  { nome: "Investitore", etichetta: "Chi paga", tipo: "investitore" },
  { nome: "Costo da preventivo €", etichetta: "Costo da preventivo €", tipo: "numero", min: 0, max: 10_000_000 },
  { nome: "Contributo concesso €", etichetta: "Contributo concesso €", tipo: "numero", min: 0, max: 10_000_000, rara: true },
  { nome: "Fattore F", etichetta: "Fattore F", tipo: "numero", min: 0, max: 0.5, decimali: 2, rara: true },
  { nome: "Estremi atto", etichetta: "Estremi dell'atto", tipo: "testo", rara: true },
  { nome: "Data incasso contributo", etichetta: "Incasso del contributo", tipo: "data", rara: true },
];

/** La tabella degli impianti: si compila con "Usa questa taglia" oppure a mano, con i dati di un preventivo. */
function TabellaImpianti(props: {
  tabelle: Tabelle;
  aggiorna: (f: (t: Tabelle) => Tabelle) => void;
  costanti: CostantiImpianti | null;
  esito: EsitoProgetto | null;
  entrataPrevista: string | null;
}) {
  const { tabelle, aggiorna, costanti, entrataPrevista } = props;
  const cer = tabelle.generale.tipo === "CER";
  const rare = COLONNE.filter((c) => c.rara).map((c) => c.nome);
  const conRare = tabelle.impianti.some((r) => rare.some((n) => r[n] != null && r[n] !== ""));
  const [mostraRare, setMostraRare] = useState(conRare);
  const colonne = COLONNE.filter((c) => !c.rara || mostraRare || conRare);
  const etichette = tabelle.punti.map((r) => r.punto).filter((p): p is string => !!p?.trim());
  const membri = [...new Set(tabelle.punti.map((r) => r.membro).filter((m): m is string => !!m?.trim()))].sort();
  const errori = props.esito?.errori_impianti ?? [];

  const cambiaCella = (i: number, nome: string, v: string | number | null) =>
    aggiorna((t) => ({ ...t, impianti: t.impianti.map((r, j) => (j === i ? { ...r, [nome]: v } : r)) }));
  const nuova = (): RigaImpianto => Object.fromEntries([
    ...(costanti?.colonne ?? COLONNE.map((c) => c.nome)).map((c) => [c, null]),
    ["Impianto", cer ? `FV ${tabelle.impianti.length + 1}` : "FV tetto"], ["Punto", etichette[0] ?? null],
    ["Inclinazione °", 30], ["Orientamento °", 0], ["Entrata in esercizio", entrataPrevista],
  ]);

  return (
    <section className="section" aria-labelledby="t-impianti">
      <h2 id="t-impianti"><span className="section-icon"><Icon name="solare" /></span>{cer ? "Dati degli impianti" : "Dati dell'impianto"}</h2>
      <p>
        <Brief label="Dati degli impianti">{"Scegli una taglia qui sopra oppure inserisci i dati di un preventivo. Impianti fotovoltaici nuovi (in esercizio dopo il 16/12/2021), fino a 1 MW, al massimo uno per contatore."}</Brief>
      </p>
      <div className="toolbar aggiungi">
        <button type="button" className="btn" onClick={() => aggiorna((t) => ({ ...t, impianti: [...t.impianti, nuova()] }))}>
          <Plus size={16} /> Aggiungi un impianto
        </button>
        <label className="interruttore">
          <input type="checkbox" checked={mostraRare || conRare} disabled={conRare} onChange={(e) => setMostraRare(e.target.checked)} />
          <span>Mostra anche seconda falda e contributo PNRR già concesso</span>
        </label>
      </div>
      {tabelle.impianti.length === 0 ? (
        <p className="placeholder">Ancora nessun impianto. Scegli una taglia della proposta oppure aggiungi un impianto a mano.</p>
      ) : (
        <>
        <p className="scorri small muted">Scorri la tabella verso destra per vedere tutte le colonne.</p>
        <Scorrevole className="table-wrap" etichetta="Tabella degli impianti">
          <table className="data contatori impianti">
            <caption className="sr-only">Impianti fotovoltaici, uno per riga</caption>
            <thead>
              <tr>
                {colonne.map((c) => <th key={c.nome} scope="col">{c.etichetta}</th>)}
                <th scope="col"><span className="sr-only">Azioni</span></th>
              </tr>
            </thead>
            <tbody>
              {tabelle.impianti.map((r, i) => {
                const nome = String(r["Impianto"] ?? `riga ${i + 1}`);
                return (
                  <tr key={i}>
                    {colonne.map((c) => {
                      const v = r[c.nome] ?? null;
                      const etichetta = `${c.etichetta} di ${nome}`;
                      return (
                        <td key={c.nome}>
                          {c.tipo === "testo" ? (
                            <input type="text" aria-label={etichetta} value={v == null ? "" : String(v)} maxLength={80}
                              onChange={(e) => cambiaCella(i, c.nome, e.target.value || null)} />
                          ) : c.tipo === "numero" ? (
                            <CampoNumero etichetta={etichetta} valore={typeof v === "number" ? v : null} min={c.min} max={c.max}
                              decimali={c.decimali ?? 0} onChange={(x) => cambiaCella(i, c.nome, x)} />
                          ) : c.tipo === "data" ? (
                            <input type="date" aria-label={etichetta} value={v == null ? "" : String(v)}
                              onChange={(e) => cambiaCella(i, c.nome, e.target.value || null)} />
                          ) : (
                            <Scelta etichetta={etichetta} valore={v == null ? null : String(v)}
                              opzioni={c.tipo === "punto" ? [...etichette, costanti?.sola_immissione ?? "(POD dedicato, sola immissione)"]
                                : [...membri, costanti?.investitore_esterno ?? "Soggetto esterno (es. ESCo)"]}
                              onChange={(x) => cambiaCella(i, c.nome, x)} />
                          )}
                        </td>
                      );
                    })}
                    <td>
                      <button type="button" className="btn icon small" aria-label={`Togli ${nome}`} title="Togli la riga"
                        onClick={() => aggiorna((t) => ({ ...t, impianti: t.impianti.filter((_, j) => j !== i) }))}>
                        <X size={16} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Scorrevole>
        </>
      )}
      <p className="small muted">
        Se il costo da preventivo è vuoto si usa il costo massimo di riferimento del DM 414/2023, una stima alta. Il
        contributo PNRR conta solo se già concesso con un atto: lo sportello è chiuso.
      </p>
      <div aria-live="polite">
        <Messaggi titolo="Impianti da completare" messaggi={errori} bloccanti />
      </div>
    </section>
  );
}
