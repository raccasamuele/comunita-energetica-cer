// Passo 2: la tabella dei contatori (una riga per POD), le famiglie tipo e i consumi ora per ora (file del
// distributore, curva-consumi o profilo energetico del simulatore della casa). La lettura dei file e i controlli li fa
// il motore.

import { useId, useState } from "react";
import { AlertTriangle, CheckCircle2, Copy, ExternalLink, Info, Loader2, Plus, Printer, Download, X } from "lucide-react";
import { Icon } from "../ui/icons";
import { Brief, InfoTip } from "../ui/info-tip";
import { Messaggi, QualitaContatori } from "../ui/issues";
import { base64, scaricaBase64 } from "../bozza";
import { linkFamiglie } from "../scheda/scheda";
import type { Motore } from "../motore/client";
import type { ConsumiOrari, Costanti, EsitoProgetto, RigaImpianto, RigaPunto, ScenarioProfilo, Tabelle } from "../motore/contratto";
import { kwh } from "../formato";
import { CampoNumero, Scelta } from "./campi";
import { Scorrevole } from "../ui/scorrevole";

const MAX_BYTE_FILE = 50_000_000;

const rigaVuota = (n: number): RigaPunto => ({
  punto: `Contatore ${n}`, membro: null, tipo_soggetto: null, tipologia: null, kwh_annui: null, f1_kwh: null,
  f23_kwh: null, area: null, tensione: "BT",
});

type EsitoFile =
  | { tono: "ok" | "calcolata"; testo: string; avvisi: string[] }
  | { tono: "errore"; testo: string };

/** Il profilo energetico letto, in attesa della scelta dello scenario. */
interface SceltaProfilo {
  contatore: string;
  file: { nome: string; base64: string }[];
  scenari: ScenarioProfilo[];
  comune: string | null;
  scenario: string;
  contaFv: boolean;
}

/** Nome della riga del passo 3 aggiunta per il FV di casa (cersim.web.nome_impianto_casa). */
const impiantoDiCasa = (contatore: string) => `FV di casa (${contatore})`.slice(0, 120);

const numero = (x: number) => x.toLocaleString("it-IT", { maximumFractionDigits: 1 });

