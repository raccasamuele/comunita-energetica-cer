// Campi dei moduli con le classi dello stile di Casa (.field, .hint, .field-error).

import { Children, cloneElement, isValidElement, useEffect, useId, useRef, useState, useSyncExternalStore, type ReactElement, type ReactNode } from "react";
import { InfoTip } from "../ui/info-tip";

/** Numero scritto all'italiana: la virgola è il decimale; il punto seguito da gruppi di tre cifre separa le migliaia
 * ("12.000" → 12000), altrimenti è un decimale ("45.07"). Testo vuoto → null; testo non leggibile → NaN. */
export function leggiNumero(testo: string): number | null {
  let t = testo.trim().replace(/\s/g, "").replace(/−/g, "-");
  if (!t) return null;
  if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
  else if (/^-?[1-9]\d{0,2}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, "");
  return /^-?(\d+\.?\d*|\.\d+)$/.test(t) ? Number(t) : NaN;
}

// Caselle visibili che mostrano un errore: finché ce n'è una, il modello tiene l'ultimo valore valido e non il testo
// scritto, quindi salvare o scaricare darebbe un file diverso da quello che si vede.
const nonValide = new Set<string>();
const ascolti = new Set<() => void>();
function segnaNonValida(chiave: string, nonValida: boolean) {
  if (nonValida === nonValide.has(chiave)) return;
  if (nonValida) nonValide.add(chiave);
  else nonValide.delete(chiave);
  ascolti.forEach((f) => f());
}
const ascolta = (f: () => void) => {
  ascolti.add(f);
  return () => void ascolti.delete(f);
};

/** Quante caselle numeriche mostrano ora un errore. */
export function useCampiNonValidi(): number {
  return useSyncExternalStore(ascolta, () => nonValide.size);
}

export const AVVISO_CAMPI_NON_VALIDI = "Correggi prima i campi segnati in rosso: finché restano così, il file userebbe il valore precedente.";

export function scriviNumero(x: number | null, decimali = 0, gruppi = true): string {
  if (x == null || !Number.isFinite(x)) return "";
  return x.toLocaleString("it-IT", { maximumFractionDigits: decimali, useGrouping: gruppi ? "always" : false });
}

/** Casella per un numero: tiene il testo mentre si scrive e segnala ciò che non è un numero o è fuori intervallo. */
export function CampoNumero(props: {
  id?: string;
  valore: number | null;
  onChange: (v: number | null) => void;
  etichetta?: string; // nome accessibile, quando non c'è un <label>
  min?: number;
  max?: number;
  decimali?: number;
  gruppi?: boolean;
  disabled?: boolean;
  descrittoDa?: string;
  segnaposto?: string; // il valore predefinito che vale con la casella vuota
}) {
  const { valore, decimali = 0, gruppi = true } = props;
  const [testo, setTesto] = useState(scriviNumero(valore, decimali, gruppi));
  const inScrittura = useRef(false);
  const errore = useId();
  useEffect(() => {
    if (!inScrittura.current) setTesto(scriviNumero(valore, decimali, gruppi));
  }, [valore, decimali, gruppi]);
  const letto = leggiNumero(testo);
  const problema =
    letto !== null && Number.isNaN(letto) ? "Non è un numero" :
    letto !== null && props.min !== undefined && letto < props.min ? `Almeno ${scriviNumero(props.min, decimali, gruppi)}` :
    letto !== null && props.max !== undefined && letto > props.max ? `Al massimo ${scriviNumero(props.max, decimali, gruppi)}` :
    null;
  useEffect(() => {
    segnaNonValida(errore, problema !== null);
    return () => segnaNonValida(errore, false);
  }, [errore, problema]);
  return (
    <span className="num-input">
      <input
        id={props.id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        aria-label={props.etichetta}
        aria-invalid={problema ? true : undefined}
        aria-describedby={[props.descrittoDa, problema ? errore : undefined].filter(Boolean).join(" ") || undefined}
        value={testo}
        placeholder={props.segnaposto}
        disabled={props.disabled}
        onFocus={() => (inScrittura.current = true)}
        onBlur={() => {
          inScrittura.current = false;
          if (!problema) setTesto(scriviNumero(valore, decimali, gruppi));
        }}
        onChange={(e) => {
          setTesto(e.target.value);
          const v = leggiNumero(e.target.value);
          if (v === null || (!Number.isNaN(v) && (props.min === undefined || v >= props.min) && (props.max === undefined || v <= props.max))) {
            props.onChange(v);
          }
        }}
      />
      {problema && <span id={errore} className="field-error">{problema}</span>}
    </span>
  );
}

/** Etichetta, campo e suggerimento. */
export function Campo({ id, etichetta, suggerimento, children }: { id: string; etichetta: string; suggerimento?: ReactNode; children: ReactNode }) {
  return (
    <div className="field">
      <div className="field-label"><label htmlFor={id}>{etichetta}</label>{suggerimento && <InfoTip id={`${id}-aiuto`} label={etichetta}>{suggerimento}</InfoTip>}</div>
      {Children.map(children, (child) => isValidElement(child) ? cloneElement(child as ReactElement<Record<string, unknown>>, {
        [typeof child.type === "string" ? "aria-describedby" : "descrittoDa"]: suggerimento ? `${id}-aiuto` : undefined,
      }) : child)}
    </div>
  );
}

/** Elenco a scelta; con `vuota` si parte senza scelta. Il valore attuale resta tra le opzioni anche se l'elenco
 * del motore non è ancora arrivato. */
export function Scelta(props: {
  id?: string;
  valore: string | null;
  opzioni: string[];
  onChange: (v: string | null) => void;
  etichetta?: string;
  vuota?: string;
  etichette?: Record<string, string>;
  disabled?: boolean;
  descrittoDa?: string;
}) {
  const opzioni = props.valore && !props.opzioni.includes(props.valore) ? [props.valore, ...props.opzioni] : props.opzioni;
  return (
    <select
      id={props.id}
      aria-label={props.etichetta}
      aria-describedby={props.descrittoDa}
      value={props.valore ?? ""}
      disabled={props.disabled}
      onChange={(e) => props.onChange(e.target.value || null)}
    >
      {(props.vuota || !props.valore) && <option value="">{props.vuota ?? "Scegli…"}</option>}
      {opzioni.map((o) => (
        <option key={o} value={o}>{props.etichette?.[o] ?? o}</option>
      ))}
    </select>
  );
}
