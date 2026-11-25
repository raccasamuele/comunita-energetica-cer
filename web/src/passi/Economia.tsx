// Passo 4: come si dividono i contributi (scelta obbligatoria), i prezzi dell'energia e i valori avanzati, come
// nell'app Streamlit. I valori vuoti valgono quelli delle assunzioni economiche del motore (costanti_economia), che
// compaiono come segnaposto. I prezzi orari caricati restano nella bozza di questo browser, non nel salvataggio.

import { useEffect, useId, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, X } from "lucide-react";
import { Icon } from "../ui/icons";
import { InfoTip } from "../ui/info-tip";
import { Messaggi } from "../ui/issues";
import { base64 } from "../bozza";
import type { Motore } from "../motore/client";
import type { CostantiEconomia, Tabelle } from "../motore/contratto";
import { euro } from "../formato";
import { Campo, CampoNumero, scriviNumero } from "./campi";

const QUOTE: { valore: number; etichetta: string; didascalia: string }[] = [
  { valore: 0, etichetta: "0% ai membri", didascalia: "Tutto a chi investe" },
  { valore: 0.5, etichetta: "50% ai membri", didascalia: "Metà a chi investe" },
  { valore: 1, etichetta: "100% ai membri", didascalia: "Niente a chi investe" },
];

