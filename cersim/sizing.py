"""Dimensionamento di UN impianto alla volta (gli altri restano fissi).

Per ogni taglia della griglia (che include le soglie normative 200/600 kW della
potenza nominale GSE e i salti di costo della tabella CAPEX, più un
raffinamento attorno al massimo) si rieseguono bilancio orario ed economia
sugli scenari indicati. Il criterio è il VAN CONSOLIDATO mediano; accanto si
mostra il VAN dell'investitore, segnalando le taglie in cui è negativo.

Con qualità dati `C` la funzione restituisce la curva ma NESSUNA taglia
indicata: i numeri servono solo a esplorare. Nessuna taglia neppure quando
tutte hanno VAN consolidato negativo: l'alternativa "non investire" vale 0 €.
Il contributo in capitale è escluso dalla curva: l'atto di concessione vale
per il progetto approvato, non per qualunque taglia.
"""

from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np

from cersim.economics import ParametriEconomici, capex, costruisci_ledger, kpi
from cersim.eligibility import check
from cersim.model import Configuration, Plant
from cersim.normativa import assunzioni_economiche, pacchetto_normativo
from cersim.prices import PriceSeries
from cersim.pv import PVProfile
from cersim.scenari import Scenario, esegui_scenari, qualita_complessiva


@dataclass(frozen=True)
class PuntoCurva:
    potenza_moduli_kwp: float
    potenza_nominale_gse_kw: float
    van_consolidato_mediano: float
    van_consolidato_min: float
    van_consolidato_max: float
    van_investitore_mediano: float
    quota_condivisa_su_immessa: float  # mediana, primo anno intero
    copertura_consumi: float
    van_investitore_min: float = 0.0
    van_investitore_max: float = 0.0
    euro_anno_membri: float = 0.0  # mediana: netto del primo anno intero dei membri che non investono, in tutto
    payback_investitore: int | None = None  # mediana degli scenari (None se in metà o più non rientra)
    # quota del netto ai membri oltre la quale chi investe non rientra, nello scenario peggiore
    # (1.0 = rientra anche dando tutto ai membri; None = non rientra neanche tenendo tutto)
    quota_pareggio: float | None = None
    costo_eur: float = 0.0

    @property
    def investitore_in_perdita(self) -> bool:
        return self.van_investitore_mediano < 0


@dataclass
class RisultatoDimensionamento:
    impianto: str
    curva: list[PuntoCurva]
    qualita: str
    taglia_indicata: PuntoCurva | None
    motivo: str
    note: list[str] = field(default_factory=list)

    @property
    def dicitura(self) -> str:
        if self.taglia_indicata is None:
            testo = self.motivo
        else:
            testo = (f"Taglia con il beneficio netto mediano più alto negli scenari simulati: "
                     f"{self.taglia_indicata.potenza_moduli_kwp:.1f} kWp".replace(".", ","))
        return " ".join([testo, *self.note])


def _con_potenza(config: Configuration, plant: Plant, kwp: float) -> Configuration:
    rapporto = plant.potenza_moduli_kwp / plant.potenza_inverter_kw
    modifiche = {"potenza_moduli_kwp": kwp, "potenza_inverter_kw": kwp / rapporto}
    if plant.costo_preventivo_eur is not None:  # stesso costo al kWp del preventivo
        modifiche["costo_preventivo_eur"] = plant.costo_preventivo_eur * kwp / plant.potenza_moduli_kwp
    nuovo = plant.model_copy(update=modifiche)
    return config.model_copy(update={"plants": [nuovo if p.id == plant.id else p for p in config.plants]})


def griglia(plant: Plant, n_punti: int = 10) -> list[float]:
    """Taglie DC da valutare, con le soglie normative e di costo convertite in kWp DC."""
    massimo = plant.max_moduli_kwp
    rapporto_dc_ac = plant.potenza_moduli_kwp / plant.potenza_inverter_kw
    punti = set(np.linspace(massimo / n_punti, massimo, n_punti).round(2))

    def dc_per_nominale(kw):  # potenza nominale = min(DC, DC/rapporto)
        return kw * max(1.0, rapporto_dc_ac)

    soglie_nominali = [f.fino_a_kw for f in pacchetto_normativo().tip.fasce[:-1]]
    ipotesi = assunzioni_economiche()
    soglie_costo = [f.fino_a_kw for f in ipotesi.capex.fasce[:-1]]
    for kw in soglie_nominali:
        punti |= {round(dc_per_nominale(kw), 2), round(dc_per_nominale(kw) * 1.01, 2)}
    for kw in soglie_costo:
        dc = {"DC": kw, "AC": kw * rapporto_dc_ac, "nominale_GSE": dc_per_nominale(kw)}[ipotesi.capex.base_potenza]
        punti |= {round(dc, 2), round(dc * 1.01, 2)}
    punti.add(round(plant.potenza_moduli_kwp, 2))
    return sorted(p for p in punti if 0 < p <= massimo + 1e-9)


