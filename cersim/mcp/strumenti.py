"""Gli strumenti di cersim-mcp: le operazioni del sito (`cersim.web.FUNZIONI`) per un agente AI.

Come in Casa (mcp/strumenti.ts):
- ogni risposta ha un testo in italiano da citare e i dati strutturati, con la qualità dei dati, i limiti e
  l'avvertenza;
- i file si leggono dal percorso sul computer (meglio: il contenuto non passa dall'agente) o dal contenuto;
- il nome della configurazione, l'indirizzo e i codici POD non escono dal computer (`_privati`);
- i progetti, i consumi, i prezzi e le analisi restano in memoria finché il server è acceso, con un identificativo.

Diverso da Casa: le serie PVGIS le scarica il server (`cersim.mcp.pvgis`), e `scrivi_report` scrive un file, solo
dove l'agente indica e senza sovrascrivere.
"""

import base64
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cersim import __version__, web
from cersim.eligibility import check
from cersim.mcp.protocollo import Progress, ToolDef, ToolOutput
from cersim.mcp.pvgis import Scaricamento, scarica_serie
from cersim.mcp.scheda import SCHEDA_META
from cersim.ui_model import COLONNE_IMPIANTI, MAX_JSON_BYTE, importa_json

AVVERTENZA = ("Stima del modello con i dati indicati: non è un preventivo, né una consulenza legale o fiscale. "
              "I requisiti di legge vanno verificati con il GSE e con un professionista.")
OMESSO = "[omesso]"
MAX_FILE_CONSUMI_BYTE = 20_000_000
MAX_FILE_PREZZI_BYTE = 5_000_000
REPORT = ("Riporta insieme ai numeri la qualità dei dati, gli intervalli (minimo e massimo), le avvertenze e "
          "l'avvertenza finale, senza togliere le incertezze.")

LETTURA = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
CON_PVGIS = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
SCRITTURA = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

# Le colonne degli impianti di `ui_model` con chiavi brevi, più comode per un agente.
CAMPI_IMPIANTO = dict(zip(
    ["impianto", "punto", "kwp_moduli", "kw_inverter", "kwp_max", "inclinazione", "orientamento", "seconda_falda",
     "ombre_pct", "entrata_esercizio", "investitore", "costo_preventivo_eur", "contributo_eur", "fattore_f",
     "estremi_atto", "data_incasso_contributo"], COLONNE_IMPIANTI, strict=True))


@dataclass
class Sessione:
    """Quello che resta in memoria finché il server è acceso. Niente va su disco, salvo la cache PVGIS."""

    progetti: dict[str, str] = field(default_factory=dict)  # id → file di salvataggio (testo JSON)
    consumi: dict[str, dict] = field(default_factory=dict)  # id → voce delle curve della bozza (web._curva)
    prezzi: dict[str, dict] = field(default_factory=dict)  # id → prezzi della bozza (web.leggi_prezzi)
    analisi: dict[str, dict] = field(default_factory=dict)  # id → copia di web._ultima
    contatori: dict[str, int] = field(default_factory=dict)

    def nuovo(self, tipo: str) -> str:
        n = self.contatori.get(tipo, 0) + 1
        self.contatori[tipo] = n
        return f"{tipo}-{n}"


@dataclass
class Opzioni:
    cache_dir: Path | None = None
    rete: bool = True


# --- parti comuni -----------------------------------------------------------------------------------------


def _errore(testo: str, **altro) -> ToolOutput:
    return ToolOutput(testo, {"ok": False, "errore": testo, **altro}, True)


def _chiusura(qualita: str | None = None) -> str:
    q = f"Qualità dei dati: {qualita}. " if qualita else ""
    return f"{q}{AVVERTENZA} Motore cersim {__version__}."


def _privati(testo_progetto: str) -> list[str]:
    """Testi del progetto che non escono: nome della configurazione, indirizzo, codici POD."""
    try:
        cfg = json.loads(testo_progetto).get("configurazione") or {}
    except (ValueError, AttributeError):
        return []
    fuori = {cfg.get("nome"), cfg.get("indirizzo")}
    fuori |= {cp.get("codice_pod") for cp in cfg.get("connection_points") or [] if isinstance(cp, dict)}
    return sorted({s.strip() for s in fuori if isinstance(s, str) and len(s.strip()) >= 3}, key=len, reverse=True)


def _redigi(valore, segreti: list[str]):
    if not segreti:
        return valore
    if isinstance(valore, str):
        for s in segreti:
            valore = valore.replace(s, OMESSO)
        return valore
    if isinstance(valore, list):
        return [_redigi(v, segreti) for v in valore]
    if isinstance(valore, dict):
        return {k: _redigi(v, segreti) for k, v in valore.items()}
    return valore


def _redigi_output(out: ToolOutput, segreti: list[str]) -> ToolOutput:
    return ToolOutput(_redigi(out.text, segreti), _redigi(out.structured, segreti), out.is_error)


def _rete_o_dispositivo(s: str) -> bool:
    # \\server\…, //server/…, \\?\…, \\.\…: si leggono solo file sul computer
    return bool(re.match(r"^[\\/]{2}", s))


