"""Consumi calcolati da un altro modello, per esempio il simulatore della casa (pompa di calore, isolamento…).

Il file di scambio è un JSON versionato, descritto in docs/formato_curva_consumi.md: la stessa forma media di
`model.CurvaMisurata` (kWh medi per tipo di giorno, mese e ora civile Europe/Rome, 864 celle nell'ordine
`TIPI_GIORNO` × mesi × ore) con il consumo annuo e chi l'ha calcolata.

- `leggi_curva_calcolata` legge un file non fidato: rifiuta formato, versione, campi e valori non validi con un
  messaggio leggibile e restituisce una curva di natura *calcolata*. La simulazione la usa come una misurata; la
  qualità dei dati no: vale come la bolletta, mai come una misura (`loads.qualita_consumi`).
- `esporta` è l'esportazione di riferimento da una serie oraria: la usano i test e chi scrive l'esportazione nel
  simulatore della casa.
"""

import json
import math
import re

import numpy as np
import pandas as pd

from cersim.misure import ANNO_RIFERIMENTO, kwh_anno_riferimento
from cersim.model import CELLE_CURVA, MAX_KWH_ANNUI, TIPI_GIORNO, CurvaMisurata, NaturaCurva
from cersim.timebase import local_frame

FORMATO = "curva-consumi"
VERSIONE = 3
VERSIONI_LETTE = (1, 2, 3)
NATURA = "calcolato"
UNITA = "kWh"
MAX_BYTE = 200_000  # 864 numeri stanno in una ventina di kB
TOLLERANZA_KWH = 0.02  # scarto ammesso tra consumo annuo dichiarato e quello della curva sul calendario di riferimento
SCARTO_DA_SEGNALARE = 0.005
MAX_MOTORE = 80
MAX_DESCRIZIONE = 200
MAX_KWP = 10_000  # FV già tolto dai prelievi
MAX_KWH_BATTERIA = 1_000  # batteria già considerata nei prelievi
OBBLIGATORI = ("formato", "versione", "natura", "unita", "fonte", "kwh_annui", "ore")
# dalla versione 2: i kWp di FV già tolti dai consumi (0 se nessuno), perché lo stesso impianto non si conti due volte
OBBLIGATORI_V2 = ("fv_sottratto_kwp",)
# dalla versione 3: la capacità della batteria di casa già considerata nei prelievi (0 se nessuna)
OBBLIGATORI_V3 = ("batteria_kwh",)
FACOLTATIVI = ("motore", "descrizione")
NOMI_FONTE = {"simulatore-casa": "simulatore della casa"}
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre")
_FONTE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_VIETATI = re.compile(r"[\x00-\x1f\x7f`*_\[\]<>#|~!\\]")  # caratteri di controllo e segni di Markdown o HTML


def _non_numero(nome: str):
    raise ValueError(f"valore non numerico ({nome})")


def _numero(valore) -> float | None:
    """Il valore come float finito, oppure None se non è un numero JSON finito (i booleani non sono numeri)."""
    if isinstance(valore, bool) or not isinstance(valore, int | float):
        return None
    try:
        x = float(valore)
    except OverflowError:
        return None
    return x if math.isfinite(x) else None


def _testo(valore, campo: str, massimo: int) -> str | None:
    if valore is None:
        return None
    if not isinstance(valore, str):
        raise ValueError(f"il campo {campo} deve essere un testo")
    pulito = " ".join(_VIETATI.sub(" ", valore).split())
    return pulito[:massimo] or None


def cella(i: int) -> str:
    """Posizione leggibile di una cella: 'feriale, gennaio, ore 13'."""
    tipo, resto = divmod(i, 12 * 24)
    mese, ora = divmod(resto, 24)
    return f"{TIPI_GIORNO[tipo]}, {MESI[mese]}, ore {ora}"