export function Economia({ tabelle, aggiorna, motore }: {
  tabelle: Tabelle;
  aggiorna: (f: (t: Tabelle) => Tabelle) => void;
  motore: Motore;
}) {
  const p = tabelle.parametri as Record<string, number | string | null | undefined>;
  const tipo = tabelle.generale.tipo;
  const [costanti, setCostanti] = useState<CostantiEconomia | null>(null);
  const quota = typeof p.quota_membri === "number" ? p.quota_membri : null;
  const [altra, setAltra] = useState(quota !== null && !QUOTE.some((q) => q.valore === quota));

  useEffect(() => {
    motore.chiama("costanti_economia", { tipo }).then(setCostanti).catch(() => undefined);
  }, [motore, tipo]);

  const cambia = (chiave: string, valore: number | string | null) =>
    aggiorna((t) => {
      const parametri = { ...t.parametri, [chiave]: valore };
      if (valore === null) delete parametri[chiave];
      return { ...t, parametri };
    });
  const numero = (chiave: string) => (typeof p[chiave] === "number" ? (p[chiave] as number) : null);
  const medie = costanti?.prezzi_medi;

  return (
    <>
      <section className="section" aria-labelledby="t-riparto">
        <h2 id="t-riparto"><span className="section-icon"><Icon name="riparto" /></span>Come si dividono i contributi</h2>
        <p className="sintesi">
          <InfoTip text="Scegli la quota dei contributi destinata ai membri." label="Come funziona il riparto">Tolti i costi di gestione, i contributi GSE vanno in parte ai membri, in proporzione all'energia condivisa, e il resto a chi ha pagato l'impianto. La quota la decidono statuto o contratto.</InfoTip>
        </p>
        <fieldset className="scelte">
          <legend>Quota del netto ai membri</legend>
          {QUOTE.map((q) => (
            <label key={q.valore} className="scelta">
              <input type="radio" name="quota" checked={!altra && quota === q.valore}
                onChange={() => { setAltra(false); cambia("quota_membri", q.valore); }} />
              <span><strong>{q.etichetta}</strong><span className="small muted">{q.didascalia}</span></span>
            </label>
          ))}
          <label className="scelta">
            <input type="radio" name="quota" checked={altra}
              onChange={() => { setAltra(true); cambia("quota_membri", quota ?? 0.3); }} />
            <span><strong>Altra quota</strong></span>
          </label>
        </fieldset>
        {altra && (
          <div className="grid">
            <Campo id="quota-altra" etichetta="Quota ai membri, %">
              <CampoNumero id="quota-altra" valore={quota === null ? null : Math.round(quota * 100)} min={0} max={100}
                onChange={(v) => cambia("quota_membri", v === null ? null : v / 100)} />
            </Campo>
          </div>
        )}
        {quota === null && (
          <div className="notice info"><AlertTriangle size={18} /><div>Scegli quanta parte dei contributi va ai membri: senza questa scelta lo scenario non si calcola.</div></div>
        )}
      </section>

      <Prezzi tabelle={tabelle} aggiorna={aggiorna} motore={motore} medie={medie} />

      <section className="section" aria-labelledby="t-avanzati">
        <h2 id="t-avanzati"><span className="section-icon"><Icon name="sensibilita" /></span>Valori avanzati</h2>
        <details className="advanced">
          <summary>Bollette, vendita, costi e tasso di sconto</summary>
          <p className="small muted">Valori tipici in grigio: cambiali solo se hai dati migliori.</p>
          <div className="grid allinea-campi">
            <Campo id="costo-evitabile" etichetta="Risparmio in bolletta per kWh autoconsumato, €"
              suggerimento="Quota energia più oneri variabili della bolletta, non il prezzo medio totale">
              <CampoNumero id="costo-evitabile" valore={numero("costo_evitabile_eur_kwh")} min={0} max={1} decimali={3}
                segnaposto={costanti ? scriviNumero(costanti.costo_evitabile_eur_kwh, 3) : undefined} descrittoDa="costo-evitabile-aiuto"
                onChange={(v) => cambia("costo_evitabile_eur_kwh", v)} />
            </Campo>
            <Campo id="tasso-sconto" etichetta="Tasso di sconto reale, %"
              suggerimento="Quanto renderebbe il denaro in un altro investimento, al netto dell'inflazione: serve a confrontare euro di anni diversi">
              <CampoNumero id="tasso-sconto" valore={numero("tasso_sconto") === null ? null : numero("tasso_sconto")! * 100} min={0} max={20} decimali={1}
                segnaposto={costanti ? scriviNumero(costanti.tasso_sconto * 100, 1) : undefined} descrittoDa="tasso-sconto-aiuto"
                onChange={(v) => cambia("tasso_sconto", v === null ? null : v / 100)} />
            </Campo>
          </div>
          <fieldset className="scelte">
            <legend>Vendita dell'energia immessa</legend>
            {[["RID", "Ritiro dedicato GSE"], ["mercato", "A un trader"]].map(([valore, etichetta]) => (
              <label key={valore} className="scelta">
                <input type="radio" name="regime" checked={(p.regime_vendita ?? "RID") === valore} onChange={() => cambia("regime_vendita", valore)} />
                <span><strong>{etichetta}</strong></span>
              </label>
            ))}
          </fieldset>
          <h3 className="sottotitolo-avanzati">Costi da preventivo</h3>
          <p className="small muted">Vuoto vale il predefinito. Il costo degli impianti va al passo 3.</p>
          <div className="grid allinea-campi">
            <Campo id="om" etichetta="Manutenzione e assicurazione, % del costo all'anno">
              <CampoNumero id="om" valore={numero("om_assicurazione_quota_anno") === null ? null : numero("om_assicurazione_quota_anno")! * 100}
                min={0} max={10} decimali={1} segnaposto={costanti ? scriviNumero(costanti.om_assicurazione_quota_anno * 100, 1) : undefined}
                onChange={(v) => cambia("om_assicurazione_quota_anno", v === null ? null : v / 100)} />
            </Campo>
            <Campo id="gestione" etichetta="Gestione della configurazione, €/anno" suggerimento="Contabilità, piattaforma, referente">
              <CampoNumero id="gestione" valore={numero("gestione_eur_anno")} min={0} max={100_000} descrittoDa="gestione-aiuto"
                segnaposto={costanti ? scriviNumero(costanti.gestione_eur_anno) : undefined} onChange={(v) => cambia("gestione_eur_anno", v)} />
            </Campo>
            <Campo id="costituzione" etichetta="Costituzione, € una tantum"
              suggerimento="Atto costitutivo e statuto per una CER, contratto tra i partecipanti per un gruppo">
              <CampoNumero id="costituzione" valore={numero("costituzione_eur")} min={0} max={100_000} descrittoDa="costituzione-aiuto"
                segnaposto={costanti ? scriviNumero(costanti.costituzione_eur) : undefined} onChange={(v) => cambia("costituzione_eur", v)} />
            </Campo>
          </div>
        </details>
      </section>
    </>
  );
}

