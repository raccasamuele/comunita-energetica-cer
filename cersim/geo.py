"""Luogo della configurazione: indirizzo → coordinate e regione; tabelle per regione.

Privacy: `geocode` invia l'indirizzo al servizio pubblico Nominatim di
OpenStreetMap. Qui non viene salvato nulla su disco; l'eventuale cache di
sessione è compito dell'interfaccia.
"""

import threading
import time
import unicodedata
from dataclasses import dataclass

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "cersim/0.1 (simulatore CER, progetto studentesco)"
MIN_INTERVALLO_S = 1.0  # policy Nominatim: al massimo 1 richiesta al secondo

# Area per la correzione geografica della tariffa premio FV (DM 414/2023, Allegato 1)
# e zona di mercato GME nella configurazione zonale in vigore dal 1/1/2021.
# Da riverificare sulle fonti nella Tappa 2 (PLAN.md, punto 9).
REGIONI: dict[str, tuple[str, str]] = {
    "Piemonte": ("Nord", "NORD"),
    "Valle d'Aosta": ("Nord", "NORD"),
    "Lombardia": ("Nord", "NORD"),
    "Trentino-Alto Adige": ("Nord", "NORD"),
    "Veneto": ("Nord", "NORD"),
    "Friuli-Venezia Giulia": ("Nord", "NORD"),
    "Liguria": ("Nord", "NORD"),
    "Emilia-Romagna": ("Nord", "NORD"),
    "Toscana": ("Centro", "CNOR"),
    "Umbria": ("Centro", "CNOR"),
    "Marche": ("Centro", "CNOR"),
    "Lazio": ("Centro", "CSUD"),
    "Abruzzo": ("Centro", "CSUD"),
    "Campania": ("Sud", "CSUD"),
    "Molise": ("Sud", "SUD"),
    "Puglia": ("Sud", "SUD"),
    "Basilicata": ("Sud", "SUD"),
    "Calabria": ("Sud", "CALA"),
    "Sicilia": ("Sud", "SICI"),
    "Sardegna": ("Sud", "SARD"),
}
ZONE_VALIDE_DAL = 2021

_ALIAS = {
    "valledaostavalleedaoste": "Valle d'Aosta",
    "trentinoaltoadigesudtirol": "Trentino-Alto Adige",
    "trentino": "Trentino-Alto Adige",
    "altoadige": "Trentino-Alto Adige",
    "sudtirol": "Trentino-Alto Adige",
    "friuliveneziagiulia": "Friuli-Venezia Giulia",
    "sicily": "Sicilia",
    "sardinia": "Sardegna",
    "tuscany": "Toscana",
    "lombardy": "Lombardia",
    "piedmont": "Piemonte",
    "apulia": "Puglia",
}


def _chiave(testo: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", testo).encode("ascii", "ignore").decode()
    return "".join(c for c in ascii_.lower() if c.isalnum())


_PER_CHIAVE = {_chiave(nome): nome for nome in REGIONI} | _ALIAS


def normalizza_regione(nome: str) -> str:
    """Nome canonico della regione; accetta varianti ("Valle d'Aosta / Vallée d'Aoste", "Sicily"…)."""
    for candidato in (nome, nome.split("/")[0]):
        trovato = _PER_CHIAVE.get(_chiave(candidato))
        if trovato:
            return trovato
    raise ValueError(f"Regione non riconosciuta: {nome!r}")


def area_geografica(regione: str) -> str:
    """'Nord' | 'Centro' | 'Sud' ai fini della correzione geografica della TIP."""
    return REGIONI[normalizza_regione(regione)][0]


def zona_mercato(regione: str, anno: int) -> str:
    """Zona di mercato GME della regione nell'anno dei prezzi."""
    if anno < ZONE_VALIDE_DAL:
        raise ValueError(f"Configurazione zonale prima del {ZONE_VALIDE_DAL} non supportata (anno {anno})")
    return REGIONI[normalizza_regione(regione)][1]


@dataclass(frozen=True)
class Luogo:
    lat: float
    lon: float
    regione: str
    descrizione: str


_lock = threading.Lock()
_ultima_richiesta = 0.0


def geocode(indirizzo: str, timeout: float = 10.0) -> Luogo:
    """Indirizzo italiano → coordinate e regione, via Nominatim.

    Rispetta il limite di 1 richiesta al secondo anche con più sessioni nello
    stesso processo. Solleva `LookupError` se l'indirizzo non viene trovato.
    """
    global _ultima_richiesta
    with _lock:
        attesa = MIN_INTERVALLO_S - (time.monotonic() - _ultima_richiesta)
        if attesa > 0:
            time.sleep(attesa)
        try:
            risposta = requests.get(
                NOMINATIM_URL,
                params={"q": indirizzo, "format": "jsonv2", "addressdetails": 1, "countrycodes": "it", "limit": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
        finally:
            _ultima_richiesta = time.monotonic()
    risposta.raise_for_status()
    risultati = risposta.json()
    if not risultati:
        raise LookupError(f"Indirizzo non trovato: {indirizzo!r}")
    primo = risultati[0]
    stato = primo.get("address", {}).get("state")
    if not stato:
        raise LookupError(f"Regione non disponibile per: {indirizzo!r}")
    return Luogo(
        lat=float(primo["lat"]),
        lon=float(primo["lon"]),
        regione=normalizza_regione(stato),
        descrizione=primo.get("display_name", indirizzo),
    )