/** Scarica un file JSON nel browser. */
function scaricaJson(dati: unknown, nome: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(dati, null, 1)], { type: "application/json" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: nome });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function MembriConsumi(props: {
  tabelle: Tabelle;
  aggiorna: (f: (t: Tabelle) => Tabelle) => void;
  costanti: Costanti | null;
  esito: EsitoProgetto | null;
  motore: Motore;
  /** Il profilo energetico arrivato da Casa («Porta nella CER»), già scelto come file dei consumi. */
  arrivo?: File | null;
  arrivoUsato?: () => void;
}) {
  const { tabelle, aggiorna, costanti, motore } = props;
  const cer = tabelle.generale.tipo === "CER";
  const [nFamiglie, setNFamiglie] = useState<number | null>(10);
  const [occupato, setOccupato] = useState<string | null>(null);

  function cambiaRiga(i: number, parte: Partial<RigaPunto>) {
    aggiorna((t) => {
      const punti = t.punti.map((r, j) => (j === i ? { ...r, ...parte } : r));
      let curve = t.curve;
      const prima = t.punti[i].punto;
      // la curva segue il contatore quando gli si cambia nome
      if (parte.punto !== undefined && prima && curve[prima] && parte.punto && !curve[parte.punto]) {
        const { [prima]: curva, ...altre } = curve;
        curve = { ...altre, [parte.punto]: curva };
      }
      return { ...t, punti, curve };
    });
  }

  function togliRiga(i: number) {
    aggiorna((t) => {
      const etichetta = t.punti[i].punto;
      const curve = { ...t.curve };
      if (etichetta) delete curve[etichetta];
      return { ...t, punti: t.punti.filter((_, j) => j !== i), curve };
    });
  }

  async function aggiungiFamiglie() {
    if (!nFamiglie) return;
    setOccupato("famiglie");
    try {
      const righe = await motore.chiama("famiglie", { n: nFamiglie, inizio: tabelle.punti.length + 1 });
      aggiorna((t) => ({ ...t, punti: [...t.punti, ...righe] }));
    } finally {
      setOccupato(null);
    }
  }

  const riepilogo = props.esito?.ok ? props.esito.riepilogo : undefined;
  const errori = props.esito && !props.esito.ok ? props.esito.errori : [];

  return (
    <>
      <p className="sintesi">
        <InfoTip text="Una riga per contatore, con i consumi della bolletta." label="Membri e consumi">I contatori (POD) dello stesso membro hanno lo stesso nome. Consumo annuo e fasce sono in bolletta; senza consumo, una famiglia vale {kwh(costanti?.kwh_famiglia_tipo ?? 2700)} all'anno (ARERA).</InfoTip>
      </p>

      <section className="section" aria-labelledby="t-contatori">
        <h2 id="t-contatori"><span className="section-icon"><Icon name="contatore" /></span>I contatori</h2>
        <RaccogliConLink tabelle={tabelle} aggiorna={aggiorna} motore={motore} />
        <div className="toolbar aggiungi">
          <div className="field">
            <label htmlFor="n-famiglie">Famiglie da aggiungere</label>
            <CampoNumero id="n-famiglie" valore={nFamiglie} min={1} max={100} onChange={setNFamiglie} />
          </div>
          <button type="button" className="btn" onClick={() => void aggiungiFamiglie()} disabled={!nFamiglie || occupato !== null}>
            {occupato === "famiglie" ? <Loader2 size={16} /> : <Icon name="comunita" />} Aggiungi famiglie tipo
          </button>
          <button type="button" className="btn" onClick={() => aggiorna((t) => ({ ...t, punti: [...t.punti, rigaVuota(t.punti.length + 1)] }))}>
            <Plus size={16} /> Aggiungi un contatore
          </button>
        </div>

        {tabelle.punti.length === 0 ? (
          <p className="placeholder">
            Ancora nessun contatore. Aggiungi le famiglie tipo o un contatore alla volta, oppure carica l'esempio di
            Torino o un lavoro salvato dall'ingresso.
          </p>
        ) : (
          <>
            <p className="scorri small muted">Scorri la tabella verso destra per vedere consumi e altre colonne.</p>
            <TabellaContatori tabelle={tabelle} costanti={costanti} cer={cer} cambia={cambiaRiga} togli={togliRiga} />
          </>
        )}
        {cer && (
          <p className="small muted">
            <InfoTip text="Senza cabina primaria verificata i contributi restano condizionali." label="Area convenzionale">Area convenzionale: il codice della cabina primaria, sulla mappa del GSE per indirizzo o POD.</InfoTip>
          </p>
        )}

        <div aria-live="polite">
          {riepilogo && (
            <div className="notice ok">
              <CheckCircle2 size={18} />
              <div>
                {riepilogo.contatori} {riepilogo.contatori === 1 ? "contatore" : "contatori"} di {riepilogo.membri}{" "}
                {riepilogo.membri === 1 ? "membro" : "membri"}, circa {kwh(riepilogo.kwh_annui)} all'anno.{" "}
              </div>
            </div>
          )}
          {riepilogo && <QualitaContatori qualita={riepilogo.qualita_consumi} />}
          <Messaggi titolo="Contatori da completare" messaggi={errori} bloccanti />
        </div>
      </section>

      <ConsumiOraPerOra tabelle={tabelle} aggiorna={aggiorna} motore={motore} arrivo={props.arrivo ?? null} arrivoUsato={props.arrivoUsato} />
    </>
  );
}

/** Il link per famiglie e attività e le schede che rimandano: la tabella si compila da sola, e una scheda rimandata
 * aggiorna le righe di chi l'ha mandata (cersim.web.leggi_schede). */
