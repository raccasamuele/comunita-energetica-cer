"""Profilo energetico di una casa: il file comune fra il simulatore della casa e cersim (docs/formato_profilo_energetico.md).

Un profilo ha uno o più scenari della stessa casa (la situazione attuale e i pacchetti di interventi). Ogni scenario
porta i consumi elettrici **prima** del fotovoltaico, il FV e la batteria di casa, e i prelievi dalla rete dopo FV e
batteria (lo stesso contenuto di un file `curva-consumi`).

- `leggi_profilo` legge un file non fidato e rifiuta con un messaggio leggibile ciò che non va.
- `applica_scenario` trasforma uno scenario nei dati di un contatore: con il FV contato nella comunità, curva dei
  consumi prima del FV, batteria sul punto e impianto da aggiungere; altrimenti la curva dei prelievi, come
  `curva-consumi`.
- `esporta_profilo` scrive il profilo di un contatore: quello caricato, oppure i suoi consumi se non ha impianti.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date

from cersim import __version__
from cersim.curva_calcolata import (MAX_DESCRIZIONE, MAX_KWH_BATTERIA, MAX_KWP, MAX_MOTORE, NOMI_FONTE, SCARTO_DA_SEGNALARE,
                                    TOLLERANZA_KWH, _FONTE, _kw, _kwh, _non_numero, _numero, _testo, cella)
from cersim.misure import ANNO_RIFERIMENTO, kwh_anno_riferimento
from cersim.model import (CELLE_CURVA, MAX_KWH_ANNUI, BatteriaCasa, ComuneProfilo, ConnectionPoint, CurvaMisurata,
                          FvProfilo, NaturaCurva, PrezzoBolletta, ProfiloPunto, StimaProfilo, UsiProfilo)

FORMATO = "profilo-energetico"
VERSIONE = 2  # la 2 aggiunge `bolletta`; senza bolletta si scrive ancora la 1, che leggono anche i lettori vecchi
VERSIONI_LETTE = (1, 2)
MAX_BYTE = 2_000_000
MAX_SCENARI = 20
STATI = ("documentato", "misurato", "ipotizzato", "sconosciuto")
USI = ("altri_usi_kwh", "pompa_di_calore_kwh", "raffrescamento_kwh")
STIMA = ("immissioni_kwh", "autoconsumo_kwh")
ESCLUSI = ("codice POD", "nomi e indirizzo", "codice cliente", "letture del contatore con le date", "importi")
_ID = re.compile(r"^[A-Za-z0-9-]{1,20}$")
_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CAMPI = {
    "radice": (("formato", "versione", "fonte", "data", "comune", "scenari", "esclusi"), ("motore", "descrizione", "bolletta")),
    "bolletta": (("eur_kwh", "stato"), ("fasce",)),
    "comune": (("codice_istat", "nome", "lat", "lon"), ()),
    "scenario": (("id", "nome", "attuale", "consumi", "fv", "batteria", "prelievi"), ("stima",)),
    "consumi": (("natura", "stato", "kwh_annui", "ore"), ("giorni", "dal", "al", "usi")),
    "fv": (("kwp", "inclinazione", "orientamento", "perdite_pct", "esistente"), ()),
    "batteria": (("capacita_kwh", "potenza_kw", "rendimento_pct", "riserva_pct"), ()),
    "prelievi": (("kwh_annui", "ore"), ()),
}


@dataclass(frozen=True)
class Scenario:
    id: str
    nome: str
    attuale: bool
    natura: str  # "calcolato" | "misurato"
    stato: str
    consumi_kwh: float
    consumi: tuple[float, ...]
    periodo: tuple[int, date, date] | None  # giorni, dal, al: solo per i consumi misurati
    usi: dict[str, float]
    fv: FvProfilo | None
    batteria: BatteriaCasa | None
    prelievi_kwh: float
    prelievi: tuple[float, ...]
    stima: dict[str, float]


@dataclass(frozen=True)
class Profilo:
    fonte: str
    motore: str | None
    descrizione: str | None
    data: date
    comune: ComuneProfilo | None
    scenari: tuple[Scenario, ...]
    avvisi: list[str] = field(default_factory=list)
    bolletta: PrezzoBolletta | None = None

    def scenario(self, sid: str) -> Scenario:
        for s in self.scenari:
            if s.id == sid:
                return s
        raise ValueError(f"Il profilo non ha lo scenario {sid!r}")


def _oggetto(dati, cosa: str, dove: str, versione: int = VERSIONE) -> dict:
    if not isinstance(dati, dict):
        raise ValueError(f"{dove}: atteso un oggetto")
    obbligatori, facoltativi = CAMPI[cosa]
    if versione < 2:
        facoltativi = tuple(c for c in facoltativi if c != "bolletta")
    if sconosciuti := sorted(set(dati) - set(obbligatori) - set(facoltativi)):
        raise ValueError(f"{dove}: campi non previsti dalla versione {versione}: {', '.join(map(str, sconosciuti))[:200]}")
    if mancanti := [c for c in obbligatori if c not in dati]:
        raise ValueError(f"{dove}: mancano i campi {', '.join(mancanti)}")
    return dati


def _num(valore, dove: str, minimo: float, massimo: float, *, escluso_minimo=False) -> float:
    x = _numero(valore)
    if x is None or x < minimo or x > massimo or (escluso_minimo and x == minimo):
        da = f"maggiore di {minimo:g}" if escluso_minimo else f"tra {minimo:g}"
        raise ValueError(f"{dove}: serve un numero {da} {'e al massimo' if escluso_minimo else 'e'} {massimo:,.0f}".replace(",", "."))
    return x


def _data(valore, dove: str) -> date:
    if not isinstance(valore, str) or not _DATA.match(valore):
        raise ValueError(f"{dove}: serve una data AAAA-MM-GG")
    try:
        return date.fromisoformat(valore)
    except ValueError:
        raise ValueError(f"{dove}: data non valida") from None


def _ore(dati: dict, dove: str, avvisi: list[str], *, zero_ammesso: bool) -> tuple[float, tuple[float, ...]]:
    """kWh annui e 864 celle, controllati come in `curva-consumi`: kWh finiti e non negativi, consumo annuo che torna
    con la forma sul calendario di riferimento."""
    kwh = _num(dati["kwh_annui"], f"{dove}, kwh_annui", 0, MAX_KWH_ANNUI)
    ore = dati["ore"]
    if not isinstance(ore, list) or len(ore) != CELLE_CURVA:
        trovati = f": ne ha {len(ore)}" if isinstance(ore, list) else ""
        raise ValueError(f"{dove}: il campo ore deve essere un elenco di {CELLE_CURVA} valori{trovati}")
    valori = []
    for i, v in enumerate(ore):
        x = _numero(v)
        if x is None or x < 0:
            raise ValueError(f"{dove}: valore {i} delle ore non valido ({cella(i)}): servono kWh finiti e non negativi")
        valori.append(round(x, 5))
    if sum(valori) <= 0 or kwh <= 0:
        if zero_ammesso and sum(valori) == 0 and kwh == 0:
            return 0.0, tuple(valori)
        raise ValueError(f"{dove}: la curva è tutta a zero o il consumo annuo è zero")
    della_curva = kwh_anno_riferimento(valori)
    scarto = abs(della_curva - kwh) / kwh
    if scarto > TOLLERANZA_KWH:
        raise ValueError(f"{dove}: il consumo annuo dichiarato ({_kwh(kwh)} kWh) non torna con la curva "
                         f"({_kwh(della_curva)} kWh sul calendario del {ANNO_RIFERIMENTO}): scarto del {scarto:.1%}, "
                         f"ammesso fino al {TOLLERANZA_KWH:.0%}")
    if scarto > SCARTO_DA_SEGNALARE:
        avvisi.append(f"{dove}: consumo annuo dichiarato {_kwh(kwh)} kWh, dalla curva {_kwh(della_curva)} kWh: "
                      "si usa quello dichiarato")
    return round(kwh, 1), tuple(valori)


def _scenario(dati, n: int, avvisi: list[str]) -> Scenario:
    dove = f"Scenario {n}"
    d = _oggetto(dati, "scenario", dove)
    sid = d["id"]
    if not isinstance(sid, str) or not _ID.match(sid):
        raise ValueError(f"{dove}: id di lettere, cifre e trattini, al massimo 20 caratteri")
    nome = _testo(d["nome"], "nome", 80)
    if not nome:
        raise ValueError(f"{dove}: manca il nome")
    dove = f"Scenario «{nome}»"
    if not isinstance(d["attuale"], bool):
        raise ValueError(f"{dove}: attuale deve essere vero o falso")

    c = _oggetto(d["consumi"], "consumi", f"{dove}, consumi")
    if c["natura"] not in ("calcolato", "misurato"):
        raise ValueError(f"{dove}: natura dei consumi «calcolato» o «misurato»")
    if c["stato"] not in STATI:
        raise ValueError(f"{dove}: stato dei consumi tra {', '.join(STATI)}")
    consumi_kwh, consumi = _ore(c, f"{dove}, consumi", avvisi, zero_ammesso=False)
    periodo = None
    if c["natura"] == "misurato":
        if not all(k in c for k in ("giorni", "dal", "al")):
            raise ValueError(f"{dove}: i consumi misurati indicano giorni, dal e al")
        giorni = _numero(c["giorni"])
        if giorni is None or giorni != int(giorni) or not 1 <= giorni <= 3660:
            raise ValueError(f"{dove}: giorni con misure non validi")
        dal, al = _data(c["dal"], f"{dove}, dal"), _data(c["al"], f"{dove}, al")
        if al < dal:
            raise ValueError(f"{dove}: il periodo delle misure finisce prima di cominciare")
        periodo = (int(giorni), dal, al)
    elif any(k in c for k in ("giorni", "dal", "al")):
        raise ValueError(f"{dove}: i consumi calcolati non hanno giorni né periodo di misura")
    usi = {}
    if "usi" in c:
        if not isinstance(c["usi"], dict) or set(c["usi"]) - set(USI):
            raise ValueError(f"{dove}: usi ammessi {', '.join(USI)}")
        usi = {k: _num(v, f"{dove}, {k}", 0, MAX_KWH_ANNUI) for k, v in c["usi"].items()}

    fv = None
    if d["fv"] is not None:
        f = _oggetto(d["fv"], "fv", f"{dove}, fv")
        if not isinstance(f["esistente"], bool):
            raise ValueError(f"{dove}: esistente del FV deve essere vero o falso")
        fv = FvProfilo(kwp=_num(f["kwp"], f"{dove}, kWp del FV", 0, MAX_KWP, escluso_minimo=True),
                       inclinazione=_num(f["inclinazione"], f"{dove}, inclinazione", 0, 90),
                       orientamento=_num(f["orientamento"], f"{dove}, orientamento", -180, 180),
                       perdite_pct=_num(f["perdite_pct"], f"{dove}, perdite", 0, 50), esistente=f["esistente"])
    batteria = None
    if d["batteria"] is not None:
        if fv is None:
            raise ValueError(f"{dove}: una batteria di casa si carica dal fotovoltaico: manca il FV")
        b = _oggetto(d["batteria"], "batteria", f"{dove}, batteria")
        batteria = BatteriaCasa(
            capacita_kwh=_num(b["capacita_kwh"], f"{dove}, capacità della batteria", 0, MAX_KWH_BATTERIA, escluso_minimo=True),
            potenza_kw=_num(b["potenza_kw"], f"{dove}, potenza della batteria", 0, MAX_KWH_BATTERIA, escluso_minimo=True),
            rendimento_pct=_num(b["rendimento_pct"], f"{dove}, rendimento della batteria", 0, 100, escluso_minimo=True),
            riserva_pct=_num(b["riserva_pct"], f"{dove}, riserva della batteria", 0, 99))

    p = _oggetto(d["prelievi"], "prelievi", f"{dove}, prelievi")
    prelievi_kwh, prelievi = _ore(p, f"{dove}, prelievi", avvisi, zero_ammesso=True)
    if fv is None and abs(prelievi_kwh - consumi_kwh) > 0.01 * consumi_kwh + 1:
        raise ValueError(f"{dove}: senza FV i prelievi devono coincidere con i consumi")
    stima = {}
    if d.get("stima") is not None:
        if not isinstance(d["stima"], dict) or set(d["stima"]) - set(STIMA):
            raise ValueError(f"{dove}: stima ammessa {', '.join(STIMA)}")
        stima = {k: _num(v, f"{dove}, {k}", 0, MAX_KWH_ANNUI) for k, v in d["stima"].items()}
    return Scenario(id=sid, nome=nome, attuale=d["attuale"], natura=c["natura"], stato=c["stato"],
                    consumi_kwh=consumi_kwh, consumi=consumi, periodo=periodo, usi=usi, fv=fv, batteria=batteria,
                    prelievi_kwh=prelievi_kwh, prelievi=prelievi, stima=stima)


def _bolletta(dati, avvisi: list[str]) -> PrezzoBolletta | None:
    """Il prezzo variabile della bolletta della casa, imposte comprese. Con stato «sconosciuto» non si usa."""
    if dati is None:
        return None
    d = _oggetto(dati, "bolletta", "Bolletta")
    if d["stato"] not in STATI:
        raise ValueError(f"Bolletta: stato del prezzo tra {', '.join(STATI)}")
    eur_kwh = _num(d["eur_kwh"], "Bolletta, eur_kwh", 0, 1)
    fasce = None
    if d.get("fasce") is not None:
        if not isinstance(d["fasce"], dict) or set(d["fasce"]) != {"F1", "F2", "F3"}:
            raise ValueError("Bolletta: le fasce sono F1, F2 e F3")
        fasce = {k: _num(v, f"Bolletta, fascia {k}", 0, 1) for k, v in d["fasce"].items()}
    if d["stato"] == "sconosciuto":
        avvisi.append("il prezzo della bolletta nel profilo è sconosciuto: per il risparmio in bolletta vale quello "
                      "del passo Economia")
        return None
    return PrezzoBolletta(eur_kwh=eur_kwh, fasce=fasce, stato=d["stato"])


def leggi_profilo(contenuto: bytes) -> Profilo:
    """Profilo da un file non fidato. Solleva ValueError con un messaggio leggibile."""
    if len(contenuto) > MAX_BYTE:
        raise ValueError(f"Il file supera {MAX_BYTE // 1_000_000} MB: non sembra un profilo energetico")
    try:
        dati = json.loads(contenuto.decode("utf-8-sig"), parse_constant=_non_numero)
    except UnicodeDecodeError:
        raise ValueError("Il file non è un testo UTF-8: non sembra un profilo energetico") from None
    except RecursionError:
        raise ValueError("Il file non è un JSON valido") from None
    except ValueError as e:
        raise ValueError(f"Il file non è un JSON valido ({getattr(e, 'msg', e)})") from None
    if not isinstance(dati, dict) or dati.get("formato") != FORMATO:
        raise ValueError(f"Non è un profilo energetico: il campo formato deve essere {FORMATO!r}")
    versione = dati.get("versione")
    if isinstance(versione, bool) or not isinstance(versione, int):
        raise ValueError("Il campo versione deve essere un numero intero")
    if versione not in VERSIONI_LETTE:
        piu_recente = versione > max(VERSIONI_LETTE)
        raise ValueError(f"Versione {versione} del profilo non supportata (questo simulatore legge la "
                         f"{', '.join(map(str, VERSIONI_LETTE))})" + (": aggiorna il simulatore" if piu_recente else ""))
    d = _oggetto(dati, "radice", "Profilo", versione)
    fonte = d["fonte"]
    if not isinstance(fonte, str) or not _FONTE.match(fonte):
        raise ValueError("Il campo fonte deve essere un nome breve in minuscolo, per esempio 'simulatore-casa'")
    comune = None
    if d["comune"] is not None:
        c = _oggetto(d["comune"], "comune", "Comune")
        if not isinstance(c["codice_istat"], str) or not re.fullmatch(r"[0-9]{6}", c["codice_istat"]):
            raise ValueError("Comune: il codice ISTAT ha sei cifre")
        nome = _testo(c["nome"], "nome del comune", 80)
        if not nome:
            raise ValueError("Comune: manca il nome")
        comune = ComuneProfilo(codice_istat=c["codice_istat"], nome=nome, lat=_num(c["lat"], "Comune, lat", 35, 48),
                               lon=_num(c["lon"], "Comune, lon", 6, 19))
    if not isinstance(d["esclusi"], list) or not all(isinstance(x, str) for x in d["esclusi"]):
        raise ValueError("Il campo esclusi deve essere un elenco di testi")
    scenari = d["scenari"]
    if not isinstance(scenari, list) or not 1 <= len(scenari) <= MAX_SCENARI:
        raise ValueError(f"Il profilo deve avere da 1 a {MAX_SCENARI} scenari")
    avvisi: list[str] = []
    letti = tuple(_scenario(s, n, avvisi) for n, s in enumerate(scenari, 1))
    ids = [s.id for s in letti]
    if len(set(ids)) != len(ids):
        raise ValueError("Due scenari del profilo hanno lo stesso id")
    if sum(s.attuale for s in letti) > 1:
        raise ValueError("Al massimo uno scenario è la situazione attuale")
    return Profilo(fonte=fonte, motore=_testo(d.get("motore"), "motore", MAX_MOTORE),
                   descrizione=_testo(d.get("descrizione"), "descrizione", MAX_DESCRIZIONE),
                   data=_data(d["data"], "Data del profilo"), comune=comune, scenari=letti, avvisi=avvisi,
                   bolletta=_bolletta(d.get("bolletta"), avvisi))


def sintesi(profilo: Profilo) -> list[dict]:
    """Gli scenari da scegliere, in breve, per l'interfaccia."""
    return [{"id": s.id, "nome": s.nome, "attuale": s.attuale, "consumi_kwh": s.consumi_kwh,
             "prelievi_kwh": s.prelievi_kwh, "fv_kwp": s.fv.kwp if s.fv else None,
             "fv_esistente": s.fv.esistente if s.fv else None,
             "batteria_kwh": s.batteria.capacita_kwh if s.batteria else None, "usi": s.usi} for s in profilo.scenari]