def leggi_file(percorso, estensioni: tuple[str, ...], max_byte: int) -> bytes:
    """Un file sul computer, in sola lettura. Solleva ValueError con un messaggio che non ripete il percorso."""
    if not isinstance(percorso, str) or not percorso.strip():
        raise ValueError("Il percorso deve essere il percorso di un file.")
    if _rete_o_dispositivo(percorso.strip()):
        raise ValueError("Percorso non ammesso: indica un file su questo computer.")
    file = Path(percorso.strip()).expanduser().resolve()
    if _rete_o_dispositivo(str(file)):
        raise ValueError("Percorso non ammesso: indica un file su questo computer.")
    if file.suffix.lower() not in estensioni:
        raise ValueError(f"Il file deve essere {' o '.join(estensioni)}.")
    try:
        if not file.exists():
            raise ValueError("File non trovato.")
        if not file.is_file():
            raise ValueError("Il percorso non è un file.")
        if file.stat().st_size > max_byte:
            raise ValueError("File troppo grande.")
        return file.read_bytes()
    except OSError:
        raise ValueError("File non trovato o non leggibile.") from None


PROGETTO_PROP = {
    "progetto_id": {"type": "string", "description": "Identificativo di un progetto creato o aperto in questa "
                                                    "sessione (crea_progetto, controlla_progetto)."},
    "percorso": {"type": "string", "description": "In alternativa: percorso di un file del progetto (.json, "
                                                 "«Salva il lavoro» del sito o dell'app) su questo computer. Da "
                                                 "preferire al contenuto: il file non passa dall'agente."},
    "contenuto": {"type": "string", "description": "In alternativa: il testo del file del progetto."},
}


def _testo_progetto(args: dict, s: Sessione) -> str:
    """Il file del progetto, da uno dei tre modi. Solleva ValueError."""
    scelti = [k for k in ("progetto_id", "percorso", "contenuto") if args.get(k) is not None]
    if len(scelti) != 1:
        raise ValueError("Indica il progetto con uno solo fra «progetto_id», «percorso» e «contenuto».")
    if scelti[0] == "progetto_id":
        testo = s.progetti.get(str(args["progetto_id"]))
        if testo is None:
            raise ValueError("Progetto non trovato: i progetti restano solo finché il server è acceso.")
        return testo
    if scelti[0] == "contenuto":
        if not isinstance(args["contenuto"], str):
            raise ValueError("«contenuto» deve essere il testo del file.")
        if len(args["contenuto"].encode()) > MAX_JSON_BYTE:
            raise ValueError("File troppo grande.")
        return args["contenuto"]
    return leggi_file(args["percorso"], (".json",), MAX_JSON_BYTE).decode("utf-8-sig", errors="replace")


def _apri(args: dict, s: Sessione) -> tuple[str, str]:
    """Il progetto controllato e il suo identificativo nella sessione (nuovo se arriva da file o contenuto)."""
    testo = _testo_progetto(args, s)
    importa_json(testo)  # ValueError con un messaggio leggibile
    if args.get("progetto_id") is not None:
        return testo, str(args["progetto_id"])
    pid = s.nuovo("progetto")
    s.progetti[pid] = testo
    return testo, pid


def _base64_file(percorsi, estensioni, max_byte) -> list[dict]:
    if not isinstance(percorsi, list) or not percorsi or not all(isinstance(p, str) for p in percorsi):
        raise ValueError("«percorsi» deve essere un elenco di file.")
    return [{"nome": Path(p.strip()).name, "base64": base64.b64encode(leggi_file(p, estensioni, max_byte)).decode()}
            for p in percorsi]


def _scarica(richieste: list[dict], opz: Opzioni, progress: Progress | None) -> Scaricamento:
    return scarica_serie(richieste, cache_dir=opz.cache_dir, rete=opz.rete, progress=progress)


def _tabelle(testo: str) -> dict:
    t = web.tabelle_da_progetto(testo)
    if not t["ok"]:
        raise ValueError(t["errore"])
    return t["tabelle"]


def _da_tabelle(s: Sessione, tabelle: dict) -> tuple[dict, str | None]:
    """Nuovo progetto dalle tabelle della bozza: l'esito di `web.progetto_da_tabelle` e l'identificativo."""
    esito = web.progetto_da_tabelle(tabelle)
    if not esito["ok"]:
        return esito, None
    pid = s.nuovo("progetto")
    s.progetti[pid] = esito["progetto"]
    return esito, pid


def _riepilogo_testo(r: dict) -> str:
    q = r["qualita_consumi"]
    return (f"{r['membri']} membri, {r['contatori']} contatori, {r['kwh_annui']:,} kWh all'anno".replace(",", ".")
            + f" ({r['famiglie_tipo']} con il consumo della famiglia tipo). Qualità dei consumi: "
              f"{q['A']} A, {q['B']} B, {q['C']} C.")


# --- gli strumenti ----------------------------------------------------------------------------------------