def leggi_curva_calcolata(contenuto: bytes) -> tuple[CurvaMisurata, list[str]]:
    """Curva calcolata da un file di scambio, con gli avvisi. Solleva ValueError con un messaggio leggibile."""
    if len(contenuto) > MAX_BYTE:
        raise ValueError(f"Il file supera {MAX_BYTE // 1000} kB: non sembra una curva dei consumi")
    try:
        dati = json.loads(contenuto.decode("utf-8-sig"), parse_constant=_non_numero)
    except UnicodeDecodeError:
        raise ValueError("Il file non è un testo UTF-8: non sembra una curva dei consumi") from None
    except RecursionError:
        raise ValueError("Il file non è un JSON valido") from None
    except ValueError as e:  # anche json.JSONDecodeError
        raise ValueError(f"Il file non è un JSON valido ({getattr(e, 'msg', e)})") from None
    if not isinstance(dati, dict) or dati.get("formato") != FORMATO:
        raise ValueError(f"Non è una curva dei consumi: il campo formato deve essere {FORMATO!r}")

    versione = dati.get("versione")
    if isinstance(versione, bool) or not isinstance(versione, int):
        raise ValueError("Il campo versione deve essere un numero intero")
    if versione not in VERSIONI_LETTE:
        piu_recente = versione > max(VERSIONI_LETTE)
        raise ValueError(f"Versione {versione} del formato non supportata (questo simulatore legge la "
                         f"{', '.join(map(str, VERSIONI_LETTE))})" + (": aggiorna il simulatore" if piu_recente else ""))
    previsti = OBBLIGATORI + (OBBLIGATORI_V2 if versione >= 2 else ()) + (OBBLIGATORI_V3 if versione >= 3 else ())
    if sconosciuti := sorted(set(dati) - set(previsti) - set(FACOLTATIVI)):
        raise ValueError(f"Campi non previsti dalla versione {versione}: {', '.join(map(str, sconosciuti))[:200]}")
    if mancanti := [c for c in previsti if c not in dati]:
        raise ValueError(f"Mancano i campi: {', '.join(mancanti)}")

    if dati["natura"] != NATURA:
        if dati["natura"] == "misurato":
            raise ValueError("Questo formato è solo per consumi calcolati: i consumi misurati si caricano con i file "
                             "del Portale Consumi o di e-distribuzione")
        raise ValueError(f"Il campo natura deve essere {NATURA!r}")
    if dati["unita"] != UNITA:
        raise ValueError(f"I valori devono essere in {UNITA} (campo unita)")
    fonte = dati["fonte"]
    if not isinstance(fonte, str) or not _FONTE.match(fonte):
        raise ValueError("Il campo fonte deve essere un nome breve in minuscolo, per esempio 'simulatore-casa'")
    motore = _testo(dati.get("motore"), "motore", MAX_MOTORE)
    descrizione = _testo(dati.get("descrizione"), "descrizione", MAX_DESCRIZIONE)

    kwh_annui = _numero(dati["kwh_annui"])
    if kwh_annui is None or not 0 < kwh_annui <= MAX_KWH_ANNUI:
        raise ValueError(f"Il consumo annuo (kwh_annui) deve essere un numero maggiore di zero e al massimo "
                         f"{MAX_KWH_ANNUI:,.0f} kWh".replace(",", "."))
    ore = dati["ore"]
    if not isinstance(ore, list) or len(ore) != CELLE_CURVA:
        trovati = f": ne ha {len(ore)}" if isinstance(ore, list) else ""
        raise ValueError(f"Il campo ore deve essere un elenco di {CELLE_CURVA} valori{trovati}")
    valori = []
    for i, v in enumerate(ore):
        x = _numero(v)
        if x is None or x < 0:
            raise ValueError(f"Valore {i} delle ore non valido ({cella(i)}): servono kWh finiti e non negativi")
        valori.append(round(x, 5))
    if sum(valori) <= 0:
        raise ValueError("La curva è tutta a zero")

    fv_sottratto = None
    if versione >= 2:
        fv_sottratto = _numero(dati["fv_sottratto_kwp"])
        if fv_sottratto is None or not 0 <= fv_sottratto <= MAX_KWP:
            raise ValueError(f"Il campo fv_sottratto_kwp deve essere un numero tra 0 e {MAX_KWP:,.0f} kWp".replace(",", "."))
        fv_sottratto = round(fv_sottratto, 2) or None

    batteria = None
    if versione >= 3:
        batteria = _numero(dati["batteria_kwh"])
        if batteria is None or not 0 <= batteria <= MAX_KWH_BATTERIA:
            raise ValueError(f"Il campo batteria_kwh deve essere un numero tra 0 e {MAX_KWH_BATTERIA:,.0f} kWh".replace(",", "."))
        batteria = round(batteria, 2) or None

    avvisi = []
    if fv_sottratto:
        avvisi.append(f"questi consumi hanno già tolto un fotovoltaico da {_kw(fv_sottratto)} kWp: sono i prelievi dalla "
                      "rete. Non inserire di nuovo quell'impianto su questo punto, solo impianti nuovi")
    if batteria:
        avvisi.append(f"questi prelievi tengono già conto di una batteria di casa da {_kw(batteria)} kWh. Una batteria privata "
                      "si scarica la sera, proprio nelle ore in cui la comunità potrebbe coprire quei consumi: riduce "
                      "l'energia condivisa e i contributi")
    della_curva = kwh_anno_riferimento(valori)
    scarto = abs(della_curva - kwh_annui) / kwh_annui
    if scarto > TOLLERANZA_KWH:
        raise ValueError(f"Il consumo annuo dichiarato ({_kwh(kwh_annui)} kWh) non torna con la curva "
                         f"({_kwh(della_curva)} kWh sul calendario del {ANNO_RIFERIMENTO}): scarto del {scarto:.1%}, "
                         f"ammesso fino al {TOLLERANZA_KWH:.0%}")
    if scarto > SCARTO_DA_SEGNALARE:
        avvisi.append(f"consumo annuo dichiarato {_kwh(kwh_annui)} kWh, dalla curva {_kwh(della_curva)} kWh: "
                      "si usa quello dichiarato")

    nome = NOMI_FONTE.get(fonte, fonte)
    dettagli = descrizione or motore
    etichetta = f"{nome}: {dettagli}" if dettagli else nome
    if len(etichetta) > 80:
        etichetta = etichetta[:79].rstrip() + "…"
    curva = CurvaMisurata(ore=tuple(valori), natura=NaturaCurva.CALCOLATA, kwh_annui=round(kwh_annui, 1),
                          fonte=etichetta, fv_sottratto_kwp=fv_sottratto, batteria_kwh=batteria)
    return curva, avvisi


