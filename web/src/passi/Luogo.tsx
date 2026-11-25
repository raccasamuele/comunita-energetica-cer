// Passo 1: nome, che cosa si simula, data di costituzione e posizione (indirizzo, regione, coordinate).

import { CreditiOsm } from "../ui/crediti-osm";
import { useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, Search } from "lucide-react";
import { Icon } from "../ui/icons";
import { Brief, InfoTip } from "../ui/info-tip";
import { Messaggi } from "../ui/issues";
import type { Motore } from "../motore/client";
import type { Costanti, Generale } from "../motore/contratto";
import { cercaIndirizzo, indirizzoRicerca, type LuogoTrovato } from "../motore/indirizzo";
import { Campo, CampoNumero, Scelta, scriviNumero } from "./campi";

const TIPI = [
  {
    valore: "gruppo",
    titolo: "Gruppo di autoconsumatori (condominio)",
    testo: "Stesso edificio, impianto sull'edificio. Serve un contratto tra i partecipanti.",
  },
  {
    valore: "CER",
    titolo: "Comunità energetica rinnovabile (CER)",
    testo: "Edifici anche diversi, sotto la stessa cabina primaria. Serve un soggetto giuridico con statuto; grandi imprese escluse.",
  },
] as const;

type Ricerca =
  | { stato: "ferma" }
  | { stato: "in corso" }
  | { stato: "scelta"; luoghi: LuogoTrovato[]; licenza: string }
  | { stato: "trovato"; testo: string; licenza: string; regioneMancante: boolean }
  | { stato: "errore"; testo: string };

const arrotonda = (x: number) => Math.round(x * 1e4) / 1e4;

