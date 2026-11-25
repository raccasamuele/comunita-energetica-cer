import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";

/** Dettagli su richiesta; la copia resta nel DOM per aria-describedby e nella stampa. */
/** Pagina tecnica della CER (indirizzo senza «.html»: quello con «.html» risponde con un rinvio). */
export const METODO_CER = "https://raccasamuele.it/metodo/comunita-energetica";

/** Paragrafi a cui l'interfaccia può rimandare: elenco chiuso, da raccasamuele.it/docs/metodo/collegamenti.md
 *  (tutti presenti nella pagina pubblicata il 6/11/2026). */
export const METODO_ID = [
  "pvgis-richiesta-serie", "calendario-rimappatura", "fotovoltaico-degrado-inverter", "consumi-totale-forma", "consumi-varianti-orarie",
  "curve-misurate-calcolate", "bilancio-contatore", "batteria-privata", "condivisione-oraria", "esempio-contemporaneita",
  "perimetri-decorrenze", "attribuzione-impianti-punti", "tip-per-impianto", "capitale-esenzioni-f", "cacv-valorizzazione",
  "riparto-netto", "van-consolidamento", "profilo-energetico",
] as const;
export type MetodoId = (typeof METODO_ID)[number];

/** «Come lo calcoliamo»: apre il paragrafo della pagina tecnica in una nuova scheda; in stampa mostra l'indirizzo. */
export function MethodLink({ anchor }: { anchor: MetodoId }) {
  return <a className="method-link" href={`${METODO_CER}#${anchor}`} target="_blank" rel="noopener">Come lo calcoliamo<span className="sr-only"> (si apre in una nuova scheda)</span></a>;
}

export function InfoTip({ label, children, id, text, method }: { label: string; children: ReactNode; id?: string; text?: string; method?: MetodoId }) {
  const generatedId = useId();
  const contentId = id ?? `info-${generatedId}`;
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<CSSProperties>({ visibility: "hidden" });
  const root = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const place = () => {
      if (!button.current || !content.current) return;
      const rect = button.current.getBoundingClientRect();
      const viewport = window.visualViewport;
      const leftEdge = viewport?.offsetLeft ?? 0;
      const topEdge = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? window.innerWidth;
      const height = viewport?.height ?? window.innerHeight;
      if (rect.bottom < topEdge || rect.top > topEdge + height) { setOpen(false); return; }
      const popupWidth = Math.min(336, width - 24);
      content.current.style.width = `${popupWidth}px`;
      content.current.style.maxHeight = `${height - 32}px`;
      const popupHeight = Math.min(content.current.scrollHeight, height - 32);
      setPosition({
        width: popupWidth,
        maxHeight: height - 32,
        left: Math.max(leftEdge + 12, Math.min(rect.left, leftEdge + width - popupWidth - 12)),
        top: Math.max(topEdge + 12, Math.min(rect.bottom + 8, topEdge + height - popupHeight - 12)),
      });
    };
    const dismiss = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      button.current?.focus();
    };
    place();
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", dismiss);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("focusin", dismiss);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
    };
  }, [open]);
  // Solo l'ultima parola resta unita al comando; il resto della frase può andare a capo.
  const words = text?.match(/^(.*\s)?(\S+)\s*$/s);
  return <>{words?.[1]}<span className={`info-tip${words ? " info-anchor" : ""}`} ref={root}>
    {words && <>{words[2]}{"\u00a0"}</>}
    <button ref={button} type="button" className="info-trigger" aria-label={`Spiegazione: ${label}`} aria-expanded={open} aria-controls={contentId} onClick={() => setOpen((value) => !value)}><span aria-hidden="true">?</span></button>
    <span ref={content} id={contentId} className="info-copy" role="note" aria-label={`Dettaglio: ${label}`} hidden={!open} style={position}>{children}{method && <span className="method-line"><MethodLink anchor={method} /></span>}</span>
  </span></>;
}

/** Per la prosa: una frase resta visibile, il testo integrale è sempre raggiungibile. */
export function Brief({ label, children, method }: { label: string; children: ReactNode; method?: MetodoId }) {
  if (typeof children !== "string") return <InfoTip label={label} method={method}>{children}</InfoTip>;
  const first = children.match(/^.*?[.!?](?:\s|$)/)?.[0].trim();
  if (!first || first === children.trim()) return method ? <InfoTip text={children} label={label} method={method}>{children}</InfoTip> : <>{children}</>;
  return <InfoTip text={first} label={label} method={method}>{children}</InfoTip>;
}
