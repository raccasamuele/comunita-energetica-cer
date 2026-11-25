// Un contenitore che può scorrere di lato (tabelle larghe, grafici su telefono). Quando il contenuto è più largo,
// il contenitore entra nell'ordine del Tab ed è una regione con un nome, così si scorre anche con le frecce della
// tastiera (WCAG 2.1.1, regola axe scrollable-region-focusable). Quando ci sta tutto non aggiunge fermate al Tab.
import { useEffect, useRef, useState, type ReactNode } from "react";

export function Scorrevole({ className, etichetta, children }: { className: string; etichetta: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [scorre, setScorre] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const misura = () => setScorre(el.scrollWidth > el.clientWidth + 1);
    misura();
    const osserva = new ResizeObserver(misura);
    osserva.observe(el);
    if (el.firstElementChild) osserva.observe(el.firstElementChild);
    return () => osserva.disconnect();
  }, []);
  return (
    <div ref={ref} className={className} {...(scorre ? { tabIndex: 0, role: "region", "aria-label": `${etichetta} (scorre di lato)` } : {})}>
      {children}
    </div>
  );
}
