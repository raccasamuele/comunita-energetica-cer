import { InfoTip } from "./info-tip";

/** Il motore resta la fonte del testo. Raggruppa solo messaggi identici, anche riferiti a righe diverse. */
export function raggruppaMessaggi(messages: string[]) {
  const groups = new Map<string, { testo: string; soggetti: string[]; totale: number }>();
  for (const message of messages) {
    const match = message.match(/^([^:]{1,120}):\s+(.+)$/s);
    const testo = match?.[2] ?? message;
    const current = groups.get(testo) ?? { testo, soggetti: [], totale: 0 };
    if (match && !current.soggetti.includes(match[1])) current.soggetti.push(match[1]);
    current.totale++;
    groups.set(testo, current);
  }
  return [...groups.values()];
}

export function Messaggi({ titolo = "Dati da verificare", messaggi, bloccanti = false }: {
  titolo?: string; messaggi: string[]; bloccanti?: boolean;
}) {
  if (!messaggi.length) return null;
  const groups = raggruppaMessaggi(messaggi);
  const content = <ul className="issues elenco">{groups.map((group) => <li key={group.testo}>
    {bloccanti ? group.testo : <InfoTip text={group.testo.split(/(?<=[.!?])\s/)[0]} label="Messaggio del controllo">{group.testo}</InfoTip>}
    {group.soggetti.length > 0 && <ul className="issue-chips" aria-label="Righe interessate">{group.soggetti.map((nome) => <li key={nome}><span>{nome}</span></li>)}</ul>}
    {group.totale > 1 && !group.soggetti.length && <span className="small muted"> ({group.totale} segnalazioni)</span>}
  </li>)}</ul>;
  return bloccanti
    ? <div className="notice bad issue-errors" role="alert"><strong>{titolo} ({messaggi.length})</strong>{content}</div>
    : <details className="issue-summary"><summary>{titolo} ({messaggi.length})</summary>{content}</details>;
}

export function QualitaContatori({ qualita }: { qualita: Record<"A" | "B" | "C", number> }) {
  const nomi = { A: "Curva completa", B: "Da bolletta o curva", C: "Con valori tipici" };
  const aiuti = { A: "Consumi misurati per almeno 11 mesi e con almeno tre quarti dei consumi coperti.", B: "Consumi annui da bolletta o curve calcolate: la forma oraria può essere stimata.", C: "Consumi ricavati da valori tipici: sostituiscili con dati di bolletta o misure." };
  return <details className="issue-summary"><summary>Qualità dei contatori ({Object.values(qualita).reduce((a, b) => a + b, 0)})</summary>
    <ul className="issue-chips">{(["A", "B", "C"] as const).filter((q) => qualita[q] > 0).map((q) => <li key={q}><span>
      <InfoTip text={`${nomi[q]} (${qualita[q]})`} label={nomi[q]}>{aiuti[q]}</InfoTip>
    </span></li>)}</ul>
  </details>;
}
