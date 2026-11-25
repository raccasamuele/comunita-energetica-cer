"""Ponte tra le tabelle dell'interfaccia e il modello dati (senza dipendere da Streamlit).

L'utente compila due tabelle con etichette leggibili:
- punti di prelievo: una riga per POD (un membro può averne più di uno);
- impianti: una riga per impianto, collegato a un POD o a un POD di sola immissione.
`configurazione_da_tabelle` le traduce in una `Configuration` validata e
restituisce gli errori in italiano invece di sollevare eccezioni.
`esporta_json` / `importa_json` salvano e ricaricano il lavoro (con limiti di
dimensione e validazione dello schema).
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from pydantic import ValidationError

from cersim.model import (
    ID_RISERVATI,
    TERZO,
    BatteriaCasa,
    CapitalGrant,
    Configuration,
    ConnectionPoint,
    CurvaMisurata,
    Fasce,
    Incasso,
    Member,
    Plant,
    ProfiloPunto,
    Ruolo,
    Tensione,
    Tipologia,
    TipoConfigurazione,
    TipoSoggetto,
)

VERSIONE_SCHEMA = 1
MAX_JSON_BYTE = 12_000_000  # con le curve misurate: circa 50 kB per contatore
EDIFICIO_GRUPPO = "edificio"
SOLA_IMMISSIONE = "(POD dedicato, sola immissione)"
INVESTITORE_ESTERNO = "Soggetto esterno (es. ESCo)"

TIPI_SOGGETTO = {
    "Persona fisica": TipoSoggetto.PERSONA_FISICA,
    "Condominio": TipoSoggetto.CONDOMINIO,
    "Ente territoriale (es. Comune)": TipoSoggetto.ENTE_TERRITORIALE,
    "Ente religioso": TipoSoggetto.ENTE_RELIGIOSO,
    "Ente del terzo settore": TipoSoggetto.TERZO_SETTORE,
    "PMI": TipoSoggetto.PMI,
    "Grande impresa": TipoSoggetto.GRANDE_IMPRESA,
    "Altro": TipoSoggetto.ALTRO,
}
TIPOLOGIE = {
    "Famiglia": Tipologia.DOMESTICO,
    "Ufficio / negozio": Tipologia.UFFICIO_COMMERCIALE,
    "Scuola": Tipologia.SCUOLA,
    "Municipio / uffici pubblici": Tipologia.PA_MUNICIPIO,
    "PMI / laboratorio": Tipologia.PMI,
}
_ETICHETTA_SOGGETTO = {v: k for k, v in TIPI_SOGGETTO.items()}
_ETICHETTA_TIPOLOGIA = {v: k for k, v in TIPOLOGIE.items()}

COLONNE_PUNTI = ["Punto", "Membro", "Tipo soggetto", "Tipologia consumo", "kWh annui", "F1 kWh", "F23 kWh",
                 "Area convenzionale GSE", "Tensione"]
COLONNE_IMPIANTI = ["Impianto", "Punto", "kWp moduli", "kW inverter", "kWp max installabili", "Inclinazione °",
                    "Orientamento °", "Seconda falda °", "Ombre %", "Entrata in esercizio", "Investitore",
                    "Costo da preventivo €", "Contributo concesso €", "Fattore F", "Estremi atto",
                    "Data incasso contributo"]


@dataclass
class Generale:
    nome: str
    tipo: str  # "CER" | "gruppo"
    lat: float
    lon: float
    regione: str
    indirizzo: str | None = None
    data_costituzione: date | None = None


@dataclass
class Esito:
    config: Configuration | None
    errori: list[str] = field(default_factory=list)


NUMERICHE_PUNTI = ["kWh annui", "F1 kWh", "F23 kWh"]
NUMERICHE_IMPIANTI = ["kWp moduli", "kW inverter", "kWp max installabili", "Inclinazione °", "Orientamento °",
                      "Seconda falda °", "Ombre %", "Costo da preventivo €", "Contributo concesso €", "Fattore F"]
DATE_IMPIANTI = ["Entrata in esercizio", "Data incasso contributo"]


PERDITE_SISTEMA_PCT = 14.0  # perdite di cavi, inverter, temperatura e sporco (valore consigliato da PVGIS)


def perdite_con_ombre(ombre_pct: float | None) -> float:
    """Perdite totali per PVGIS: perdite di sistema più le ombre di edifici vicini, combinate."""
    ombre = min(max(ombre_pct or 0.0, 0.0), 40.0)
    return round(100 * (1 - (1 - PERDITE_SISTEMA_PCT / 100) * (1 - ombre / 100)), 1)


def ombre_da_perdite(perdite_pct: float) -> float | None:
    if perdite_pct <= PERDITE_SISTEMA_PCT + 0.05:
        return None
    return round(100 * (1 - (1 - perdite_pct / 100) / (1 - PERDITE_SISTEMA_PCT / 100)), 1)


def _tipizza(df: pd.DataFrame, colonne: list[str], numeriche: list[str], date_: list[str]) -> pd.DataFrame:
    """Colonne con il tipo giusto per l'editor: numeri come float, date come datetime, il resto come testo."""
    out = df.reindex(columns=colonne).copy()
    for c in colonne:
        if c in numeriche:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
        elif c in date_:
            out[c] = pd.to_datetime(out[c], errors="coerce")
        else:
            out[c] = out[c].astype(object).where(out[c].notna(), None)
    return out.reset_index(drop=True)


