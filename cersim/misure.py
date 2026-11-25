"""Consumi misurati: i file del Portale Consumi e di e-distribuzione, ridotti a una forma media per la simulazione.

Formati letti, da export reali descritti in fonti pubbliche (vedi docs/consumi_misurati.md):

- **Portale Consumi** (ARERA e Acquirente Unico, `letture.csv`, pulsante *Scarica letture*): intestazione
  `pod;data_lettura;data_ricezione;motivazione;lettura_monoraria;lettura_f1;…;tipo_flusso;annomese_riferimento;
  ea1;…;ea96`, una riga per giorno, kWh per quarto d'ora con il punto decimale. Copre fino a cinque anni, a volte
  con giorni mancanti. Contiene il POD: il lettore lo scarta subito e non lo restituisce.
- **e-distribuzione, sito** (`ExportData_<mese>.csv`, un mese per file): intestazione
  `Giorno;00:00-00:15;…;23:45-00:00`, righe `"GG/MM/AAAA";"0,359";…;` con virgolette e virgola decimale.
- **e-distribuzione, app** (`FORNUTA<POD>.csv`, per email): stessa intestazione, data `GG/MM/AAAA 00:00`,
  valori senza virgolette.

Le colonne sono in ora civile. Giorni del cambio d'ora, dagli export reali di e-distribuzione: a marzo una riga con
le colonne 02:00-03:00 a zero (quell'ora non esiste); a ottobre due righe con la stessa data, la prima con
00:00-03:00 in ora legale, la seconda dalle 02:00 in ora solare. Per il Portale Consumi il cambio d'ora non è
documentato: si applica la stessa regola e, con una sola riga, l'ora ripetuta di ottobre si legge una volta.

`curva_misurata` riduce le letture a kWh medi per tipo di giorno, mese e ora (`model.CurvaMisurata`): così la
curva vale per ogni anno di progetto, anche con mesi mancanti. Tiene anche pochi giorni veri, senza data, scelti per
ogni tipo di giorno e mese dal meno al più consumato: la simulazione li pesca, perché la sola media sovrastima la
condivisione. Non porta con sé date, POD e il resto delle letture.
"""

import csv
import io
import re
import warnings
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from cersim.model import CELLE_CURVA, GIORNI_PER_CELLA, TIPI_GIORNO, CurvaMisurata
from cersim.timebase import TZ, calendario_np, local_frame

QUARTI = 96
MAX_BYTE = 10_000_000
MIN_GIORNI = 28  # meno di quattro settimane non dicono abbastanza sulla forma dei consumi
ANNO_RIFERIMENTO = 2023  # calendario su cui si stima il consumo annuo dalla forma media
_ORA_CAMBIO = range(8, 12)  # colonne 02:00-02:45: inesistenti a marzo, doppie a ottobre
_COLONNA = re.compile(r"^\d{2}:\d{2}-\d{2}:\d{2}$")
_DATA = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?: \d{2}:\d{2}(?::\d{2})?)?$")
_DATA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


@dataclass
class Letture:
    """kWh per quarto d'ora, con indice UTC sull'inizio del quarto d'ora."""

    quarti: pd.Series
    fonte: str
    avvisi: list[str] = field(default_factory=list)


def _testo(contenuto: bytes) -> str:
    if len(contenuto) > MAX_BYTE:
        raise ValueError(f"Il file supera {MAX_BYTE // 1_000_000} MB: non sembra un file di consumi")
    try:
        return contenuto.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenuto.decode("cp1252")  # file aperti e risalvati con Excel


def _data(cella: str) -> date:
    cella = cella.strip().strip('"')
    if m := _DATA.match(cella):
        gg, mm, aaaa = (int(x) for x in m.groups())
        return date(aaaa, mm, gg)
    if m := _DATA_ISO.match(cella):
        aaaa, mm, gg = (int(x) for x in m.groups())
        return date(aaaa, mm, gg)
    raise ValueError(f"data non riconosciuta ({cella!r})")


def _numero(cella: str) -> float | None:
    cella = cella.strip().strip('"').strip()
    if not cella:
        return None
    if "," in cella:  # virgola decimale, eventuali punti delle migliaia
        cella = cella.replace(".", "").replace(",", ".")
    valore = float(cella)
    if valore < 0 or valore != valore:
        raise ValueError(f"valore non valido ({cella!r})")
    return valore


