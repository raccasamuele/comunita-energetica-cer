"""Caricamento e validazione dei pacchetti versionati (normativo, economico, soggetti).

Ogni pacchetto ha data di revisione e di scadenza. Con il pacchetto normativo
scaduto i contributi non si calcolano (`PacchettoScadutoError`): l'app mostra
solo il bilancio energetico finché qualcuno non lo rivede sulle fonti.
"""

from datetime import date
from functools import cache
from importlib import resources
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PacchettoScadutoError(RuntimeError):
    pass


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class FasciaTip(_Base):
    fino_a_kw: float
    base_eur_mwh: float
    cap_eur_mwh: float


class Tip(_Base):
    prezzo_riferimento_eur_mwh: float
    fasce: list[FasciaTip]
    correzione_geografica_fv_eur_mwh: dict[str, float]
    durata_anni: int
    termine_accesso_entrata_esercizio: date
    F_massimo: float = Field(ge=0, le=1)
    intensita_per_F_massimo: float = Field(gt=0, le=1)


class Eccedenza(_Base):
    soglia_solo_tip: float
    soglia_con_contributo_capitale: float


class Cacv(_Base):
    trase_eur_mwh: dict[int, float]
    btau_max_eur_mwh: dict[int, float]
    coefficiente_perdite_evitate: dict[str, float]
    durata_anni: int
    rinnovo_oltre_durata: bool


class FasciaCorrispettivo(_Base):
    fino_a_kw: float
    fisso_eur_anno: float
    variabile_eur_kw_anno: float
    variabile_oltre_kw: float = 0.0  # la quota variabile vale solo sulla potenza oltre questa soglia


class CorrispettiviGse(_Base):
    fasce: list[FasciaCorrispettivo]


class ScaglioneRid(_Base):
    fino_a_kw: float
    eur_per_kw: float = Field(ge=0)


class Rid(_Base):
    verificato: bool
    esenti_fino_a_kw: float = Field(ge=0)
    scaglioni: list[ScaglioneRid]
    massimale_eur_anno: float = Field(ge=0)

    def onere_annuo(self, potenza_nominale_kw: float) -> float:
        """Tariffa GSE dell'anno per un impianto in ritiro dedicato: scaglioni progressivi, con massimale."""
        if potenza_nominale_kw <= self.esenti_fino_a_kw:
            return 0.0
        totale, inizio = 0.0, 0.0
        for s in self.scaglioni:
            if potenza_nominale_kw <= inizio:
                break
            totale += (min(potenza_nominale_kw, s.fino_a_kw) - inizio) * s.eur_per_kw
            inizio = s.fino_a_kw
        return min(totale, self.massimale_eur_anno)


class _Versionato(_Base):
    versione: str
    revisione: date
    scadenza: date

    def scaduto(self, oggi: date | None = None) -> bool:
        return (oggi or date.today()) > self.scadenza


class PacchettoNormativo(_Versionato):
    tip: Tip
    eccedenza: Eccedenza
    cacv: Cacv
    corrispettivi_gse: CorrispettiviGse
    rid: Rid

    @model_validator(mode="after")
    def _fasce_ordinate(self):
        for nome, fasce in (("tip", self.tip.fasce), ("corrispettivi_gse", self.corrispettivi_gse.fasce)):
            limiti = [f.fino_a_kw for f in fasce]
            if limiti != sorted(limiti):
                raise ValueError(f"{nome}: fasce non ordinate")
        return self

    def fascia_tip(self, potenza_nominale_kw: float) -> FasciaTip:
        for f in self.tip.fasce:
            if potenza_nominale_kw <= f.fino_a_kw:
                return f
        raise ValueError(f"Potenza oltre l'ultima fascia TIP: {potenza_nominale_kw} kW")

    def corrispettivo_gse_annuo(self, potenza_nominale_kw: float) -> float:
        for f in self.corrispettivi_gse.fasce:
            if potenza_nominale_kw <= f.fino_a_kw:
                return f.fisso_eur_anno + f.variabile_eur_kw_anno * max(0.0, potenza_nominale_kw - f.variabile_oltre_kw)
        raise ValueError(f"Potenza oltre l'ultima fascia dei corrispettivi: {potenza_nominale_kw} kW")

    @staticmethod
    def _valore_per_anno(tabella: dict[int, float], anno: int) -> float:
        """Valore dell'anno; per gli anni successivi all'ultimo noto, l'ultimo (congelato in termini reali)."""
        noti = sorted(tabella)
        precedenti = [a for a in noti if a <= anno]
        return tabella[precedenti[-1] if precedenti else noti[0]]

    def trase(self, anno: int) -> float:
        return self._valore_per_anno(self.cacv.trase_eur_mwh, anno)

    def btau(self, anno: int) -> float:
        return self._valore_per_anno(self.cacv.btau_max_eur_mwh, anno)