def tipizza_punti(df: pd.DataFrame) -> pd.DataFrame:
    return _tipizza(df, COLONNE_PUNTI, NUMERICHE_PUNTI, [])


def tipizza_impianti(df: pd.DataFrame) -> pd.DataFrame:
    return _tipizza(df, COLONNE_IMPIANTI, NUMERICHE_IMPIANTI, DATE_IMPIANTI)


def punti_vuoti() -> pd.DataFrame:
    return tipizza_punti(pd.DataFrame(columns=COLONNE_PUNTI))


def impianti_vuoti() -> pd.DataFrame:
    return tipizza_impianti(pd.DataFrame(columns=COLONNE_IMPIANTI))


def famiglie_tipo(n: int, inizio: int = 1, kwh: float | None = None) -> pd.DataFrame:
    """Righe per N famiglie con il consumo della famiglia tipo ARERA (o quello indicato)."""
    righe = [{"Punto": f"Famiglia {i}", "Membro": f"Famiglia {i}", "Tipo soggetto": "Persona fisica",
              "Tipologia consumo": "Famiglia", "kWh annui": kwh, "Tensione": "BT"} for i in range(inizio, inizio + n)]
    return tipizza_punti(pd.DataFrame(righe, columns=COLONNE_PUNTI))


def _slug(testo: str, usati: set[str]) -> str:
    base = unicodedata.normalize("NFKD", str(testo)).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")[:50] or "id"
    candidato, k = base, 2
    while candidato in usati:
        candidato, k = f"{base}_{k}", k + 1
    usati.add(candidato)
    return candidato


