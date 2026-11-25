import pytest
import requests

from cersim import geo


@pytest.mark.parametrize(
    "nome, atteso",
    [
        ("Piemonte", "Piemonte"),
        ("valle d'aosta / Vallée d'Aoste", "Valle d'Aosta"),
        ("Trentino-Alto Adige/Südtirol", "Trentino-Alto Adige"),
        ("Friuli Venezia Giulia", "Friuli-Venezia Giulia"),
        ("Sicily", "Sicilia"),
        ("EMILIA ROMAGNA", "Emilia-Romagna"),
    ],
)
def test_normalizza_regione(nome, atteso):
    assert geo.normalizza_regione(nome) == atteso


def test_regione_sconosciuta():
    with pytest.raises(ValueError):
        geo.normalizza_regione("Baviera")


def test_tabelle_complete():
    assert len(geo.REGIONI) == 20
    assert geo.area_geografica("Lombardia") == "Nord"
    assert geo.area_geografica("Umbria") == "Centro"
    assert geo.area_geografica("Campania") == "Sud"
    assert geo.zona_mercato("Umbria", 2023) == "CNOR"
    assert geo.zona_mercato("Calabria", 2021) == "CALA"
    with pytest.raises(ValueError, match="2021"):
        geo.zona_mercato("Calabria", 2020)


class _Risposta:
    def __init__(self, dati):
        self._dati = dati

    def raise_for_status(self):
        pass

    def json(self):
        return self._dati


def test_geocode(monkeypatch):
    chiamate = []

    def finto_get(url, params, headers, timeout):
        chiamate.append((params, headers))
        return _Risposta([{"lat": "45.7372", "lon": "7.3206", "display_name": "Aosta",
                           "address": {"state": "Valle d'Aosta / Vallée d'Aoste"}}])

    monkeypatch.setattr(requests, "get", finto_get)
    monkeypatch.setattr(geo.time, "sleep", lambda s: None)
    luogo = geo.geocode("Piazza Chanoux, Aosta")
    assert luogo.regione == "Valle d'Aosta"
    assert luogo.lat == pytest.approx(45.7372)
    params, headers = chiamate[0]
    assert params["countrycodes"] == "it"
    assert headers["User-Agent"].startswith("cersim")


def test_geocode_non_trovato(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Risposta([]))
    monkeypatch.setattr(geo.time, "sleep", lambda s: None)
    with pytest.raises(LookupError):
        geo.geocode("indirizzo inesistente")


def test_geocode_rispetta_un_secondo(monkeypatch):
    attese = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Risposta([{"lat": "1", "lon": "1", "address": {"state": "Lazio"}}]))
    monkeypatch.setattr(geo.time, "sleep", lambda s: attese.append(s))
    geo.geocode("a")
    geo.geocode("b")
    assert attese and attese[-1] > 0.9
