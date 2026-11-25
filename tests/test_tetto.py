import math
from types import SimpleNamespace

import numpy as np
import pytest
import requests

from cersim import tetto as modulo
from cersim.tetto import (
    QUOTA_DIRETTA,
    Edificio,
    asse_lungo,
    correggi,
    dimensioni,
    disegno_svg,
    edifici_da_osm,
    est_ovest,
    falda_migliore,
    falda_opposta,
    link_google_earth,
    orizzonte,
    perdita_ombre,
    scarica_edifici,
    stima_tetto,
    tetto_disegnato,
)

LAT, LON = 45.07, 7.69


def rettangolo(cx, cy, lungo, corto, gradi_asse=90.0):
    """Rettangolo centrato in (cx, cy) con il lato lungo nella direzione `gradi_asse` (da nord, orario)."""
    a = math.radians(gradi_asse)
    ux, uy = math.sin(a), math.cos(a)  # direzione del lato lungo
    vx, vy = -uy, ux
    angoli = [(+1, +1), (+1, -1), (-1, -1), (-1, +1)]
    return tuple((cx + s * lungo / 2 * ux + t * corto / 2 * vx, cy + s * lungo / 2 * uy + t * corto / 2 * vy)
                 for s, t in angoli)


def edificio(cx=0.0, cy=0.0, piani=5, lungo=30.0, corto=12.0, forma=None, gradi_asse=90.0):
    return Edificio(rettangolo(cx, cy, lungo, corto, gradi_asse), piani * 3.0 + 1.0 if piani else None, piani, forma)


def test_lettura_della_risposta_di_overpass():
    def anello(dlat):
        return [{"lat": LAT + dlat, "lon": LON}, {"lat": LAT + dlat, "lon": LON + 0.0003},
                {"lat": LAT + dlat + 0.0002, "lon": LON + 0.0003}, {"lat": LAT + dlat, "lon": LON}]
    elementi = [
        {"type": "way", "geometry": anello(0), "tags": {"building": "yes", "height": "12 m", "roof:shape": "flat"}},
        {"type": "way", "geometry": anello(0.001), "tags": {"building": "yes", "building:levels": "4"}},
        {"type": "relation", "tags": {"building": "yes"},
         "members": [{"role": "outer", "geometry": anello(0.002)}, {"role": "inner", "geometry": anello(0.002)}]},
        {"type": "way", "geometry": anello(0)[:2], "tags": {"building": "yes"}},  # sagoma incompleta: scartata
    ]
    edifici = edifici_da_osm(elementi, LAT, LON)
    assert len(edifici) == 3
    assert edifici[0].altezza_m == 12 and edifici[0].forma_tetto == "piano"
    assert edifici[1].piani == 4 and edifici[1].altezza_m == 13 and edifici[1].forma_tetto is None


def test_orientamento_della_falda():
    assert asse_lungo(rettangolo(0, 0, 40, 10, 90)) == pytest.approx(90, abs=1)  # lato lungo est-ovest
    assert asse_lungo(rettangolo(0, 0, 40, 10, 30)) == pytest.approx(30, abs=1)
    assert falda_migliore(90) == pytest.approx(0)  # colmo est-ovest: una falda guarda a sud
    assert abs(falda_migliore(0)) == pytest.approx(90)  # colmo nord-sud: falde a est e a ovest
    assert falda_migliore(60) == pytest.approx(-30)  # falda verso sud-est


def test_superficie_e_kwp():
    utile, kwp = dimensioni(400, "piano", 10)
    assert utile == pytest.approx(240) and kwp == pytest.approx(32)
    utile, kwp = dimensioni(400, "a falde", 20)
    assert utile == pytest.approx(200 / math.cos(math.radians(20)) * 0.7)
    assert kwp > 0
    assert dimensioni(400, "a falde", 20, falde=2) == pytest.approx((2 * utile, 2 * kwp))


@pytest.mark.parametrize("azimut, atteso", [(-90, True), (90, True), (-60, True), (130, True), (-45, True),
                                            (0, False), (30, False), (-170, False), (180, False)])
def test_falde_a_est_e_a_ovest(azimut, atteso):
    assert est_ovest(azimut) is atteso
    assert est_ovest(falda_opposta(azimut)) is atteso  # vale per tutte e due le falde


def test_falda_opposta():
    assert falda_opposta(-90) == 90 and falda_opposta(90) == -90
    assert falda_opposta(-30) == 150 and falda_opposta(150) == -30 and falda_opposta(0) == 180