def valori_predefiniti(args: dict) -> ToolOutput:
    tipo = args.get("tipo") if args.get("tipo") in ("gruppo", "CER") else "gruppo"
    c, imp, eco = web.costanti(), web.costanti_impianti(), web.costanti_economia(tipo)
    strutturato = {
        "motore": __version__, "regioni": c["regioni"], "tipi_soggetto": c["tipi_soggetto"],
        "tipologie_consumo": c["tipologie"], "tensioni": c["tensioni"], "kwh_famiglia_tipo": c["kwh_famiglia_tipo"],
        "max_contatori": c["max_contatori"],
        "impianti": {"campi": list(CAMPI_IMPIANTO), "inclinazione_tipica": imp["inclinazione"],
                     "m2_per_kwp": imp["m2_per_kwp"], "livelli_ombre": imp["livelli_ombre"],
                     "punto_sola_immissione": imp["sola_immissione"], "investitore_esterno": imp["investitore_esterno"],
                     "termine_tip": imp["termine_tip"]},
        "economia": {"tipo": tipo, **eco,
                     "parametri": list(web.PARAMETRI),
                     "nota": "quota_membri (da 0 a 1) è obbligatoria: senza, lo scenario non si calcola."},
    }
    testo = (f"Valori per un {('gruppo di autoconsumatori' if tipo == 'gruppo' else 'comunità energetica')}: "
             f"famiglia tipo {c['kwh_famiglia_tipo']} kWh/anno, fino a {c['max_contatori']} contatori. "
             f"Tipi di soggetto: {', '.join(c['tipi_soggetto'])}. Tipologie di consumo: {', '.join(c['tipologie'])}. "
             f"Costo evitabile in bolletta {eco['costo_evitabile_eur_kwh']} €/kWh, tasso di sconto reale "
             f"{eco['tasso_sconto']}, gestione {eco['gestione_eur_anno']} €/anno, costituzione "
             f"{eco['costituzione_eur']} €. Termine per l'entrata in esercizio con la tariffa premio: "
             f"{imp['termine_tip']}.")
    return ToolOutput(testo, strutturato)


def _controlla(testo: str, pid: str, opz: Opzioni) -> ToolOutput:
    config, parametri = importa_json(testo)
    rep = check(config)
    riepilogo = web._riepilogo(config)
    richieste = web.richieste_pvgis(testo)
    manca_quota = parametri.get("quota_membri") is None
    impianti = [{"id": p.id, "nome": p.nome, "punto": p.connection_point, "kwp": p.potenza_moduli_kwp,
                 "investitore": p.investitore} for p in config.plants]
    nomi = {m.id: m.nome for m in config.members}
    contatori = [{"punto": cp.id, "membro": nomi.get(cp.titolare, cp.titolare), "ruolo": cp.ruolo.value}
                 for cp in config.connection_points]
    righe = [f"Progetto aperto ({'comunità energetica' if config.tipo.value == 'CER' else 'gruppo di autoconsumatori'}"
             f", regione {config.regione}): {_riepilogo_testo(riepilogo)}",
             "Contatori: " + "; ".join(f"{c['punto']} ({c['membro']})" for c in contatori[:30])
             + (f" e altri {len(contatori) - 30}" if len(contatori) > 30 else "") + ".",
             f"Impianti: {len(impianti)}" + (": " + "; ".join(f"{i['id']} {i['kwp']:g} kWp sul contatore {i['punto']}"
                                                              for i in impianti) if impianti else
                                             ". Per proporne uno usa proponi_impianto.")]
    if rep.non_supportati:
        righe.append("Non supportato dal simulatore:\n- " + "\n- ".join(rep.non_supportati))
    if manca_quota:
        righe.append("Manca la quota dei contributi ai membri (quota_membri): senza, analizza_scenario non calcola.")
    righe.append(f"Per l'analisi servono {len(richieste)} serie PVGIS: il server le scarica da sé.")
    righe.append(_chiusura())
    return ToolOutput("\n\n".join(righe), {
        "ok": True, "progetto_id": pid, "tipo": config.tipo.value, "regione": config.regione, "riepilogo": riepilogo,
        "contatori": contatori, "impianti": impianti, "parametri": parametri, "manca_quota_membri": manca_quota,
        "supportata": rep.supportata, "non_supportati": rep.non_supportati, "da_verificare": rep.da_verificare,
        "serie_pvgis": len(richieste), "avvertenza": AVVERTENZA})


def controlla_progetto(args: dict, s: Sessione, opz: Opzioni) -> ToolOutput:
    try:
        testo, pid = _apri(args, s)
    except ValueError as e:
        return _errore(f"Il progetto non si apre: {e}")
    return _redigi_output(_controlla(testo, pid, opz), _privati(testo))


def _righe_impianti(impianti) -> list[dict]:
    if not isinstance(impianti, list):
        raise ValueError("«impianti» deve essere un elenco.")
    righe = []
    for r in impianti:
        if not isinstance(r, dict):
            raise ValueError("Ogni impianto deve essere un oggetto.")
        sconosciuti = set(r) - set(CAMPI_IMPIANTO)
        if sconosciuti:
            raise ValueError(f"Campi degli impianti sconosciuti: {', '.join(sorted(sconosciuti))}.")
        righe.append({colonna: r.get(campo) for campo, colonna in CAMPI_IMPIANTO.items()})
    return righe