@dataclass(frozen=True)
class Applicato:
    curva: CurvaMisurata
    batteria: BatteriaCasa | None
    impianto: dict | None  # kWp, inclinazione, orientamento, perdite_pct, esistente: la riga da aggiungere al passo 3
    profilo: ProfiloPunto
    avvisi: list[str]


def _etichetta(profilo: Profilo, s: Scenario, cosa: str) -> str:
    testo = f"{NOMI_FONTE.get(profilo.fonte, profilo.fonte)}: {s.nome}, {cosa}"
    return testo if len(testo) <= 80 else testo[:79].rstrip() + "…"


def applica_scenario(profilo: Profilo, sid: str, conta_fv: bool) -> Applicato:
    """I dati di un contatore da uno scenario. `conta_fv`: il FV di casa entra nella comunità (consumi prima del FV,
    batteria sul punto, impianto da aggiungere); altrimenti la curva sono i prelievi, come `curva-consumi`."""
    s = profilo.scenario(sid)
    conta = conta_fv and s.fv is not None
    avvisi = [a for a in profilo.avvisi if a.startswith(f"Scenario «{s.nome}»") or a.startswith("il prezzo della bolletta")]
    if conta:
        curva = CurvaMisurata(ore=s.consumi, natura=NaturaCurva.CALCOLATA, kwh_annui=s.consumi_kwh,
                              fonte=_etichetta(profilo, s, "consumi prima del FV"))
        impianto = {"kwp": s.fv.kwp, "inclinazione": s.fv.inclinazione, "orientamento": s.fv.orientamento,
                    "perdite_pct": s.fv.perdite_pct, "esistente": s.fv.esistente}
        avvisi.append(f"il fotovoltaico di casa da {_kw(s.fv.kwp)} kWp entra nella comunità: al passo 3 c'è il suo "
                      "impianto, " + ("indica quando è entrato in esercizio. Se prima del 16/12/2021 la CER non lo può "
                                      "contare: ricarica il profilo con «Solo prelievi»" if s.fv.esistente
                                      else "controlla la data prevista di entrata in esercizio"))
        if s.batteria:
            avvisi.append(f"la batteria di casa da {_kw(s.batteria.capacita_kwh)} kWh è simulata sul contatore: si "
                          "carica solo dal suo fotovoltaico e si scarica la sera, riducendo l'energia condivisa")
        batteria = s.batteria
    else:
        if s.prelievi_kwh <= 0:
            raise ValueError(f"Lo scenario «{s.nome}» non ha prelievi dalla rete: conta il fotovoltaico nella comunità")
        fv = s.fv.kwp if s.fv else None
        curva = CurvaMisurata(ore=s.prelievi, natura=NaturaCurva.CALCOLATA, kwh_annui=s.prelievi_kwh,
                              fonte=_etichetta(profilo, s, "prelievi dalla rete" if fv else "consumi"),
                              fv_sottratto_kwp=fv, batteria_kwh=s.batteria.capacita_kwh if s.batteria else None)
        if fv:
            avvisi.append(f"questi consumi hanno già tolto un fotovoltaico da {_kw(fv)} kWp: sono i prelievi dalla rete. "
                          "Non inserire di nuovo quell'impianto su questo punto, solo impianti nuovi")
        if s.batteria:
            avvisi.append(f"questi prelievi tengono già conto di una batteria di casa da {_kw(s.batteria.capacita_kwh)} "
                          "kWh. Una batteria privata si scarica la sera, proprio nelle ore in cui la comunità potrebbe "
                          "coprire quei consumi: riduce l'energia condivisa e i contributi")
        impianto, batteria = None, None
    if profilo.bolletta and conta:
        b = profilo.bolletta
        prezzo = (" / ".join(f"{k} {v:.3f}" for k, v in b.fasce.items()) if b.fasce else f"{b.eur_kwh:.3f}").replace(".", ",")
        avvisi.append(f"il risparmio in bolletta dell'energia che la casa consuma dal suo fotovoltaico usa il prezzo "
                      f"della sua bolletta ({prezzo} €/kWh, imposte comprese), non quello del passo Economia")
    if s.natura == "misurato":
        avvisi.append("nel profilo i consumi sono misurati, ma un file di scambio vale come stima: la qualità resta B. "
                      "Per la qualità A carica i file del distributore")
    punto = ProfiloPunto(fonte=profilo.fonte, motore=profilo.motore, data=profilo.data, comune=profilo.comune,
                         scenario=s.id, nome=s.nome, attuale=s.attuale, natura_consumi=s.natura, periodo=s.periodo,
                         stato_consumi=s.stato, usi=UsiProfilo(**s.usi) if s.usi else None, fv=s.fv,
                         prelievi_kwh=s.prelievi_kwh, prelievi=s.prelievi,
                         stima=StimaProfilo(**s.stima) if s.stima else None, conta_fv=conta, bolletta=profilo.bolletta,
                         **({} if conta else {"consumi_kwh": s.consumi_kwh, "consumi": s.consumi, "batteria": s.batteria}))
    return Applicato(curva=curva, batteria=batteria, impianto=impianto, profilo=punto, avvisi=avvisi)


