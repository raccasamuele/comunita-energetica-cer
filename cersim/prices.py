"""Prezzi zonali orari (Pz) per TIP, perdite evitate e vendita dell'energia.

Licenza dei dati: le condizioni d'uso del GME consentono solo un uso personale
e vietano la ridistribuzione e il download automatico (docs/fonti_normative.md).
Per questo il repository NON contiene prezzi e il codice non li scarica:

- `prezzi_da_csv`: legge un file orario (o quartorario) fornito dall'utente;
- `anno_dei_prezzi`: ricava dal file l'anno a cui si riferisce;
- `prezzo_costante`: prezzo piatto, qualità dati `C`.

Gli scenari di livello (basso/base/alto) riscalano la media mantenendo la forma
oraria dell'anno storico: nelle ore di sole i prezzi restano più bassi.
I prezzi vanno aggiornati una volta l'anno con l'ultimo anno disponibile.

Formato CSV: colonna `inizio` con data e ora di inizio del periodo in ISO 8601
CON fuso orario (es. `2024-03-31T02:00:00+02:00`), più una colonna per zona
(`NORD`, `CNOR`, `CSUD`, `SUD`, `CALA`, `SICI`, `SARD`) in €/MWh.
"""

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from cersim.timebase import TZ, remap_reference_year, year_index

ZONE = ("NORD", "CNOR", "CSUD", "SUD", "CALA", "SICI", "SARD")
MAX_RIGHE_CSV = 40_000  # un anno quartorario sono ~35.000 righe
MAX_ORE_MANCANTI = 24


@dataclass(frozen=True)
class PriceSeries:
    eur_mwh: pd.Series  # indice: ore UTC dell'anno civile italiano `year`
    year: int
    zona: str
    fonte: str
    qualita: str  # "B" prezzi orari reali, "C" prezzo costante

    @property
    def media(self) -> float:
        return float(self.eur_mwh.mean())

    def scalata(self, media_eur_mwh: float) -> "PriceSeries":
        """Stessa forma oraria, media riportata al livello indicato."""
        if self.media <= 0:
            raise ValueError("Impossibile riscalare una serie con media non positiva")
        return PriceSeries(self.eur_mwh * (media_eur_mwh / self.media), self.year, self.zona, self.fonte, self.qualita)

    def per_anno_progetto(self, anno: int) -> np.ndarray:
        """Serie rimappata sul calendario dell'anno di progetto (giorno della settimana allineato)."""
        return remap_reference_year(self.year, anno).apply(self.eur_mwh.to_numpy())


def prezzo_costante(valore_eur_mwh: float, anno: int, zona: str = "NORD") -> PriceSeries:
    return PriceSeries(
        pd.Series(float(valore_eur_mwh), index=year_index(anno), name="eur_mwh"),
        anno,
        zona,
        fonte=f"prezzo costante {valore_eur_mwh:g} €/MWh",
        qualita="C",
    )


# Limiti di plausibilità dei prezzi del giorno prima in €/MWh: il tetto armonizzato europeo è 4.000 €/MWh (5.000 dal
# 2023 se scatta l'aumento automatico), il minimo −500 €/MWh.
PREZZO_MIN_EUR_MWH = -500.0
PREZZO_MAX_EUR_MWH = 5000.0


def _leggi_tabella(percorso, usecols=None) -> pd.DataFrame:
    """Il CSV dei prezzi, con messaggi d'errore in italiano per i file sbagliati più comuni (vuoti, Excel, codifica,
    separatore «;»). Solleva ValueError."""
    if hasattr(percorso, "read"):
        posizione = percorso.tell() if hasattr(percorso, "tell") else 0
        grezzo = percorso.read()
        if hasattr(percorso, "seek"):
            percorso.seek(posizione)
    else:
        grezzo = Path(percorso).read_bytes()
    if isinstance(grezzo, str):
        grezzo = grezzo.encode("utf-8")
    inizio = grezzo[:4]
    if not grezzo.strip():
        raise ValueError("il file è vuoto")
    if inizio.startswith(b"PK") or inizio.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError("è un file Excel, non un CSV: aprilo e salvalo come «CSV UTF-8»")
    if inizio.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("è in UTF-16: salvalo come «CSV UTF-8»")
    try:
        testo = grezzo.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("non è un file di testo in UTF-8: salvalo come «CSV UTF-8»") from None
    prima = testo.splitlines()[0] if testo.splitlines() else ""
    sep = ";" if prima.count(";") > prima.count(",") else ","
    try:
        dati = pd.read_csv(io.StringIO(testo), sep=sep, nrows=MAX_RIGHE_CSV + 1, dtype=str, skipinitialspace=True)
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        raise ValueError("le righe non hanno tutte lo stesso numero di colonne: non sembra un CSV di prezzi") from None
    dati.columns = [str(c).strip() for c in dati.columns]
    if "inizio" not in dati.columns:
        colonne = {c.lower() for c in dati.columns}
        if {"data", "ora"} <= colonne or "pun" in colonne:
            raise ValueError("sembra il file del GME, con le colonne Data e Ora: va convertito nel formato del "
                             "simulatore, con la colonna 'inizio' (data, ora e fuso orario) e una colonna per zona in "
                             "€/MWh")
        raise ValueError("manca la colonna 'inizio' con data, ora e fuso orario (es. 2024-03-31T02:00:00+02:00)")
    if usecols:
        dati = dati[usecols]
    return dati


