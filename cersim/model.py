"""Schema dei dati di una configurazione (CER o gruppo di autoconsumatori).

Entità:
- `Member`: un soggetto (famiglia, comune, negozio…) con il suo tipo giuridico.
- `ConnectionPoint`: un punto di connessione (POD). È l'unità del bilancio
  energetico: un membro può averne più di uno. Può avere una batteria privata
  dietro il contatore (`BatteriaCasa`, dal profilo energetico della casa).
- `Plant`: un impianto FV, sempre collegato a un punto di connessione
  (al massimo un impianto per punto in v1).
- `Configuration`: l'insieme, con tipo (CER / gruppo) e luogo.

La validazione rifiuta dati incoerenti (riferimenti mancanti, NaN, valori
fuori scala) prima di qualunque calcolo. Le regole normative di
ammissibilità sono in `eligibility.py`, non qui.
"""

from datetime import date
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cersim.geo import normalizza_regione

DEFAULT_KWH_DOMESTICO = 2700.0  # famiglia tipo ARERA: 4 persone, 3 kW, residente

MAX_MEMBRI = 200
MAX_PUNTI = 200
CELLE_GIORNI_VERI = 36  # tipo di giorno × mese
GIORNI_PER_CELLA = 6  # sul benchmark OPSD bastano: oltre, la sovrastima non scende e il file cresce
MAX_IMPIANTI = 50
MAX_KWH_ANNUI = 10_000_000.0  # 10 GWh
MAX_KWP = 5_000.0

TERZO = "terzo"  # soggetto esterno alla configurazione (es. una ESCo)
# Conti del ledger che non sono membri (economics.py). Un membro con lo stesso
# identificativo confonderebbe i flussi, quindi questi nomi sono riservati.
CONFIGURAZIONE = "configurazione"
GSE = "GSE"
MERCATO = "mercato"
FORNITORI = "fornitori"
BOLLETTA = "bolletta_evitata"
ID_RISERVATI = frozenset({CONFIGURAZIONE, GSE, MERCATO, FORNITORI, BOLLETTA, TERZO})

Id = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")]
Nome = Annotated[str, Field(min_length=1, max_length=120)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)


class TipoConfigurazione(str, Enum):
    CER = "CER"
    GRUPPO = "gruppo"


class TipoSoggetto(str, Enum):
    PERSONA_FISICA = "persona_fisica"
    CONDOMINIO = "condominio"
    ENTE_TERRITORIALE = "ente_territoriale"
    ENTE_RELIGIOSO = "ente_religioso"
    TERZO_SETTORE = "terzo_settore"
    PMI = "pmi"
    GRANDE_IMPRESA = "grande_impresa"
    ALTRO = "altro"


class Tipologia(str, Enum):
    DOMESTICO = "domestico"
    UFFICIO_COMMERCIALE = "ufficio_commerciale"
    SCUOLA = "scuola"
    PA_MUNICIPIO = "pa_municipio"
    PMI = "pmi"


class Ruolo(str, Enum):
    BIDIREZIONALE = "bidirezionale"
    SOLA_IMMISSIONE = "sola_immissione"


class Tensione(str, Enum):
    BT = "BT"
    MT = "MT"


class Member(_Base):
    id: Id
    nome: Nome
    tipo_soggetto: TipoSoggetto


class Fasce(_Base):
    """Consumi annui per fascia (kWh), come in bolletta: F1/F2/F3 oppure F1/F23."""

    f1: float = Field(ge=0)
    f2: float | None = Field(default=None, ge=0)
    f3: float | None = Field(default=None, ge=0)
    f23: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _f2_f3_oppure_f23(self):
        separate = self.f2 is not None and self.f3 is not None
        if separate == (self.f23 is not None) or (self.f2 is None) != (self.f3 is None):
            raise ValueError("Indicare F2 e F3, oppure solo F23")
        if self.totale <= 0:
            raise ValueError("Il totale delle fasce deve essere positivo")
        return self

    @property
    def totale(self) -> float:
        return self.f1 + (self.f23 if self.f23 is not None else self.f2 + self.f3)