def _batteria(b: BatteriaCasa | None) -> dict | None:
    return None if b is None else {"capacita_kwh": b.capacita_kwh, "potenza_kw": b.potenza_kw,
                                   "rendimento_pct": b.rendimento_pct, "riserva_pct": b.riserva_pct}


def _fv(f: FvProfilo | None) -> dict | None:
    return None if f is None else f.model_dump()


def esporta_profilo(cp: ConnectionPoint, ha_impianto: bool, *, oggi: date | None = None) -> dict:
    """Profilo di un contatore (da scrivere con `json.dumps`), senza nome del membro né POD.

    Con un profilo caricato si riscrive il suo scenario così com'era (consumi, FV, batteria, prelievi). Senza profilo
    servono una curva oraria e nessun impianto né batteria sul punto: lo scenario è la situazione attuale."""
    curva = cp.curva_misurata
    if curva is None:
        raise ValueError(f"Il contatore {cp.id} non ha consumi ora per ora: il profilo porta la curva oraria")
    p = cp.profilo
    if p is None and (ha_impianto or cp.batteria is not None):
        raise ValueError(f"Il contatore {cp.id} ha un impianto: il profilo si scarica per i contatori senza impianto "
                         "o caricati da un profilo")
    if p is not None:
        consumi_ore, consumi_kwh = (curva.ore, curva.kwh_annui) if p.conta_fv else (p.consumi, p.consumi_kwh)
        consumi = {"natura": p.natura_consumi, "stato": p.stato_consumi, "kwh_annui": consumi_kwh,
                   "ore": list(consumi_ore)}
        if p.periodo:
            consumi |= {"giorni": p.periodo[0], "dal": p.periodo[1].isoformat(), "al": p.periodo[2].isoformat()}
        if p.usi:
            consumi["usi"] = p.usi.model_dump(exclude_none=True)
        batteria = cp.batteria if p.conta_fv else p.batteria
        scenario = {"id": p.scenario, "nome": p.nome, "attuale": p.attuale, "consumi": consumi, "fv": _fv(p.fv),
                    "batteria": _batteria(batteria), "prelievi": {"kwh_annui": p.prelievi_kwh, "ore": list(p.prelievi)}}
        if p.stima:
            scenario["stima"] = p.stima.model_dump(exclude_none=True)
        comune = p.comune.model_dump() if p.comune else None
        bolletta = p.bolletta.model_dump(exclude_none=True) if p.bolletta else None
    else:
        consumi = {"natura": "misurato" if curva.misurata else "calcolato",
                   "stato": "misurato" if curva.misurata else "ipotizzato", "kwh_annui": curva.kwh_annui,
                   "ore": list(curva.ore)}
        if curva.misurata:
            consumi |= {"giorni": curva.giorni, "dal": curva.dal.isoformat(), "al": curva.al.isoformat()}
        scenario = {"id": "attuale", "nome": "Situazione attuale", "attuale": True, "consumi": consumi, "fv": None,
                    "batteria": None, "prelievi": {"kwh_annui": curva.kwh_annui, "ore": list(curva.ore)}}
        comune = None
        bolletta = None
    profilo = {"formato": FORMATO, "versione": 2 if bolletta else 1, "fonte": "cersim", "motore": f"cersim {__version__}",
               "data": (oggi or date.today()).isoformat(), "descrizione": "profilo di un contatore dal simulatore CER",
               "comune": comune, "scenari": [scenario], "esclusi": list(ESCLUSI)}
    if bolletta:
        profilo["bolletta"] = bolletta
    return profilo
