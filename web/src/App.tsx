import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Download,
  Loader2,
  TriangleAlert,
  Upload,
  X,
} from "lucide-react";
import { bozzaVuota, cancellaBozza, leggiBozza, nomeFile, salvaBozza } from "./bozza";
import { Motore } from "./motore/client";
import type { Avvio, Costanti, CostantiImpianti, EsitoProgetto, Generale, Tabelle } from "./motore/contratto";
import { AVVISO_CAMPI_NON_VALIDI, useCampiNonValidi } from "./passi/campi";
import { Economia } from "./passi/Economia";
import { Impianti, tettoIniziale, type StatoTetto } from "./passi/Impianti";
import { Luogo } from "./passi/Luogo";
import { MembriConsumi } from "./passi/Membri";
import { Risultati } from "./passi/Risultati";
import { megabyte, secondi } from "./formato";
import { leggiArrivo } from "./ponte";
import { BarraFamiglia } from "./ui/famiglia";
import { Icon, type IconName } from "./ui/icons";
import { URL_COPYRIGHT_OSM } from "./ui/crediti-osm";
import { InfoTip } from "./ui/info-tip";
import { Messaggi } from "./ui/issues";

type IdPasso = "luogo" | "membri" | "impianti" | "economia" | "risultati";
const PASSI: { id: IdPasso; etichetta: string; titolo: string; icona: IconName }[] = [
  { id: "luogo", etichetta: "Luogo", titolo: "Luogo e configurazione", icona: "localita" },
  { id: "membri", etichetta: "Membri e consumi", titolo: "Membri e consumi", icona: "comunita" },
  { id: "impianti", etichetta: "Impianti", titolo: "Impianti fotovoltaici", icona: "solare" },
  { id: "economia", etichetta: "Economia", titolo: "Economia e riparto", icona: "economia-comunita" },
  { id: "risultati", etichetta: "Risultati", titolo: "Risultati", icona: "risultati" },
];
const MAX_BYTE_SALVATAGGIO = 12_000_000; // come cersim.ui_model.MAX_JSON_BYTE

type StatoMotore = { tipo: "avvio"; fase: string } | { tipo: "pronto"; avvio: Avvio } | { tipo: "errore"; messaggio: string };
type Messaggio = { tono: "ok" | "bad" | "info"; testo: string; dettagli?: string[] };

function Logo() {
  return (
    <span className="logo-mark" aria-hidden="true">
      <Icon name="comunita" size={38} />
    </span>
  );
}

