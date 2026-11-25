"""Il tetto dell'edificio: superficie, forma, orientamento e ombre degli edifici vicini.

- `tetto_disegnato`: il tetto disegnato dall'utente sulla foto aerea (angoli in
  lon, lat). È la strada principale: precisa e senza dipendere da servizi lenti.

- `scarica_edifici` chiede al servizio Overpass di OpenStreetMap le sagome degli
  edifici entro un raggio (privacy: invia le coordinate dell'edificio; nulla
  viene salvato su disco). Dati © OpenStreetMap contributors, licenza ODbL.
- `stima_tetto` trova l'edificio che contiene il punto e ne ricava superficie a
  terra, forma del tetto (se sulla mappa), altezza (da `height` o dai piani),
  verso della falda migliore, superficie utile e kWp installabili. Se le due falde
  guardano a est e a ovest (`est_ovest`) dà anche i valori con tutte e due.
- Ombre: profilo dell'orizzonte creato dagli edifici più alti nei dintorni
  (`orizzonte`) e quota di energia persa nell'anno (`perdita_ombre`), con il
  percorso del sole ora per ora. Stima semplice: solo la luce diretta viene
  bloccata, alberi e rilievi esclusi (il rilievo lo considera già PVGIS).
Tutti i valori sono stime da correggere con il sopralluogo di un installatore.
"""

import math
import threading
import time
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd
import requests

from cersim.geo import USER_AGENT

# server pubblici di Overpass, in ordine: il primo è il principale, il secondo è un'alternativa volontaria
OVERPASS_URL = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
ATTRIBUZIONE = "Sagome degli edifici © OpenStreetMap contributors (licenza ODbL)"
FOTO_AEREA_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
FOTO_AEREA_ATTRIBUZIONE = "Foto aerea: Esri, Maxar, Earthstar Geographics e comunità GIS"
PRIVACY_FOTO = ("La foto aerea arriva dai server di Esri e la mappa usa librerie da servizi pubblici: il tuo browser "
                "chiede le immagini della zona che guardi. Il disegno resta nella tua sessione.")
LIVELLI_OMBRE = (
    ("Nessuna ombra importante", 0.0),
    ("Qualche ombra al mattino o alla sera", 5.0),
    ("Ombre per una parte del giorno", 12.0),
    ("Molto ombreggiato", 25.0),
)
RAGGIO_M = 150.0
MIN_INTERVALLO_S = 2.0
ALTEZZA_PIANO_M = 3.0
SETTORE_GRADI = 5  # risoluzione dell'orizzonte
QUOTA_DIRETTA = 0.65  # parte della luce sul pannello che arriva diretta dal sole (media annua, Italia)
MAX_DISTANZA_EDIFICIO_M = 25.0

# superficie utile e densità dei moduli (ipotesi prudenti, da verificare con un installatore)
FORME = ("piano", "a falde")
USO_TETTO = {"piano": 0.60, "a falde": 0.70}  # quota libera da bordi, camini, lucernari, locali tecnici
M2_PER_KWP = {"piano": 7.5, "a falde": 5.5}  # su tetto piano i moduli inclinati vanno distanziati
INCLINAZIONE = {"piano": 10.0, "a falde": 20.0}
MARGINE_KWP = 0.2
KWP_MASSIMI = 1000.0  # intervallo mostrato attorno alla stima: ±20%
EST_OVEST_GRADI = 45.0  # falde entro questo scarto da est e da ovest: rendono quasi uguali, si usano tutte e due

_TETTI_PIANI = {"flat"}
_TETTI_A_FALDE = {"gabled", "hipped", "half-hipped", "pyramidal", "skillion", "mansard", "gambrel", "saltbox",
                  "side_hipped"}


@dataclass(frozen=True)
class Edificio:
    poligono: tuple[tuple[float, float], ...]  # metri, x verso est e y verso nord, origine nel punto cercato
    altezza_m: float | None = None
    piani: int | None = None
    forma_tetto: str | None = None  # "piano" | "a falde" | None se la mappa non lo dice


