// Contratto dei messaggi tra l'interfaccia e il motore cersim nel Web Worker (docs/web_architettura.md).
// Il progetto viaggia come testo: è il file di salvataggio del lavoro (cersim.ui_model.esporta_json).

/** Una serie PVGIS che serve all'analisi; `parametri` è la query di seriescalc da inoltrare così com'è. */
export interface RichiestaPvgis {
  chiave: string;
  parametri: Record<string, string | number>;
}

export interface Banda {
  minimo: number | null;
  mediana: number | null;
  massimo: number | null;
}

/** Uscita di cersim.web.analizza_web (versione del contratto 1). */
export interface Risultato {
  contratto: number;
  ok: boolean;
  errore?: string;
  motore?: string;
  supportata?: boolean;
  non_supportati?: string[];
  da_verificare?: string[];
  qualita?: "A" | "B" | "C";
  economia_disabilitata?: string | null;
  fonti_pv?: string[];
  bande?: Record<string, Banda>;
  avvisi?: string[];
  base?: {
    van_investitore: number | null;
    van_consolidato: number | null;
    tir_investitore: number | null;
    payback_investitore: number | null;
    contributi_primo_anno_intero: Record<string, number | null>;
  };
}

/** Tempi del primo caricamento, misurati nel Worker. */
export interface Avvio {
  motore: string;
  pyodide: string;
  python_s: number;
  pacchetti_s: number;
  cersim_s: number;
  scaricati_mb: number;
}

// --- passi 1 e 2: la bozza del progetto, nelle tabelle di cersim.ui_model (cersim/web.py, FUNZIONI) ---------------

/** Elenchi per i campi a scelta, dal motore (cersim.web.costanti). */
export interface Costanti {
  contratto: number;
  motore: string;
  regioni: string[];
  tipi_soggetto: string[];
  tipologie: string[];
  tensioni: string[];
  kwh_famiglia_tipo: number;
  max_contatori: number;
}

export interface Generale {
  nome: string;
  tipo: "gruppo" | "CER";
  indirizzo: string;
  lat: number | null;
  lon: number | null;
  regione: string;
  data_costituzione: string | null; // AAAA-MM-GG
}

/** Una riga della tabella dei contatori (cersim.web.CAMPI_PUNTO). */
export interface RigaPunto {
  punto: string | null;
  membro: string | null;
  tipo_soggetto: string | null;
  tipologia: string | null;
  kwh_annui: number | null;
  f1_kwh: number | null;
  f23_kwh: number | null;
  area: string | null;
  tensione: string | null;
}

/** Curva oraria di un contatore: la curva per il motore e la descrizione da mostrare. */
export interface ConsumiOrari {
  curva: Record<string, unknown>;
  descrizione: string;
  calcolata: boolean;
  /** Dal profilo energetico della casa: la batteria simulata sul contatore e lo scenario caricato. */
  batteria?: { capacita_kwh: number; potenza_kw: number; rendimento_pct: number; riserva_pct: number };
  profilo?: { scenario: string; nome: string; conta_fv: boolean; [k: string]: unknown };
}

/** Uno scenario del profilo energetico, da scegliere (cersim.profilo.sintesi). */
export interface ScenarioProfilo {
  id: string;
  nome: string;
  attuale: boolean;
  consumi_kwh: number;
  prelievi_kwh: number;
  fv_kwp: number | null;
  fv_esistente: boolean | null;
  batteria_kwh: number | null;
  usi: Record<string, number>;
}

/** La bozza: tutto ciò che serve per rifare il salvataggio. Gli impianti hanno le colonne di cersim.ui_model e si
 * modificano al passo 3; `base` è il lavoro ricaricato, da cui si riprendono i campi che le tabelle non mostrano. */
export interface Tabelle {
  generale: Generale;
  punti: RigaPunto[];
  impianti: RigaImpianto[];
  curve: Record<string, ConsumiOrari>;
  parametri: Record<string, unknown>;
  base?: Record<string, unknown> | null;
  prezzi?: Record<string, SeriePrezzi>; // prezzi orari del passo 4, solo in questo browser
}

export interface Riepilogo {
  membri: number;
  contatori: number;
  kwh_annui: number;
  famiglie_tipo: number;
  qualita_consumi: Record<"A" | "B" | "C", number>;
}

/** cersim.web.progetto_da_tabelle: il salvataggio, oppure gli errori del passo 1, dei contatori e degli impianti. */
export interface EsitoProgetto {
  ok: boolean;
  errori_luogo: string[];
  errori: string[];
  errori_impianti?: string[];
  progetto?: string;
  riepilogo?: Riepilogo;
}

// --- passo 3: tetto, proposta delle tre taglie e tabella degli impianti (cersim/web.py) ---------------------------