def _quarti_reali(giorno: date) -> int:
    inizio = datetime(giorno.year, giorno.month, giorno.day, tzinfo=TZ)
    domani = giorno + timedelta(days=1)
    fine = datetime(domani.year, domani.month, domani.day, tzinfo=TZ)
    return int((fine.astimezone(UTC) - inizio.astimezone(UTC)) / timedelta(minutes=15))


def _istante(giorno: date, colonna: int, fold: int = 0) -> datetime:
    ora, minuti = divmod(colonna * 15, 60)
    return datetime(giorno.year, giorno.month, giorno.day, ora, minuti, tzinfo=TZ, fold=fold).astimezone(UTC)


def _quarti_del_giorno(giorno: date, righe: list[list[float | None]], avvisi: list[str]) -> list[tuple[datetime, float]]:
    """(inizio in UTC, kWh) dei quarti d'ora di un giorno, con le regole del cambio d'ora del modulo."""
    out: list[tuple[datetime, float]] = []

    def aggiungi(valori, colonne, fold=0):
        out.extend((_istante(giorno, c, fold), valori[c]) for c in colonne if valori[c] is not None)

    quarti = _quarti_reali(giorno)
    if quarti == QUARTI or len(righe) > 2:
        if len(righe) > 1:
            avvisi.append(f"{giorno:%d/%m/%Y}: {len(righe)} righe, usata l'ultima")
        aggiungi(righe[-1], range(QUARTI))
    elif quarti < QUARTI:  # marzo: le 02:00-03:00 non esistono
        aggiungi(righe[-1], [c for c in range(QUARTI) if c not in _ORA_CAMBIO])
    elif len(righe) == 1:  # ottobre con una sola riga: l'ora ripetuta si legge una volta
        avvisi.append(f"{giorno:%d/%m/%Y}: ritorno all'ora solare in una sola riga, un'ora letta una volta")
        aggiungi(righe[0], range(QUARTI))
    else:  # ottobre: prima riga in ora legale fino alle 03:00, seconda in ora solare dalle 02:00
        legale, solare = righe
        aggiungi(legale, range(12))
        aggiungi(solare, _ORA_CAMBIO, fold=1)
        aggiungi(solare, range(12, QUARTI))
    return out


def _serie(per_giorno: dict[date, list[list[float | None]]], fonte: str, avvisi: list[str]) -> Letture:
    quarti: dict[datetime, float] = {}
    for giorno in sorted(per_giorno):
        quarti.update(_quarti_del_giorno(giorno, per_giorno[giorno], avvisi))
    if not quarti:
        raise ValueError("Nel file non ci sono consumi da leggere")
    serie = pd.Series(quarti, dtype=float).sort_index()
    serie.index = pd.DatetimeIndex(serie.index).tz_convert("UTC")
    return Letture(serie, fonte, avvisi)


def _valori(celle: list[str], giorno: date, avvisi: list[str]) -> list[float | None]:
    valori: list[float | None] = []
    for cella in (celle + [""] * QUARTI)[:QUARTI]:
        try:
            valori.append(_numero(cella))
        except ValueError:
            avvisi.append(f"{giorno:%d/%m/%Y}: valore ignorato ({cella.strip()!r})")
            valori.append(None)
    return valori


def _e_distribuzione(righe: list[list[str]]) -> Letture:
    avvisi: list[str] = []
    per_giorno: dict[date, list[list[float | None]]] = {}
    app = False
    for numero, riga in enumerate(righe[1:], start=2):
        if not riga or not riga[0].strip():
            continue
        try:
            giorno = _data(riga[0])
        except ValueError as e:
            raise ValueError(f"Riga {numero}: {e}") from None
        app = app or " " in riga[0].strip().strip('"')
        per_giorno.setdefault(giorno, []).append(_valori(riga[1:], giorno, avvisi))
    return _serie(per_giorno, "e-distribuzione, app" if app else "e-distribuzione, sito", avvisi)