def _quota_pareggio(config, report, params, esiti, oggi) -> float | None:
    """Quota del netto ai membri fino alla quale chi investe rientra (VAN ≥ 0) in tutti gli scenari.

    Il VAN di chi investe cala in modo lineare con la quota: bastano gli estremi 0 e 1, ricalcolando solo
    il ledger (fisica e contributi restano quelli dello scenario)."""
    quote = []
    for e in esiti:
        van = []
        for q in (0.0, 1.0):
            led = costruisci_ledger(config, report, e.energia, None, replace(params, quota_membri=q),
                                    contributi=e.ledger.contributi, oggi=oggi)
            van.append(kpi(config, led).van_investitore)
        tutto_a_chi_investe, tutto_ai_membri = van
        if tutto_a_chi_investe < 0:
            return None
        if tutto_ai_membri >= 0:
            quote.append(1.0)
        else:
            quote.append(tutto_a_chi_investe / (tutto_a_chi_investe - tutto_ai_membri))
    return min(quote) if quote else None


def dimensiona(
    config: Configuration,
    plant_id: str,
    params: ParametriEconomici,
    pv_per_anno: dict[int, dict[str, PVProfile]],
    prezzi: dict[int, PriceSeries],
    scenari: list[Scenario],
    *,
    n_punti: int = 10,
    n_anni: int | None = None,
    oggi: date | None = None,
) -> RisultatoDimensionamento:
    plant = next(p for p in config.plants if p.id == plant_id)
    note = []
    if plant.contributo_capitale is not None:
        plant = plant.model_copy(update={"contributo_capitale": None})
        config = config.model_copy(update={"plants": [plant if p.id == plant_id else p for p in config.plants]})
        note.append("La curva non comprende il contributo in capitale: l'atto di concessione vale per il progetto "
                    "approvato, non per qualunque taglia.")
    if plant.costo_preventivo_eur is not None:
        note.append("Per le altre taglie il costo è stimato con lo stesso costo al kWp del preventivo.")

    def valuta(kwp: float) -> tuple[PuntoCurva, str] | None:
        variante = _con_potenza(config, plant, kwp)
        report = check(variante)
        if not report.supportata:
            return None
        esiti = esegui_scenari(variante, report, params, pv_per_anno, prezzi, scenari, n_anni=n_anni, oggi=oggi)
        cons = [e.kpi.van_consolidato for e in esiti]
        inv = [e.kpi.van_investitore for e in esiti]
        tot = [(e.energia.anni[1] if len(e.energia.anni) > 1 else e.energia.anni[0]).totali() for e in esiti]
        nuovo = next(p for p in variante.plants if p.id == plant_id)
        membri = [sum(v for m, v in e.kpi.euro_anno_per_membro.items() if m != e.kpi.investitore) for e in esiti]
        rientri = sorted(np.inf if e.kpi.payback_investitore is None else e.kpi.payback_investitore for e in esiti)
        rientro = rientri[(len(rientri) - 1) // 2]
        punto = PuntoCurva(
            potenza_moduli_kwp=kwp,
            potenza_nominale_gse_kw=nuovo.potenza_nominale_gse,
            van_consolidato_mediano=float(np.median(cons)),
            van_consolidato_min=float(np.min(cons)),
            van_consolidato_max=float(np.max(cons)),
            van_investitore_mediano=float(np.median(inv)),
            quota_condivisa_su_immessa=float(np.median([t["quota_condivisa_su_immessa"] for t in tot])),
            copertura_consumi=float(np.median([t["copertura_consumi"] for t in tot])),
            van_investitore_min=float(np.min(inv)),
            van_investitore_max=float(np.max(inv)),
            euro_anno_membri=float(np.median(membri)),
            payback_investitore=None if np.isinf(rientro) else int(rientro),
            quota_pareggio=_quota_pareggio(variante, report, params, esiti, oggi),
            costo_eur=capex(nuovo, assunzioni_economiche(), params.fattore_capex),
        )
        return punto, qualita_complessiva(variante, pv_per_anno, esiti)

    valutati: dict[float, PuntoCurva] = {}
    qualita = "B"
    for kwp in griglia(plant, n_punti):
        esito = valuta(kwp)
        if esito:
            valutati[kwp], q = esito
            qualita = max(qualita, q)

    if valutati:  # raffinamento attorno al massimo
        ordinati = sorted(valutati)
        i = int(np.argmax([valutati[k].van_consolidato_mediano for k in ordinati]))
        sinistra, destra = ordinati[max(0, i - 1)], ordinati[min(len(ordinati) - 1, i + 1)]
        for kwp in np.linspace(sinistra, destra, 5)[1:-1].round(2):
            if kwp not in valutati:
                esito = valuta(float(kwp))
                if esito:
                    valutati[float(kwp)], q = esito
                    qualita = max(qualita, q)

    curva = [valutati[k] for k in sorted(valutati)]
    if not curva:
        return RisultatoDimensionamento(plant_id, [], qualita, None, "Nessuna taglia supportata", note)
    migliore = max(curva, key=lambda p: p.van_consolidato_mediano)
    if migliore.van_consolidato_mediano <= 0:
        note.insert(0, "In nessuna taglia simulata il beneficio netto della configurazione è positivo: "
                       "l'alternativa migliore è non investire (0 €).")
    if qualita == "C":
        return RisultatoDimensionamento(plant_id, curva, qualita, None,
                                        "Qualità C, dati tipici o semplificati: curva esplorativa, nessuna taglia "
                                        "indicata.", note)
    if migliore.van_consolidato_mediano <= 0:
        return RisultatoDimensionamento(plant_id, curva, qualita, None, "Nessuna taglia indicata.", note)
    return RisultatoDimensionamento(plant_id, curva, qualita, migliore, "", note)