def _kwh(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _kw(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def forma_media(orarie: pd.Series) -> np.ndarray:
    """kWh medi per tipo di giorno, mese e ora civile (3 × 12 × 24) da una serie oraria di kWh con indice orario
    con fuso. Tipo di giorno e ora si leggono in ora civile Europe/Rome, come in `timebase.local_frame`."""
    if not isinstance(orarie.index, pd.DatetimeIndex) or orarie.index.tz is None:
        raise ValueError("Serve una serie oraria con indice di date e fuso orario")
    cal = local_frame(orarie.index)
    medie = pd.DataFrame({"tipo": cal["day_type"].to_numpy(), "mese": cal["month"].to_numpy(),
                          "ora": cal["hour"].to_numpy(), "kwh": orarie.to_numpy(dtype=float)}
                         ).groupby(["tipo", "mese", "ora"])["kwh"].mean()
    forma = np.full((len(TIPI_GIORNO), 12, 24), np.nan)
    for (tipo, mese, ora), valore in medie.items():
        forma[TIPI_GIORNO.index(tipo), mese - 1, ora] = valore
    if np.isnan(forma).any():
        raise ValueError("La serie non copre tutti i mesi, tipi di giorno e ore: serve un anno intero")
    return forma


def esporta(orarie: pd.Series, *, fonte: str = "simulatore-casa", motore: str | None = None,
            descrizione: str | None = None, fv_sottratto_kwp: float = 0, batteria_kwh: float = 0) -> dict:
    """File di scambio (da scrivere con `json.dumps`) da un anno di consumi orari in kWh. Senza batteria resta la
    versione 2, come scrive il simulatore della casa; con la batteria è la 3."""
    forma = forma_media(orarie)
    batteria = {"batteria_kwh": batteria_kwh} if batteria_kwh > 0 else {}
    return {"formato": FORMATO, "versione": 3 if batteria else 2, "natura": NATURA, "unita": UNITA, "fonte": fonte,
            "motore": motore, "descrizione": descrizione, "fv_sottratto_kwp": fv_sottratto_kwp, **batteria,
            "kwh_annui": round(float(orarie.sum()), 1), "ore": [round(float(v), 5) for v in forma.reshape(CELLE_CURVA)]}