class FasciaCapex(_Base):
    fino_a_kw: float
    eur_per_kw: float


class Capex(_Base):
    base_potenza: Literal["DC", "AC", "nominale_GSE"]
    fasce: list[FasciaCapex]


class Impianto(_Base):
    om_quota_capex_anno: float
    assicurazione_quota_capex_anno: float
    sostituzione_inverter_eur_per_kw_ac: float
    anno_sostituzione_inverter: int
    smaltimento_eur_per_kwp: float
    degradazione_annua: float
    vita_utile_anni: int


class CostiConfigurazione(_Base):
    costituzione_eur: dict[str, float]
    gestione_eur_anno: dict[str, float]


class Finanza(_Base):
    tasso_sconto_reale: float


class Bolletta(_Base):
    costo_evitabile_eur_kwh: float


class Prezzi(_Base):
    media_eur_mwh: dict[Literal["basso", "base", "alto"], float]
    vendita_mercato_sconto: float = Field(ge=0, lt=1)


class AssunzioniEconomiche(_Versionato):
    capex: Capex
    impianto: Impianto
    configurazione: CostiConfigurazione
    finanza: Finanza
    prezzi: Prezzi
    bolletta: Bolletta

    def capex_eur_per_kw(self, potenza_kw: float) -> float:
        """Costo unitario della fascia (come nella fonte)."""
        for f in self.capex.fasce:
            if potenza_kw <= f.fino_a_kw:
                return f.eur_per_kw
        return self.capex.fasce[-1].eur_per_kw

    def capex_totale(self, potenza_kw: float) -> float:
        """Costo totale a scaglioni: ogni fascia di potenza al suo costo unitario.

        Applicare il costo della fascia a tutta la potenza farebbe costare meno un
        impianto appena sopra una soglia che uno appena sotto: a scaglioni il
        costo è continuo e crescente.
        """
        totale, inizio = 0.0, 0.0
        for f in self.capex.fasce:
            if potenza_kw <= inizio:
                break
            totale += (min(potenza_kw, f.fino_a_kw) - inizio) * f.eur_per_kw
            inizio = f.fino_a_kw
        if potenza_kw > inizio:
            totale += (potenza_kw - inizio) * self.capex.fasce[-1].eur_per_kw
        return totale


Flag = Literal["si", "no", "sconosciuto"]


class VoceSoggetto(_Base):
    ammissibile_socio_CER: Literal["ammesso", "non_ammesso", "sconosciuto"]
    soggetto_esente_F: Flag
    impresa_ai_fini_eccedenza: Flag
    nota: str | None = None


class ClassificazioneSoggetti(_Versionato):
    soggetti: dict[str, VoceSoggetto]


def _leggi(nome: str) -> dict:
    testo = resources.files("cersim.data").joinpath(nome).read_text(encoding="utf-8")
    return yaml.safe_load(testo)


@cache
def pacchetto_normativo() -> PacchettoNormativo:
    return PacchettoNormativo.model_validate(_leggi("parametri_normativi.yaml"))


@cache
def assunzioni_economiche() -> AssunzioniEconomiche:
    return AssunzioniEconomiche.model_validate(_leggi("assunzioni_economiche.yaml"))


@cache
def classificazione_soggetti() -> ClassificazioneSoggetti:
    return ClassificazioneSoggetti.model_validate(_leggi("classificazione_soggetti.yaml"))


def verifica_validita(pacchetto: _Versionato, oggi: date | None = None) -> None:
    if pacchetto.scaduto(oggi):
        raise PacchettoScadutoError(
            f"Il pacchetto {type(pacchetto).__name__} versione {pacchetto.versione} è scaduto il "
            f"{pacchetto.scadenza:%d/%m/%Y}: i contributi non vengono calcolati finché non viene rivisto sulle fonti."
        )