def anno_dei_prezzi(percorso) -> int:
    """Anno civile italiano a cui si riferisce un file di prezzi (quello della maggior parte delle righe)."""
    dati = _leggi_tabella(percorso, usecols=["inizio"])
    inizio = pd.to_datetime(dati["inizio"].astype(str).str.strip(), utc=True, format="ISO8601", errors="coerce").dropna()
    if inizio.empty:
        raise ValueError("nessuna data valida nella colonna 'inizio' (formato atteso: 2024-03-31T02:00:00+02:00)")
    return int(inizio.dt.tz_convert(TZ).dt.year.mode().iloc[0])


def prezzi_da_csv(percorso, zona: str, anno: int) -> PriceSeries:
    """Prezzi dell'anno civile `anno` per la zona, da un file fornito dall'utente (percorso o file aperto)."""
    if zona not in ZONE:
        raise ValueError(f"Zona sconosciuta: {zona}")
    dati = _leggi_tabella(percorso)
    if len(dati) > MAX_RIGHE_CSV:
        raise ValueError(f"File troppo grande (oltre {MAX_RIGHE_CSV} righe)")
    if dati.empty:
        raise ValueError("il file ha l'intestazione ma nessuna riga di prezzi")
    if zona not in dati:
        raise ValueError(f"Il file deve avere le colonne 'inizio' e '{zona}' (la zona di mercato della regione)")

    testo = dati["inizio"].astype(str).str.strip()
    senza_fuso = ~testo.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True)
    if senza_fuso.any():
        raise ValueError(f"La colonna 'inizio' deve indicare il fuso orario (es. +01:00 / +02:00): manca alla riga "
                         f"{_riga(senza_fuso)}")
    inizio = pd.to_datetime(testo, utc=True, format="ISO8601", errors="coerce")
    if inizio.isna().any():
        raise ValueError(f"data non valida nella colonna 'inizio' alla riga {_riga(inizio.isna())} (formato atteso: "
                         "2024-03-31T02:00:00+02:00)")
    colonna = dati[zona].astype(str).str.strip()
    if colonna.str.fullmatch(r"-?\d+,\d+").any() and not colonna.str.contains(r"\.").any():
        colonna = colonna.str.replace(",", ".", regex=False)  # virgola decimale, all'italiana
    valori = pd.to_numeric(colonna, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(valori).all():
        raise ValueError(f"Il file contiene prezzi mancanti o non numerici (prima alla riga "
                         f"{_riga(pd.Series(~np.isfinite(valori)))})")
    mediana = float(np.median(valori))
    if 0 < abs(mediana) < 2:
        raise ValueError("i prezzi sembrano in €/kWh (mediana sotto 2): servono in €/MWh, moltiplicati per 1000")
    if valori.min() < PREZZO_MIN_EUR_MWH or valori.max() > PREZZO_MAX_EUR_MWH:
        raise ValueError(f"prezzi fuori scala (da {valori.min():g} a {valori.max():g} €/MWh): il mercato va da "
                         f"{PREZZO_MIN_EUR_MWH:g} a {PREZZO_MAX_EUR_MWH:g} €/MWh")

    serie = pd.Series(valori, index=pd.DatetimeIndex(inizio))
    orari = serie.groupby(serie.index.floor("h")).mean()  # quarti d'ora → media oraria
    idx = year_index(anno)
    allineati = orari.reindex(idx)
    mancanti = int(allineati.isna().sum())
    if mancanti > MAX_ORE_MANCANTI:
        raise ValueError(f"Mancano {mancanti} ore di prezzi per il {anno}")
    allineati = allineati.interpolate(limit_direction="both")
    nome = Path(getattr(percorso, "name", None) or str(percorso)).name
    return PriceSeries(allineati.rename("eur_mwh"), anno, zona, fonte=f"file utente {nome} ({anno}, {zona})", qualita="B")


def _riga(maschera: pd.Series) -> int:
    """Numero di riga nel file (1 è l'intestazione) del primo valore segnato."""
    return int(np.flatnonzero(np.asarray(maschera))[0]) + 2
