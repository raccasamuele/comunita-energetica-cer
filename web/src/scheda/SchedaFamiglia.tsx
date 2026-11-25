// La pagina del link per famiglie e attività: che cosa serve, dove trovarlo, i propri consumi, un file da mandare.
// Si apre subito: il motore Python parte solo se si allegano i consumi ora per ora.

import { useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Upload, Loader2, X } from "lucide-react";
import { Icon } from "../ui/icons";
import { Brief, InfoTip } from "../ui/info-tip";
import { Messaggi } from "../ui/issues";
import { base64 } from "../bozza";
import type { Motore } from "../motore/client";
import { AVVISO_CAMPI_NON_VALIDI, CampoNumero, Scelta, useCampiNonValidi } from "../passi/campi";
import { kwh } from "../formato";
import { controlla, creaScheda, nomeFileScheda, testi, type ContatoreScheda, type Scheda } from "./scheda";

const ENTE = "Ente territoriale (es. Comune)";
const MAX_BYTE_FILE = 50_000_000;

let motore: Motore | null = null;
/** Il motore si avvia solo la prima volta che servono i file orari. */
const motoreScheda = async (suStato: (fase: string) => void) => {
  const { Motore } = await import("../motore/client");
  return (motore ??= new Motore(suStato));
};

const contatoreNuovo = (i: number, tipologia: string | null): ContatoreScheda => ({
  nome: i === 0 ? "Contatore" : `Contatore ${i + 1}`, tipologia, kwh_annui: null, f1_kwh: null, f23_kwh: null, tensione: "BT", curva: null,
});

