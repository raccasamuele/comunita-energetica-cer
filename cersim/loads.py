"""Profili orari di consumo sintetici per tipologia, tarati su consumo annuo e fasce.

Le forme giornaliere (feriale / sabato / festivo) e i fattori mensili sono
IPOTESI del modello, non dati misurati: in Italia non esiste un dataset orario
aperto per le utenze domestiche. Sono la principale fonte di incertezza
dell'energia condivisa; per questo esistono le varianti (`VARIANTI`) usate
per la banda di scenari. Le curve reali dei membri arriveranno nella v2.

Tutto è in ora civile Europe/Rome: chi è a casa alle 20 lo è d'inverno e d'estate.
"""

import zlib
from functools import lru_cache

import numpy as np
import pandas as pd

from cersim.model import CELLE_GIORNI_VERI, GIORNI_PER_CELLA, TIPI_GIORNO, ConnectionPoint, Ruolo, Tipologia
from cersim.timebase import TZ, calendario_np, frame_per, year_index

_FORME: dict[Tipologia, dict[str, list[float]]] = {
    Tipologia.DOMESTICO: {
        "feriale": [0.45, 0.38, 0.35, 0.33, 0.33, 0.36, 0.50, 0.80, 0.85, 0.70, 0.62, 0.62,
                    0.75, 0.78, 0.65, 0.58, 0.60, 0.75, 0.95, 1.20, 1.40, 1.35, 1.10, 0.75],
        "sabato": [0.50, 0.42, 0.37, 0.34, 0.33, 0.34, 0.40, 0.55, 0.75, 0.90, 0.95, 0.95,
                   1.00, 1.00, 0.85, 0.75, 0.75, 0.85, 1.00, 1.20, 1.35, 1.30, 1.10, 0.80],
        "festivo": [0.55, 0.45, 0.38, 0.35, 0.33, 0.33, 0.36, 0.45, 0.65, 0.85, 1.00, 1.05,
                    1.20, 1.15, 0.90, 0.78, 0.78, 0.85, 1.00, 1.20, 1.30, 1.25, 1.05, 0.78],
        "mensile": [1.15, 1.08, 1.00, 0.92, 0.88, 0.92, 1.05, 0.98, 0.90, 0.95, 1.05, 1.17],
    },
    Tipologia.UFFICIO_COMMERCIALE: {
        "feriale": [0.25] * 7 + [0.45, 0.80, 1.00, 1.00, 1.00, 0.95, 0.90, 0.95, 1.00, 1.00, 1.00,
                                 0.95, 0.70, 0.45, 0.30, 0.25, 0.25],
        "sabato": [0.25] * 8 + [0.50, 0.75] + [0.80] * 8 + [0.70, 0.50, 0.35] + [0.25] * 3,
        "festivo": [0.25] * 24,
        "mensile": [1.00, 0.97, 0.95, 0.92, 0.95, 1.08, 1.18, 0.88, 1.00, 0.95, 0.97, 1.05],
    },
    Tipologia.SCUOLA: {
        "feriale": [0.15] * 7 + [0.35, 0.90, 1.00, 1.00, 1.00, 1.00, 0.85, 0.55, 0.50, 0.45, 0.35, 0.25]
        + [0.15] * 5,
        "sabato": [0.15] * 8 + [0.40] + [0.45] * 4 + [0.30] + [0.15] * 10,
        "festivo": [0.15] * 24,
        "mensile": [1.10, 1.05, 1.00, 0.95, 0.95, 0.70, 0.30, 0.15, 0.85, 1.00, 1.05, 0.95],
    },
    Tipologia.PA_MUNICIPIO: {
        "feriale": [0.30] * 7 + [0.50, 0.90] + [1.00] * 4 + [0.85, 0.75, 0.80, 0.80, 0.70, 0.50, 0.40]
        + [0.30] * 4,
        "sabato": [0.30] * 8 + [0.45] * 5 + [0.30] * 11,
        "festivo": [0.30] * 24,
        "mensile": [1.08, 1.03, 0.98, 0.93, 0.93, 1.00, 1.05, 0.85, 0.98, 0.97, 1.05, 1.12],
    },
    Tipologia.PMI: {
        "feriale": [0.30] * 6 + [0.50, 0.85] + [1.00] * 4 + [0.80] + [1.00] * 4 + [0.85, 0.55, 0.40]
        + [0.30] * 4,
        "sabato": [0.30] * 7 + [0.55] * 6 + [0.30] * 11,
        "festivo": [0.28] * 24,
        "mensile": [0.98, 1.00, 1.02, 1.00, 1.03, 1.05, 1.05, 0.60, 1.02, 1.03, 1.02, 0.90],
    },
}