TIPI_GIORNO = ("feriale", "sabato", "festivo")
CELLE_CURVA = len(TIPI_GIORNO) * 12 * 24


class NaturaCurva(str, Enum):
    MISURATA = "misurata"  # dai file del distributore o del Portale Consumi (cersim.misure)
    CALCOLATA = "calcolata"  # da un modello, per esempio il simulatore della casa (cersim.curva_calcolata)


class CurvaMisurata(_Base):
    """Consumi orari di un contatore, ridotti a una forma media: kWh medi per tipo di giorno, mese e ora civile
    (ordine `TIPI_GIORNO` × mesi × ore). Di solito sono misurati: si ricavano dai file del distributore o del
    Portale Consumi con `cersim.misure` e non contengono il POD né le singole letture. Con `natura` calcolata
    vengono da un modello (`cersim.curva_calcolata`): la simulazione li usa allo stesso modo, la qualità dei dati
    no. I salvataggi senza `natura` sono curve misurate."""

    ore: tuple[float, ...]
    natura: NaturaCurva = NaturaCurva.MISURATA
    giorni: int | None = Field(default=None, ge=1)  # giorni con misure; solo per le curve misurate
    dal: date | None = None
    al: date | None = None
    kwh_annui: float = Field(ge=0, le=MAX_KWH_ANNUI)  # stima annua dalla forma media
    fonte: str = Field(max_length=80)
    # giorni veri senza data: (tipo di giorno × 12 + mese − 1, 24 valori in kWh). La media conserva i totali ma non i
    # picchi, e sovrastima la condivisione: la simulazione pesca da qui. I vecchi salvataggi non li hanno e usano la media.
    giorni_veri: tuple[tuple[int, tuple[float, ...]], ...] = ()
    # kWp di FV già tolti dai consumi (curve calcolate dalla versione 2 del formato): sono prelievi, non consumi lordi
    fv_sottratto_kwp: float | None = Field(default=None, gt=0, le=10_000)
    # capacità della batteria di casa già considerata nei prelievi (versione 3 del formato): riduce l'energia condivisa
    batteria_kwh: float | None = Field(default=None, gt=0, le=1_000)

    @model_validator(mode="after")
    def _forma(self):
        if len(self.ore) != CELLE_CURVA:
            raise ValueError(f"La curva dei consumi deve avere {CELLE_CURVA} valori")
        if any(v < 0 or v != v for v in self.ore):
            raise ValueError("La curva dei consumi ha valori negativi o non numerici")
        if self.kwh_annui > 0 and not any(self.ore):
            raise ValueError("La curva dei consumi è tutta a zero ma dichiara un consumo annuo")
        for cella, valori in self.giorni_veri:
            if not 0 <= cella < CELLE_GIORNI_VERI or len(valori) != 24 or any(not 0 <= v < float("inf") for v in valori):
                raise ValueError("La curva dei consumi ha un giorno misurato non valido")
        if any(sum(c == cella for c, _ in self.giorni_veri) > GIORNI_PER_CELLA for cella in {c for c, _ in self.giorni_veri}):
            raise ValueError("La curva dei consumi ha troppi giorni misurati")
        periodo = (self.giorni, self.dal, self.al)
        if self.natura is NaturaCurva.MISURATA:
            if None in periodo:
                raise ValueError("La curva misurata deve indicare giorni e periodo delle misure")
            if self.al < self.dal:
                raise ValueError("La curva misurata finisce prima di cominciare")
        elif periodo != (None, None, None):
            raise ValueError("Una curva calcolata non ha giorni né periodo di misura")
        return self

    @property
    def misurata(self) -> bool:
        return self.natura is NaturaCurva.MISURATA

    def valore(self, tipo_giorno: int, mese: int, ora: int) -> float:
        return self.ore[(tipo_giorno * 12 + mese - 1) * 24 + ora]