def crea_progetto(args: dict, s: Sessione, opz: Opzioni) -> ToolOutput:
    generale = args.get("generale")
    if not isinstance(generale, dict):
        return _errore("Indica i dati generali («generale»): tipo, lat, lon, regione.")
    punti = list(args.get("punti") or [])
    famiglie = args.get("famiglie_tipo")
    try:
        if famiglie:
            n = int(famiglie.get("numero", 0)) if isinstance(famiglie, dict) else int(famiglie)
            kwh = famiglie.get("kwh_annui") if isinstance(famiglie, dict) else None
            punti += web.famiglie(n, inizio=1 + sum(1 for p in punti if str(p.get("punto", "")).startswith("Famiglia")),
                                  kwh=kwh)
        curve = {}
        for punto, cid in (args.get("consumi") or {}).items():
            if cid not in s.consumi:
                raise ValueError(f"Consumi «{cid}» non trovati: leggili prima con leggi_consumi.")
            curve[str(punto)] = s.consumi[cid]
        impianti = _righe_impianti(args.get("impianti") or [])
        parametri = args.get("parametri") or {}
        if not isinstance(parametri, dict):
            raise ValueError("«parametri» deve essere un oggetto.")
    except (ValueError, TypeError, AttributeError) as e:
        return _errore(str(e))
    tabelle = {"generale": {**generale, "nome": generale.get("nome") or "Progetto dall'agente"}, "punti": punti,
               "impianti": impianti, "curve": curve, "parametri": parametri}
    esito, pid = _da_tabelle(s, tabelle)
    if pid is None:
        errori = esito["errori_luogo"] + esito["errori"] + esito.get("errori_impianti", [])
        return _errore("Il progetto non si crea:\n- " + "\n- ".join(errori), errori=errori)
    out = _controlla(esito["progetto"], pid, opz)
    out.text = f"Progetto creato: {pid}.\n\n" + out.text
    return _redigi_output(out, _privati(esito["progetto"]))


def esporta_progetto(args: dict, s: Sessione, opz: Opzioni) -> ToolOutput:
    try:
        testo, pid = _apri(args, s)
    except ValueError as e:
        return _errore(f"Il progetto non si apre: {e}")
    return ToolOutput(
        f"Il file del progetto {pid}: salvalo come .json e aprilo nel sito (cer.raccasamuele.it, «Apri un lavoro») o "
        "nell'app. Contiene i dati inseriti, anche nomi e indirizzo se ci sono.\n\n" + testo,
        {"ok": True, "progetto_id": pid, "file": json.loads(testo)})


def leggi_consumi(args: dict, s: Sessione, opz: Opzioni) -> ToolOutput:
    try:
        file = _base64_file(args.get("percorsi"), (".csv", ".json", ".txt"), MAX_FILE_CONSUMI_BYTE)
    except ValueError as e:
        return _errore(str(e))
    r = web.leggi_consumi(file, scenario=args.get("scenario"), conta_fv=bool(args.get("conta_fv", True)))
    if not r["ok"]:
        return _errore(f"I consumi non si leggono: {r['errore']}")
    if r.get("scegli"):
        scenari = r["scenari"]
        return ToolOutput(
            "È un profilo energetico di Casa: scegli lo scenario e richiama leggi_consumi con «scenario».\n"
            + json.dumps(scenari, ensure_ascii=False),
            {"ok": True, "scegli_scenario": True, "scenari": scenari, "avvisi": r["avvisi"]})
    cid = s.nuovo("consumi")
    s.consumi[cid] = {k: r[k] for k in ("curva", "descrizione", "calcolata", "batteria", "profilo") if k in r}
    curva = r["curva"]
    strutturato = {"ok": True, "consumi_id": cid, "descrizione": r["descrizione"], "calcolata": r["calcolata"],
                   "kwh_annui": round(curva["kwh_annui"]), "natura": curva.get("natura"), "giorni": curva.get("giorni"),
                   "fonte": curva.get("fonte"), "batteria": "batteria" in r, "impianto_dal_profilo": r.get("impianto"),
                   "avvisi": r["avvisi"]}
    testo = (f"Consumi letti: {cid}, circa {round(curva['kwh_annui']):,} kWh all'anno.".replace(",", ".")
             + f" {r['descrizione']}"
             + (f"\nAvvisi:\n- " + "\n- ".join(r["avvisi"]) if r["avvisi"] else "")
             + f"\nPer usarli, in crea_progetto: «consumi»: {{\"<nome del contatore>\": \"{cid}\"}}."
             + ("\nIl profilo ha anche un impianto di casa: aggiungilo agli impianti se va contato."
                if r.get("impianto") else ""))
    return ToolOutput(testo, strutturato)


def leggi_prezzi(args: dict, s: Sessione, opz: Opzioni) -> ToolOutput:
    try:
        file = _base64_file(args.get("percorsi"), (".csv", ".txt"), MAX_FILE_PREZZI_BYTE)
    except ValueError as e:
        return _errore(str(e))
    r = web.leggi_prezzi(file, str(args.get("regione") or ""))
    if not r["ok"]:
        return _errore("I prezzi non si leggono:\n- " + "\n- ".join(r["errori"]), errori=r["errori"])
    pid = s.nuovo("prezzi")
    s.prezzi[pid] = r["prezzi"]
    anni = [{"anno": v["anno"], "zona": v["zona"], "fonte": v["fonte"], "media_eur_mwh": v["media"]}
            for v in r["prezzi"].values()]
    testo = (f"Prezzi letti: {pid}. " + "; ".join(f"{a['anno']} zona {a['zona']}, media {a['media_eur_mwh']} €/MWh"
                                                   for a in anni)
             + ". I valori orari restano sul computer (i dati del GME sono per uso personale)."
             + (f"\nScartati:\n- " + "\n- ".join(r["errori"]) if r["errori"] else ""))
    return ToolOutput(testo, {"ok": True, "prezzi_id": pid, "anni": anni, "errori": r["errori"]})