export default function App() {
  const [iniziato, setIniziato] = useState(false);
  const [passo, setPasso] = useState<IdPasso>("luogo");
  const [stato, setStato] = useState<StatoMotore>({ tipo: "avvio", fase: "In attesa" });
  const [tabelle, setTabelle] = useState<Tabelle>(() => leggiBozza() ?? bozzaVuota());
  const [costanti, setCostanti] = useState<Costanti | null>(null);
  const [costantiImpianti, setCostantiImpianti] = useState<CostantiImpianti | null>(null);
  const [statoTetto, setStatoTetto] = useState<StatoTetto>(tettoIniziale);
  const [esito, setEsito] = useState<EsitoProgetto | null>(null);
  const [bozzaSalvata, setBozzaSalvata] = useState(true);
  const [messaggio, setMessaggio] = useState<Messaggio | null>(null);
  const [occupato, setOccupato] = useState<string | null>(null);
  // il profilo energetico arrivato da Casa con «Porta nella CER», in attesa del contatore al passo 2
  const [arrivo, setArrivo] = useState<File | null>(null);
  const nonValidi = useCampiNonValidi();
  useEffect(() => {
    if (nonValidi === 0) setMessaggio((m) => (m?.testo === AVVISO_CAMPI_NON_VALIDI ? null : m));
  }, [nonValidi]);
  const motore = useRef<Motore | null>(null);
  const titolo = useRef<HTMLHeadingElement>(null);
  const sceltaFile = useRef<HTMLInputElement>(null);
  const controllo = useRef(0);
  motore.current ??= new Motore((fase) => setStato({ tipo: "avvio", fase }));

  useEffect(() => {
    // il motore si carica subito, in sottofondo: mentre si compilano i passi diventa pronto
    motore.current!
      .avvia()
      .then((avvio) => {
        setStato({ tipo: "pronto", avvio });
        return Promise.all([motore.current!.chiama("costanti", {}), motore.current!.chiama("costanti_impianti", {})]);
      })
      .then(([c, ci]) => {
        setCostanti(c);
        setCostantiImpianti(ci);
      })
      .catch((e: unknown) => setStato({ tipo: "errore", messaggio: e instanceof Error ? e.message : String(e) }));
  }, []);

  useEffect(() => {
    // «Porta nella CER» da Casa: il profilo arriva nel frammento dell'indirizzo, che si toglie subito dopo la lettura
    void leggiArrivo(window.location.hash).then((letto) => {
      if (!letto) return;
      history.replaceState(null, "", window.location.pathname + window.location.search);
      if ("errore" in letto) {
        setMessaggio({ tono: "bad", testo: letto.errore });
        return;
      }
      setArrivo(new File([letto.testo], letto.nome, { type: "application/json" }));
      setIniziato(true);
      setPasso("membri");
      setMessaggio({
        tono: "ok",
        testo: "Il profilo della casa è arrivato da Casa. Qui sotto, in «Consumi ora per ora», scegli il contatore della casa e premi «Usa questi consumi».",
      });
    });
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0 });
    titolo.current?.focus({ preventScroll: true });
    // sul telefono la barra dei passi scorre di lato: il passo aperto deve restare in vista
    document.querySelector('.nav [aria-current="step"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [passo, iniziato]);

  // a ogni modifica: la bozza nel browser e, poco dopo, il controllo del motore (salvataggio e riepilogo)
  useEffect(() => {
    setBozzaSalvata(salvaBozza(tabelle));
    const n = ++controllo.current;
    const attesa = setTimeout(() => {
      motore.current!
        .chiama("progetto_da_tabelle", { tabelle })
        .then((e) => n === controllo.current && setEsito(e))
        .catch(() => undefined); // un motore che non parte si vede già nella barra laterale
    }, 300);
    return () => clearTimeout(attesa);
  }, [tabelle]);

  const aggiorna = (f: (t: Tabelle) => Tabelle) => setTabelle(f);

  async function carica(testo: string, origine: string) {
    setOccupato("carica");
    setMessaggio({ tono: "info", testo: stato.tipo === "pronto" ? `Lettura di ${origine}…` : `Lettura di ${origine}: il motore di calcolo si sta avviando…` });
    try {
      const caricato = await motore.current!.chiama("tabelle_da_progetto", { progetto: testo });
      if (!caricato.ok) {
        setMessaggio({ tono: "bad", testo: `${origine}: ${caricato.errore}` });
        return;
      }
      setEsito(null);
      setTabelle(caricato.tabelle);
      setPasso("luogo");
      setIniziato(true);
      setStatoTetto(tettoIniziale());
      setMessaggio({ tono: "ok", testo: `Caricato: ${caricato.tabelle.generale.nome || origine}.` });
    } catch (e) {
      setMessaggio({ tono: "bad", testo: e instanceof Error ? e.message : String(e) });
    } finally {
      setOccupato(null);
    }
  }

  async function esempio() {
    const risposta = await fetch("./esempi/torino.json").catch(() => null);
    if (!risposta?.ok) {
      setMessaggio({ tono: "bad", testo: "L'esempio di Torino non si è caricato: riprova." });
      return;
    }
    await carica(await risposta.text(), "l'esempio di Torino");
  }

  async function importa(file: File | undefined) {
    if (sceltaFile.current) sceltaFile.current.value = "";
    if (!file) return;
    if (file.size > MAX_BYTE_SALVATAGGIO) {
      setMessaggio({ tono: "bad", testo: `${file.name}: il file è troppo grande per un salvataggio (al massimo 12 MB).` });
      return;
    }
    await carica(await file.text(), file.name);
  }

  async function esporta() {
    if (nonValidi > 0) {
      setMessaggio({ tono: "bad", testo: AVVISO_CAMPI_NON_VALIDI });
      return;
    }
    setOccupato("esporta");
    try {
      const fresco = await motore.current!.chiama("progetto_da_tabelle", { tabelle });
      setEsito(fresco);
      if (!fresco.ok || !fresco.progetto) {
        setMessaggio({ tono: "bad", testo: "Il lavoro non si può ancora salvare:", dettagli: [...fresco.errori_luogo, ...fresco.errori] });
        return;
      }
      const url = URL.createObjectURL(new Blob([fresco.progetto], { type: "application/json" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: nomeFile(tabelle.generale.nome) });
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessaggio({ tono: "ok", testo: `Salvato in ${a.download}. Si riapre con Importa, qui o nell'app Streamlit.` });
    } catch (e) {
      setMessaggio({ tono: "bad", testo: e instanceof Error ? e.message : String(e) });
    } finally {
      setOccupato(null);
    }
  }

  function nuovo() {
    if ((tabelle.punti.length > 0 || tabelle.generale.nome) && !window.confirm("Iniziare un nuovo progetto? La bozza sarà sostituita: salva prima il progetto se ti serve.")) return;
    cancellaBozza();
    setEsito(null);
    setTabelle(bozzaVuota());
    setStatoTetto(tettoIniziale());
    setMessaggio(null);
    setPasso("luogo");
    setIniziato(true);
  }

  function tornaAllInizio() {
    if (!window.confirm("Tornare all'inizio? La bozza resta in questo browser. Salva il progetto per conservarne una copia.")) return;
    setIniziato(false);
    setMessaggio(null);
  }

  const indice = PASSI.findIndex((p) => p.id === passo);
  const corrente = PASSI[indice];
  const progetto = esito?.ok ? esito.progetto ?? null : null;
  const corpo =
    passo === "luogo" ? (
      <Luogo generale={tabelle.generale} cambia={(parte: Partial<Generale>) => aggiorna((t) => ({ ...t, generale: { ...t.generale, ...parte } }))}
        costanti={costanti} errori={esito?.errori_luogo ?? []} motore={motore.current!} />
    ) :
    passo === "membri" ? <MembriConsumi tabelle={tabelle} aggiorna={aggiorna} costanti={costanti} esito={esito} motore={motore.current!}
      arrivo={arrivo} arrivoUsato={() => setArrivo(null)} /> :
    passo === "impianti" ? (
      <Impianti tabelle={tabelle} aggiorna={aggiorna} costanti={costantiImpianti} esito={esito} motore={motore.current!}
        stato={statoTetto} cambia={setStatoTetto} />
    ) :
    passo === "economia" ? <Economia tabelle={tabelle} aggiorna={aggiorna} motore={motore.current!} /> :
    <Risultati motore={motore.current!} progetto={progetto} prezzi={tabelle.prezzi} impianti={tabelle.impianti.length}
      erroriImpianti={esito?.errori_impianti ?? []}
      salva={() => void esporta()} salvataggio={occupato !== null}
      vai={(p) => setPasso(p)} />;

  return (
    <div className="shell">
      <aside className="sidebar no-print" aria-label="Navigazione">
        <BarraFamiglia corrente="cer" />
        <div className="logo">
          <Logo />
          <div>
            <strong>Comunità energetica</strong>
            <small>simulatore CER · nel browser</small>
          </div>
        </div>
        {/* prima di iniziare i passi sono spenti: su telefono la barra scorre di lato e deve restare raggiungibile */}
        <nav className="nav" aria-label="Passi" tabIndex={iniziato ? undefined : 0}>
          {PASSI.map((p, i) => {
            return (
              <button key={p.id} type="button" disabled={!iniziato} aria-current={iniziato && passo === p.id ? "step" : undefined} onClick={() => setPasso(p.id)}>
                <Icon name={p.icona} />
                <span>{p.etichetta}</span>
                <span className="num muted small">{i + 1}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          {iniziato && <div className="sidebar-actions">
            <button type="button" onClick={() => void esporta()} disabled={occupato !== null}><Upload size={16} /> Salva il progetto</button>
            <button type="button" onClick={tornaAllInizio} disabled={occupato !== null}>Torna all'inizio</button>
          </div>}
          <div className="small muted">
            {bozzaSalvata
              ? "La bozza resta in questo browser."
              : "Questo browser non tiene la bozza: salva il progetto per non perderlo."}
          </div>
          <StatoDelMotore stato={stato} />
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div>
            <h1 ref={titolo} tabIndex={-1} className="step-title">{iniziato ? corrente.titolo : "L'energia del quartiere, in comune"}</h1>
          </div>
        </header>
        <input ref={sceltaFile} type="file" accept=".json,application/json" hidden aria-label="File di salvataggio da importare"
          onChange={(e) => void importa(e.target.files?.[0])} />

        <div aria-live="polite">
          {messaggio && (
            <div className={`notice ${messaggio.tono}`} role={messaggio.tono === "bad" ? "alert" : "status"}>
              {messaggio.tono === "bad" ? <TriangleAlert size={18} /> : messaggio.tono === "ok" ? <CheckCircle2 size={18} /> : <Loader2 size={18} />}
              <div>
                {messaggio.testo}
                {messaggio.dettagli && <Messaggi titolo="Dati da completare" messaggi={messaggio.dettagli} bloccanti />}
              </div>
              <button type="button" className="btn icon small ghost" aria-label="Chiudi il messaggio" onClick={() => setMessaggio(null)}><X size={16} /></button>
            </div>
          )}
        </div>

        {!iniziato ? <main className="panel entry">
          <h2><Icon name="condivisa" size={32} /> Valuta una comunità energetica</h2>
          <p><InfoTip text="Parti dai consumi e dai tetti della tua comunità." label="Il percorso della CER">In cinque passi scegli il luogo, raccogli i consumi, definisci gli impianti e il riparto, poi confronti i benefici e i loro intervalli. Puoi iniziare con dati tipici e completarli con bollette e preventivi.</InfoTip></p>
          <div className="toolbar">
            <button type="button" className="btn primary" onClick={nuovo} disabled={occupato !== null}><Icon name="rapida" /> Inizia un progetto</button>
            {(tabelle.punti.length > 0 || tabelle.generale.nome) && <button type="button" className="btn" onClick={() => setIniziato(true)} disabled={occupato !== null}>Riprendi la bozza</button>}
          </div>
          <div className="toolbar">
            <button type="button" className="btn" onClick={() => void esempio()} disabled={occupato !== null}><Icon name="casa" /> Esempio di Torino</button>
            <button type="button" className="btn" onClick={() => sceltaFile.current?.click()} disabled={occupato !== null}><Download size={16} /> Importa</button>
          </div>
          <p className="small muted"><InfoTip text="Torino: 12 famiglie, una panetteria e un tetto da 20 kWp." label="Esempio di Torino">Il condominio è simulato come comunità energetica, con il 50% del netto dei contributi destinato ai membri. È un punto di partenza modificabile.</InfoTip></p>
        </main> : passo === "risultati" ? <main>{corpo}</main> : <main className="panel">{corpo}</main>}

        {iniziato && <div className="toolbar no-print" style={{ justifyContent: "space-between" }}>
          <button type="button" className="btn" disabled={indice === 0} onClick={() => setPasso(PASSI[indice - 1].id)}>
            <ChevronLeft size={16} /> Indietro
          </button>
          <button type="button" className="btn primary" disabled={indice === PASSI.length - 1} onClick={() => setPasso(PASSI[indice + 1].id)}>
            {indice < PASSI.length - 1 ? PASSI[indice + 1].etichetta : "Fine"} <ChevronRight size={16} />
          </button>
        </div>}
        <footer className="foot">
          <InfoTip text="I dati dei contatori restano nel browser." label="Privacy e uso del sito">Il calcolo gira in questo browser: i dati dei contatori non vengono inviati a nessun server. La bozza locale non è un backup: salva il progetto per conservarlo. © 2026 Samuele Racca: puoi usare liberamente questo sito, anche per lavoro; il codice è open source, con licenza MIT.</InfoTip>{" "}
          <a href="./licenza.txt">Licenza e crediti</a> · <a href="./privacy.html">Privacy</a>.
          {" "}Dati di terzi: produzione PVGIS © Unione Europea; indirizzi ed edifici{" "}
          <a href={URL_COPYRIGHT_OSM} target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a> (ODbL);
          foto aerea Esri.
        </footer>
      </div>
    </div>
  );
}

function StatoDelMotore({ stato }: { stato: StatoMotore }) {
  if (stato.tipo === "errore") {
    return (
      <div className="stato-motore" role="alert">
        <TriangleAlert size={16} />
        <div>
          Il motore di calcolo non si è avviato: ricarica la pagina.
          <details><summary className="small">Dettagli tecnici</summary><span className="small">{stato.messaggio}</span></details>
        </div>
      </div>
    );
  }
  if (stato.tipo === "avvio") {
    return <div className="stato-motore" role="status"><Loader2 size={16} /> Motore: {stato.fase.toLowerCase()}…</div>;
  }
  const a = stato.avvio;
  const totale = a.python_s + a.pacchetti_s + a.cersim_s;
  return (
    <div className="stato-motore" role="status"
      title={`cersim ${a.motore} pronto in ${secondi(totale)} (Python ${secondi(a.python_s)}, pacchetti ${secondi(a.pacchetti_s)}, cersim ${secondi(a.cersim_s)}) · Pyodide ${a.pyodide} · ${megabyte(a.scaricati_mb)}`}>
      <Cpu size={16} /> Motore di calcolo pronto
    </div>
  );
}