class BatteriaCasa(_Base):
    """Batteria privata dietro il contatore di un membro, dal profilo energetico della casa: si carica solo dal
    surplus dell'impianto sullo stesso punto e si scarica sui consumi del punto, con le regole del simulatore della
    casa (rendimento diviso in parti uguali fra carica e scarica, riserva, potenza massima). Non si carica dalla rete."""

    capacita_kwh: float = Field(gt=0, le=1_000)  # capacità utile
    potenza_kw: float = Field(gt=0, le=1_000)
    rendimento_pct: float = Field(gt=0, le=100)  # andata e ritorno
    riserva_pct: float = Field(default=0.0, ge=0, lt=100)


class FvProfilo(_Base):
    """Il FV dello scenario di un profilo energetico, come l'ha descritto chi l'ha scritto."""

    kwp: float = Field(gt=0, le=10_000)
    inclinazione: float = Field(ge=0, le=90)
    orientamento: float = Field(ge=-180, le=180)  # convenzione PVGIS: 0 = sud, 90 = ovest, -90 = est
    perdite_pct: float = Field(ge=0, le=50)
    esistente: bool


class ComuneProfilo(_Base):
    codice_istat: str = Field(pattern=r"^[0-9]{6}$")
    nome: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=35, le=48)
    lon: float = Field(ge=6, le=19)


class UsiProfilo(_Base):
    """Di cui dei consumi elettrici di uno scenario, come li ha calcolati il simulatore della casa (kWh all'anno)."""

    altri_usi_kwh: float | None = Field(default=None, ge=0, le=MAX_KWH_ANNUI)
    pompa_di_calore_kwh: float | None = Field(default=None, ge=0, le=MAX_KWH_ANNUI)
    raffrescamento_kwh: float | None = Field(default=None, ge=0, le=MAX_KWH_ANNUI)


class StimaProfilo(_Base):
    """Immissioni e autoconsumo annui stimati da chi ha scritto il profilo, solo per confronto (kWh)."""

    immissioni_kwh: float | None = Field(default=None, ge=0, le=MAX_KWH_ANNUI)
    autoconsumo_kwh: float | None = Field(default=None, ge=0, le=MAX_KWH_ANNUI)


class PrezzoBolletta(_Base):
    """Il prezzo variabile dell'elettricità nella bolletta della casa, imposte comprese, €/kWh prelevato.
    Con le fasce, ogni ora ARERA usa il prezzo della sua fascia; senza, vale `eur_kwh` in tutte le ore."""

    eur_kwh: float = Field(ge=0, le=1)
    fasce: dict[Literal["F1", "F2", "F3"], float] | None = None
    stato: str = Field(pattern=r"^(documentato|misurato|ipotizzato)$")

    @model_validator(mode="after")
    def _fasce_complete(self):
        if self.fasce is not None and (set(self.fasce) != {"F1", "F2", "F3"} or any(not 0 <= v <= 1 for v in self.fasce.values())):
            raise ValueError("Le fasce del prezzo in bolletta sono F1, F2 e F3, ciascuna tra 0 e 1 €/kWh")
        return self


class ProfiloPunto(_Base):
    """Lo scenario del profilo energetico caricato su un contatore, conservato per riscaricare il profilo senza
    perdite (`cersim.profilo.esporta_profilo`). I consumi stanno nella curva del punto, la batteria nel punto."""

    fonte: str = Field(max_length=40)
    motore: str | None = Field(default=None, max_length=80)
    data: date
    comune: ComuneProfilo | None = None
    scenario: str = Field(pattern=r"^[A-Za-z0-9-]{1,20}$")
    nome: str = Field(min_length=1, max_length=80)
    attuale: bool
    natura_consumi: str = Field(default="calcolato", pattern=r"^(calcolato|misurato)$")
    periodo: tuple[int, date, date] | None = None  # giorni, dal, al dei consumi misurati
    stato_consumi: str
    usi: UsiProfilo | None = None
    fv: FvProfilo | None = None
    prelievi_kwh: float = Field(ge=0, le=MAX_KWH_ANNUI)
    prelievi: tuple[float, ...]
    stima: StimaProfilo | None = None
    conta_fv: bool  # True: consumi prima del FV nella curva del punto, batteria sul punto, impianto al passo 3
    # con conta_fv False la curva del punto sono i prelievi: consumi e batteria si conservano qui per riscaricarli
    consumi_kwh: float | None = Field(default=None, ge=0, le=MAX_KWH_ANNUI)
    consumi: tuple[float, ...] | None = None
    batteria: BatteriaCasa | None = None
    # prezzo della bolletta della casa: decide il risparmio in bolletta dell'autoconsumo fisico di questo contatore
    bolletta: PrezzoBolletta | None = None

    @model_validator(mode="after")
    def _forma(self):
        for nome, ore in (("prelievi", self.prelievi), ("consumi", self.consumi)):
            if ore is not None and (len(ore) != CELLE_CURVA or any(not 0 <= v < float("inf") for v in ore)):
                raise ValueError(f"I {nome} del profilo devono avere {CELLE_CURVA} valori non negativi")
        if not self.conta_fv and self.consumi is None:
            raise ValueError("Il profilo con i soli prelievi deve conservare i consumi")
        return self