def _prezzi(args: dict, s: Sessione) -> dict | None:
    pid = args.get("prezzi_id")
    if pid is None:
        return None
    if pid not in s.prezzi:
        raise ValueError("Prezzi non trovati: leggili prima con leggi_prezzi.")
    return s.prezzi[pid]


def proponi_impianto(args: dict, s: Sessione, opz: Opzioni, progress: Progress | None = None) -> ToolOutput:
    try:
        testo, pid = _apri(args, s)
        tabelle = _tabelle(testo)
        tabelle["prezzi"] = _prezzi(args, s)
    except ValueError as e:
        return _errore(f"Il progetto non si apre: {e}")
    scelta = dict(args.get("tetto") or {})
    scelta.setdefault("entrata", web.entrata_prevista(tabelle["generale"].get("data_costituzione"))["entrata"])
    forma = scelta.pop("forma", None) or "a falde"
    superficie = scelta.pop("superficie_m2", None)
    if scelta.get("kwp_max") is None and superficie is not None:
        m2_per_kwp = web.costanti_impianti()["m2_per_kwp"]
        if forma not in m2_per_kwp:
            return _errore(f"Forma del tetto: una fra {', '.join(m2_per_kwp)}.")
        scelta["kwp_max"] = float(superficie) / m2_per_kwp[forma]
    scelta.setdefault("ombre_pct", 0)
    scelta["punto"] = _punto(tabelle, scelta.get("punto"))
    r = web.richieste_proposta(tabelle, scelta)
    if not r["ok"]:
        return _redigi_output(_errore(f"La proposta non si calcola: {r['errore']}"), _privati(testo))
    pv = _scarica(r["richieste"], opz, progress)
    p = web.proposta(tabelle, scelta, pv.serie)
    if not p["ok"]:
        return _redigi_output(_errore(f"La proposta non si calcola: {p['errore']}"), _privati(testo))
    opzioni = []
    for o in p["opzioni"]:
        esito, nuovo = _da_tabelle(s, {**tabelle, "impianti": o["impianti"]})
        opzioni.append({k: v for k, v in o.items() if k != "impianti"} | {"progetto_id": nuovo,
                                                                          "errori": [] if nuovo else esito["errori"]})
    righe = [f"Tre taglie per il tetto del progetto {pid} (beneficio netto della configurazione su 25 anni, dal "
             "minimo al massimo degli scenari):"]
    for o in opzioni:
        righe.append(f"- {o['nome']}: {o['kwp']:g} kWp, costo {_euro(o['costo'])}, beneficio tra "
                     f"{_euro(o['van_minimo'])} e {_euro(o['van_massimo'])} (mediana {_euro(o['van_mediana'])}), "
                     f"{_euro(o['euro_anno_membri'])} all'anno ai membri. {o['commento']}"
                     + (f" Progetto con questa taglia: {o['progetto_id']}." if o["progetto_id"] else ""))
    if p["nessuna_conviene"]:
        righe.append("Nessuna taglia conviene in tutti gli scenari.")
    if p["quota_provvisoria"]:
        righe.append(f"Quota dei contributi ai membri non scelta: calcolata con {p['quota_membri']:.0%} provvisorio.")
    righe += [*p["note"], pv.frase(), REPORT, _chiusura(p["qualita"])]
    return _redigi_output(ToolOutput("\n".join(righe), {
        "ok": True, "progetto_id": pid, "qualita": p["qualita"], "quota_membri": p["quota_membri"],
        "quota_provvisoria": p["quota_provvisoria"], "investitore": p["investitore"],
        "nessuna_conviene": p["nessuna_conviene"], "note": p["note"], "opzioni": opzioni, "curva": p["curva"],
        "pvgis": _pvgis(pv), "avvertenza": AVVERTENZA}), _privati(testo))


def _punto(tabelle: dict, punto) -> str | None:
    """Il contatore come lo chiama il progetto salvato: dopo il salvataggio «Famiglia 1» diventa «Famiglia_1».
    Si accetta anche il nome del membro, se ha un solo contatore."""
    if not isinstance(punto, str):
        return punto
    righe = tabelle.get("punti") or []
    if any(r["punto"] == punto for r in righe):
        return punto
    simili = [r["punto"] for r in righe if r["punto"] == re.sub(r"[^A-Za-z0-9]+", "_", punto).strip("_")]
    del_membro = [r["punto"] for r in righe if r.get("membro") == punto]
    for candidati in (simili, del_membro):
        if len(candidati) == 1:
            return candidati[0]
    return punto


def _euro(v) -> str:
    return "n.d." if v is None else f"{v:,.0f} €".replace(",", ".")


def _pvgis(pv: Scaricamento) -> dict:
    return {"serie": len(pv.serie) + len(pv.mancanti), "dalla_cache": pv.dalla_cache, "scaricate": pv.scaricate,
            "mancanti": len(pv.mancanti), "frase": pv.frase()}