def _portale(righe: list[list[str]]) -> Letture:
    intestazione = [c.strip().lower() for c in righe[0]]
    try:
        i_data = intestazione.index("data_lettura")
        i_ea = intestazione.index("ea1")
    except ValueError:
        raise ValueError("Intestazione del Portale Consumi incompleta: mancano data_lettura o ea1") from None
    i_motivo = intestazione.index("motivazione") if "motivazione" in intestazione else None
    avvisi: list[str] = []
    righe_giorno: dict[date, list[tuple[bool, list[float | None]]]] = {}
    for numero, riga in enumerate(righe[1:], start=2):
        if len(riga) <= i_data or not riga[i_data].strip():
            continue
        try:
            giorno = _data(riga[i_data])
        except ValueError as e:
            raise ValueError(f"Riga {numero}: {e}") from None
        sostitutiva = i_motivo is not None and "sost" in riga[i_motivo].lower()
        righe_giorno.setdefault(giorno, []).append((sostitutiva, _valori(riga[i_ea:i_ea + QUARTI], giorno, avvisi)))
    per_giorno = {}
    for giorno, voci in righe_giorno.items():
        sostitutive = [v for s, v in voci if s]
        if sostitutive:  # una lettura che ne corregge un'altra vale da sola
            per_giorno[giorno] = sostitutive[-1:]
        elif _quarti_reali(giorno) > QUARTI and len(voci) == 2:  # ottobre su due righe, come e-distribuzione
            per_giorno[giorno] = [v for _, v in voci]
        else:
            per_giorno[giorno] = [voci[-1][1]]
    return _serie(per_giorno, "Portale Consumi", avvisi)


def leggi_file(contenuto: bytes) -> Letture:
    """Letture di un file del Portale Consumi o di e-distribuzione. Solleva ValueError con un messaggio leggibile se
    il formato non è riconosciuto. Il POD, se c'è, non viene letto."""
    righe = [r for r in csv.reader(io.StringIO(_testo(contenuto)), delimiter=";") if any(c.strip() for c in r)]
    if len(righe) < 2:
        raise ValueError("Il file è vuoto o ha solo l'intestazione")
    intestazione = [c.strip().strip('"').lower() for c in righe[0]]
    if intestazione[0] == "pod" and "data_lettura" in intestazione:
        return _portale(righe)
    colonne = [c for c in intestazione[1:QUARTI + 1]]
    if intestazione[0] == "giorno" and len(colonne) == QUARTI and colonne[0] == "00:00-00:15" and all(
            _COLONNA.match(c) for c in colonne):
        return _e_distribuzione(righe)
    raise ValueError("Formato non riconosciuto: servono il file letture.csv del Portale Consumi oppure la curva di "
                     "carico a quarti d'ora di e-distribuzione (colonne Giorno;00:00-00:15;…)")


def unisci(letture: list[Letture]) -> Letture:
    """Più file dello stesso contatore (per esempio un mese per file): i quarti d'ora ripetuti valgono una volta,
    quelli del file caricato dopo prevalgono."""
    if not letture:
        raise ValueError("Nessun file da unire")
    serie = pd.concat([l.quarti for l in letture])
    serie = serie[~serie.index.duplicated(keep="last")].sort_index()
    fonti = list(dict.fromkeys(l.fonte for l in letture))
    return Letture(serie, ", ".join(fonti), [a for l in letture for a in l.avvisi])


def curva_misurata(letture: Letture, *, min_giorni: int = MIN_GIORNI) -> CurvaMisurata:
    """Forma media dei consumi: kWh medi per tipo di giorno, mese e ora civile.

    Le ore con quarti d'ora mancanti si completano in proporzione; i mesi senza misure prendono la media degli altri
    mesi dello stesso tipo di giorno. Il consumo annuo è la forma media sul calendario del 2023."""
    q = letture.quarti
    per_ora = q.groupby(q.index.floor("h"))
    orarie = per_ora.sum() * 4 / per_ora.count()
    giorni = orarie.index.tz_convert(TZ).normalize().unique()
    if len(giorni) < min_giorni:
        raise ValueError(f"Servono almeno {min_giorni} giorni di misure: il file ne ha {len(giorni)}")

    cal = local_frame(pd.DatetimeIndex(orarie.index))
    medie = pd.DataFrame({"tipo": cal["day_type"].to_numpy(), "mese": cal["month"].to_numpy(),
                          "ora": cal["hour"].to_numpy(), "kwh": orarie.to_numpy()}
                         ).groupby(["tipo", "mese", "ora"])["kwh"].mean()
    forma = np.full((len(TIPI_GIORNO), 12, 24), np.nan)
    for (tipo, mese, ora), valore in medie.items():
        forma[TIPI_GIORNO.index(tipo), mese - 1, ora] = valore
    with warnings.catch_warnings():  # medie di celle tutte vuote: restano NaN e si completano dopo
        warnings.simplefilter("ignore", RuntimeWarning)
        for t in range(len(TIPI_GIORNO)):
            if np.isnan(forma[t]).all():  # nessun giorno di questo tipo: si usa la media degli altri tipi
                forma[t] = np.nanmean(forma, axis=0)
            media_ore = np.nanmean(forma[t], axis=0)  # media sui mesi disponibili, ora per ora
            forma[t] = np.where(np.isnan(forma[t]), media_ore, forma[t])
        forma = np.where(np.isnan(forma), np.nanmean(forma), forma)

    return CurvaMisurata(ore=tuple(round(float(v), 5) for v in forma.reshape(CELLE_CURVA)), giorni=len(giorni),
                         dal=giorni[0].date(), al=giorni[-1].date(), kwh_annui=round(kwh_anno_riferimento(forma), 1),
                         fonte=letture.fonte[:80], giorni_veri=_giorni_veri(orarie, cal))