class ConnectionPoint(_Base):
    id: Id
    titolare: Id
    ruolo: Ruolo = Ruolo.BIDIREZIONALE
    codice_pod: str | None = Field(default=None, max_length=32)
    tipologia_profilo: Tipologia | None = None
    kwh_annui: float | None = Field(default=None, ge=0, le=MAX_KWH_ANNUI)
    fasce: Fasce | None = None
    tensione: Tensione = Tensione.BT
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    area_convenzionale: str | None = Field(default=None, max_length=64)
    edificio_id: str | None = Field(default=None, max_length=64)
    # consumi misurati (o calcolati, vedi `CurvaMisurata.natura`): se c'è, decide ora e quantità dei consumi al
    # posto della curva tipica. Il nome resta per i salvataggi.
    curva_misurata: CurvaMisurata | None = None
    batteria: BatteriaCasa | None = None
    profilo: ProfiloPunto | None = None

    @model_validator(mode="after")
    def _consumi_coerenti(self):
        if self.ruolo is Ruolo.SOLA_IMMISSIONE:
            if (self.tipologia_profilo is not None or self.fasce is not None or (self.kwh_annui or 0) > 0
                    or self.curva_misurata is not None or self.batteria is not None):
                raise ValueError(f"Il punto {self.id} è di sola immissione: non può avere consumi")
            return self
        if self.batteria is not None and self.curva_misurata is not None and (
                self.curva_misurata.fv_sottratto_kwp or self.curva_misurata.batteria_kwh):
            raise ValueError(f"Il punto {self.id} ha una batteria e consumi da cui sono già tolti FV o batteria: "
                             "la batteria sarebbe contata due volte")
        if self.profilo is not None and self.curva_misurata is None:
            raise ValueError(f"Il punto {self.id} ha un profilo energetico ma nessuna curva dei consumi")
        if self.tipologia_profilo is None:
            raise ValueError(f"Il punto {self.id} deve indicare la tipologia di consumo")
        if (self.kwh_annui is None and self.fasce is None and self.curva_misurata is None
                and self.tipologia_profilo is not Tipologia.DOMESTICO):
            raise ValueError(f"Il punto {self.id} deve indicare il consumo annuo (default solo per i domestici)")
        if self.fasce is not None and self.kwh_annui is not None:
            if abs(self.fasce.totale - self.kwh_annui) > 0.05 * max(self.kwh_annui, 1.0):
                raise ValueError(f"Il punto {self.id}: la somma delle fasce differisce di oltre il 5% dal consumo annuo")
        return self

    @property
    def kwh_da_default(self) -> bool:
        """True se il consumo non viene dalla bolletta ma dalla famiglia tipo ARERA."""
        return (self.ruolo is Ruolo.BIDIREZIONALE and self.kwh_annui is None and self.fasce is None
                and self.curva_misurata is None)

    @property
    def kwh_effettivi(self) -> float:
        if self.ruolo is Ruolo.SOLA_IMMISSIONE:
            return 0.0
        if self.curva_misurata is not None:
            return self.curva_misurata.kwh_annui
        if self.kwh_annui is not None:
            return self.kwh_annui
        if self.fasce is not None:
            return self.fasce.totale
        return DEFAULT_KWH_DOMESTICO