def analizza_scenario(args: dict, s: Sessione, opz: Opzioni, progress: Progress | None = None) -> ToolOutput:
    try:
        testo, pid = _apri(args, s)
        prezzi = _prezzi(args, s)
    except ValueError as e:
        return _errore(f"Il progetto non si apre: {e}")
    pv = _scarica(web.richieste_pvgis(testo), opz, progress)
    r = web.risultati(testo, pv.serie, prezzi)
    segreti = _privati(testo)
    if not r.get("ok"):
        motivi = r.get("errore") or "; ".join(r.get("non_supportati") or []) or "configurazione non supportata"
        return _redigi_output(_errore(f"Lo scenario non si calcola: {motivi}", non_supportati=r.get("non_supportati")),
                              segreti)
    aid = s.nuovo("analisi")
    s.analisi[aid] = dict(web._ultima)
    frase = "".join(t for t, _ in r["frase"])
    righe = [frase, f"{r['qualita']['testo']}: {r['qualita']['spiegazione']}."]
    if r.get("economia_disabilitata"):
        righe.append(f"Conti economici non calcolati: {r['economia_disabilitata']}")
    for c in r.get("cifre", []):
        righe.append(f"- {c['voce']}: {_num(c['valore'])} {c['unita']} (tra {_num(c['minimo'])} e "
                     f"{_num(c['massimo'])}). {c['significato']}")
    if r.get("confronto"):
        righe.append(r["confronto"]["frase"])
    if r.get("per_membro"):
        righe.append("Netto all'anno per membro: " + "; ".join(f"{m['membro']} {_euro(m['netto'])}"
                                                                for m in r["per_membro"]) + ".")
    righe.append("Requisiti: " + "; ".join(f"{q['nome']}: {q['stato']} ({q['motivo']})" for q in r["requisiti"]) + ".")
    if r["da_verificare"]:
        righe.append("Da verificare fuori dal simulatore:\n- " + "\n- ".join(r["da_verificare"]))
    if r["precisione"]["voci"]:
        righe.append(r["precisione"]["frase"] + "\n- " + "\n- ".join(f"{v['cosa']}: {v['perche']}"
                                                                     for v in r["precisione"]["voci"]))
    righe.append("Avvertenze:\n- " + "\n- ".join(r["avvertenze"]))
    righe.append(f"Prezzi: {', '.join(r['fonti_prezzi']) or 'n.d.'}. {pv.frase()} {r['nota_intervalli']}")
    righe.append(f"Analisi {aid}: per la curva delle taglie usa dimensiona_impianto, per il PDF o l'Excel "
                 "scrivi_report.")
    righe += [REPORT, _chiusura(r["qualita"]["lettera"])]
    strutturato = {k: v for k, v in r.items() if k not in ("giorno_tipo", "colori", "frase")}
    strutturato |= {"analisi_id": aid, "progetto_id": pid, "frase": frase, "pvgis": _pvgis(pv),
                    "avvertenza": AVVERTENZA}
    return _redigi_output(ToolOutput("\n\n".join(righe), strutturato), segreti)


def _num(v) -> str:
    return "n.d." if v is None else f"{v:,.0f}".replace(",", ".")


def _con_analisi(args: dict, s: Sessione):
    aid = args.get("analisi_id")
    if aid not in s.analisi:
        raise ValueError("Analisi non trovata: calcolala prima con analizza_scenario (restano finché il server è "
                         "acceso).")
    web._ultima.clear()
    web._ultima.update(s.analisi[aid])
    return aid


def _segreti_analisi(s: Sessione, aid: str) -> list[str]:
    cfg = s.analisi[aid]["analisi"].config
    return _privati(json.dumps({"configurazione": cfg.model_dump(mode="json")}))


def dimensiona_impianto(args: dict, s: Sessione, opz: Opzioni) -> ToolOutput:
    try:
        aid = _con_analisi(args, s)
    except ValueError as e:
        return _errore(str(e))
    impianti = [p.id for p in s.analisi[aid]["analisi"].config.plants]
    impianto = args.get("impianto") or (impianti[0] if len(impianti) == 1 else None)
    if impianto is None:
        return _errore(f"Indica l'impianto: uno fra {', '.join(impianti)}.")
    n = min(max(int(args.get("n_punti") or 8), 3), 15)
    r = web.dimensionamento(str(impianto), n_punti=n)
    if not r["ok"]:
        return _errore(f"Il dimensionamento non si calcola: {r['errore']}")
    righe = [f"Beneficio netto mediano su 25 anni per taglia dell'impianto {impianto} (configurazione / chi investe):"]
    righe += [f"- {q['kwp']:g} kWp: {_euro(q['configurazione'])} / {_euro(q['investitore'])}" for q in r["curva"]]
    righe += [r["dicitura"], REPORT, _chiusura()]
    return _redigi_output(ToolOutput("\n".join(righe), {"ok": True, "analisi_id": aid, "impianto": impianto,
                                                        "dicitura": r["dicitura"], "curva": r["curva"],
                                                        "avvertenza": AVVERTENZA}), _segreti_analisi(s, aid))


