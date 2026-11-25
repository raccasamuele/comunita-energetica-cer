"""Le serie PVGIS che servono a un'analisi, scaricate dal server stesso.

Nel sito le scarica il browser tramite l'intermediario (PVGIS non manda le intestazioni CORS); qui il server gira sul
computer e le chiede direttamente a PVGIS, con la stessa cache su disco di `cersim.pv` (stesso nome dei file, stessa
scadenza): una serie scaricata dall'app Streamlit vale anche qui, e viceversa. Una serie che non arriva vale come nel
sito: produzione dal modello semplificato, qualità C.

A PVGIS escono solo le coordinate arrotondate a 0,01° (circa 1 km), l'orientamento e le perdite dell'impianto.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from cersim.pv import PVGIS_URL, _leggi_cache, _lock_per, _scrivi_cache_atomica, default_cache_dir

TIMEOUT_S = 60.0
MAX_ERRORI_DI_FILA = 2  # dopo due serie fallite di fila PVGIS è giù o la rete manca: le altre non si chiedono


@dataclass
class Scaricamento:
    serie: dict[str, dict] = field(default_factory=dict)  # chiave → {"time", "P"}, come la cache di cersim.pv
    dalla_cache: int = 0
    scaricate: int = 0
    mancanti: list[str] = field(default_factory=list)
    errore: str | None = None  # il primo errore di rete, per il testo della risposta

    @property
    def tutte(self) -> bool:
        return not self.mancanti

    def frase(self) -> str:
        n = len(self.serie) + len(self.mancanti)
        if not n:
            return "Nessuna serie PVGIS da scaricare: non ci sono impianti."
        if self.tutte:
            return (f"Produzione fotovoltaica da PVGIS: {n} serie ({self.dalla_cache} dalla cache, "
                    f"{self.scaricate} scaricate).")
        return (f"PVGIS non ha dato {len(self.mancanti)} serie su {n}"
                f"{f' ({self.errore})' if self.errore else ''}: per quelle la produzione viene dal modello "
                "semplificato e la qualità dei risultati scende a C. Riprova più tardi per avere i dati di PVGIS.")


def scarica_serie(richieste: list[dict], *, cache_dir: Path | None = None, rete: bool = True,
                  progress=None) -> Scaricamento:
    """Per ogni richiesta di `cersim.web` (`{"chiave", "parametri"}`): la serie dalla cache valida, altrimenti da
    PVGIS. Senza `rete` si usa solo la cache."""
    cartella = cache_dir or default_cache_dir()
    esito = Scaricamento()
    errori_di_fila = 0
    for i, r in enumerate(richieste):
        chiave, parametri = r["chiave"], r["parametri"]
        percorso = cartella / f"{chiave}.json"
        with _lock_per(str(percorso)):
            dati = _leggi_cache(percorso)
            if dati is not None:
                esito.dalla_cache += 1
            elif not rete or errori_di_fila >= MAX_ERRORI_DI_FILA:
                esito.mancanti.append(chiave)
                if not rete and esito.errore is None:
                    esito.errore = "server avviato senza rete"
            else:
                try:
                    risposta = requests.get(PVGIS_URL, params=parametri, timeout=TIMEOUT_S)
                    risposta.raise_for_status()
                    orarie = risposta.json()["outputs"]["hourly"]
                    dati = {"scaricato_il": datetime.now(timezone.utc).isoformat(), "parametri": parametri,
                            "time": [h["time"] for h in orarie], "P": [h["P"] for h in orarie]}
                    _scrivi_cache_atomica(percorso, dati)
                    esito.scaricate += 1
                    errori_di_fila = 0
                except (requests.RequestException, ValueError, KeyError, TypeError) as e:
                    errori_di_fila += 1
                    esito.mancanti.append(chiave)
                    if esito.errore is None:
                        esito.errore = _motivo(e)
                    dati = None
        if dati is not None:
            esito.serie[chiave] = dati
        if progress:
            progress(i + 1, len(richieste), f"Serie PVGIS {i + 1} di {len(richieste)}")
    return esito


def _motivo(e: Exception) -> str:
    if isinstance(e, requests.Timeout):
        return "PVGIS non ha risposto in tempo"
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"PVGIS ha risposto con l'errore {e.response.status_code}"
    if isinstance(e, requests.ConnectionError):
        return "PVGIS non raggiungibile"
    return "risposta di PVGIS non leggibile"