def _vuoto(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    try:
        return bool(pd.isna(v))  # NaN, NaT, pd.NA
    except (TypeError, ValueError):
        return False


def _numero(v) -> float | None:
    return None if _vuoto(v) else float(v)


def _testo(v) -> str | None:
    return None if _vuoto(v) else str(v).strip()


def _data(v) -> date | None:
    if _vuoto(v):
        return None
    return pd.Timestamp(v).date()


def _righe(df: pd.DataFrame) -> list[dict]:
    """Righe non completamente vuote."""
    return [r for r in df.to_dict("records") if not all(_vuoto(x) for x in r.values())]


def configurazione_da_tabelle(generale: Generale, punti: pd.DataFrame, impianti: pd.DataFrame,
                              base: Configuration | None = None,
                              curve: dict[str, CurvaMisurata] | None = None,
                              batterie: dict[str, BatteriaCasa] | None = None,
                              profili: dict[str, ProfiloPunto] | None = None) -> Esito:
    """Configurazione dalle tabelle. `base` è il lavoro ricaricato da JSON: le tabelle non mostrano
    tutti i campi, quindi identificativi e campi avanzati (scadenzari in più rate, produttore, decorrenze,
    POD, edificio, impianti fuori edificio…) si riprendono dalla base finché la riga non li contraddice.
    `curve`: le curve misurate per etichetta del contatore; dove c'è una curva, consumo annuo e fasce della tabella
    non si usano. Senza `curve` restano quelle della base. `batterie` e `profili` (dal profilo energetico della
    casa) seguono le curve: con `curve` valgono quelli indicati, senza restano quelli della base."""
    errori: list[str] = []
    gruppo = generale.tipo == TipoConfigurazione.GRUPPO.value
    righe_punti, righe_impianti = _righe(punti), _righe(impianti)
    if not righe_punti:
        return Esito(None, ["Aggiungi almeno un punto di prelievo"])
    base_membri = {m.nome: m for m in base.members} if base else {}
    base_punti = {c.id: c for c in base.connection_points} if base else {}
    base_impianti = {p.nome: p for p in base.plants} if base else {}
    edificio = (base.edificio_id_gruppo if base and base.edificio_id_gruppo else EDIFICIO_GRUPPO) if gruppo else None

    # --- membri -----------------------------------------------------------------
    nomi_tabella = {_testo(r.get("Membro")) for r in righe_punti}
    usati: set[str] = set(ID_RISERVATI)  # un membro chiamato "GSE" diventa "GSE_2"
    usati |= {m.id for nome, m in base_membri.items() if nome in nomi_tabella}
    membri: dict[str, Member] = {}
    tipo_di: dict[str, str] = {}
    for n, r in enumerate(righe_punti, 1):
        nome = _testo(r.get("Membro"))
        tipo = _testo(r.get("Tipo soggetto"))
        if not nome:
            errori.append(f"Riga {n} dei punti: manca il nome del membro")
            continue
        if tipo not in TIPI_SOGGETTO:
            errori.append(f"Riga {n} dei punti ({nome}): scegli il tipo di soggetto")
            continue
        if nome in tipo_di and tipo_di[nome] != tipo:
            errori.append(f"{nome} compare con tipi di soggetto diversi")
            continue
        tipo_di[nome] = tipo
        if nome not in membri:
            mid = base_membri[nome].id if nome in base_membri else _slug(nome, usati)
            membri[nome] = Member(id=mid, nome=nome, tipo_soggetto=TIPI_SOGGETTO[tipo])
    if base:  # membri senza contatore ma citati negli impianti (es. un produttore) restano
        citati = {base.referente} | {getattr(p, ruolo) for p in base.plants
                                     for ruolo in ("investitore", "proprietario", "produttore")}
        for m in base.members:
            if m.id in citati and m.nome not in membri and m.id not in usati:
                membri[m.nome] = m
                usati.add(m.id)
    ids_membri = {m.id for m in membri.values()} | {TERZO}

    # --- punti di prelievo ----------------------------------------------------------
    usati_punti: set[str] = {_testo(r.get("Punto")) for r in righe_punti} & set(base_punti)
    punto_id: dict[str, str] = {}
    cps: list[ConnectionPoint] = []
    for n, r in enumerate(righe_punti, 1):
        nome_membro = _testo(r.get("Membro"))
        if nome_membro not in membri:
            continue
        etichetta = _testo(r.get("Punto")) or f"Punto {n}"
        if etichetta in punto_id:
            errori.append(f"Il punto '{etichetta}' compare due volte: usa nomi diversi")
            continue
        tipologia = _testo(r.get("Tipologia consumo"))
        if tipologia not in TIPOLOGIE:
            errori.append(f"Punto '{etichetta}': scegli la tipologia di consumo")
            continue
        f1, f23 = _numero(r.get("F1 kWh")), _numero(r.get("F23 kWh"))
        fasce = None
        if (f1 is None) != (f23 is None):
            errori.append(f"Punto '{etichetta}': indica sia F1 sia F23, oppure nessuna delle due")
            continue
        prima = base_punti.get(etichetta)
        curva = curve.get(etichetta) if curve is not None else (prima.curva_misurata if prima else None)
        if curve is not None:
            batteria = (batterie or {}).get(etichetta) if curva else None
            profilo = (profili or {}).get(etichetta) if curva else None
        else:
            batteria, profilo = (prima.batteria, prima.profilo) if prima else (None, None)
        try:
            if f1 is not None and curva is None:
                fasce = Fasce(f1=f1, f23=f23)
                if prima and prima.fasce and _stesse_fasce(prima.fasce, fasce):
                    fasce = prima.fasce  # conserva F2 e F3 separate
            cid = etichetta if prima else _slug(etichetta, usati_punti)
            if gruppo:
                edificio_punto = prima.edificio_id if prima and prima.edificio_id else edificio
            else:
                edificio_punto = prima.edificio_id if prima else None
            cps.append(ConnectionPoint(
                id=cid,
                titolare=membri[nome_membro].id,
                tipologia_profilo=TIPOLOGIE[tipologia],
                kwh_annui=None if curva else _numero(r.get("kWh annui")),
                fasce=None if curva else fasce,
                curva_misurata=curva,
                batteria=batteria,
                profilo=profilo,
                tensione=Tensione(_testo(r.get("Tensione")) or "BT"),
                area_convenzionale=None if gruppo else _testo(r.get("Area convenzionale GSE")),
                edificio_id=edificio_punto,
                codice_pod=prima.codice_pod if prima else None,
                lat=prima.lat if prima else None,
                lon=prima.lon if prima else None,
            ))
            punto_id[etichetta] = cid
        except (ValidationError, ValueError) as e:
            errori.append(f"Punto '{etichetta}': {_messaggio(e)}")

    # --- impianti ------------------------------------------------------------------
    plants: list[Plant] = []
    nomi_impianti = {_testo(r.get("Impianto")) for r in righe_impianti}
    usati_impianti: set[str] = {p.id for nome, p in base_impianti.items() if nome in nomi_impianti}
    for n, r in enumerate(righe_impianti, 1):
        nome = _testo(r.get("Impianto")) or f"Impianto {n}"
        prima = base_impianti.get(nome)
        investitore_nome = _testo(r.get("Investitore"))
        if investitore_nome == INVESTITORE_ESTERNO:
            investitore = TERZO
        elif investitore_nome in membri:
            investitore = membri[investitore_nome].id
        else:
            errori.append(f"Impianto '{nome}': scegli chi paga l'impianto (investitore)")
            continue
        etichetta_punto = _testo(r.get("Punto"))
        if etichetta_punto == SOLA_IMMISSIONE:
            if investitore == TERZO:
                errori.append(f"Impianto '{nome}': un POD dedicato deve essere intestato a un membro; "
                              "scegli un membro come investitore o collega l'impianto a un punto esistente")
                continue
            pod_prima = base_punti.get(prima.connection_point) if prima else None
            if (pod_prima and pod_prima.ruolo is Ruolo.SOLA_IMMISSIONE and pod_prima.titolare in ids_membri
                    and pod_prima.id not in usati_punti):
                cps.append(pod_prima)
                cid = pod_prima.id
                usati_punti.add(cid)
            else:
                cid = _slug(f"{nome}_POD", usati_punti)
                cps.append(ConnectionPoint(id=cid, titolare=investitore, ruolo=Ruolo.SOLA_IMMISSIONE,
                                           edificio_id=edificio))
        elif etichetta_punto in punto_id:
            cid = punto_id[etichetta_punto]
        else:
            errori.append(f"Impianto '{nome}': scegli il punto di connessione")
            continue
        try:
            kwp = _numero(r.get("kWp moduli"))
            kw_ac = _numero(r.get("kW inverter")) or kwp
            entrata = _data(r.get("Entrata in esercizio"))
            if kwp is None or entrata is None:
                errori.append(f"Impianto '{nome}': indica kWp dei moduli e data di entrata in esercizio")
                continue
            avanzati = _avanzati(prima, entrata, ids_membri) if prima else {}
            # la colonna vuota vale "nessuna ombra", salvo perdite di sistema più basse del solito ricaricate da un file
            if not _vuoto(r.get("Ombre %")) or prima is None or prima.perdite_pct > PERDITE_SISTEMA_PCT:
                avanzati["perdite_pct"] = perdite_con_ombre(_numero(r.get("Ombre %")))
            plants.append(Plant(
                id=prima.id if prima else _slug(nome, usati_impianti),
                nome=nome,
                connection_point=cid,
                potenza_moduli_kwp=kwp,
                potenza_inverter_kw=kw_ac,
                potenza_moduli_max_kwp=_numero(r.get("kWp max installabili")),
                tilt=_numero(r.get("Inclinazione °")) if not _vuoto(r.get("Inclinazione °")) else 30.0,
                azimut=_numero(r.get("Orientamento °")) if not _vuoto(r.get("Orientamento °")) else 0.0,
                azimut_2=_numero(r.get("Seconda falda °")) if not _vuoto(r.get("Seconda falda °")) else None,
                investitore=investitore,
                data_entrata_esercizio=entrata,
                contributo_capitale=_contributo(r, prima.contributo_capitale if prima else None),
                costo_preventivo_eur=_numero(r.get("Costo da preventivo €")) or None,
                **avanzati,
            ))
        except (ValidationError, ValueError) as e:
            errori.append(f"Impianto '{nome}': {_messaggio(e)}")

    if errori:
        return Esito(None, errori)
    try:
        config = Configuration(
            nome=generale.nome or "Configurazione",
            tipo=TipoConfigurazione(generale.tipo),
            indirizzo=generale.indirizzo,
            lat=generale.lat,
            lon=generale.lon,
            regione=generale.regione,
            members=list(membri.values()),
            connection_points=cps,
            plants=plants,
            referente=base.referente if base and base.referente in ids_membri - {TERZO} else None,
            edificio_id_gruppo=edificio,
            data_costituzione=generale.data_costituzione,
        )
    except ValidationError as e:
        return Esito(None, [_messaggio(e)])
    return Esito(config, [])


def _stesse_fasce(prima: Fasce, tabella: Fasce) -> bool:
    f23 = prima.f23 if prima.f23 is not None else (prima.f2 or 0) + (prima.f3 or 0)
    return abs(prima.f1 - tabella.f1) < 1e-6 and abs(f23 - tabella.f23) < 1e-6


def _avanzati(prima: Plant, entrata: date, ids_membri: set[str]) -> dict:
    """Campi dell'impianto che le tabelle non mostrano, ripresi dal lavoro ricaricato se ancora coerenti."""
    out = {"nell_edificio": prima.nell_edificio, "perdite_pct": prima.perdite_pct}
    for ruolo in ("proprietario", "produttore"):
        if getattr(prima, ruolo) in ids_membri:
            out[ruolo] = getattr(prima, ruolo)
    for campo in ("data_inizio_periodo_incentivazione", "data_decorrenza_servizio_cacer", "data_decorrenza_vendita"):
        valore = getattr(prima, campo)
        if valore is not None and valore >= entrata:
            out[campo] = valore
    return out


def _contributo(r: dict, prima: CapitalGrant | None = None) -> CapitalGrant | None:
    importo = _numero(r.get("Contributo concesso €"))
    if not importo:
        return None
    incasso = _data(r.get("Data incasso contributo"))
    fattore_f = _numero(r.get("Fattore F"))
    estremi = _testo(r.get("Estremi atto")) or ""
    prima_data = prima.scadenzario_incassi[0].data if prima and prima.scadenzario_incassi else None
    if prima is not None and (prima.importo_eur, prima.fattore_F, prima.estremi_atto, prima_data) == (
            importo, fattore_f, estremi, incasso):
        return prima  # riga invariata: conserva scadenzario in più rate e intensità
    return CapitalGrant(
        importo_eur=importo,
        fattore_F=fattore_f,
        estremi_atto=estremi,
        scadenzario_incassi=[Incasso(data=incasso, importo_eur=importo)] if incasso else None,
    )


def _messaggio(e: Exception) -> str:
    if isinstance(e, ValidationError):
        parti = []
        for err in e.errors():
            testo = err.get("msg", "")
            testo = testo.removeprefix("Value error, ")
            campo = ".".join(str(x) for x in err.get("loc", ()) if not isinstance(x, int))
            parti.append(f"{campo}: {testo}" if campo else testo)
        return "; ".join(parti)
    return str(e)


def tabelle_da_configurazione(config: Configuration) -> tuple[Generale, pd.DataFrame, pd.DataFrame]:
    """Inverso di `configurazione_da_tabelle`, per ricaricare un lavoro salvato."""
    generale = Generale(nome=config.nome, tipo=config.tipo.value, lat=config.lat, lon=config.lon,
                        regione=config.regione_normalizzata, indirizzo=config.indirizzo,
                        data_costituzione=config.data_costituzione)
    nomi = {m.id: m.nome for m in config.members}
    tipo = {m.id: _ETICHETTA_SOGGETTO[m.tipo_soggetto] for m in config.members}
    etichetta_punto = {}
    righe = []
    for cp in config.connection_points:
        if cp.ruolo is Ruolo.SOLA_IMMISSIONE:
            etichetta_punto[cp.id] = SOLA_IMMISSIONE
            continue
        etichetta_punto[cp.id] = cp.id
        righe.append({
            "Punto": cp.id, "Membro": nomi[cp.titolare], "Tipo soggetto": tipo[cp.titolare],
            "Tipologia consumo": _ETICHETTA_TIPOLOGIA[cp.tipologia_profilo], "kWh annui": cp.kwh_effettivi if cp.curva_misurata else cp.kwh_annui,
            "F1 kWh": cp.fasce.f1 if cp.fasce else None,
            "F23 kWh": (cp.fasce.f23 if cp.fasce.f23 is not None else cp.fasce.f2 + cp.fasce.f3) if cp.fasce else None,
            "Area convenzionale GSE": cp.area_convenzionale, "Tensione": cp.tensione.value,
        })
    impianti = []
    for p in config.plants:
        g = p.contributo_capitale
        impianti.append({
            "Impianto": p.nome, "Punto": etichetta_punto[p.connection_point], "kWp moduli": p.potenza_moduli_kwp,
            "kW inverter": p.potenza_inverter_kw, "kWp max installabili": p.potenza_moduli_max_kwp,
            "Inclinazione °": p.tilt, "Orientamento °": p.azimut, "Seconda falda °": p.azimut_2,
            "Ombre %": ombre_da_perdite(p.perdite_pct),
            "Entrata in esercizio": p.data_entrata_esercizio,
            "Investitore": INVESTITORE_ESTERNO if p.investitore == TERZO else nomi[p.investitore],
            "Costo da preventivo €": p.costo_preventivo_eur,
            "Contributo concesso €": g.importo_eur if g else None, "Fattore F": g.fattore_F if g else None,
            "Estremi atto": g.estremi_atto if g else None,
            "Data incasso contributo": g.scadenzario_incassi[0].data if g and g.scadenzario_incassi else None,
        })
    return (generale, tipizza_punti(pd.DataFrame(righe, columns=COLONNE_PUNTI)),
            tipizza_impianti(pd.DataFrame(impianti, columns=COLONNE_IMPIANTI)))


def esporta_json(config: Configuration, parametri: dict) -> str:
    dati = config.model_dump(mode="json")
    for cp in dati["connection_points"]:  # campi del profilo energetico: assenti se vuoti, come nei file di prima
        for campo in ("batteria", "profilo"):
            if cp.get(campo) is None:
                cp.pop(campo, None)
    return json.dumps({"schema": VERSIONE_SCHEMA, "configurazione": dati, "parametri": parametri},
                      ensure_ascii=False, indent=2)


# stessi limiti dei campi del passo Economia
LIMITI_PARAMETRI = {"quota_membri": ("quota ai membri", 0, 1), "costo_evitabile_eur_kwh": ("costo evitabile", 0, 1),
                    "tasso_sconto": ("tasso di sconto", 0, 0.2), "om_assicurazione_quota_anno": ("quota O&M", 0, 0.1),
                    "gestione_eur_anno": ("gestione", 0, 100_000), "costituzione_eur": ("costituzione", 0, 100_000)}
REGIMI_VENDITA = ("RID", "mercato")


def _controlla_parametri(parametri: dict) -> None:
    for chiave, (nome, minimo, massimo) in LIMITI_PARAMETRI.items():
        valore = parametri.get(chiave)
        if valore is None:
            continue
        if isinstance(valore, bool) or not isinstance(valore, int | float) or not minimo <= valore <= massimo:
            raise ValueError(f"Parametro non valido: {nome} deve essere un numero tra {minimo} e {massimo:g}")
    if parametri.get("regime_vendita") not in (None, *REGIMI_VENDITA):
        raise ValueError(f"Parametro non valido: regime di vendita sconosciuto, ammessi {' e '.join(REGIMI_VENDITA)}")


def importa_json(dati: str | bytes) -> tuple[Configuration, dict]:
    """Ricarica un lavoro salvato. Solleva ValueError con un messaggio leggibile."""
    if len(dati) > MAX_JSON_BYTE:
        raise ValueError("File troppo grande")
    try:
        contenuto = json.loads(dati)
    except json.JSONDecodeError as e:
        raise ValueError(f"Il file non è un JSON valido ({e.msg})") from None
    if not isinstance(contenuto, dict) or contenuto.get("schema") != VERSIONE_SCHEMA:
        raise ValueError("File non riconosciuto: non è un salvataggio di cersim compatibile")
    try:
        config = Configuration.model_validate(contenuto.get("configurazione"))
    except ValidationError as e:
        raise ValueError("Configurazione non valida: " + _messaggio(e)) from None
    parametri = contenuto.get("parametri") or {}
    if not isinstance(parametri, dict):
        raise ValueError("Parametri non validi")
    _controlla_parametri(parametri)
    ammessi = {"quota_membri", "costo_evitabile_eur_kwh", "tasso_sconto", "regime_vendita",
               "om_assicurazione_quota_anno", "gestione_eur_anno", "costituzione_eur"}
    return config, {k: v for k, v in parametri.items() if k in ammessi}