def scrivi_report(args: dict, s: Sessione, opz: Opzioni) -> ToolOutput:
    try:
        aid = _con_analisi(args, s)
    except ValueError as e:
        return _errore(str(e))
    formato = args.get("formato")
    if formato not in ("pdf", "xlsx"):
        return _errore("Il formato è «pdf» o «xlsx».")
    percorso = args.get("percorso")
    if not isinstance(percorso, str) or not percorso.strip() or _rete_o_dispositivo(percorso.strip()):
        return _errore("Indica dove salvare il report: un percorso su questo computer.")
    file = Path(percorso.strip()).expanduser().resolve()
    if file.suffix.lower() != f".{formato}":
        return _errore(f"Il file del report deve finire con .{formato}.")
    if file.exists():
        return _errore("Il file esiste già: il server non sovrascrive. Indica un altro nome.")
    if not file.parent.is_dir():
        return _errore("La cartella non esiste.")
    r = web.report(formato)
    if not r["ok"]:
        return _errore(f"Il report non si scrive: {r['errore']}")
    dati = base64.b64decode(r["base64"])
    try:
        with open(file, "xb") as f:  # "x": non sovrascrive neanche se il file compare nel frattempo
            f.write(dati)
    except OSError:
        return _errore("Il file non si scrive: controlla la cartella e i permessi.")
    return ToolOutput(f"Report {formato.upper()} dell'analisi {aid} salvato in {file} ({len(dati) // 1024} kB). "
                      "Contiene i dati del progetto, anche nomi e indirizzo se ci sono.",
                      {"ok": True, "analisi_id": aid, "formato": formato, "percorso": str(file), "byte": len(dati)})


# --- definizioni ------------------------------------------------------------------------------------------

_PROGETTO_SCHEMA = {"type": "object", "properties": PROGETTO_PROP, "additionalProperties": False}
_PREZZI_PROP = {"prezzi_id": {"type": "string", "description": "Facoltativo: prezzi orari letti con leggi_prezzi. "
                                                               "Senza, prezzo costante (qualità più bassa)."}}