for _t, _f in _FORME.items():
    assert all(len(_f[k]) == 24 for k in ("feriale", "sabato", "festivo")) and len(_f["mensile"]) == 12, _t


# variante → (nome, fattore sui consumi tra le 8 e le 19, spostamento della forma in ore). IPOTESI del modello:
# servono a mostrare quanto il risultato dipende da quando si consuma, non a descrivere famiglie reali.
VARIANTI = {
    1: ("più consumi di giorno", 1.3, 0),
    2: ("più consumi la sera", 0.8, 1),
}


def nome_variante(variante: int) -> str:
    return "consumi tipici" if variante == 0 else VARIANTI[variante][0]


GIORNI_PER_A = 330  # circa undici mesi di misure: la forma copre tutte le stagioni
QUOTA_MISURATA_PER_A = 0.75  # parte dei consumi che deve venire da curve misurate per la qualità A


def qualita_consumi(cp: ConnectionPoint) -> str:
    """'A' con una curva misurata di quasi un anno; 'B' con una curva più corta, con una curva calcolata (per esempio
    dal simulatore della casa: è una stima, non una misura) o con consumo annuo e fasce dalla bolletta; altrimenti
    'C'."""
    if cp.ruolo is Ruolo.SOLA_IMMISSIONE:
        return "B"
    if (curva := cp.curva_misurata) is not None:
        return "A" if curva.misurata and curva.giorni >= GIORNI_PER_A else "B"
    return "B" if (not cp.kwh_da_default and cp.fasce is not None) else "C"


def quota_misurata(cps) -> float:
    """Parte dei consumi della configurazione che viene da curve misurate di qualità A."""
    consumano = [c for c in cps if c.ruolo is not Ruolo.SOLA_IMMISSIONE]
    totale = sum(c.kwh_effettivi for c in consumano)
    misurati = sum(c.kwh_effettivi for c in consumano if qualita_consumi(c) == "A")
    return misurati / totale if totale else 0.0


def qualita_insieme(cps, qualita_pv: list[str], qualita_prezzi: list[str]) -> str:
    """Qualità dei risultati. Basta un dato tipico per scendere a 'C'. Produzione da PVGIS e prezzi orari reali sono
    il meglio che si può avere per un impianto nuovo, quindi non limitano: decidono i consumi. 'A' se almeno tre
    quarti dei consumi vengono da curve misurate di quasi un anno e il resto è almeno da bolletta."""
    consumi = [qualita_consumi(c) for c in cps]
    if "C" in consumi + list(qualita_pv) + list(qualita_prezzi):
        return "C"
    return "A" if quota_misurata(cps) >= QUOTA_MISURATA_PER_A else "B"