class Incasso(_Base):
    data: date
    importo_eur: float = Field(gt=0)


class CapitalGrant(_Base):
    """Contributo in conto capitale GIÀ CONCESSO (lo strumento non ne prevede l'accesso)."""

    importo_eur: float = Field(gt=0)
    intensita: float | None = Field(default=None, gt=0, le=1, description="quota dei costi ammessi, dall'atto")
    fattore_F: float | None = Field(default=None, ge=0, le=0.5, description="riduzione TIP, se indicata nell'atto")
    estremi_atto: str = Field(min_length=1, max_length=200)
    scadenzario_incassi: list[Incasso] | None = None

    @model_validator(mode="after")
    def _dati_atto(self):
        if self.intensita is None and self.fattore_F is None:
            raise ValueError("Indicare l'intensità del contributo o il fattore F riportati nell'atto di concessione")
        if self.scadenzario_incassi:
            totale = sum(i.importo_eur for i in self.scadenzario_incassi)
            if abs(totale - self.importo_eur) > 0.01 * self.importo_eur:
                raise ValueError("La somma dello scadenzario degli incassi deve coincidere con l'importo concesso")
        return self


class Plant(_Base):
    id: Id
    nome: Nome
    connection_point: Id
    potenza_moduli_kwp: float = Field(gt=0, le=MAX_KWP)
    potenza_inverter_kw: float = Field(gt=0, le=MAX_KWP)
    potenza_moduli_max_kwp: float | None = Field(default=None, gt=0, le=MAX_KWP)
    tilt: float = Field(default=30.0, ge=0, le=90)
    azimut: float = Field(default=0.0, ge=-180, le=180, description="convenzione PVGIS: 0 = sud, 90 = ovest, -90 = est")
    # tetto a due falde (di solito est e ovest) con un solo inverter: metà dei moduli per falda
    azimut_2: float | None = Field(default=None, ge=-180, le=180, description="orientamento della seconda falda")
    perdite_pct: float = Field(default=14.0, ge=0, le=50)
    investitore: Id
    proprietario: Id | None = None
    produttore: Id | None = None
    data_entrata_esercizio: date
    data_inizio_periodo_incentivazione: date | None = None
    data_decorrenza_servizio_cacer: date | None = None
    data_decorrenza_vendita: date | None = None
    nell_edificio: bool = True
    contributo_capitale: CapitalGrant | None = None
    # costo complessivo da preventivo (IVA esclusa); se manca si usa la tabella delle assunzioni economiche
    costo_preventivo_eur: float | None = Field(default=None, gt=0, le=MAX_KWP * 10_000)

    @model_validator(mode="after")
    def _coerenza(self):
        if self.potenza_moduli_max_kwp is not None and self.potenza_moduli_max_kwp < self.potenza_moduli_kwp:
            raise ValueError(f"Impianto {self.id}: la potenza massima installabile è minore di quella installata")
        for nome in ("data_inizio_periodo_incentivazione", "data_decorrenza_servizio_cacer", "data_decorrenza_vendita"):
            valore = getattr(self, nome)
            if valore is not None and valore < self.data_entrata_esercizio:
                raise ValueError(f"Impianto {self.id}: {nome} precede l'entrata in esercizio")
        return self

    @property
    def potenza_nominale_gse(self) -> float:
        """Potenza ai fini GSE: minore tra potenza dei moduli (DC) e degli inverter (AC)."""
        return min(self.potenza_moduli_kwp, self.potenza_inverter_kw)

    @property
    def max_moduli_kwp(self) -> float:
        return self.potenza_moduli_max_kwp or self.potenza_moduli_kwp

    @property
    def proprietario_effettivo(self) -> str:
        return self.proprietario or self.investitore

    @property
    def produttore_effettivo(self) -> str:
        return self.produttore or self.proprietario_effettivo

    @property
    def inizio_incentivazione(self) -> date:
        return self.data_inizio_periodo_incentivazione or self.data_entrata_esercizio

    @property
    def decorrenza_servizio(self) -> date:
        return self.data_decorrenza_servizio_cacer or self.data_entrata_esercizio

    @property
    def decorrenza_vendita(self) -> date:
        return self.data_decorrenza_vendita or self.data_entrata_esercizio