def test_ombre_solo_da_edifici_piu_alti_a_sud():
    io = edificio()
    a_sud = edificio(0, -25, piani=12)
    a_nord = edificio(0, 25, piani=12)
    basso_a_sud = edificio(0, -25, piani=2)
    profilo_sud = orizzonte(io, [a_sud], altezza_m=16)
    assert profilo_sud[180 // 5] > 10 and profilo_sud[0] == 0
    ombre_sud = perdita_ombre(profilo_sud, LAT, LON, 20, 0)
    ombre_nord = perdita_ombre(orizzonte(io, [a_nord], altezza_m=16), LAT, LON, 20, 0)
    assert ombre_sud > 5 and ombre_nord < 1
    assert perdita_ombre(orizzonte(io, [basso_a_sud], altezza_m=16), LAT, LON, 20, 0) == 0
    assert perdita_ombre(np.full(72, 89.0), LAT, LON, 20, 0) == pytest.approx(100 * QUOTA_DIRETTA, abs=0.5)


def test_stima_del_tetto_e_correzioni():
    edifici = [edificio(forma="a falde"), edificio(0, -25, piani=12), edificio(60, 0, piani=None)]
    t = stima_tetto(edifici, LAT, LON)
    assert t.forma == "a falde" and t.forma_da_mappa and t.piani == 5
    assert t.area_terra_m2 == pytest.approx(360) and t.azimut == 0 and t.ombre_pct > 0
    assert t.kwp_intervallo[0] < t.kwp_max < t.kwp_intervallo[1]
    assert any("non hanno l'altezza" in n for n in t.note)
    piano = correggi(t, forma="piano", piani=5, inclinazione=10)
    assert piano.forma == "piano" and not piano.forma_da_mappa and piano.azimut == 0
    assert piano.kwp_max != t.kwp_max
    alto = correggi(t, forma="a falde", piani=13, inclinazione=20)  # più alto del vicino: niente ombre
    assert alto.ombre_pct == 0
    svg = disegno_svg(t)
    assert svg.count("<polygon") == 3
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')  # si mostra come immagine con st.image


def test_tetto_senza_altezza_e_senza_forma():
    t = stima_tetto([edificio(piani=None), edificio(0, -25, piani=12)], LAT, LON)
    assert t.forma == "a falde" and not t.forma_da_mappa and t.ombre_pct == 0
    assert any("piani" in n for n in t.note) and any("piano o a falde" in n for n in t.note)


def test_nessun_edificio_nel_punto():
    with pytest.raises(LookupError):
        stima_tetto([edificio(200, 200)], LAT, LON)
    vicino = stima_tetto([edificio(0, 12, lungo=10, corto=6)], LAT, LON)  # il punto cade in strada, a 9 m
    assert vicino.area_terra_m2 == pytest.approx(60)


class Risposta:
    def __init__(self, stato, dati=None):
        self.status_code, self._dati = stato, dati

    def json(self):
        return self._dati

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_server_pieno_si_passa_al_successivo(monkeypatch):
    chiamati = []

    def finto(url, **kwargs):
        chiamati.append(url)
        return Risposta(502) if len(chiamati) == 1 else Risposta(200, {"elements": [{"type": "way"}]})

    monkeypatch.setattr(requests, "get", finto)
    monkeypatch.setattr(modulo, "MIN_INTERVALLO_S", 0.0)
    assert scarica_edifici(LAT, LON) == [{"type": "way"}]
    assert chiamati == list(modulo.OVERPASS_URL[:2])


def test_nessun_server_risponde(monkeypatch):
    monkeypatch.setattr(modulo, "MIN_INTERVALLO_S", 0.0)
    with pytest.raises(requests.RequestException):  # la rete è bloccata da conftest
        scarica_edifici(LAT, LON)


def angoli_lonlat(lungo=30.0, corto=12.0, gradi_asse=90.0):
    """Rettangolo disegnato attorno al punto (LAT, LON), come lo restituisce la mappa (GeoJSON, chiuso)."""
    kx, ky = 111_320.0 * math.cos(math.radians(LAT)), 110_540.0
    punti = [(LON + x / kx, LAT + y / ky) for x, y in rettangolo(0, 0, lungo, corto, gradi_asse)]
    return [list(p) for p in punti + punti[:1]]


def test_tetto_disegnato():
    t = tetto_disegnato(angoli_lonlat())
    assert t.area_terra_m2 == pytest.approx(360, rel=0.01) and t.forma == "a falde" and t.azimut == 0
    assert t.ombre_pct == 0 and not t.vicini
    assert t.lat == pytest.approx(LAT) and t.lon == pytest.approx(LON)
    ruotato = tetto_disegnato(angoli_lonlat(gradi_asse=60))
    assert ruotato.azimut == pytest.approx(-30, abs=1)  # falda verso sud-est
    piano = tetto_disegnato(angoli_lonlat(), forma="piano")
    assert piano.superficie_utile_m2 == pytest.approx(360 * 0.6, rel=0.01)


def test_tetto_disegnato_con_colmo_da_nord_a_sud():
    t = tetto_disegnato(angoli_lonlat(gradi_asse=0))  # falde a est e a ovest
    assert t.est_ovest and abs(t.azimut) == pytest.approx(90) and t.azimut_2 == -t.azimut
    assert t.superficie_utile_due_falde_m2 == pytest.approx(2 * t.superficie_utile_m2)
    assert t.kwp_max_due_falde == pytest.approx(2 * t.kwp_max)
    assert t.ombre_pct_due_falde == 0
    storto = tetto_disegnato(angoli_lonlat(gradi_asse=20))  # falde a est-sud-est e a ovest-nord-ovest
    assert storto.est_ovest and storto.azimut == pytest.approx(-70, abs=1)
    assert storto.azimut_2 == pytest.approx(110, abs=1)
    for sud in (tetto_disegnato(angoli_lonlat()), tetto_disegnato(angoli_lonlat(gradi_asse=60)),
                tetto_disegnato(angoli_lonlat(gradi_asse=0), forma="piano")):
        assert not sud.est_ovest and sud.azimut_2 is None and sud.kwp_max_due_falde is None


def test_ombre_sulle_due_falde():
    io = edificio(forma="a falde", gradi_asse=0)  # colmo da nord a sud
    a_est = edificio(25, 0, piani=12, gradi_asse=0)
    t = stima_tetto([io, a_est], LAT, LON)
    assert t.est_ovest
    falda_est, falda_ovest = sorted((t.azimut, t.azimut_2))
    profilo = orizzonte(io, [a_est], t.altezza_m)
    ombre_est = perdita_ombre(profilo, LAT, LON, t.inclinazione, falda_est)
    ombre_ovest = perdita_ombre(profilo, LAT, LON, t.inclinazione, falda_ovest)
    assert ombre_est > ombre_ovest  # l'edificio a est copre il sole del mattino
    assert t.ombre_pct_due_falde == pytest.approx((ombre_est + ombre_ovest) / 2, abs=0.25)


def test_tetto_disegnato_con_le_ombre_dalla_mappa():
    def anello(dx, dy, lato=0.0002):
        lat, lon = LAT + dy, LON + dx
        return [{"lat": lat, "lon": lon}, {"lat": lat, "lon": lon + lato}, {"lat": lat + lato, "lon": lon + lato},
                {"lat": lat + lato, "lon": lon}, {"lat": lat, "lon": lon}]
    elementi = [
        {"type": "way", "geometry": anello(-0.0001, -0.0001), "tags": {"building:levels": "5"}},  # lo stesso edificio
        {"type": "way", "geometry": anello(-0.0001, -0.0005), "tags": {"building:levels": "14"}},  # più alto, a sud
    ]
    t = tetto_disegnato(angoli_lonlat(), piani=5, elementi_osm=elementi)
    assert len(t.vicini) == 1 and t.ombre_pct > 0


@pytest.mark.parametrize("angoli", [[[LON, LAT], [LON + 1e-5, LAT]], angoli_lonlat(2, 2), angoli_lonlat(900, 900)],
                         ids=["due_angoli", "troppo_piccolo", "troppo_grande"])
def test_disegni_non_validi(angoli):
    with pytest.raises(ValueError):
        tetto_disegnato(angoli)


def test_link_google_earth():
    assert link_google_earth(45.07, 7.69).startswith("https://earth.google.com/web/@45.070000,7.690000,")


def test_ricerca_che_rinuncia_presto(monkeypatch):
    chiamati = []

    def lento(url, **kwargs):
        chiamati.append(kwargs["timeout"])
        raise requests.Timeout("lento")

    monkeypatch.setattr(requests, "get", lento)
    monkeypatch.setattr(modulo, "MIN_INTERVALLO_S", 0.0)
    monkeypatch.setattr(modulo, "OVERPASS_URL", ("https://uno", "https://due", "https://tre"))
    orologio = iter([0.0, 0.0, 0.0, 5.0, 5.0, 40.0])  # il secondo server risponde dopo 40 s: si rinuncia
    monkeypatch.setattr(modulo, "time", SimpleNamespace(monotonic=lambda: next(orologio, 40.0), sleep=lambda s: None))
    monkeypatch.setattr(modulo, "_ultima", 0.0)
    with pytest.raises(requests.RequestException):
        scarica_edifici(LAT, LON, timeout=15, tempo_massimo=30)
    assert len(chiamati) < len(modulo.OVERPASS_URL) and all(t <= 15 for t in chiamati)