def crea_strumenti(opz: Opzioni | None = None, sessione: Sessione | None = None) -> list[ToolDef]:
    opz = opz or Opzioni()
    s = sessione or Sessione()

    def con(f: Callable, lungo: bool = False):
        return (lambda a, p: f(a, s, opz, p)) if lungo else (lambda a, p: f(a, s, opz))

    strumenti = [
        ToolDef("valori_predefiniti", "Valori e scelte ammesse",
                "Elenchi ammessi (regioni, tipi di soggetto, tipologie di consumo) e valori predefiniti dell'economia "
                "e degli impianti. Da chiamare prima di crea_progetto per usare i nomi giusti.",
                {"type": "object", "properties": {"tipo": {"type": "string", "enum": ["gruppo", "CER"],
                                                           "description": "Gruppo di autoconsumatori o comunità "
                                                                          "energetica (cambia i costi)."}},
                 "additionalProperties": False},
                lambda a, p: valori_predefiniti(a), LETTURA),
        ToolDef("controlla_progetto", "Controlla un progetto",
                "Apre un progetto salvato dal sito o dall'app (o creato in questa sessione) e dice se è completo: "
                "membri, contatori, consumi, impianti, quota ai membri, configurazioni non supportate. Restituisce "
                "un progetto_id da usare con gli altri strumenti.",
                _PROGETTO_SCHEMA, con(controlla_progetto), LETTURA),
        ToolDef("crea_progetto", "Crea un progetto",
                "Crea un progetto di gruppo di autoconsumatori o comunità energetica dai dati della conversazione: "
                "luogo, contatori (o N famiglie tipo), impianti, parametri economici. Usa i nomi di "
                "valori_predefiniti. Restituisce un progetto_id.",
                {"type": "object", "required": ["generale"], "additionalProperties": False, "properties": {
                    "generale": {"type": "object", "description": "Dati del passo 1.", "properties": {
                        "tipo": {"type": "string", "enum": ["gruppo", "CER"]},
                        "lat": {"type": "number"}, "lon": {"type": "number"},
                        "regione": {"type": "string"}, "nome": {"type": "string"},
                        "indirizzo": {"type": "string"},
                        "data_costituzione": {"type": "string", "description": "AAAA-MM-GG"}},
                        "required": ["tipo", "lat", "lon", "regione"]},
                    "punti": {"type": "array", "description": "Un contatore per riga.", "items": {
                        "type": "object", "properties": {k: {"type": ["string", "number", "null"]}
                                                         for k in web.CAMPI_PUNTO}}},
                    "famiglie_tipo": {"type": "object", "description": "Aggiunge N famiglie con il consumo tipo.",
                                      "properties": {"numero": {"type": "integer", "minimum": 1, "maximum": 100},
                                                     "kwh_annui": {"type": "number"}}},
                    "impianti": {"type": "array", "description": "Impianti già decisi (altrimenti proponi_impianto).",
                                 "items": {"type": "object", "properties": {
                                     k: {"type": ["string", "number", "boolean", "null"]} for k in CAMPI_IMPIANTO}}},
                    "consumi": {"type": "object", "description": "Contatore → consumi_id di leggi_consumi.",
                                "additionalProperties": {"type": "string"}},
                    "parametri": {"type": "object", "description": "quota_membri (0–1, obbligatoria per i "
                                                                   "risultati) e gli altri di valori_predefiniti.",
                                  "properties": {k: {"type": ["number", "string"]} for k in web.PARAMETRI}}}},
                con(crea_progetto), LETTURA | {"idempotentHint": False}),
        ToolDef("leggi_consumi", "Leggi i consumi di un contatore",
                "Legge la curva oraria di un contatore da file sul computer: i CSV del distributore (anche più mesi "
                "insieme), un file curva-consumi o un profilo energetico di Casa. Restituisce un consumi_id per "
                "crea_progetto. I valori orari non escono dal computer.",
                {"type": "object", "required": ["percorsi"], "additionalProperties": False, "properties": {
                    "percorsi": {"type": "array", "items": {"type": "string"},
                                 "description": "Percorsi dei file dello stesso contatore."},
                    "scenario": {"type": "string", "description": "Solo per un profilo di Casa: lo scenario."},
                    "conta_fv": {"type": "boolean", "description": "Profilo di Casa: consumi prima del FV di casa."}}},
                con(leggi_consumi), LETTURA),
        ToolDef("leggi_prezzi", "Leggi i prezzi orari",
                "Legge i prezzi orari dell'energia da CSV sul computer (uno per anno, per esempio dal GME) per la "
                "zona della regione. Restituisce un prezzi_id. I valori orari non escono dal computer.",
                {"type": "object", "required": ["percorsi", "regione"], "additionalProperties": False, "properties": {
                    "percorsi": {"type": "array", "items": {"type": "string"}},
                    "regione": {"type": "string"}}},
                con(leggi_prezzi), LETTURA),
        ToolDef("proponi_impianto", "Proponi la taglia del fotovoltaico",
                "Tre taglie commentate per un tetto (piccola, consigliata, grande) con il beneficio per la "
                "configurazione e per i membri. Scarica da PVGIS la produzione (qualche secondo, con "
                "l'avanzamento). Ogni taglia dà un nuovo progetto_id con l'impianto già inserito.",
                {"type": "object", "required": ["tetto"], "additionalProperties": False, "properties": {
                    **PROGETTO_PROP, **_PREZZI_PROP,
                    "tetto": {"type": "object", "required": ["punto", "investitore", "inclinazione", "azimut"],
                              "properties": {
                                  "punto": {"type": "string", "description": "Contatore a cui si collega."},
                                  "investitore": {"type": "string", "description": "Membro che paga, o il soggetto "
                                                                                   "esterno di valori_predefiniti."},
                                  "kwp_max": {"type": "number", "description": "kWp che il tetto ospita."},
                                  "superficie_m2": {"type": "number", "description": "In alternativa a kwp_max: "
                                                                                     "superficie utile del tetto."},
                                  "forma": {"type": "string", "enum": ["a falde", "piano"],
                                            "description": "Con superficie_m2: sul tetto piano servono più m²."},
                                  "inclinazione": {"type": "number", "description": "Gradi, 0–90."},
                                  "azimut": {"type": "number", "description": "0 sud, 90 ovest, -90 est."},
                                  "azimut_2": {"type": "number", "description": "Seconda falda (est-ovest)."},
                                  "ombre_pct": {"type": "number", "description": "Perdite per ombre, 0–40."},
                                  "entrata": {"type": "string", "description": "Entrata in esercizio, AAAA-MM-GG."}}}}},
                con(proponi_impianto, True), CON_PVGIS),
        ToolDef("analizza_scenario", "Analizza lo scenario",
                "I risultati completi del progetto come nel passo 5 del sito: energia condivisa, contributi GSE, "
                "beneficio netto con gli intervalli, chi riceve cosa, requisiti, sensibilità, qualità dei dati. "
                "Scarica da PVGIS la produzione (qualche secondo, con l'avanzamento). Restituisce un analisi_id.",
                {"type": "object", "additionalProperties": False, "properties": {**PROGETTO_PROP, **_PREZZI_PROP}},
                con(analizza_scenario, True), CON_PVGIS),
        ToolDef("dimensiona_impianto", "Curva delle taglie",
                "Beneficio netto per diverse taglie di un impianto, sull'analisi indicata.",
                {"type": "object", "required": ["analisi_id"], "additionalProperties": False, "properties": {
                    "analisi_id": {"type": "string"},
                    "impianto": {"type": "string", "description": "Id dell'impianto; facoltativo se è uno solo."},
                    "n_punti": {"type": "integer", "minimum": 3, "maximum": 15}}},
                con(dimensiona_impianto), LETTURA),
        ToolDef("scrivi_report", "Scrivi il report",
                "Salva il report PDF o il file Excel dell'analisi nel percorso indicato dall'utente. Non sovrascrive "
                "file esistenti.",
                {"type": "object", "required": ["analisi_id", "formato", "percorso"], "additionalProperties": False,
                 "properties": {"analisi_id": {"type": "string"}, "formato": {"type": "string", "enum": ["pdf", "xlsx"]},
                                "percorso": {"type": "string", "description": "File da creare, .pdf o .xlsx."}}},
                con(scrivi_report), SCRITTURA),
        ToolDef("esporta_progetto", "Esporta il file del progetto",
                "Il file di salvataggio del progetto (JSON), da salvare e aprire nel sito o nell'app. Contiene "
                "tutti i dati inseriti.",
                _PROGETTO_SCHEMA, con(esporta_progetto), LETTURA),
    ]
    # La scheda nella chat (MCP Apps) per tutti tranne esporta_progetto, che è il file da salvare: i client che la
    # supportano la mostrano con il risultato.
    for t in strumenti:
        if t.name != "esporta_progetto":
            t.meta = SCHEDA_META
    return strumenti