function RaccogliConLink({ tabelle, aggiorna, motore }: { tabelle: Tabelle; aggiorna: (f: (t: Tabelle) => Tabelle) => void; motore: Motore }) {
  const link = linkFamiglie(tabelle.generale.nome);
  const idFile = useId();
  const [copiato, setCopiato] = useState(false);
  const [inLettura, setInLettura] = useState(false);
  const [esito, setEsito] = useState<{ messaggi: string[]; errore?: string } | null>(null);
  const [versione, setVersione] = useState(0);
  const [stampa, setStampa] = useState<{ fase: string | null; errore?: string }>({ fase: null });

  /** La stessa scheda su un foglio A4 (cersim.report.scheda_famiglia_pdf), con il link e le righe da compilare a
   * mano: per chi non usa il computer o per l'assemblea. Usa i pacchetti dei report, caricati la prima volta. */
  async function scaricaScheda() {
    try {
      setStampa({ fase: "Carico i pacchetti dei report (la prima volta, qualche secondo)…" });
      await motore.preparaReport();
      setStampa({ fase: "Preparo la scheda da stampare…" });
      const r = await motore.chiama("scheda_pdf", { configurazione: tabelle.generale.nome || null, link });
      if (!r.ok) {
        setStampa({ fase: null, errore: r.errore });
        return;
      }
      scaricaBase64(r.base64, r.nome, "application/pdf");
      setStampa({ fase: null });
    } catch (e) {
      setStampa({ fase: null, errore: e instanceof Error ? e.message : String(e) });
    }
  }

  async function copia() {
    try {
      await navigator.clipboard.writeText(link);
      setCopiato(true);
      setTimeout(() => setCopiato(false), 3000);
    } catch {
      (document.getElementById("link-famiglie") as HTMLInputElement | null)?.select();
    }
  }

  async function leggi(file: File[]) {
    if (file.length === 0) return;
    setInLettura(true);
    try {
      const contenuti = await Promise.all(file.map(async (f) => ({ nome: f.name, base64: await base64(f) })));
      const r = await motore.chiama("leggi_schede", { file: contenuti, tabelle });
      if (r.lette > 0) aggiorna((t) => ({ ...t, punti: r.punti, curve: r.curve }));
      setEsito({ messaggi: r.messaggi });
    } catch (e) {
      setEsito({ messaggi: [], errore: e instanceof Error ? e.message : String(e) });
    } finally {
      setInLettura(false);
      setVersione((v) => v + 1);
    }
  }

  return (
    <details className="advanced">
      <summary><Icon name="scheda-famiglia" /> Raccogli i consumi con un link</summary>
      <p>
        <Brief label="Raccogliere i consumi">{"Manda il link a famiglie e attività: ognuno inserisce i suoi consumi e ti rimanda un piccolo file. Caricalo qui e la tabella si compila da sola; una scheda rimandata aggiorna le righe di chi l'ha mandata."}</Brief>
      </p>
      <div className="cerca">
        <div className="field">
          <label htmlFor="link-famiglie">Link per le famiglie</label>
          <input id="link-famiglie" type="text" readOnly value={link} onFocus={(e) => e.target.select()} />
        </div>
        <button type="button" className="btn" onClick={() => void copia()}>
          {copiato ? <CheckCircle2 size={16} /> : <Copy size={16} />} {copiato ? "Copiato" : "Copia il link"}
        </button>
      </div>
      <div className="toolbar">
        <a className="btn small ghost" href={link} target="_blank" rel="noopener">Anteprima della scheda <ExternalLink size={14} aria-hidden="true" /><span className="sr-only"> (si apre in una nuova scheda)</span></a>
        <button type="button" className="btn small ghost" disabled={stampa.fase !== null} onClick={() => void scaricaScheda()}
          title="Un foglio A4 con che cosa serve, dove trovarlo, il link e una tabella da compilare a mano">
          <Printer size={14} aria-hidden="true" /> Scheda da stampare (PDF)
        </button>
      </div>
      <div aria-live="polite">
        {stampa.fase && <p className="small muted" role="status"><Loader2 size={14} aria-hidden="true" /> {stampa.fase}</p>}
        {stampa.errore && <div className="notice bad" role="alert"><AlertTriangle size={18} aria-hidden="true" /><div>{stampa.errore}</div></div>}
      </div>
      <div className="field">
        <label htmlFor={idFile}>Schede ricevute</label>
        <input key={versione} id={idFile} type="file" accept=".json,application/json" multiple disabled={inLettura}
          onChange={(e) => void leggi(Array.from(e.target.files ?? []))} />
      </div>
      <div aria-live="polite">
        {inLettura && <p className="muted" role="status"><Loader2 size={14} /> Lettura delle schede…</p>}
        {esito?.errore && <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{esito.errore}</div></div>}
        {esito && esito.messaggi.length > 0 && (
          <Messaggi titolo="Schede ricevute" messaggi={esito.messaggi} bloccanti={!esito.messaggi[0].startsWith("Contatori aggiunti")} />
        )}
      </div>
    </details>
  );
}