function Prezzi({ tabelle, aggiorna, motore, medie }: {
  tabelle: Tabelle;
  aggiorna: (f: (t: Tabelle) => Tabelle) => void;
  motore: Motore;
  medie: Record<"basso" | "base" | "alto", number> | undefined;
}) {
  const idFile = useId();
  const [versione, setVersione] = useState(0);
  const [inLettura, setInLettura] = useState(false);
  const [errori, setErrori] = useState<string[]>([]);
  const caricati = Object.values(tabelle.prezzi ?? {}).sort((a, b) => a.anno - b.anno);

  async function leggi(file: File[]) {
    if (file.length === 0) return;
    setInLettura(true);
    setErrori([]);
    try {
      const contenuti = await Promise.all(file.map(async (f) => ({ nome: f.name, base64: await base64(f) })));
      const r = await motore.chiama("leggi_prezzi", { file: contenuti, regione: tabelle.generale.regione });
      setErrori(r.errori);
      if (r.ok) aggiorna((t) => ({ ...t, prezzi: r.prezzi }));
    } catch (e) {
      setErrori([e instanceof Error ? e.message : String(e)]);
    } finally {
      setInLettura(false);
      setVersione((v) => v + 1);
    }
  }

  return (
    <section className="section" aria-labelledby="t-prezzi">
      <h2 id="t-prezzi"><span className="section-icon"><Icon name="crescita" /></span>Prezzi dell'energia</h2>
      <p className="sintesi">
        <InfoTip text={`Scenari a ${medie ? `${scriviNumero(medie.basso)}, ${scriviNumero(medie.base)} e ${scriviNumero(medie.alto)} €/MWh` : "tre livelli di prezzo"}.`} label="Prezzi degli scenari">Senza prezzi orari il prezzo è costante e la qualità resta C; un anno di prezzi orari dà la forma reale della giornata, con i prezzi più bassi nelle ore di sole.</InfoTip>
      </p>
      <details className="advanced" open={caricati.length > 0}>
        <summary>Carica prezzi orari, per uso personale</summary>
        <p className="small muted">
          <InfoTip text="Dati GME solo per uso personale." label="Uso dei prezzi GME">Non sono inclusi nel sito, restano in questo browser e non finiscono nel file esportato.</InfoTip>
        </p>
        <details className="advanced">
          <summary>Formato del file</summary>
          <p className="small">
            Colonna <code>inizio</code> con data, ora e fuso orario (es. 2024-03-31T02:00:00+02:00) e una colonna per zona
            (NORD, CNOR, CSUD, SUD, CALA, SICI, SARD) in €/MWh. Più anni: 2021, 2022 e 2023 si abbinano al meteo dello
            stesso anno; per gli altri si usa il file più recente.
          </p>
        </details>
        <div className="field">
          <label htmlFor={idFile}>File CSV dei prezzi, uno per anno</label>
          <input key={versione} id={idFile} type="file" accept=".csv,text/csv" multiple disabled={inLettura}
            onChange={(e) => void leggi(Array.from(e.target.files ?? []))} />
        </div>
        <div aria-live="polite">
          {inLettura && <p className="muted" role="status"><Loader2 size={14} /> Lettura dei prezzi…</p>}
          <Messaggi titolo="File dei prezzi da correggere" messaggi={errori} bloccanti />
        </div>
        {caricati.length > 0 && (
          <>
            <div className="notice ok"><CheckCircle2 size={18} /><div>Prezzi orari in uso per la regione {tabelle.generale.regione}.</div></div>
            <ul className="curve">
              {caricati.map((s) => (
                <li key={s.anno}>
                  <span><strong>{s.anno}</strong>, zona {s.zona}, media {euro(s.media)}/MWh</span>
                  <button type="button" className="btn small" aria-label={`Togli i prezzi del ${s.anno}`}
                    onClick={() => aggiorna((t) => {
                      const prezzi = { ...(t.prezzi ?? {}) };
                      delete prezzi[String(s.anno)];
                      return { ...t, prezzi };
                    })}>
                    <X size={14} /> Togli
                  </button>
                </li>
              ))}
            </ul>
            <p className="small muted">Se cambi regione al passo 1, ricarica i file: la zona di mercato dipende dalla regione.</p>
          </>
        )}
      </details>
    </section>
  );
}