export function Luogo(props: {
  generale: Generale;
  cambia: (parte: Partial<Generale>) => void; // si applica alla bozza più recente, anche dopo un'attesa
  costanti: Costanti | null;
  errori: string[];
  motore: Motore;
}) {
  const g = props.generale;
  const cambia = props.cambia;
  const [ricerca, setRicerca] = useState<Ricerca>({ stato: "ferma" });
  const disponibile = indirizzoRicerca() !== null;
  const [aMano, setAMano] = useState(!disponibile);

  async function cerca() {
    const testo = g.indirizzo.trim();
    if (testo.length < 3) {
      setRicerca({ stato: "errore", testo: "Scrivi l'indirizzo, con il comune: per esempio Via Roma 1, Torino." });
      return;
    }
    setRicerca({ stato: "in corso" });
    try {
      const { luoghi, licenza } = await cercaIndirizzo(testo);
      if (luoghi.length === 0) {
        setRicerca({ stato: "errore", testo: "Nessun luogo trovato. Aggiungi il comune, oppure correggi la posizione a mano." });
        setAMano(true);
      } else if (luoghi.length === 1) {
        await scegli(luoghi[0], licenza);
      } else {
        setRicerca({ stato: "scelta", luoghi, licenza });
      }
    } catch (e) {
      setRicerca({ stato: "errore", testo: `Ricerca non riuscita: ${e instanceof Error ? e.message : String(e)}. Inserisci coordinate e regione a mano.` });
      setAMano(true);
    }
  }

  async function scegli(l: LuogoTrovato, licenza: string) {
    cambia({ lat: arrotonda(l.lat), lon: arrotonda(l.lon) });
    setRicerca({ stato: "trovato", testo: l.descrizione, licenza, regioneMancante: false });
    // la regione arriva come la scrive OpenStreetMap: il motore la riconduce ai nomi che usa (cersim.geo); al primo
    // accesso risponde quando ha finito di avviarsi
    const regione = l.regione ? (await props.motore.chiama("regione", { nome: l.regione })).regione : null;
    if (regione) {
      cambia({ regione });
    } else {
      setRicerca({ stato: "trovato", testo: l.descrizione, licenza, regioneMancante: true });
      setAMano(true);
    }
  }

  const posizione =
    g.lat != null && g.lon != null
      ? `${g.regione}, coordinate ${scriviNumero(g.lat, 4, false)} e ${scriviNumero(g.lon, 4, false)}`
      : null;

  return (
    <>
      <p className="sintesi"><InfoTip text="Scegli la configurazione e il luogo da cui partire." label="Luogo e configurazione">La posizione serve a stimare la produzione solare; la regione determina la zona di mercato. La data di costituzione sarà confrontata con l'entrata in esercizio degli impianti.</InfoTip></p>
      <section className="section" aria-labelledby="t-configurazione">
        <h2 id="t-configurazione"><span className="section-icon"><Icon name="comunita" /></span>La configurazione</h2>
        <div className="grid">
          <Campo id="nome" etichetta="Nome della configurazione">
            <input id="nome" type="text" value={g.nome} maxLength={120} placeholder="Condominio Via Roma 1"
              onChange={(e) => cambia({ nome: e.target.value })} />
          </Campo>
          <Campo id="costituzione" etichetta="Data di costituzione, anche prevista"
            suggerimento="Gli impianti devono entrare in esercizio dopo la costituzione, salvo deroghe.">
            <input id="costituzione" type="date" value={g.data_costituzione ?? ""} aria-describedby="costituzione-aiuto"
              onChange={(e) => cambia({ data_costituzione: e.target.value || null })} />
          </Campo>
        </div>
        <fieldset className="scelte">
          <legend>Che cosa vuoi simulare</legend>
          {TIPI.map((t) => (
            <div key={t.valore} className="scelta tipo-configurazione">
              <label>
                <input type="radio" name="tipo" value={t.valore} checked={g.tipo === t.valore}
                  onChange={() => cambia({ tipo: t.valore })} />
                <strong>{t.titolo}</strong>
              </label>
              <p className="muted small"><Brief label={t.titolo}>{t.testo}</Brief></p>
            </div>
          ))}
        </fieldset>
      </section>

      <section className="section" aria-labelledby="t-dove">
        <h2 id="t-dove"><span className="section-icon"><Icon name="localita" /></span>Dove si trova</h2>
        <form className="cerca" onSubmit={(e) => { e.preventDefault(); void cerca(); }}>
          <Campo id="indirizzo" etichetta="Indirizzo"
            suggerimento={disponibile
              ? "Solo premendo Cerca l'indirizzo va a OpenStreetMap, attraverso il nostro intermediario."
              : "La ricerca dell'indirizzo non è attiva in questa versione del sito: inserisci coordinate e regione a mano."}>
            <input id="indirizzo" type="text" value={g.indirizzo} maxLength={300} placeholder="Via Roma 1, Torino"
              aria-describedby="indirizzo-aiuto" autoComplete="street-address"
              onChange={(e) => cambia({ indirizzo: e.target.value })} />
          </Campo>
          <button type="submit" className="btn" disabled={!disponibile || ricerca.stato === "in corso"}>
            {ricerca.stato === "in corso" ? <Loader2 size={16} /> : <Search size={16} />} Cerca
          </button>
        </form>

        <div aria-live="polite">
          {ricerca.stato === "in corso" && <p className="muted" role="status">Ricerca in corso…</p>}
          {ricerca.stato === "errore" && (
            <div className="notice bad" role="alert"><AlertTriangle size={18} /><div>{ricerca.testo}</div></div>
          )}
          {ricerca.stato === "trovato" && (
            <div className="notice ok">
              <CheckCircle2 size={18} />
              <div>
                Trovato: {ricerca.testo}.
                {ricerca.regioneMancante && " La regione non è stata riconosciuta: sceglila qui sotto."}
                <div><CreditiOsm cosa="Indirizzi:" /></div>
              </div>
            </div>
          )}
          {ricerca.stato === "scelta" && (
            <>
              <p id="t-luoghi">Più luoghi corrispondono: scegli quello giusto.</p>
              <ul className="pick-list" aria-labelledby="t-luoghi">
                {ricerca.luoghi.map((l) => (
                  <li key={`${l.lat},${l.lon},${l.descrizione}`}>
                    <button type="button" className="pick" onClick={() => void scegli(l, ricerca.licenza)}>
                      <strong>{l.comune ?? l.descrizione.split(",")[0]}</strong>
                      <span className="small muted">{l.descrizione}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <p><CreditiOsm cosa="Indirizzi:" /></p>
            </>
          )}
        </div>

        {posizione && <p className="posizione">Posizione per la stima del sole: <strong>{posizione}</strong>.</p>}

        <details className="advanced" open={aMano} onToggle={(e) => setAMano((e.target as HTMLDetailsElement).open)}>
          <summary>Correggi la posizione a mano</summary>
          <div className="grid">
            <Campo id="lat" etichetta="Latitudine" suggerimento="Tra 35 e 48, per esempio 45,0703">
              <CampoNumero id="lat" valore={g.lat} decimali={4} gruppi={false} min={35} max={48} descrittoDa="lat-aiuto"
                onChange={(lat) => cambia({ lat })} />
            </Campo>
            <Campo id="lon" etichetta="Longitudine" suggerimento="Tra 6 e 19, per esempio 7,6869">
              <CampoNumero id="lon" valore={g.lon} decimali={4} gruppi={false} min={6} max={19} descrittoDa="lon-aiuto"
                onChange={(lon) => cambia({ lon })} />
            </Campo>
            <Campo id="regione" etichetta="Regione"
              suggerimento={props.costanti ? "Decide la zona di mercato e la correzione della tariffa premio." : "Elenco in arrivo dal motore di calcolo…"}>
              <Scelta id="regione" valore={g.regione || null} opzioni={props.costanti?.regioni ?? []}
                onChange={(regione) => cambia({ regione: regione ?? "" })} />
            </Campo>
          </div>
        </details>
      </section>

      <Messaggi titolo="Da completare nel luogo" messaggi={props.errori} bloccanti />
    </>
  );
}