/** Una riga della tabella degli impianti, con le colonne di cersim.ui_model (COLONNE_IMPIANTI). */
export type RigaImpianto = Record<string, string | number | null>;

/** Elenchi e valori del passo 3 (cersim.web.costanti_impianti). */
export interface CostantiImpianti {
  forme: string[];
  inclinazione: Record<string, number>;
  m2_per_kwp: Record<string, number>;
  livelli_ombre: { etichetta: string; pct: number }[];
  sola_immissione: string;
  investitore_esterno: string;
  colonne: string[];
  foto_aerea_url: string;
  foto_aerea_attribuzione: string;
  attribuzione_osm: string;
  quota_provvisoria: number;
  termine_tip: string;
}

/** Il tetto disegnato (cersim.web.tetto). `ombre_pct` e `svg` solo con gli edifici vicini. */
export type EsitoTetto =
  | {
      ok: true;
      lat: number;
      lon: number;
      area_terra_m2: number;
      superficie_utile_m2: number;
      azimut: number;
      est_ovest: boolean;
      ombre_pct: number | null;
      ombre_pct_due_falde: number | null;
      vicini: number;
      note: string[];
      svg: string | null;
    }
  | { ok: false; errore: string };

/** Che cosa si è scelto per il tetto e chi paga (cersim.proposta.SceltaTetto). */
export interface SceltaTetto {
  kwp_max: number;
  inclinazione: number;
  azimut: number;
  azimut_2: number | null;
  ombre_pct: number;
  punto: string;
  investitore: string;
  entrata: string; // AAAA-MM-GG
}

export interface OpzioneProposta {
  nome: string;
  kwp: number;
  costo: number | null;
  van_minimo: number | null;
  van_mediana: number | null;
  van_massimo: number | null;
  euro_anno_membri: number | null;
  commento: string;
  conviene_a_entrambi: boolean;
  impianti: RigaImpianto[]; // la tabella degli impianti con questa taglia
}

/** cersim.web.proposta: tre taglie commentate e la curva delle taglie provate. */
export type EsitoProposta =
  | {
      ok: true;
      qualita: "A" | "B" | "C";
      quota_membri: number;
      quota_provvisoria: boolean;
      investitore: string;
      nessuna_conviene: boolean;
      note: string[];
      opzioni: OpzioneProposta[];
      curva: { kwp: number; minimo: number | null; mediana: number | null; massimo: number | null }[];
    }
  | { ok: false; errore: string };

export type Caricato = { ok: true; tabelle: Tabelle } | { ok: false; errore: string };
export type ConsumiLetti =
  | ({ ok: true; scegli?: undefined; avvisi: string[]; impianto?: (RigaImpianto & { esistente: boolean }) | null } & ConsumiOrari)
  | { ok: true; scegli: true; scenari: ScenarioProfilo[]; comune: string | null; descrizione: string | null; avvisi: string[] }
  | { ok: false; errore: string };

// --- passi 4 e 5: economia e risultati completi (cersim/web.py) ---------------------------------------------------

/** Valori predefiniti del passo 4 (cersim.web.costanti_economia). */
export interface CostantiEconomia {
  prezzi_medi: Record<"basso" | "base" | "alto", number>;
  costo_evitabile_eur_kwh: number;
  tasso_sconto: number;
  om_assicurazione_quota_anno: number;
  gestione_eur_anno: number;
  costituzione_eur: number;
}

/** Prezzi orari di un anno caricati dall'utente: restano nella bozza, non nel salvataggio (uso personale). */
export interface SeriePrezzi {
  anno: number;
  zona: string;
  fonte: string;
  qualita: string;
  media: number;
  valori: number[];
}

export interface TabellaDati {
  colonne: string[];
  righe: (number | string | null)[][];
}

/** cersim.web.risultati: tutto ciò che il passo 5 mostra, come nell'app Streamlit. */
export interface RisultatiCompleti {
  contratto: number;
  ok: boolean;
  errore?: string;
  motore?: string;
  non_supportati?: string[];
  da_verificare?: string[];
  economia_disabilitata?: string | null;
  frase?: [string, boolean][];
  qualita?: { lettera: "A" | "B" | "C"; testo: string; tono: "ok" | "forse"; spiegazione: string };
  nota_intervalli?: string;
  fonti_prezzi?: string[];
  fonti_pv?: string[];
  precisione?: { frase: string; voci: { cosa: string; perche: string; passo: number | null }[] };
  requisiti?: { nome: string; stato: string; tono: "ok" | "no" | "forse"; motivo: string }[];
  giorno_tipo?: { anno: number; mesi: TabellaDati[] };
  mensile?: TabellaDati;
  avvertenze?: string[];
  impianti?: { id: string; nome: string }[];
  bande?: Record<string, Banda | null>;
  cifre?: { voce: string; valore: number | null; minimo: number | null; massimo: number | null; unita: string; significato: string }[];
  confronto?: { frase: string; righe: { voce: string; banda: Banda | null; descrizione: string }[] };
  cassa?: TabellaDati;
  sensibilita?: { base: number | null; anno_meteo: number; voci: { parametro: string; variazione: string; basso: number | null; alto: number | null }[] };
  chi_riceve?: TabellaDati & { anno: number };
  per_membro?: { membro: string; netto: number | null }[];
}

