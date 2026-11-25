"""Checklist di ammissibilità v1, con esito a tre valori.

Ogni requisito è `ammesso`, `non_ammesso` o `sconosciuto`, con il motivo.
"Sconosciuto" non vale mai come "ammesso": i contributi che ne dipendono
vanno presentati come condizionali.

Tre livelli di esito:
- `non_supportati`: casi fuori dall'ambito della v1 (impianti esistenti, oltre
  1 MW, fuori dall'edificio nel gruppo…). La simulazione li rifiuta.
- esiti per configurazione e per impianto (TIP, CACV, contributo in capitale).
- `da_verificare`: requisiti che lo strumento non può controllare (statuto,
  adesione volontaria, controllo…), da far verificare a un professionista.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from cersim.model import TERZO, Configuration, Plant, TipoConfigurazione
from cersim.normativa import classificazione_soggetti, pacchetto_normativo

DATA_RIFERIMENTO_IMPIANTI_NUOVI = date(2021, 12, 16)  # entrata in vigore del D.Lgs. 199/2021
POTENZA_MAX_KW = 1000.0


class Stato(str, Enum):
    AMMESSO = "ammesso"
    NON_AMMESSO = "non_ammesso"
    SCONOSCIUTO = "sconosciuto"


@dataclass(frozen=True)
class Esito:
    stato: Stato
    motivo: str

    @property
    def ammesso(self) -> bool:
        return self.stato is Stato.AMMESSO


def combina(*esiti: Esito) -> Stato:
    """Il peggiore degli esiti: non_ammesso > sconosciuto > ammesso."""
    stati = {e.stato for e in esiti}
    if Stato.NON_AMMESSO in stati:
        return Stato.NON_AMMESSO
    if Stato.SCONOSCIUTO in stati:
        return Stato.SCONOSCIUTO
    return Stato.AMMESSO


def _peggiore(*esiti: Esito) -> Esito:
    stato = combina(*esiti)
    motivi = [e.motivo for e in esiti if e.stato is stato]
    return Esito(stato, "; ".join(motivi))


@dataclass(frozen=True)
class EsitiImpianto:
    tip: Esito
    cacv: Esito
    contributo_capitale: Esito | None


@dataclass
class EligibilityReport:
    configurazione: dict[str, Esito]
    impianti: dict[str, EsitiImpianto]
    non_supportati: list[str] = field(default_factory=list)
    da_verificare: list[str] = field(default_factory=list)

    @property
    def stato_configurazione(self) -> Stato:
        return combina(*self.configurazione.values())

    @property
    def supportata(self) -> bool:
        return not self.non_supportati

    @property
    def condizionale(self) -> bool:
        """True se qualche contributo dipende da requisiti non verificati."""
        esiti = list(self.configurazione.values())
        for e in self.impianti.values():
            esiti += [e.tip, e.cacv]
        return combina(*esiti) is Stato.SCONOSCIUTO


class UnsupportedConfigurationError(ValueError):
    def __init__(self, motivi: list[str]):
        super().__init__("Configurazione non supportata in v1:\n- " + "\n- ".join(motivi))
        self.motivi = motivi


def check(config: Configuration) -> EligibilityReport:
    non_supportati: list[str] = []
    conf: dict[str, Esito] = {}

    conf["soci"] = _soci(config)
    conf["cabina_primaria"] = _cabina(config)
    if config.tipo is TipoConfigurazione.GRUPPO:
        non_supportati += _perimetro_gruppo(config)

    impianti: dict[str, EsitiImpianto] = {}
    for plant in config.plants:
        non_supportati += _impianto_supportato(config, plant)
        base = _peggiore(conf["soci"], conf["cabina_primaria"])
        tip = _peggiore(base, _impianto_nuovo_rispetto_costituzione(config, plant), _termine_accesso_tip(plant))
        impianti[plant.id] = EsitiImpianto(
            tip=tip,
            cacv=base,
            contributo_capitale=_contributo(plant),
        )

    return EligibilityReport(
        configurazione=conf,
        impianti=impianti,
        non_supportati=non_supportati,
        da_verificare=_da_verificare(config),
    )


def assert_supported(report: EligibilityReport) -> None:
    if not report.supportata:
        raise UnsupportedConfigurationError(report.non_supportati)


def _soci(config: Configuration) -> Esito:
    if config.tipo is not TipoConfigurazione.CER:
        return Esito(Stato.AMMESSO, "Gruppo di autoconsumatori: nessun requisito sui soci della CER")
    soggetti = classificazione_soggetti().soggetti
    esiti = []
    for m in config.members:
        voce = soggetti[m.tipo_soggetto.value]
        stato = Stato(voce.ammissibile_socio_CER)
        if stato is not Stato.AMMESSO:
            esiti.append(Esito(stato, f"{m.nome}: {voce.nota or m.tipo_soggetto.value}"))
    if not esiti:
        return Esito(Stato.AMMESSO, "Tutti i membri sono di un tipo ammesso nella CER")
    return _peggiore(*esiti)


def _cabina(config: Configuration) -> Esito:
    if config.tipo is TipoConfigurazione.GRUPPO:
        return Esito(Stato.AMMESSO, "Gruppo: tutti i punti nello stesso edificio")
    mancanti = [c.id for c in config.connection_points if not c.area_convenzionale]
    if mancanti:
        return Esito(
            Stato.SCONOSCIUTO,
            "Stessa cabina primaria non verificata: manca l'area convenzionale (mappa GSE) per "
            + ", ".join(mancanti),
        )
    aree = {c.area_convenzionale for c in config.connection_points}
    if len(aree) > 1:
        return Esito(Stato.NON_AMMESSO, "I punti appartengono ad aree convenzionali diverse: " + ", ".join(sorted(aree)))
    return Esito(Stato.AMMESSO, f"Tutti i punti nell'area convenzionale {aree.pop()}")


def _perimetro_gruppo(config: Configuration) -> list[str]:
    motivi = []
    for c in config.connection_points:
        if c.edificio_id != config.edificio_id_gruppo:
            motivi.append(f"Il punto {c.id} non è nell'edificio del gruppo ({config.edificio_id_gruppo})")
    for p in config.plants:
        if not p.nell_edificio:
            motivi.append(f"L'impianto {p.id} è fuori dall'edificio: nel gruppo la v1 supporta solo impianti nell'edificio")
    return motivi


def _impianto_supportato(config: Configuration, plant: Plant) -> list[str]:
    motivi = []
    if plant.potenza_nominale_gse > POTENZA_MAX_KW:
        motivi.append(f"L'impianto {plant.id} supera 1 MW di potenza nominale GSE")
    if plant.data_entrata_esercizio < DATA_RIFERIMENTO_IMPIANTI_NUOVI:
        motivi.append(
            f"L'impianto {plant.id} è entrato in esercizio prima del 16/12/2021: "
            "impianti esistenti e potenziamenti non sono supportati in v1"
        )
    return motivi


def _impianto_nuovo_rispetto_costituzione(config: Configuration, plant: Plant) -> Esito:
    if config.data_costituzione is None:
        return Esito(Stato.SCONOSCIUTO, "Data di costituzione non indicata: requisito 'impianto nuovo' non verificabile")
    if plant.data_entrata_esercizio < config.data_costituzione:
        return Esito(
            Stato.SCONOSCIUTO,
            f"L'impianto {plant.id} è entrato in esercizio prima della costituzione: ammesso solo nei casi "
            "previsti dalle deroghe, da verificare",
        )
    return Esito(Stato.AMMESSO, f"L'impianto {plant.id} entra in esercizio dopo la costituzione")


def _termine_accesso_tip(plant: Plant) -> Esito:
    termine = pacchetto_normativo().tip.termine_accesso_entrata_esercizio
    if plant.data_entrata_esercizio > termine:
        return Esito(
            Stato.NON_AMMESSO,
            f"L'impianto {plant.id} entra in esercizio dopo il {termine:%d/%m/%Y}: il DM 414/2023 (art. 1 c. 2) non "
            "consente nuovi accessi alla tariffa premio dopo quella data, salvo proroghe",
        )
    return Esito(Stato.AMMESSO, f"L'impianto {plant.id} entra in esercizio entro il {termine:%d/%m/%Y}")


def _contributo(plant: Plant) -> Esito | None:
    if plant.contributo_capitale is None:
        return None
    if plant.investitore == TERZO:
        return Esito(
            Stato.NON_AMMESSO,
            "Il contributo in capitale non spetta a un soggetto esterno alla configurazione",
        )
    return Esito(
        Stato.AMMESSO,
        f"Contributo dichiarato come già concesso (atto: {plant.contributo_capitale.estremi_atto})",
    )


def _da_verificare(config: Configuration) -> list[str]:
    comuni = [
        "Contratto di diritto privato tra i partecipanti e nomina del referente",
        "Disponibilità degli impianti e delle superfici (titolo, autorizzazioni, connessione)",
    ]
    if config.tipo is TipoConfigurazione.CER:
        return [
            "Atto costitutivo e statuto della CER (soggetto di diritto autonomo, scopo principale di benefici "
            "ambientali, economici o sociali, non di profitti finanziari)",
            "Partecipazione aperta e volontaria, con diritto di recesso",
            "Controllo della CER da parte dei soci ammessi (persone fisiche, PMI, enti territoriali, ecc.)",
            "Per le PMI: la partecipazione non è l'attività commerciale o industriale principale",
            *comuni,
        ]
    return [
        "Tutti i partecipanti si trovano nello stesso edificio o condominio",
        "Per le imprese: la partecipazione non è l'attività commerciale o industriale principale",
        *comuni,
    ]
