/** Illustrazioni clay generate per il progetto, WebP trasparenti 48/96 px. */
export type IconName = "casa" | "localita" | "bolletta" | "risultati" | "sensibilita" | "report" | "rapida" | "verifica" | "clima" | "costi" | "solare" | "nome" | "crescita" | "comunita" | "contatore" | "tetto-mappa" | "condivisa" | "riparto" | "economia-comunita" | "scheda-famiglia" | "ombre";
export function Icon({ name, size = 24, label, className = "" }: { name: IconName; size?: number; label?: string; className?: string }) {
  const source = `${import.meta.env.BASE_URL}icons/${name}`;
  return <img className={`casa-icon ${className}`} src={`${source}.webp`} srcSet={`${source}.webp 1x, ${source}-2x.webp 2x`} width={size} height={size} alt={label ?? ""} aria-hidden={label ? undefined : true} draggable={false} />;
}