def load_profile(cp: ConnectionPoint, index_utc: pd.DatetimeIndex, variante: int = 0) -> np.ndarray:
    """Consumo orario (kWh) del punto sull'anno di `index_utc`.

    `variante = 0` è la forma base; le varianti di `VARIANTI` spostano i consumi
    verso il giorno o verso la sera per TUTTI i punti insieme (è un'incertezza comune,
    non si compensa tra i membri) e aggiungono un rumore giornaliero diverso per punto.
    Consumo annuo e fasce restano quelli della bolletta.
    """
    if cp.ruolo is Ruolo.SOLA_IMMISSIONE:
        return np.zeros(len(index_utc))

    cal = _colonne(index_utc)
    if cp.curva_misurata is not None:  # ora e quantità note (misurate o calcolate): le varianti non si applicano
        curva = np.asarray(cp.curva_misurata.ore).reshape(len(TIPI_GIORNO), 12, 24)
        tipo = np.select([cal["day_type"] == t for t in TIPI_GIORNO], range(len(TIPI_GIORNO)))
        raw = curva[tipo, cal["month"] - 1, cal["hour"]]
        if cp.curva_misurata.giorni_veri:
            raw = _pesca_giorni(cp, raw, tipo * 12 + cal["month"] - 1, cal, index_utc)
        return _tara(raw, cal["fascia"], cp)
    raw = _forma_base(cp.tipologia_profilo, index_utc, cal, variante)
    if variante:
        fattore_giorno, rumore_ora = _rumore(cp.id, variante, int(cal["day"].max()) + 1, len(index_utc))
        raw = raw * (fattore_giorno[cal["day"]] * rumore_ora)
    return _tara(raw, cal["fascia"], cp)


def _forma_base(tipologia: str, index_utc: pd.DatetimeIndex, cal: dict[str, np.ndarray], variante: int) -> np.ndarray:
    """Forma oraria della tipologia (prima del rumore e della taratura sulla bolletta): uguale per tutti i contatori
    della stessa tipologia, quindi per un anno intero si calcola una volta sola (`_forma_base_anno`)."""
    if len(index_utc):
        year = int(index_utc[0].tz_convert(TZ).year)
        full = year_index(year)
        if len(index_utc) == len(full) and index_utc[0] == full[0]:
            return _forma_base_anno(tipologia, year, variante)
    return _calcola_forma(tipologia, cal, variante)


@lru_cache(maxsize=256)
def _forma_base_anno(tipologia: str, year: int, variante: int) -> np.ndarray:
    forma = _calcola_forma(tipologia, calendario_np(year), variante)
    forma.setflags(write=False)
    return forma


def _calcola_forma(tipologia: str, cal: dict[str, np.ndarray], variante: int) -> np.ndarray:
    forma = _FORME[tipologia]
    giornaliere = {k: np.asarray(forma[k], dtype=float) for k in ("feriale", "sabato", "festivo")}
    mensile = np.asarray(forma["mensile"], dtype=float)
    if variante:
        if variante not in VARIANTI:
            raise ValueError(f"Variante dei consumi sconosciuta: {variante}")
        _, fattore_giorno, spostamento = VARIANTI[variante]
        ore_di_sole = np.zeros(24, dtype=bool)
        ore_di_sole[8:19] = True
        for k, v in giornaliere.items():
            v = np.roll(v, spostamento)
            giornaliere[k] = np.where(ore_di_sole, v * fattore_giorno, v)
    hour = cal["hour"]
    raw = np.empty(len(hour))
    for tipo_giorno, forma_giorno in giornaliere.items():
        sel = cal["day_type"] == tipo_giorno
        raw[sel] = forma_giorno[hour[sel]]
    raw *= mensile[cal["month"] - 1]
    return raw


@lru_cache(maxsize=2048)  # ~70 kB per voce: con 200 contatori e 2 varianti ~30 MB
def _rumore(punto: str, variante: int, n_giorni: int, n_ore: int) -> tuple[np.ndarray, np.ndarray]:
    """Rumore giornaliero correlato (AR(1)) e orario del contatore: dipende solo dal contatore, dalla variante e dalla
    lunghezza dell'anno, quindi è lo stesso in tutti gli anni di 365 (o 366) giorni e si calcola una volta sola."""
    rng = np.random.default_rng(zlib.crc32(f"{punto}|{variante}".encode()))
    fattore_giorno = np.empty(n_giorni)
    x = 0.0
    for g in range(n_giorni):
        x = 0.7 * x + rng.normal(0.0, 0.1)
        fattore_giorno[g] = np.exp(x)
    rumore_ora = np.exp(rng.normal(0.0, 0.05, n_ore))
    fattore_giorno.setflags(write=False)
    rumore_ora.setflags(write=False)
    return fattore_giorno, rumore_ora