class Configuration(_Base):
    nome: Nome
    tipo: TipoConfigurazione
    indirizzo: str | None = Field(default=None, max_length=300)
    lat: float = Field(ge=35, le=48, description="Italia")
    lon: float = Field(ge=6, le=19, description="Italia")
    regione: str
    members: list[Member] = Field(min_length=1, max_length=MAX_MEMBRI)
    connection_points: list[ConnectionPoint] = Field(min_length=1, max_length=MAX_PUNTI)
    plants: list[Plant] = Field(default_factory=list, max_length=MAX_IMPIANTI)
    referente: Id | None = None
    edificio_id_gruppo: str | None = Field(default=None, max_length=64)
    data_costituzione: date | None = None

    @model_validator(mode="after")
    def _riferimenti(self):
        normalizza_regione(self.regione)  # solleva ValueError se sconosciuta
        member_ids = _unici("membri", [m.id for m in self.members])
        if riservati := sorted(member_ids & ID_RISERVATI):
            raise ValueError(f"Identificativo riservato usato per un membro: {', '.join(riservati)}")
        cp_ids = _unici("punti di connessione", [c.id for c in self.connection_points])
        _unici("impianti", [p.id for p in self.plants])

        for cp in self.connection_points:
            if cp.titolare not in member_ids:
                raise ValueError(f"Il punto {cp.id} ha un titolare sconosciuto: {cp.titolare}")

        impianti_per_punto: dict[str, str] = {}
        for p in self.plants:
            if p.connection_point not in cp_ids:
                raise ValueError(f"L'impianto {p.id} è collegato a un punto sconosciuto: {p.connection_point}")
            if p.connection_point in impianti_per_punto:
                raise ValueError(
                    f"Più impianti sullo stesso punto {p.connection_point} "
                    f"({impianti_per_punto[p.connection_point]}, {p.id}): non supportato in v1"
                )
            impianti_per_punto[p.connection_point] = p.id
            for ruolo in ("investitore", "proprietario", "produttore"):
                soggetto = getattr(p, ruolo)
                if soggetto is not None and soggetto != TERZO and soggetto not in member_ids:
                    raise ValueError(f"Impianto {p.id}: {ruolo} sconosciuto ({soggetto})")

        for cp in self.connection_points:
            if cp.ruolo is Ruolo.SOLA_IMMISSIONE and cp.id not in impianti_per_punto:
                raise ValueError(f"Il punto di sola immissione {cp.id} non ha un impianto")
            if cp.batteria is not None and cp.id not in impianti_per_punto:
                raise ValueError(f"Il punto {cp.id} ha la batteria di casa ma nessun impianto: la batteria si carica "
                                 "solo dal fotovoltaico dello stesso contatore. Aggiungi l'impianto o togli i consumi "
                                 "del profilo")

        if self.referente is not None and self.referente not in member_ids:
            raise ValueError(f"Referente sconosciuto: {self.referente}")
        if self.tipo is TipoConfigurazione.GRUPPO and not self.edificio_id_gruppo:
            raise ValueError("Un gruppo di autoconsumatori deve indicare l'edificio (edificio_id_gruppo)")
        return self

    @property
    def regione_normalizzata(self) -> str:
        return normalizza_regione(self.regione)

    def member(self, member_id: str) -> Member:
        return next(m for m in self.members if m.id == member_id)

    def connection_point(self, cp_id: str) -> ConnectionPoint:
        return next(c for c in self.connection_points if c.id == cp_id)

    def plant_on(self, cp_id: str) -> Plant | None:
        return next((p for p in self.plants if p.connection_point == cp_id), None)


def _unici(cosa: str, ids: list[str]) -> set[str]:
    visti: set[str] = set()
    for i in ids:
        if i in visti:
            raise ValueError(f"Identificativo duplicato tra i {cosa}: {i}")
        visti.add(i)
    return visti