@dataclass
class Tetto:
    lat: float  # origine delle sagome
    lon: float
    area_terra_m2: float
    forma: str  # "piano" | "a falde"
    forma_da_mappa: bool
    piani: int | None
    altezza_m: float | None
    azimut: float  # convenzione PVGIS: 0 = sud, 90 = ovest, -90 = est
    inclinazione: float
    superficie_utile_m2: float
    kwp_max: float
    ombre_pct: float
    asse_lungo_gradi: float  # direzione del lato lungo (gradi da nord, in senso orario)
    edificio: Edificio
    vicini: list[Edificio] = field(default_factory=list)
    note: list[str] = field(default_factory=list)
    # solo per falde rivolte a est e a ovest (`est_ovest`): la falda opposta e i valori con tutte e due
    azimut_2: float | None = None
    superficie_utile_due_falde_m2: float | None = None
    kwp_max_due_falde: float | None = None
    ombre_pct_due_falde: float | None = None

    @property
    def kwp_intervallo(self) -> tuple[float, float]:
        return self.kwp_max * (1 - MARGINE_KWP), self.kwp_max * (1 + MARGINE_KWP)

    @property
    def est_ovest(self) -> bool:
        return self.azimut_2 is not None


# --- download ------------------------------------------------------------------------
_lock = threading.Lock()
_ultima = 0.0


def scarica_edifici(lat: float, lon: float, raggio_m: float = RAGGIO_M, timeout: float = 15.0,
                    tempo_massimo: float = 30.0) -> list[dict]:
    """Elementi `building` di OpenStreetMap entro il raggio, con geometria e tag (risposta grezza di Overpass).

    Prova i server di `OVERPASS_URL` uno dopo l'altro; un server pieno (429, 502, 503, 504) si salta. Dopo
    `tempo_massimo` secondi rinuncia: i server pubblici sono spesso sovraccarichi e l'utente non deve aspettare.
    Solleva requests.RequestException se nessuno risponde."""
    global _ultima
    query = (f'[out:json][timeout:{int(timeout)}];(way["building"](around:{raggio_m:.0f},{lat:.6f},{lon:.6f});'
             f'relation["building"](around:{raggio_m:.0f},{lat:.6f},{lon:.6f}););out geom;')
    ultimo_errore: Exception | None = None
    fine = time.monotonic() + tempo_massimo
    for url in OVERPASS_URL:
        if time.monotonic() >= fine:
            break
        with _lock:
            attesa = MIN_INTERVALLO_S - (time.monotonic() - _ultima)
            if attesa > 0:
                time.sleep(attesa)
            try:
                risposta = requests.get(url, params={"data": query}, headers={"User-Agent": USER_AGENT},
                                        timeout=min(timeout, max(1.0, fine - time.monotonic())))
            except requests.RequestException as e:
                ultimo_errore = e
                continue
            finally:
                _ultima = time.monotonic()
        if risposta.status_code in (429, 502, 503, 504):
            ultimo_errore = requests.HTTPError(f"{url}: server occupato ({risposta.status_code})")
            continue
        risposta.raise_for_status()
        try:
            return risposta.json().get("elements", [])
        except ValueError as e:
            ultimo_errore = requests.RequestException(f"{url}: risposta non valida ({e})")
    raise ultimo_errore or requests.RequestException("Nessun server Overpass disponibile")


def _metri(lat0: float, lon0: float):
    kx = 111_320.0 * math.cos(math.radians(lat0))
    ky = 110_540.0
    return lambda lat, lon: ((lon - lon0) * kx, (lat - lat0) * ky)


def _numero(testo) -> float | None:
    try:
        return float(str(testo).replace(",", ".").replace("m", "").strip())
    except (TypeError, ValueError):
        return None


def _forma(tag: str | None) -> str | None:
    if tag in _TETTI_PIANI:
        return "piano"
    if tag in _TETTI_A_FALDE:
        return "a falde"
    return None


def edifici_da_osm(elementi: list[dict], lat: float, lon: float) -> list[Edificio]:
    """Sagome in metri attorno al punto. Per i multipoligoni si usa l'anello esterno più grande."""
    in_metri = _metri(lat, lon)
    out = []
    for el in elementi:
        anelli = []
        if el.get("type") == "way" and el.get("geometry"):
            anelli = [el["geometry"]]
        elif el.get("type") == "relation":
            anelli = [m["geometry"] for m in el.get("members", [])
                      if m.get("role") == "outer" and m.get("geometry") and m["geometry"][0] == m["geometry"][-1]]
        anelli = [[in_metri(p["lat"], p["lon"]) for p in a] for a in anelli if len(a) >= 4]
        if not anelli:
            continue
        anello = max(anelli, key=lambda a: abs(_area(a)))
        tags = el.get("tags", {})
        piani = _numero(tags.get("building:levels"))
        altezza = _numero(tags.get("height"))
        if altezza is None and piani is not None:
            altezza = piani * ALTEZZA_PIANO_M + 1.0
        out.append(Edificio(tuple(anello), altezza, int(piani) if piani is not None else None,
                            _forma(tags.get("roof:shape"))))
    return out


