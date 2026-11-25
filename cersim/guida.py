"""Prima di iniziare: quali dati servono, dove trovarli e la scheda dei consumi che ogni famiglia compila.

- `COSA_SERVE`: per chi coordina, per ogni famiglia, per le attività e per le
  parti comuni, che cosa preparare e dove trovarlo, in parole semplici.
- La scheda dei consumi è un piccolo file JSON che una famiglia o un'attività
  compila dal proprio link e manda a chi coordina: `crea_scheda` lo scrive,
  `leggi_scheda` lo rilegge con limiti di dimensione e controlli,
  `unisci_schede` aggiunge o aggiorna le righe dei contatori al passo 2.
Nessun dato passa dal server: la scheda resta nel browser di chi la compila
finché non la manda di persona a chi coordina.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode, urlsplit, urlunsplit

import pandas as pd
from pydantic import ValidationError

from cersim.model import MAX_KWH_ANNUI, CurvaMisurata
from cersim.ui_model import COLONNE_PUNTI, TIPI_SOGGETTO, TIPOLOGIE, tipizza_punti

FORMATO = "cersim-scheda-consumi"
MODULO = "famiglia"  # valore del parametro ?modulo= del link
VERSIONE = 1
MAX_BYTE = 200_000  # con la curva misurata facoltativa: circa 10 kB per contatore
MAX_CONTATORI = 5
MAX_TESTO = 80
SCARTO_FASCE = 0.2  # oltre il 20% di differenza, fasce e consumo annuo vengono da periodi diversi
KWH_FAMIGLIA_TIPO = 2700


def _migliaia(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


@dataclass(frozen=True)
class Voce:
    cosa: str
    dove: str


@dataclass(frozen=True)
class Gruppo:
    titolo: str
    voci: tuple[Voce, ...]
    nota: str = ""


CONSUMO_ANNUO = Voce(
    "Il consumo di luce dell'ultimo anno, in kWh",
    "In bolletta, di solito in prima pagina vicino al grafico dei consumi, alla voce consumo annuo o consumo "
    "degli ultimi 12 mesi. Oppure sul Portale Consumi.",
)
FASCE = Voce(
    "I consumi dell'anno per fascia oraria: F1 e F2+F3",
    "Sul Portale Consumi, o in bolletta se riporta i consumi annui per fascia. Le fasce di una sola bolletta "
    "valgono per uno o due mesi: in quel caso somma le bollette dell'anno. Se ci sono F2 e F3 separate, sommale. "
    "Se non le trovi, lascia vuoto.",
)

COSA_SERVE: dict[str, Gruppo] = {
    "coordina": Gruppo("Chi coordina (amministratore, Comune, associazione)", (
        Voce("L'indirizzo dell'edificio, o degli edifici per una comunità energetica",
             "Serve a stimare quanto produce il sole in quel punto."),
        Voce("Che cosa volete fare: un gruppo di autoconsumatori o una comunità energetica",
             "Gruppo se tutti sono nello stesso edificio o condominio; comunità energetica se i membri sono in "
             "edifici diversi."),
        Voce("La data prevista di costituzione",
             "Dal calendario dell'assemblea o del consiglio. Gli impianti devono entrare in esercizio dopo."),
        Voce("Il tetto: se è piano o a falde, quanti piani ha l'edificio, quanta superficie è libera",
             "Per un condominio il tetto si disegna al passo 3 sulla foto aerea: il simulatore ne ricava superficie "
             "e orientamento e propone tre taglie dell'impianto. Per il progetto vero serve il sopralluogo di un "
             "installatore."),
        Voce("Il preventivo dell'impianto, se c'è: costo, kWp dei moduli e kW dell'inverter",
             "Dall'installatore. Senza preventivo si usa il costo massimo di riferimento del DM 414/2023, una "
             "stima alta."),
        Voce("Chi paga l'impianto e come dividere i contributi",
             "È una scelta dell'assemblea o del consiglio: nel simulatore si possono provare più ipotesi."),
        Voce("Solo per una comunità energetica: l'area convenzionale di ogni contatore",
             "Sul sito del GSE, nella mappa interattiva delle cabine primarie, cercando l'indirizzo o il codice "
             "POD del contatore."),
        Voce("Solo se già concesso: il contributo in capitale",
             "Importo, estremi e data di incasso dall'atto di concessione."),
    ), "I consumi delle famiglie e delle attività si raccolgono con il link del passo 2: ognuno compila i suoi."),
    "famiglia": Gruppo("Ogni famiglia", (
        CONSUMO_ANNUO,
        FASCE,
        Voce("Quanti contatori della luce avete", "Di solito uno: una bolletta della luce per ogni contatore."),
    ), f"Senza dati si usa la famiglia tipo da {_migliaia(KWH_FAMIGLIA_TIPO)} kWh all'anno, ma i risultati sono "
       "meno precisi."),
    "attivita": Gruppo("Negozi, uffici, laboratori e altre attività", (
        CONSUMO_ANNUO,
        FASCE,
        Voce("Il tipo di attività e se è una piccola o media impresa oppure una grande impresa",
             "Le grandi imprese non possono far parte di una comunità energetica."),
        Voce("La tensione della fornitura: bassa o media tensione",
             "In bolletta, nei dati della fornitura. Negozi e uffici sono quasi sempre in bassa tensione."),
    )),
    "parti_comuni": Gruppo("Condominio: le parti comuni", (
        Voce("La bolletta della luce delle parti comuni (scale, ascensore, cortile)",
             "La conserva l'amministratore. Servono gli stessi dati di una famiglia: consumo annuo e fasce."),
    )),
}

PORTALE_CONSUMI = (
    "Il Portale Consumi di ARERA e Acquirente Unico (www.consumienergia.it) è gratuito: si entra con SPID o CIE, si "
    "sceglie la fornitura di energia elettrica e si trovano i consumi mese per mese e per fascia."
)
CODICE_POD = (
    "Il codice POD (inizia con IT e contiene una E, per esempio IT001E…) è in prima pagina della bolletta. Alla "
    "simulazione non serve e il link per le famiglie non lo chiede; per una comunità energetica aiuta chi coordina "
    "a trovare l'area convenzionale sulla mappa del GSE."
)
PRIVACY_SCHEDA = (
    "I dati che inserisci servono solo a preparare la scheda: il sito non li salva. Alla fine scarichi un piccolo "
    "file e lo mandi tu a chi coordina, per email o messaggio. Come nome puoi usare quello che preferisci, per "
    "esempio \"interno 3\"."
)

# chi compila la scheda → tipo di soggetto e tipo di consumo (etichette della tabella del passo 2)
PROFILI = {
    "Una famiglia": ("Persona fisica", "Famiglia"),
    "Un'attività (negozio, ufficio, laboratorio)": (None, None),
    "Il condominio (parti comuni)": ("Condominio", "Municipio / uffici pubblici"),
    "Un ente pubblico (Comune, scuola)": ("Ente territoriale (es. Comune)", None),
}
SOGGETTI_ATTIVITA = ["PMI", "Grande impresa", "Ente del terzo settore", "Ente religioso", "Altro"]
ETICHETTE_SOGGETTO_ATTIVITA = {"PMI": "Piccola o media impresa", "Grande impresa": "Grande impresa",
                               "Ente del terzo settore": "Associazione o ente del terzo settore",
                               "Ente religioso": "Ente religioso", "Altro": "Altro"}
TIPOLOGIE_ATTIVITA = ["Ufficio / negozio", "PMI / laboratorio"]
TIPOLOGIE_ENTE = ["Municipio / uffici pubblici", "Scuola"]


# --- la scheda dei consumi --------------------------------------------------------------
@dataclass
class Contatore:
    nome: str
    tipologia: str
    kwh_annui: float | None = None
    f1_kwh: float | None = None
    f23_kwh: float | None = None
    tensione: str = "BT"
    curva: CurvaMisurata | None = None  # facoltativa: forma media dei consumi misurati, senza POD (cersim.misure)


@dataclass
class Scheda:
    membro: str
    tipo_soggetto: str
    contatori: list[Contatore] = field(default_factory=list)
    configurazione: str | None = None  # a chi è destinata, dal link
    compilata_il: date | None = None


def _numero(valore, nome: str, errori: list[str]) -> float | None:
    if valore is None or valore == "":
        return None
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        errori.append(f"{nome}: serve un numero")
        return None
    if not 0 <= valore <= MAX_KWH_ANNUI:
        errori.append(f"{nome}: valore fuori scala")
        return None
    return float(valore)


def controlla(scheda: Scheda) -> list[str]:
    """Errori in italiano, comprensibili da chi compila. Lista vuota = scheda pronta."""
    errori = []
    if not scheda.membro.strip():
        errori.append("Scrivi il nome con cui vuoi comparire")
    elif len(scheda.membro) > MAX_TESTO:
        errori.append(f"Il nome è troppo lungo (massimo {MAX_TESTO} caratteri)")
    if scheda.tipo_soggetto not in TIPI_SOGGETTO:
        errori.append("Scegli che tipo di soggetto sei")
    if not 1 <= len(scheda.contatori) <= MAX_CONTATORI:
        errori.append(f"Indica da 1 a {MAX_CONTATORI} contatori")
    nomi = [c.nome.strip() for c in scheda.contatori]
    if len(set(nomi)) != len(nomi):
        errori.append("Dai un nome diverso a ogni contatore")
    for i, c in enumerate(scheda.contatori, 1):
        chi = f"Contatore {i}" if len(scheda.contatori) > 1 else "Contatore"
        if not c.nome.strip() or len(c.nome) > MAX_TESTO:
            errori.append(f"{chi}: scrivi un nome breve")
        if c.tipologia not in TIPOLOGIE:
            errori.append(f"{chi}: scegli il tipo di consumo")
        if c.tensione not in ("BT", "MT"):
            errori.append(f"{chi}: tensione non valida")
        kwh = _numero(c.kwh_annui, f"{chi}, consumo annuo", errori)
        f1 = _numero(c.f1_kwh, f"{chi}, F1", errori)
        f23 = _numero(c.f23_kwh, f"{chi}, F2+F3", errori)
        if (f1 is None) != (f23 is None):
            errori.append(f"{chi}: indica sia F1 sia F2+F3, oppure lascia vuote tutte e due")
        elif f1 is not None and kwh:
            somma = f1 + f23
            if abs(somma - kwh) > SCARTO_FASCE * kwh:
                errori.append(f"{chi}: F1 più F2+F3 fa {_migliaia(somma)} kWh, molto diverso dal consumo annuo di "
                              f"{_migliaia(kwh)} kWh. Forse sono i consumi di una sola bolletta: usa i consumi "
                              "dell'anno oppure lascia vuote le fasce.")
    return errori


def crea_scheda(scheda: Scheda) -> str:
    errori = controlla(scheda)
    if errori:
        raise ValueError("; ".join(errori))
    return json.dumps({
        "formato": FORMATO,
        "versione": VERSIONE,
        "configurazione": scheda.configurazione,
        "compilata_il": (scheda.compilata_il or date.today()).isoformat(),
        "membro": scheda.membro.strip(),
        "tipo_soggetto": scheda.tipo_soggetto,
        "contatori": [{"nome": c.nome.strip(), "tipologia": c.tipologia, "kwh_annui": c.kwh_annui,
                       "f1_kwh": c.f1_kwh, "f23_kwh": c.f23_kwh, "tensione": c.tensione,
                       # a chi coordina arriva solo la forma media: i giorni veri di una famiglia restano suoi
                       "curva": c.curva.model_dump(mode="json", exclude={"giorni_veri"}) if c.curva else None}
                      for c in scheda.contatori],
    }, ensure_ascii=False, indent=2)


def leggi_scheda(dati: str | bytes) -> Scheda:
    """Rilegge una scheda ricevuta. Solleva ValueError con un messaggio leggibile."""
    if len(dati) > MAX_BYTE:
        raise ValueError("file troppo grande per essere una scheda dei consumi")
    try:
        c = json.loads(dati)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("non è una scheda dei consumi (file illeggibile)") from None
    if not isinstance(c, dict) or c.get("formato") != FORMATO:
        raise ValueError("non è una scheda dei consumi di cersim")
    if c.get("versione") != VERSIONE:
        raise ValueError("scheda di una versione diversa del simulatore")

    def testo(v) -> str:
        return v if isinstance(v, str) else ""

    contatori = c.get("contatori")
    if not isinstance(contatori, list) or not all(isinstance(x, dict) for x in contatori):
        raise ValueError("elenco dei contatori non valido")
    try:
        compilata = date.fromisoformat(c["compilata_il"]) if isinstance(c.get("compilata_il"), str) else None
    except ValueError:
        compilata = None

    def curva(x: dict) -> CurvaMisurata | None:
        if x.get("curva") is None:
            return None
        try:
            return CurvaMisurata.model_validate(x["curva"])
        except ValidationError:
            raise ValueError("i consumi misurati allegati non sono validi") from None

    scheda = Scheda(
        membro=testo(c.get("membro")),
        tipo_soggetto=testo(c.get("tipo_soggetto")),
        contatori=[Contatore(nome=testo(x.get("nome")), tipologia=testo(x.get("tipologia")),
                             kwh_annui=x.get("kwh_annui"), f1_kwh=x.get("f1_kwh"), f23_kwh=x.get("f23_kwh"),
                             tensione=testo(x.get("tensione")) or "BT", curva=curva(x))
                   for x in contatori[: MAX_CONTATORI + 1]],
        configurazione=testo(c.get("configurazione")) or None,
        compilata_il=compilata,
    )
    errori = controlla(scheda)
    if errori:
        raise ValueError("; ".join(errori))
    return scheda


def _etichette_contatori(scheda: Scheda) -> list[str]:
    if len(scheda.contatori) == 1:
        return [scheda.membro.strip()]
    return [f"{scheda.membro.strip()}, {c.nome.strip()}" for c in scheda.contatori]


def unisci_schede(punti: pd.DataFrame, schede: list[Scheda],
                  curve: dict[str, CurvaMisurata] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Aggiunge i contatori delle schede alla tabella del passo 2.

    Una scheda rimandata dallo stesso membro aggiorna le sue righe; un contatore con lo stesso nome di
    quello di un altro membro riceve un suffisso, così nessuno sovrascrive i dati di un altro. Le curve misurate
    allegate finiscono in `curve`, con l'etichetta del contatore nella tabella."""
    righe = [r for r in tipizza_punti(punti).to_dict("records")
             if any(v is not None and not (isinstance(v, float) and pd.isna(v)) for v in r.values())]
    messaggi = []
    aggiunti, aggiornati = 0, []
    for scheda in schede:
        for contatore, etichetta in zip(scheda.contatori, _etichette_contatori(scheda)):
            nuova = {"Punto": etichetta, "Membro": scheda.membro.strip(), "Tipo soggetto": scheda.tipo_soggetto,
                     "Tipologia consumo": contatore.tipologia, "kWh annui": contatore.kwh_annui,
                     "F1 kWh": contatore.f1_kwh, "F23 kWh": contatore.f23_kwh, "Tensione": contatore.tensione}
            stesso = next((r for r in righe if r["Punto"] == etichetta), None)
            if stesso is not None and stesso["Membro"] == nuova["Membro"]:
                nuova["Area convenzionale GSE"] = stesso.get("Area convenzionale GSE")  # la inserisce chi coordina
                stesso.update(nuova)
                aggiornati.append(etichetta)
                if curve is not None and contatore.curva is not None:
                    curve[etichetta] = contatore.curva
                continue
            if stesso is not None:
                k = 2
                while any(r["Punto"] == f"{etichetta} ({k})" for r in righe):
                    k += 1
                nuova["Punto"] = f"{etichetta} ({k})"
                messaggi.append(f"Il contatore '{etichetta}' c'era già per un altro membro: aggiunto come "
                                f"'{nuova['Punto']}'")
            righe.append(nuova)
            aggiunti += 1
            if curve is not None and contatore.curva is not None:
                curve[nuova["Punto"]] = contatore.curva
    if aggiunti or aggiornati:
        # chi coordina vede chi ha sostituito dati già presenti (per esempio due famiglie con lo stesso nome)
        dettaglio = f" ({', '.join(aggiornati)})" if aggiornati else ""
        messaggi.insert(0, f"Contatori aggiunti: {aggiunti}; aggiornati: {len(aggiornati)}{dettaglio}.")
    return tipizza_punti(pd.DataFrame(righe, columns=COLONNE_PUNTI)), messaggi


def nome_file(scheda: Scheda) -> str:
    base = unicodedata.normalize("NFKD", scheda.membro).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower()[:40] or "scheda"
    return f"consumi_{base}.json"


def link_famiglie(indirizzo_app: str, configurazione: str | None = None) -> str:
    """Link da girare a famiglie e attività: apre l'app nel modulo della scheda dei consumi."""
    parti = urlsplit(indirizzo_app)
    parametri = {"modulo": MODULO}
    if configurazione and configurazione.strip():
        parametri["per"] = configurazione.strip()[:MAX_TESTO]
    return urlunsplit((parti.scheme, parti.netloc, parti.path or "/", urlencode(parametri), ""))