export type Dimensionamento =
  | { ok: true; dicitura: string; curva: { kwp: number; configurazione: number | null; investitore: number | null }[] }
  | { ok: false; errore: string };

/** Le funzioni che il Worker può chiamare per nome, con i loro argomenti e risultati. */
export interface Funzioni {
  costanti: { argomenti: Record<string, never>; risultato: Costanti };
  famiglie: { argomenti: { n: number; inizio: number }; risultato: RigaPunto[] };
  regione: { argomenti: { nome: string }; risultato: { regione: string | null } };
  progetto_da_tabelle: { argomenti: { tabelle: Tabelle }; risultato: EsitoProgetto };
  tabelle_da_progetto: { argomenti: { progetto: string }; risultato: Caricato };
  leggi_consumi: {
    argomenti: {
      file: { nome: string; base64: string }[];
      scenario?: string;
      conta_fv?: boolean;
      data_costituzione?: string | null;
      contatore?: string;
    };
    risultato: ConsumiLetti;
  };
  scarica_profilo: {
    argomenti: { voce: ConsumiOrari; ha_impianto: boolean };
    risultato: { ok: true; profilo: unknown } | { ok: false; errore: string };
  };
  leggi_schede: {
    argomenti: { file: { nome: string; base64: string }[]; tabelle: Tabelle };
    risultato: { lette: number; punti: RigaPunto[]; curve: Record<string, ConsumiOrari>; messaggi: string[] };
  };
  costanti_impianti: { argomenti: Record<string, never>; risultato: CostantiImpianti };
  entrata_prevista: { argomenti: { data_costituzione: string | null }; risultato: { entrata: string } };
  tetto: {
    argomenti: { angoli: [number, number][]; forma: string; piani: number | null; inclinazione: number; edifici: unknown[] | null };
    risultato: EsitoTetto;
  };
  richieste_proposta: {
    argomenti: { tabelle: Tabelle; scelta: SceltaTetto };
    risultato: { ok: true; richieste: RichiestaPvgis[] } | { ok: false; errore: string };
  };
  proposta: { argomenti: { tabelle: Tabelle; scelta: SceltaTetto; serie: Record<string, unknown> }; risultato: EsitoProposta };
  costanti_economia: { argomenti: { tipo: string }; risultato: CostantiEconomia };
  leggi_prezzi: {
    argomenti: { file: { nome: string; base64: string }[]; regione: string };
    risultato: { ok: boolean; errori: string[]; prezzi: Record<string, SeriePrezzi> };
  };
  risultati: {
    argomenti: { progetto: string; serie: Record<string, unknown>; prezzi: Record<string, SeriePrezzi> | null };
    risultato: RisultatiCompleti;
  };
  dimensionamento: { argomenti: { impianto: string }; risultato: Dimensionamento };
  report: {
    argomenti: { formato: "pdf" | "xlsx" };
    risultato: FileDalMotore;
  };
  scheda_pdf: { argomenti: { configurazione: string | null; link: string }; risultato: FileDalMotore };
}

/** Un file preparato dal motore (report, scheda da stampare), in base64. */
export type FileDalMotore = { ok: true; nome: string; base64: string } | { ok: false; errore: string };

export type AlMotore =
  | { tipo: "avvia"; sorgenti: string }
  | { tipo: "richieste"; id: number; progetto: string }
  | { tipo: "analizza"; id: number; progetto: string; serie: Record<string, unknown> }
  | { tipo: "chiama"; id: number; funzione: keyof Funzioni; argomenti: string }
  | { tipo: "prepara_report"; id: number };

export type DaMotore =
  | { tipo: "stato"; fase: string }
  | { tipo: "pronto"; avvio: Avvio }
  | { tipo: "richieste"; id: number; richieste: RichiestaPvgis[] }
  | { tipo: "risultato"; id: number; risultato: Risultato; secondi: number }
  | { tipo: "valore"; id: number; valore: unknown }
  | { tipo: "report_pronto"; id: number }
  | { tipo: "errore"; id?: number; messaggio: string };