def _pesca_giorni(cp: ConnectionPoint, media: np.ndarray, celle: np.ndarray, cal: dict[str, np.ndarray],
                  index_utc: pd.DatetimeIndex) -> np.ndarray:
    """Ogni giorno prende uno dei giorni veri del suo tipo e mese, sempre lo stesso a parità di contatore e anno. I
    totali di ogni tipo di giorno e mese restano quelli della media; dove non ci sono giorni veri resta la media."""
    giorni = np.zeros((CELLE_GIORNI_VERI, GIORNI_PER_CELLA, 24))
    quanti = np.zeros(CELLE_GIORNI_VERI, dtype=int)
    for cella, valori in cp.curva_misurata.giorni_veri:
        giorni[cella, quanti[cella]] = valori
        quanti[cella] += 1
    anno = int(index_utc[0].tz_convert(TZ).year)
    caso = np.random.default_rng(zlib.crc32(f"{cp.id}|{anno}".encode())).random(int(cal["day"].max()) + 1)
    scelta = (caso[cal["day"]] * quanti[celle]).astype(int)
    pescati = giorni[celle, np.minimum(scelta, GIORNI_PER_CELLA - 1), cal["hour"]]
    somma_media = np.bincount(celle, media, CELLE_GIORNI_VERI)
    somma_pescati = np.bincount(celle, pescati, CELLE_GIORNI_VERI)
    utili = (quanti > 0) & (somma_pescati > 0)
    fattore = np.divide(somma_media, somma_pescati, out=np.zeros(CELLE_GIORNI_VERI), where=utili)
    return np.where(utili[celle], pescati * fattore[celle], media)


def _colonne(index_utc: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Colonne del calendario come array numpy (dalla cache se l'indice è un anno intero)."""
    if len(index_utc):
        year = int(index_utc[0].tz_convert(TZ).year)
        full = year_index(year)
        if len(index_utc) == len(full) and index_utc[0] == full[0]:
            return calendario_np(year)
    cal = frame_per(index_utc)
    return {c: np.asarray(cal[c].to_numpy(dtype=str if c in ("day_type", "fascia") else None)) for c in cal.columns}


@lru_cache(maxsize=1024)  # ~70 kB per profilo: al massimo ~70 MB
def load_profile_anno(cp: ConnectionPoint, year: int, variante: int = 0) -> np.ndarray:
    """Come `load_profile` sull'anno intero, calcolato una volta sola (array in sola lettura)."""
    profilo = load_profile(cp, year_index(year), variante)
    profilo.setflags(write=False)
    return profilo


def _tara(raw: np.ndarray, fascia: np.ndarray, cp: ConnectionPoint) -> np.ndarray:
    totale = cp.kwh_effettivi
    if cp.fasce is None:
        return np.zeros_like(raw) if totale == 0 else raw * (totale / raw.sum())  # un contatore può non consumare
    f = cp.fasce
    gruppi = [(fascia == "F1", f.f1)]
    if f.f23 is not None:
        gruppi.append(((fascia == "F2") | (fascia == "F3"), f.f23))
    else:
        gruppi += [(fascia == "F2", f.f2), (fascia == "F3", f.f3)]
    out = np.zeros_like(raw)
    for sel, kwh_fascia in gruppi:
        kwh_sel = kwh_fascia / f.totale * totale if f.totale else 0.0
        somma = raw[sel].sum()
        # forma a zero in una fascia con consumi: si distribuisce in parti uguali, così il totale della bolletta resta
        out[sel] = raw[sel] * (kwh_sel / somma) if somma > 0 else kwh_sel / max(int(sel.sum()), 1)
    return out