export function SchedaFamiglia() {
  const per = (new URLSearchParams(window.location.search).get("per") ?? "").trim().slice(0, testi.max_testo);
  const [indiceProfilo, setIndiceProfilo] = useState(0);
  const profilo = testi.profili[indiceProfilo];
  const [attivita, setAttivita] = useState<string>(testi.soggetti_attivita[0].valore);
  const [membro, setMembro] = useState("");
  const [contatori, setContatori] = useState<ContatoreScheda[]>([contatoreNuovo(0, profilo.tipologia)]);
  const titolo = useRef<HTMLHeadingElement>(null);
  const famiglia = profilo.tipologia === "Famiglia";
  const tipoSoggetto = profilo.tipo_soggetto ?? attivita;
  const tipologie = profilo.tipologia ? [] : tipoSoggetto === ENTE ? testi.tipologie_ente : testi.tipologie_attivita;

  useEffect(() => {
    document.title = "I consumi di luce · Energia in chiaro";
    titolo.current?.focus({ preventScroll: true });
  }, []);

  function scegliProfilo(i: number) {
    setIndiceProfilo(i);
    setContatori((cs) => cs.map((c) => ({ ...c, tipologia: testi.profili[i].tipologia, tensione: testi.profili[i].tipologia === "Famiglia" ? "BT" : c.tensione })));
  }

  function quanti(n: number | null) {
    if (n === null || n < 1 || n > testi.max_contatori) return;
    setContatori((cs) => (n > cs.length ? [...cs, ...Array.from({ length: n - cs.length }, (_, k) => contatoreNuovo(cs.length + k, profilo.tipologia))] : cs.slice(0, n)));
  }

  const cambia = (i: number, parte: Partial<ContatoreScheda>) => setContatori((cs) => cs.map((c, j) => (j === i ? { ...c, ...parte } : c)));

  const scheda: Scheda = {
    membro,
    tipo_soggetto: tipoSoggetto,
    // con un solo contatore il nome non si chiede: resta "Contatore", come nell'app
    contatori: contatori.length === 1 ? [{ ...contatori[0], nome: "Contatore" }] : contatori,
    configurazione: per || null,
  };
  const errori = controlla(scheda);
  const nonValidi = useCampiNonValidi();

  function scarica() {
    const url = URL.createObjectURL(new Blob([creaScheda(scheda)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: nomeFileScheda(membro) });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="app scheda">
      <header className="scheda-testa">
        <span className="logo-mark" aria-hidden="true"><Icon name="scheda-famiglia" size={44} /></span>
        <div>
          <span className="famiglia">Energia in chiaro · Comunità energetica</span>
          <h1 ref={titolo} tabIndex={-1}>I consumi di luce</h1>
          <p className="muted">
            {per && <>Per <strong>{per}</strong>. </>}<InfoTip text="Ti basta una bolletta della luce." label="A cosa serve la scheda">I consumi servono a valutare un impianto fotovoltaico condiviso.</InfoTip>
          </p>
        </div>
      </header>

      <main className="panel">
        <section className="section" aria-labelledby="t-serve">
          <h2 id="t-serve"><Icon name="bolletta" /> Che cosa serve</h2>
          <p><Brief label="Dati della bolletta">{"Il consumo dell'ultimo anno in kWh; le fasce F1 e F2+F3 se le hai. Il codice POD non serve."}</Brief></p>
          <details className="advanced">
            <summary>Dove trovo i consumi?</summary>
            <ul className="guida">
              {testi.cosa_serve.map((v) => (
                <li key={v.cosa}><strong>{v.cosa}</strong><span>{v.dove}</span></li>
              ))}
            </ul>
            <p className="small muted">{testi.portale_consumi} {testi.codice_pod}</p>
          </details>
        </section>

        <section className="section" aria-labelledby="t-dati">
          <h2 id="t-dati"><Icon name="contatore" /> I tuoi dati</h2>
          <fieldset className="scelte">
            <legend>Chi sei</legend>
            {testi.profili.map((p, i) => (
              <label key={p.etichetta} className="scelta">
                <input type="radio" name="profilo" checked={indiceProfilo === i} onChange={() => scegliProfilo(i)} />
                <span><strong>{p.etichetta}</strong></span>
              </label>
            ))}
          </fieldset>
          <div className="grid" style={{ marginTop: 14 }}>
            {profilo.tipo_soggetto === null && (
              <div className="field">
                <label htmlFor="attivita">Che tipo di attività è</label>
                <select id="attivita" value={attivita} onChange={(e) => setAttivita(e.target.value)}>
                  {testi.soggetti_attivita.map((s) => <option key={s.valore} value={s.valore}>{s.etichetta}</option>)}
                </select>
              </div>
            )}
            <div className="field">
              <label htmlFor="membro">Il nome con cui vuoi comparire</label>
              <input id="membro" type="text" value={membro} maxLength={testi.max_testo} autoComplete="off"
                placeholder={famiglia ? "Rossi, interno 3" : "Panetteria Bianchi"} onChange={(e) => setMembro(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="quanti">Quanti contatori della luce hai</label>
              <CampoNumero id="quanti" valore={contatori.length} min={1} max={testi.max_contatori} descrittoDa="quanti-aiuto" onChange={quanti} />
              <span className="hint"><InfoTip id="quanti-aiuto" text="Di solito uno." label="Quanti contatori">Una bolletta della luce per ogni contatore.</InfoTip></span>
            </div>
          </div>

          {contatori.map((c, i) => (
            <ContatoreForm key={i} i={i} c={c} multipli={contatori.length > 1} famiglia={famiglia} tipologie={tipologie} cambia={cambia} />
          ))}
        </section>

        <section className="section" aria-labelledby="t-consegna">
          <h2 id="t-consegna"><Icon name="scheda-famiglia" /> Consegna</h2>
          {!membro.trim() ? (
            <p>Scrivi il nome con cui vuoi comparire: poi potrai scaricare la scheda.</p>
          ) : errori.length > 0 || nonValidi > 0 ? (
            <Messaggi titolo="Prima di scaricare la scheda" messaggi={nonValidi > 0 ? [AVVISO_CAMPI_NON_VALIDI, ...errori] : errori} bloccanti />
          ) : (
            <>
              {scheda.contatori.some((c) => c.kwh_annui === null && !c.curva) && (
                <p className="small muted">Senza consumo annuo si userà quello di una famiglia tipo, {kwh(testi.kwh_famiglia_tipo)} all'anno.</p>
              )}
              <button type="button" className="btn primary" onClick={scarica}>
                <Upload size={16} /> Scarica la scheda
              </button>
              <p>Poi manda il file a chi coordina, per email o messaggio.</p>
            </>
          )}
          <p className="small muted"><InfoTip text="I dati restano nel browser: scegli tu a chi mandare la scheda." label="Privacy della scheda">{testi.privacy}</InfoTip></p>
        </section>
      </main>

      <footer className="foot">
        © 2026 Samuele Racca: puoi usare liberamente questo sito, anche per lavoro; il codice è open source, con licenza
        MIT. <a href="./licenza.txt">Licenza e crediti</a> · <a href="./privacy.html">Privacy</a>.
      </footer>
    </div>
  );
}

function ContatoreForm(props: {
  i: number;
  c: ContatoreScheda;
  multipli: boolean;
  famiglia: boolean;
  tipologie: string[];
  cambia: (i: number, parte: Partial<ContatoreScheda>) => void;
}) {
  const { i, c, multipli, famiglia, tipologie, cambia } = props;
  const id = `c${i}`;
  return (
    <fieldset className="contatore">
      <legend>{multipli ? `Contatore ${i + 1}` : "Il contatore"}</legend>
      <div className="grid">
        {multipli && (
          <div className="field">
            <label htmlFor={`${id}-nome`}>Nome del contatore</label>
            <input id={`${id}-nome`} type="text" value={c.nome} maxLength={testi.max_testo} aria-describedby={`${id}-nome-aiuto`}
              onChange={(e) => cambia(i, { nome: e.target.value })} />
            <span className="hint"><InfoTip id={`${id}-nome-aiuto`} label="Nome del contatore">Per esempio "Negozio" o "Magazzino".</InfoTip></span>
          </div>
        )}
        {tipologie.length > 0 && (
          <div className="field">
            <label htmlFor={`${id}-tipo`}>Come si usa l'energia</label>
            <Scelta id={`${id}-tipo`} valore={c.tipologia} opzioni={tipologie} onChange={(v) => cambia(i, { tipologia: v })} />
          </div>
        )}
        <div className="field">
          <label htmlFor={`${id}-kwh`}>Consumo dell'ultimo anno, kWh</label>
          <CampoNumero id={`${id}-kwh`} valore={c.kwh_annui} min={0} max={testi.max_kwh} onChange={(v) => cambia(i, { kwh_annui: v })} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-f1`}>di cui in F1, kWh (facoltativo)</label>
          <CampoNumero id={`${id}-f1`} valore={c.f1_kwh} min={0} max={testi.max_kwh} onChange={(v) => cambia(i, { f1_kwh: v })} />
        </div>
        <div className="field">
          <label htmlFor={`${id}-f23`}>di cui in F2+F3, kWh (facoltativo)</label>
          <CampoNumero id={`${id}-f23`} valore={c.f23_kwh} min={0} max={testi.max_kwh} descrittoDa={`${id}-f23-aiuto`} onChange={(v) => cambia(i, { f23_kwh: v })} />
          <span className="hint"><InfoTip id={`${id}-f23-aiuto`} label="Fasce F2 e F3">Somma di F2 e F3.</InfoTip></span>
        </div>
        {!famiglia && (
          <div className="field">
            <label htmlFor={`${id}-tensione`}>Tensione della fornitura</label>
            <select id={`${id}-tensione`} value={c.tensione} aria-describedby={`${id}-tensione-aiuto`}
              onChange={(e) => cambia(i, { tensione: e.target.value === "MT" ? "MT" : "BT" })}>
              <option value="BT">Bassa tensione</option>
              <option value="MT">Media tensione</option>
            </select>
            <span className="hint"><InfoTip id={`${id}-tensione-aiuto`} label="Tensione della fornitura">In bolletta, nei dati della fornitura.</InfoTip></span>
          </div>
        )}
      </div>
      <ConsumiOrariScheda i={i} c={c} cambia={cambia} />
    </fieldset>
  );
}

/** Facoltativo: i file dei consumi ora per ora. Il motore ne ricava la forma media, senza il codice POD; solo quella
 * finisce nella scheda. */
function ConsumiOrariScheda({ i, c, cambia }: { i: number; c: ContatoreScheda; cambia: (i: number, parte: Partial<ContatoreScheda>) => void }) {
  const idFile = useId();
  const [fase, setFase] = useState<string | null>(null);
  const [errore, setErrore] = useState<string | null>(null);
  const [avvisi, setAvvisi] = useState<string[]>([]);

  async function leggi(file: File[]) {
    if (file.length === 0) return;
    setErrore(null);
    if (file.reduce((s, f) => s + f.size, 0) > MAX_BYTE_FILE) {
      setErrore("I file sono troppo grandi: al massimo 50 MB insieme.");
      return;
    }
    try {
      setFase("Preparo il calcolo: la prima volta servono alcuni secondi…");
      const m = await motoreScheda((f) => setFase(`Preparo il calcolo (${f.toLowerCase()})…`));
      const contenuti = await Promise.all(file.map(async (f) => ({ nome: f.name, base64: await base64(f) })));
      const letti = await m.chiama("leggi_consumi", { file: contenuti });
      if (!letti.ok) {
        setErrore(letti.errore);
        return;
      }
      if (letti.scegli) {
        setErrore("Questo è un profilo energetico del simulatore della casa: mandalo così com'è a chi prepara la comunità, che sceglie lo scenario e se contare il tuo fotovoltaico.");
        return;
      }
      const { curva, descrizione, calcolata } = letti;
      cambia(i, { curva: { curva, descrizione, calcolata } });
      setAvvisi(letti.avvisi);
    } catch (e) {
      setErrore(e instanceof Error ? e.message : String(e));
    } finally {
      setFase(null);
    }
  }

  return (
    <div className="field consumi-scheda">
      <label htmlFor={idFile}>Facoltativo: i consumi ora per ora</label>
      <input id={idFile} type="file" accept=".csv,text/csv" multiple aria-describedby={`${idFile}-aiuto`} disabled={fase !== null}
        onChange={(e) => void leggi(Array.from(e.target.files ?? []))} />
      <span className="hint">
        <InfoTip id={`${idFile}-aiuto`} text="Il file non viene salvato e il POD non viene letto." label="Consumi orari e privacy">letture.csv del Portale Consumi o i file mensili di e-distribuzione. Nella scheda va solo la forma media dei consumi.</InfoTip>
      </span>
      <div aria-live="polite">
        {fase && <p className="muted" role="status"><Loader2 size={14} /> {fase}</p>}
        {errore && <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{errore}</div></div>}
        {c.curva && !fase && (
          <div className="notice ok">
            <CheckCircle2 size={18} />
            <div>
              Consumi letti: {c.curva.descrizione}.
              <Messaggi titolo="Consumi da verificare" messaggi={avvisi} />
              <div><button type="button" className="link" onClick={() => cambia(i, { curva: null })}><X size={12} /> Togli i consumi orari</button></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