def _giorni_veri(orarie: pd.Series, cal: pd.DataFrame) -> tuple[tuple[int, tuple[float, ...]], ...]:
    """Fino a `GIORNI_PER_CELLA` giorni completi per tipo di giorno e mese, distribuiti dal meno al più consumato."""
    tabella = pd.DataFrame({"giorno": orarie.index.tz_convert(TZ).tz_localize(None).normalize(), "tipo": cal["day_type"].to_numpy(),
                            "mese": cal["month"].to_numpy(), "ora": cal["hour"].to_numpy(), "kwh": orarie.to_numpy()})
    celle: dict[int, list[np.ndarray]] = {}
    for (_, tipo, mese), g in tabella.groupby(["giorno", "tipo", "mese"]):
        if len(g) == 24 and g["ora"].nunique() == 24:  # niente giorni parziali né cambi d'ora
            celle.setdefault(TIPI_GIORNO.index(tipo) * 12 + int(mese) - 1, []).append(g.sort_values("ora")["kwh"].to_numpy())
    out = []
    for cella in sorted(celle):
        ordinati = sorted(celle[cella], key=lambda v: v.sum())
        n = min(GIORNI_PER_CELLA, len(ordinati))
        for i in range(n):
            scelto = ordinati[round(i * (len(ordinati) - 1) / max(n - 1, 1))]
            out.append((cella, tuple(round(float(v), 3) for v in scelto)))
    return tuple(out)


def kwh_anno_riferimento(forma) -> float:
    """Consumo annuo di una forma media (3 × 12 × 24, o le sue 864 celle) sul calendario di `ANNO_RIFERIMENTO`."""
    forma = np.asarray(forma, dtype=float).reshape(len(TIPI_GIORNO), 12, 24)
    rif = calendario_np(ANNO_RIFERIMENTO)
    tipo_idx = np.select([rif["day_type"] == t for t in TIPI_GIORNO], range(len(TIPI_GIORNO)))
    return float(forma[tipo_idx, rif["month"] - 1, rif["hour"]].sum())


def curva_da_file(contenuti: list[bytes]) -> tuple[CurvaMisurata, list[str]]:
    """Curva di un contatore da uno o più file (per esempio i mesi di e-distribuzione), con gli avvisi di lettura."""
    letture = unisci([leggi_file(c) for c in contenuti])
    curva = curva_misurata(letture)
    avvisi = list(letture.avvisi)
    if curva.kwh_annui == 0:
        avvisi.append("Il file ha tutti i consumi a zero: controlla che sia il contatore giusto. "
                      "Nel calcolo questo contatore non consuma.")
    return curva, avvisi


def descrivi(curva: CurvaMisurata) -> str:
    kwh = f"{curva.kwh_annui:,.0f}".replace(",", ".")
    if not curva.misurata:
        return f"consumi calcolati, non misurati, circa {kwh} kWh all'anno ({curva.fonte})"
    return (f"dal {curva.dal:%d/%m/%Y} al {curva.al:%d/%m/%Y}, {curva.giorni} giorni con misure, circa {kwh} kWh "
            f"all'anno ({curva.fonte})")