# --- geometria ---------------------------------------------------------------------------
def _area(punti) -> float:
    p = np.asarray(punti, dtype=float)
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _contiene(punti, x: float, y: float) -> bool:
    dentro = False
    n = len(punti)
    for i in range(n):
        (x1, y1), (x2, y2) = punti[i], punti[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


def _distanza(punti, x: float, y: float) -> float:
    p = np.asarray(punti, dtype=float)
    a, b = p, np.roll(p, -1, axis=0)
    ab = b - a
    t = np.clip(((x - a[:, 0]) * ab[:, 0] + (y - a[:, 1]) * ab[:, 1]) / np.maximum((ab ** 2).sum(axis=1), 1e-9), 0, 1)
    vicino = a + ab * t[:, None]
    return float(np.hypot(vicino[:, 0] - x, vicino[:, 1] - y).min())


def _centro(punti) -> tuple[float, float]:
    p = np.asarray(punti, dtype=float)
    return float(p[:, 0].mean()), float(p[:, 1].mean())


def asse_lungo(punti) -> float:
    """Direzione del lato lungo del rettangolo minimo che contiene la sagoma, in gradi da nord (0–180)."""
    p = np.asarray(punti, dtype=float)
    migliore, area_min = 0.0, math.inf
    for i in range(len(p)):
        dx, dy = p[(i + 1) % len(p)] - p[i]
        if math.hypot(dx, dy) < 1e-6:
            continue
        a = math.atan2(dy, dx)
        c, s = math.cos(-a), math.sin(-a)
        r = p @ np.array([[c, s], [-s, c]])
        larghezza, altezza = np.ptp(r[:, 0]), np.ptp(r[:, 1])
        if larghezza * altezza < area_min:
            area_min = larghezza * altezza
            migliore = a if larghezza >= altezza else a + math.pi / 2
    return (90.0 - math.degrees(migliore)) % 180.0


def _azimut_pvgis(direzione_da_nord: float) -> float:
    return direzione_da_nord % 360.0 - 180.0


def falda_migliore(asse_gradi: float) -> float:
    """Azimut PVGIS della falda più vicina al sud, con il colmo lungo il lato lungo dell'edificio."""
    facce = [(asse_gradi + 90.0) % 360.0, (asse_gradi + 270.0) % 360.0]
    return _azimut_pvgis(min(facce, key=lambda f: abs(f - 180.0)))


def falda_opposta(azimut: float) -> float:
    """Azimut PVGIS della falda dall'altra parte del colmo."""
    return azimut - 180.0 if azimut > 0 else azimut + 180.0


def est_ovest(azimut: float) -> bool:
    """Vero se la falda e quella opposta guardano a est e a ovest (entro `EST_OVEST_GRADI`): rendono quasi uguali,
    circa l'85–90% di una falda a sud, e conviene usarle tutte e due. Con una falda a sud l'altra guarda a nord."""
    return abs(abs(azimut) - 90.0) <= EST_OVEST_GRADI


# --- ombre ----------------------------------------------------------------------------------
def orizzonte(edificio: Edificio, vicini: list[Edificio], altezza_m: float, passo_m: float = 3.0) -> np.ndarray:
    """Altezza dell'orizzonte (gradi) per settori di 5° da nord in senso orario, vista dal centro del tetto."""
    n = 360 // SETTORE_GRADI
    out = np.zeros(n)
    cx, cy = _centro(edificio.poligono)
    for v in vicini:
        if v.altezza_m is None or v.altezza_m <= altezza_m:
            continue
        punti = []
        for (x1, y1), (x2, y2) in zip(v.poligono, v.poligono[1:] + v.poligono[:1]):
            k = max(1, int(math.hypot(x2 - x1, y2 - y1) // passo_m))
            punti += [(x1 + (x2 - x1) * i / k, y1 + (y2 - y1) * i / k) for i in range(k)]
        p = np.asarray(punti) - (cx, cy)
        d = np.maximum(np.hypot(p[:, 0], p[:, 1]), 1.0)
        elevazione = np.degrees(np.arctan((v.altezza_m - altezza_m) / d))
        settore = (np.degrees(np.arctan2(p[:, 0], p[:, 1])) % 360 // SETTORE_GRADI).astype(int)
        np.maximum.at(out, settore, elevazione)
    return out


def perdita_ombre(profilo: np.ndarray, lat: float, lon: float, inclinazione: float, azimut: float,
                  anno: int = 2023) -> float:
    """Quota (%) dell'energia annua persa per l'orizzonte `profilo`: luce diretta pesata sul piano dei moduli."""
    if not np.any(profilo > 0):
        return 0.0
    t = pd.date_range(f"{anno}-01-01 00:30", f"{anno}-12-31 23:30", freq="h", tz="UTC")
    doy = np.asarray(t.dayofyear, dtype=float)
    ore = np.asarray(t.hour + t.minute / 60.0, dtype=float)
    phi, beta, gamma = math.radians(lat), math.radians(inclinazione), math.radians(azimut)
    delta = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365)
    b = 2 * np.pi * (doy - 81) / 364
    h = np.radians(15.0 * (ore + lon / 15.0 + (9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)) / 60 - 12))
    cos_z = np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.cos(h)
    elevazione = np.degrees(np.arcsin(np.clip(cos_z, -1, 1)))
    azimut_sole = (np.degrees(np.arctan2(np.sin(h), np.cos(h) * np.sin(phi) - np.tan(delta) * np.cos(phi))) + 180) % 360
    cos_inc = (np.sin(delta) * np.sin(phi) * np.cos(beta)
               - np.sin(delta) * np.cos(phi) * np.sin(beta) * np.cos(gamma)
               + np.cos(delta) * np.cos(phi) * np.cos(beta) * np.cos(h)
               + np.cos(delta) * np.sin(phi) * np.sin(beta) * np.cos(gamma) * np.cos(h)
               + np.cos(delta) * np.sin(beta) * np.sin(gamma) * np.sin(h))
    sole = cos_z > 0.02
    massa_aria = 1 / np.where(sole, cos_z, 1.0)
    diretta = np.where(sole, 1000 * 0.7 ** (massa_aria ** 0.678), 0.0) * np.clip(cos_inc, 0, None)
    coperto = elevazione < profilo[(azimut_sole // SETTORE_GRADI).astype(int) % len(profilo)]
    totale = diretta.sum()
    return float(100 * QUOTA_DIRETTA * diretta[coperto].sum() / totale) if totale > 0 else 0.0


# --- stima ------------------------------------------------------------------------------------
def dimensioni(area_terra_m2: float, forma: str, inclinazione: float, falde: int = 1) -> tuple[float, float]:
    """Superficie utile (m²) e kWp installabili. Tetto a falde: si usa la falda migliore, metà della sagoma, oppure
    tutte e due (`falde=2`) quando guardano a est e a ovest."""
    if forma == "piano":
        utile = area_terra_m2 * USO_TETTO["piano"]
    else:
        utile = area_terra_m2 * falde / 2 / math.cos(math.radians(inclinazione)) * USO_TETTO["a falde"]
    return utile, utile / M2_PER_KWP[forma]


def stima_tetto(edifici: list[Edificio], lat: float, lon: float, *, forma: str | None = None,
                piani: int | None = None, inclinazione: float | None = None) -> Tetto:
    """Tetto dell'edificio nel punto (lat, lon), le cui coordinate sono l'origine delle sagome.

    `forma`, `piani` e `inclinazione` correggono i dati della mappa quando l'utente li conosce meglio.
    Solleva LookupError se nel punto non c'è un edificio sulla mappa."""
    candidati = [e for e in edifici if _contiene(e.poligono, 0.0, 0.0)]
    if not candidati:
        vicini = sorted(((_distanza(e.poligono, 0.0, 0.0), i) for i, e in enumerate(edifici)))
        if not vicini or vicini[0][0] > MAX_DISTANZA_EDIFICIO_M:
            raise LookupError("Nessun edificio sulla mappa in quel punto: controlla le coordinate o inserisci i dati "
                              "a mano")
        candidati = [edifici[vicini[0][1]]]
    edificio = min(candidati, key=lambda e: abs(_area(e.poligono)))
    return _calcola(edificio, [e for e in edifici if e is not edificio], lat, lon, forma=forma, piani=piani,
                    inclinazione=inclinazione)


def _calcola(edificio: Edificio, altri: list[Edificio], lat: float, lon: float, *, forma: str | None,
             piani: int | None, inclinazione: float | None, con_vicini: bool = True) -> Tetto:
    note = []
    forma_da_mappa = forma is None and edificio.forma_tetto is not None
    if forma is None:
        forma = edificio.forma_tetto or "a falde"
        if edificio.forma_tetto is None:
            note.append("La mappa non dice se il tetto è piano o a falde: si assume a falde, correggi se serve.")
    if piani is not None:
        altezza = piani * ALTEZZA_PIANO_M + 1.0
    else:
        piani, altezza = edificio.piani, edificio.altezza_m
    inclinazione = INCLINAZIONE[forma] if inclinazione is None else inclinazione
    asse = asse_lungo(edificio.poligono)
    azimut = 0.0 if forma == "piano" else falda_migliore(asse)
    area = abs(_area(edificio.poligono))
    utile, kwp = dimensioni(area, forma, inclinazione)
    azimut_2 = falda_opposta(azimut) if forma == "a falde" and est_ovest(azimut) else None
    utile_2, kwp_2 = dimensioni(area, forma, inclinazione, falde=2) if azimut_2 is not None else (None, None)
    if max(kwp, kwp_2 or 0.0) > KWP_MASSIMI:
        kwp = min(kwp, KWP_MASSIMI)
        kwp_2 = min(kwp_2, KWP_MASSIMI) if kwp_2 is not None else None
        note.append(f"Sagoma molto grande: la stima è limitata a {KWP_MASSIMI:.0f} kWp, il massimo per un impianto "
                    "che accede alla tariffa premio. Forse la mappa unisce più edifici.")

    ombre = ombre_2 = 0.0
    if con_vicini and altezza is None:
        note.append("Altezza dell'edificio non presente sulla mappa: indica il numero di piani per stimare le ombre "
                    "degli edifici vicini.")
    elif con_vicini:
        senza_altezza = sum(e.altezza_m is None for e in altri)
        profilo = orizzonte(edificio, altri, altezza)
        ombre = ombre_2 = perdita_ombre(profilo, lat, lon, inclinazione, azimut)
        if azimut_2 is not None:  # metà dei moduli per falda: la perdita è la media delle due
            ombre_2 = (ombre + perdita_ombre(profilo, lat, lon, inclinazione, azimut_2)) / 2
        if senza_altezza:
            note.append(f"{senza_altezza} edifici vicini non hanno l'altezza sulla mappa: sono considerati non più alti "
                        "di questo, quindi le ombre potrebbero essere sottostimate.")
    if con_vicini:
        note.append("Alberi, camini e antenne non sono considerati: le ombre vanno verificate al sopralluogo.")
    due = azimut_2 is not None
    return Tetto(lat=lat, lon=lon, area_terra_m2=area, forma=forma, forma_da_mappa=forma_da_mappa, piani=piani, altezza_m=altezza,
                 azimut=round(azimut), inclinazione=inclinazione, superficie_utile_m2=utile, kwp_max=kwp,
                 ombre_pct=round(ombre * 2) / 2, asse_lungo_gradi=asse, edificio=edificio, vicini=altri, note=note,
                 azimut_2=round(azimut_2) if due else None, superficie_utile_due_falde_m2=utile_2,
                 kwp_max_due_falde=kwp_2, ombre_pct_due_falde=round(ombre_2 * 2) / 2 if due else None)


def correggi(tetto: Tetto, *, forma: str, piani: int | None, inclinazione: float) -> Tetto:
    """Ricalcola il tetto con forma, piani e inclinazione indicati dall'utente, senza scaricare di nuovo la mappa."""
    nuovo = _calcola(tetto.edificio, tetto.vicini, tetto.lat, tetto.lon, forma=forma, piani=piani,
                     inclinazione=inclinazione)
    return replace(nuovo, forma_da_mappa=tetto.forma_da_mappa and forma == tetto.forma)


MIN_AREA_DISEGNO_M2 = 10.0
MAX_AREA_DISEGNO_M2 = 50_000.0


def tetto_disegnato(angoli_lonlat: list, *, forma: str = "a falde", piani: int | None = None,
                    inclinazione: float | None = None, elementi_osm: list[dict] | None = None) -> Tetto:
    """Tetto disegnato dall'utente sulla foto aerea: angoli come [lon, lat] (GeoJSON).

    Superficie e orientamento vengono dal disegno, più preciso della sagoma di una mappa. Gli edifici di
    OpenStreetMap, se scaricati (`elementi_osm`), servono solo a stimare le ombre dei vicini.
    Solleva ValueError se il disegno non è un tetto plausibile."""
    punti = [(float(p[0]), float(p[1])) for p in angoli_lonlat]
    if len(punti) > 1 and punti[0] == punti[-1]:
        punti = punti[:-1]
    if len(punti) < 3:
        raise ValueError("Servono almeno tre angoli per disegnare il tetto")
    lon0 = sum(p[0] for p in punti) / len(punti)
    lat0 = sum(p[1] for p in punti) / len(punti)
    in_metri = _metri(lat0, lon0)
    poligono = tuple(in_metri(lat, lon) for lon, lat in punti)
    area = abs(_area(poligono))
    if not MIN_AREA_DISEGNO_M2 <= area <= MAX_AREA_DISEGNO_M2:
        raise ValueError(f"Il disegno misura {area:,.0f} m²: non sembra un tetto. Ridisegnalo seguendo i bordi del "
                         "tetto.".replace(",", "."))
    altezza = piani * ALTEZZA_PIANO_M + 1.0 if piani else None
    edificio = Edificio(poligono, altezza, piani, forma)
    cx, cy = _centro(poligono)
    vicini = [e for e in edifici_da_osm(elementi_osm or [], lat0, lon0) if not _contiene(e.poligono, cx, cy)]
    tetto = _calcola(edificio, vicini, lat0, lon0, forma=forma, piani=piani, inclinazione=inclinazione,
                     con_vicini=elementi_osm is not None)
    return replace(tetto, forma_da_mappa=False)


def link_google_earth(lat: float, lon: float) -> str:
    """Vista 3D inclinata di Google Earth sul punto, per controllare ombre di edifici e alberi."""
    return f"https://earth.google.com/web/@{lat:.6f},{lon:.6f},250a,350d,35y,0h,60t,0r"


# --- disegno ----------------------------------------------------------------------------------
def disegno_svg(tetto: Tetto, lato_m: float = 140.0, px: int = 320) -> str:
    """Pianta schematica: l'edificio, i vicini (più scuri quelli più alti, che possono fare ombra), il nord.

    SVG autonomo, da mostrare come immagine (st.image): sfondo e bordo sono un rettangolo, non uno stile."""
    scala = px / lato_m
    cx, cy = _centro(tetto.edificio.poligono)

    def punti(e: Edificio) -> str:
        return " ".join(f"{(x - cx) * scala + px / 2:.1f},{px / 2 - (y - cy) * scala:.1f}" for x, y in e.poligono)

    altezza = tetto.altezza_m or 0.0
    forme = []
    for v in tetto.vicini:
        alto = v.altezza_m is not None and v.altezza_m > altezza
        colore = "#87939a" if alto else "#e3e9ec"
        forme.append(f'<polygon points="{punti(v)}" fill="{colore}" stroke="#d6dee2" stroke-width="1"/>')
    forme.append(f'<polygon points="{punti(tetto.edificio)}" fill="#1f5f6b" stroke="#164852" stroke-width="1.5"/>')
    barra = 20 * scala
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {px} {px}" width="{px}" height="{px}" role="img" '
            'aria-label="Pianta dell\'edificio e degli edifici vicini">'
            f'<rect x="0.5" y="0.5" width="{px - 1}" height="{px - 1}" rx="6" fill="#f4f7f8" stroke="#d6dee2"/>'
            + "".join(forme)
            + f'<g font-family="Geist, system-ui, sans-serif" font-size="11" fill="#172026">'
              f'<path d="M{px - 22},34 L{px - 16},16 L{px - 10},34 Z" fill="#172026"/>'
              f'<text x="{px - 16}" y="48" text-anchor="middle">N</text>'
              f'<line x1="12" y1="{px - 14}" x2="{12 + barra:.1f}" y2="{px - 14}" stroke="#172026" stroke-width="2"/>'
              f'<text x="12" y="{px - 20}">20 m</text></g></svg>')