function TabellaContatori(props: {
  tabelle: Tabelle;
  costanti: Costanti | null;
  cer: boolean;
  cambia: (i: number, parte: Partial<RigaPunto>) => void;
  togli: (i: number) => void;
}) {
  const { tabelle, costanti, cer, cambia, togli } = props;
  return (
    <Scorrevole className="table-wrap" etichetta="Tabella dei contatori">
      <table className="data contatori">
        <caption className="sr-only">Contatori, una riga per POD</caption>
        <thead>
          <tr>
            <th scope="col">Contatore</th>
            <th scope="col">Membro</th>
            <th scope="col">Tipo di soggetto</th>
            <th scope="col">Tipo di consumo</th>
            <th scope="col">kWh all'anno</th>
            <th scope="col">di cui F1</th>
            <th scope="col">di cui F2+F3</th>
            {cer && <th scope="col">Area convenzionale</th>}
            <th scope="col">Tensione</th>
            <th scope="col">Ora per ora</th>
            <th scope="col"><span className="sr-only">Azioni</span></th>
          </tr>
        </thead>
        <tbody>
          {tabelle.punti.map((r, i) => {
            const nome = r.punto || `riga ${i + 1}`;
            const curva: ConsumiOrari | undefined = r.punto ? tabelle.curve[r.punto] : undefined;
            return (
              <tr key={i}>
                <td>
                  <input type="text" aria-label={`Contatore, riga ${i + 1}`} value={r.punto ?? ""} maxLength={80}
                    onChange={(e) => cambia(i, { punto: e.target.value || null })} />
                </td>
                <td>
                  <input type="text" aria-label={`Membro di ${nome}`} value={r.membro ?? ""} maxLength={120}
                    onChange={(e) => cambia(i, { membro: e.target.value || null })} />
                </td>
                <td>
                  <Scelta etichetta={`Tipo di soggetto di ${nome}`} valore={r.tipo_soggetto} opzioni={costanti?.tipi_soggetto ?? []}
                    onChange={(v) => cambia(i, { tipo_soggetto: v })} />
                </td>
                <td>
                  <Scelta etichetta={`Tipo di consumo di ${nome}`} valore={r.tipologia} opzioni={costanti?.tipologie ?? []}
                    onChange={(v) => cambia(i, { tipologia: v })} />
                </td>
                {curva ? (
                  <td colSpan={3} className="muted small">dalla curva oraria, circa {kwh(Number(curva.curva.kwh_annui))}</td>
                ) : (
                  <>
                    <td><CampoNumero etichetta={`kWh all'anno di ${nome}`} valore={r.kwh_annui} min={0} max={10_000_000} onChange={(v) => cambia(i, { kwh_annui: v })} /></td>
                    <td><CampoNumero etichetta={`kWh in F1 di ${nome}`} valore={r.f1_kwh} min={0} max={10_000_000} onChange={(v) => cambia(i, { f1_kwh: v })} /></td>
                    <td><CampoNumero etichetta={`kWh in F2 e F3 di ${nome}`} valore={r.f23_kwh} min={0} max={10_000_000} onChange={(v) => cambia(i, { f23_kwh: v })} /></td>
                  </>
                )}
                {cer && (
                  <td>
                    <input type="text" aria-label={`Area convenzionale di ${nome}`} value={r.area ?? ""} maxLength={40}
                      onChange={(e) => cambia(i, { area: e.target.value || null })} />
                  </td>
                )}
                <td>
                  <Scelta etichetta={`Tensione di ${nome}`} valore={r.tensione ?? "BT"} opzioni={costanti?.tensioni ?? ["BT", "MT"]}
                    onChange={(v) => cambia(i, { tensione: v })} />
                </td>
                <td>
                  {curva ? (
                    <span className={`badge ${curva.calcolata ? "info" : "ok"}`}>{curva.calcolata ? "calcolati" : "misurati"}</span>
                  ) : (
                    <span className="muted small">no</span>
                  )}
                </td>
                <td>
                  <button type="button" className="btn icon small" aria-label={`Togli ${nome}`} title="Togli la riga" onClick={() => togli(i)}>
                    <X size={16} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Scorrevole>
  );
}

function ConsumiOraPerOra({ tabelle, aggiorna, motore, arrivo, arrivoUsato }: {
  tabelle: Tabelle; aggiorna: (f: (t: Tabelle) => Tabelle) => void; motore: Motore; arrivo: File | null; arrivoUsato?: () => void;
}) {
  const etichette = tabelle.punti.map((r) => r.punto).filter((p): p is string => !!p?.trim());
  const [contatore, setContatore] = useState<string | null>(null);
  const [file, setFile] = useState<File[]>(() => (arrivo ? [arrivo] : []));
  const daCasa = arrivo !== null && file.length === 1 && file[0] === arrivo;
  const [versione, setVersione] = useState(0); // svuota la scelta dei file dopo l'uso
  const [inLettura, setInLettura] = useState(false);
  const [esito, setEsito] = useState<EsitoFile | null>(null);
  const [scelta, setScelta] = useState<SceltaProfilo | null>(null);
  const idFile = useId();
  const curve = Object.entries(tabelle.curve);

  async function usa() {
    if (!contatore || file.length === 0) return;
    if (file.reduce((s, f) => s + f.size, 0) > MAX_BYTE_FILE) {
      setEsito({ tono: "errore", testo: "I file sono troppo grandi: al massimo 50 MB insieme." });
      return;
    }
    setInLettura(true);
    setScelta(null);
    try {
      const contenuti = await Promise.all(file.map(async (f) => ({ nome: f.name, base64: await base64(f) })));
      const letti = await motore.chiama("leggi_consumi", { file: contenuti });
      if (!letti.ok) {
        setEsito({ tono: "errore", testo: letti.errore });
        return;
      }
      if (letti.scegli) {
        // profilo energetico: si sceglie lo scenario, poi si applica al contatore
        const primo = letti.scenari.find((s) => s.attuale) ?? letti.scenari[0];
        setScelta({ contatore, file: contenuti, scenari: letti.scenari, comune: letti.comune, scenario: primo.id, contaFv: true });
        setEsito(null); // gli avvisi dello scenario arrivano quando lo si applica
        return;
      }
      applica(contatore, letti);
    } catch (e) {
      setEsito({ tono: "errore", testo: e instanceof Error ? e.message : String(e) });
    } finally {
      setInLettura(false);
    }
  }

  function applica(punto: string, letti: ConsumiOrari & { avvisi: string[]; impianto?: (RigaImpianto & { esistente: boolean }) | null }) {
    const { curva, descrizione, calcolata, batteria, profilo, avvisi, impianto } = letti;
    const voce: ConsumiOrari = { curva, descrizione, calcolata, ...(batteria ? { batteria } : {}), ...(profilo ? { profilo } : {}) };
    aggiorna((t) => {
      // la riga del FV di casa segue il profilo: aggiunta o aggiornata se conta, tolta se non conta più
      const altri = t.impianti.filter((r) => r.Impianto !== impiantoDiCasa(punto));
      let impianti = altri;
      if (impianto) {
        const { esistente: _esistente, ...riga } = impianto;
        const membro = t.punti.find((r) => r.punto === punto)?.membro ?? null;
        const prima = t.impianti.find((r) => r.Impianto === impiantoDiCasa(punto));
        impianti = [...altri, { ...riga, Investitore: membro, "Entrata in esercizio": prima?.["Entrata in esercizio"] ?? riga["Entrata in esercizio"] }];
      }
      return { ...t, curve: { ...t.curve, [punto]: voce }, impianti };
    });
    const altro = impianto
      ? ` Al passo 3 c'è l'impianto «${impiantoDiCasa(punto)}»${impianto.esistente ? ": indica quando è entrato in esercizio" : ""}.`
      : "";
    setEsito({ tono: calcolata ? "calcolata" : "ok", testo: `${punto}: ${descrizione}.${altro}`, avvisi });
    setScelta(null);
    if (daCasa) arrivoUsato?.();
    setFile([]);
    setVersione((v) => v + 1);
  }

  async function usaScenario() {
    if (!scelta) return;
    setInLettura(true);
    try {
      const letti = await motore.chiama("leggi_consumi", {
        file: scelta.file, scenario: scelta.scenario, conta_fv: scelta.contaFv,
        data_costituzione: tabelle.generale.data_costituzione, contatore: scelta.contatore,
      });
      if (!letti.ok) setEsito({ tono: "errore", testo: letti.errore });
      else if (!letti.scegli) applica(scelta.contatore, letti);
    } catch (e) {
      setEsito({ tono: "errore", testo: e instanceof Error ? e.message : String(e) });
    } finally {
      setInLettura(false);
    }
  }

  async function scaricaProfilo(etichetta: string, voce: ConsumiOrari) {
    const r = await motore.chiama("scarica_profilo", { voce, ha_impianto: tabelle.impianti.some((i) => i.Punto === etichetta) });
    if (!r.ok) {
      setEsito({ tono: "errore", testo: r.errore });
      return;
    }
    const nome = etichetta.normalize("NFKD").replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || "contatore";
    scaricaJson(r.profilo, `profilo-energetico_${nome}.json`);
  }

  function togliCurva(etichetta: string) {
    aggiorna((t) => {
      const { [etichetta]: tolta, ...altre } = t.curve;
      // con il profilo che contava il FV, va via anche la riga aggiunta per il FV di casa
      const impianti = tolta?.profilo?.conta_fv ? t.impianti.filter((r) => r.Impianto !== impiantoDiCasa(etichetta)) : t.impianti;
      return { ...t, curve: altre, impianti };
    });
  }

  const scenario = scelta?.scenari.find((s) => s.id === scelta.scenario);

  return (
    <section className="section" aria-labelledby="t-orari">
      <h2 id="t-orari"><span className="section-icon"><Icon name="bolletta" /></span><span>Consumi ora per ora {curve.length === 0 && <span className="muted small facoltativo">(facoltativo)</span>}</span></h2>
      <p>
        <InfoTip text="I consumi orari sostituiscono la curva tipica." label="Consumi orari e qualità">Con almeno 11 mesi e tre quarti dei consumi coperti si arriva alla curva completa. Si usano la forma media e pochi giorni veri, senza data: il codice POD non viene letto e i file restano nel browser.</InfoTip>
      </p>
      <p className="small muted"><InfoTip text="I file restano nel browser; il POD non viene letto." label="Privacy dei consumi">Per il calcolo della condivisione si usano la forma media dei consumi e pochi giorni veri, senza data. Nella scheda che manda una famiglia c'è solo la forma media.</InfoTip></p>
      <details className="advanced">
        <summary>File accettati</summary>
        <ul className="small elenco">
          <li>Portale Consumi: letture.csv, dal pulsante <em>Scarica letture</em>.</li>
          <li>e-distribuzione: i file mensili ExportData della curva di carico, o quelli che l'app manda per email.</li>
          <li>Simulatore della casa: il file curva-consumi. È una stima, non una misura: la qualità resta B.</li>
          <li>Simulatore della casa: il profilo energetico. Scegli lo scenario della casa e se il suo fotovoltaico entra
            nella comunità; la qualità resta B.</li>
        </ul>
      </details>
      <div className="grid">
        <div className="field">
          <label htmlFor="curva-contatore">Contatore</label>
          <Scelta id="curva-contatore" valore={contatore && etichette.includes(contatore) ? contatore : null} opzioni={etichette}
            vuota="Scegli il contatore" onChange={setContatore} />
        </div>
        <div className="field">
          <label htmlFor={idFile}>File dei consumi, anche più mesi insieme</label>
          <input key={versione} id={idFile} type="file" accept=".csv,.json,text/csv,application/json" multiple
            onChange={(e) => setFile(Array.from(e.target.files ?? []))} />
          {daCasa && (
            <p className="small" id={`${idFile}-casa`}>
              <CheckCircle2 size={14} aria-hidden="true" /> Già scelto: il profilo arrivato da Casa.
              {etichette.length === 0 && " Aggiungi prima il contatore della casa nella tabella qui sopra."}
            </p>
          )}
        </div>
      </div>
      <div className="toolbar">
        <button type="button" className="btn" disabled={!contatore || file.length === 0 || inLettura} onClick={() => void usa()}>
          {inLettura ? <Loader2 size={16} /> : <Download size={16} />} Usa questi consumi
        </button>
      </div>

      {scelta && (
        <div className="section-inner profilo-scelta">
          <fieldset className="scelte">
            <legend>Scenario della casa per {scelta.contatore}{scelta.comune ? ` (${scelta.comune})` : ""}</legend>
            {scelta.scenari.map((s) => (
              <label key={s.id} className="scelta">
                <input type="radio" name="scenario-profilo" checked={scelta.scenario === s.id}
                  onChange={() => setScelta({ ...scelta, scenario: s.id })} />
                <span>
                  <strong>{s.nome}{s.attuale ? " (oggi)" : ""}</strong>
                  <span className="small muted">
                    consumi {kwh(s.consumi_kwh)} all'anno
                    {s.fv_kwp ? `, FV ${numero(s.fv_kwp)} kWp${s.fv_esistente ? " già installato" : " nuovo"}` : ""}
                    {s.batteria_kwh ? `, batteria ${numero(s.batteria_kwh)} kWh` : ""}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          {scenario?.fv_kwp ? (
            <fieldset className="scelte">
              <legend>Il fotovoltaico di casa</legend>
              <label className="scelta">
                <input type="radio" name="conta-fv" checked={scelta.contaFv} onChange={() => setScelta({ ...scelta, contaFv: true })} />
                <span>
                  <strong>Entra nella comunità</strong>
                  <span className="small muted">
                    Consumi prima del FV su questo contatore e impianto aggiunto al passo 3: la sua energia immessa si
                    può condividere.{scenario.batteria_kwh ? " La batteria di casa si simula sul contatore." : ""}
                    {scenario.fv_esistente ? " Se è entrato in esercizio prima del 16/12/2021 la comunità non lo può contare: scegli «Solo prelievi»." : ""}
                  </span>
                </span>
              </label>
              <label className="scelta">
                <input type="radio" name="conta-fv" checked={!scelta.contaFv} onChange={() => setScelta({ ...scelta, contaFv: false })} />
                <span>
                  <strong>Solo prelievi</strong>
                  <span className="small muted">Come il file curva-consumi: FV e batteria restano della casa, nella comunità contano solo i prelievi ({kwh(scenario.prelievi_kwh)} all'anno).</span>
                </span>
              </label>
            </fieldset>
          ) : null}
          <div className="toolbar">
            <button type="button" className="btn primary" disabled={inLettura} onClick={() => void usaScenario()}>
              {inLettura ? <Loader2 size={16} /> : <CheckCircle2 size={16} />} Usa questo scenario
            </button>
            <button type="button" className="btn" onClick={() => setScelta(null)}><X size={14} /> Annulla</button>
          </div>
        </div>
      )}

      <div aria-live="polite">
        {esito?.tono === "errore" && (
          <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{esito.testo}</div></div>
        )}
        {esito && esito.tono !== "errore" && (
          <div className={`notice ${esito.tono === "ok" ? "ok" : "info"}`}>
            {esito.tono === "ok" ? <CheckCircle2 size={18} /> : <Info size={18} />}
            <div>
              {esito.testo}
              {esito.tono === "calcolata" && (
                <> Sono consumi <strong>calcolati</strong> dal simulatore della casa, non misurati: la simulazione li usa ora
                per ora, ma la qualità di questo contatore resta <strong>B</strong>.</>
              )}
              <Messaggi titolo="Consumi da verificare" messaggi={esito.avvisi} />
            </div>
          </div>
        )}
      </div>

      {curve.length > 0 && (
        <>
          <ul className="curve">
            {curve.map(([etichetta, c]) => (
              <li key={etichetta}>
                <span>
                  <strong>{etichetta}</strong>
                  {!etichette.includes(etichetta) && " (contatore non più nella tabella)"}: {c.descrizione}
                  {c.profilo && `; scenario «${c.profilo.nome}» del profilo energetico${c.profilo.conta_fv ? ", con il FV di casa nella comunità" : ""}`}
                  {c.batteria && `, batteria di casa ${numero(c.batteria.capacita_kwh)} kWh`}
                </span>
                <span className="azioni">
                  <button type="button" className="btn small" aria-label={`Scarica il profilo energetico di ${etichetta}`}
                    title="Scarica il profilo energetico di questo contatore, senza nome né POD"
                    onClick={() => void scaricaProfilo(etichetta, c)}>
                    <Download size={14} /> Profilo
                  </button>
                  <button type="button" className="btn small" aria-label={`Togli i consumi orari di ${etichetta}`}
                    onClick={() => togliCurva(etichetta)}>
                    <X size={14} /> Togli
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <p className="small muted">Per questi contatori consumo annuo e fasce della tabella non si usano: valgono le curve caricate.</p>
        </>
      )}
    </section>
  );
}
