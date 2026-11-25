from datetime import date

import pytest
from pydantic import ValidationError

from cersim.model import (
    DEFAULT_KWH_DOMESTICO,
    CapitalGrant,
    Configuration,
    ConnectionPoint,
    Fasce,
    Incasso,
    TERZO,
)
from conftest import configurazione, impianto, membro, punto


def test_configurazione_valida_e_roundtrip_json():
    cfg = configurazione()
    di_nuovo = Configuration.model_validate_json(cfg.model_dump_json())
    assert di_nuovo == cfg


def test_nan_e_campi_extra_rifiutati():
    with pytest.raises(ValidationError):
        punto("pod1", "fam1", kwh_annui=float("nan"))
    with pytest.raises(ValidationError):
        ConnectionPoint(id="p", titolare="t", tipologia_profilo="domestico", campo_inventato=1)


def test_un_solo_impianto_per_punto():
    with pytest.raises(ValidationError, match="Più impianti sullo stesso punto"):
        configurazione(plants=[impianto("a", "podc", "cond"), impianto("b", "podc", "cond")])


def test_riferimenti_sconosciuti():
    with pytest.raises(ValidationError, match="titolare sconosciuto"):
        configurazione(cps=[punto("pod1", "nessuno"), punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=1)])
    with pytest.raises(ValidationError, match="punto sconosciuto"):
        configurazione(plants=[impianto("a", "pod_x", "cond")])
    with pytest.raises(ValidationError, match="investitore sconosciuto"):
        configurazione(plants=[impianto("a", "podc", "esco")])


def test_investitore_terzo_ammesso_nello_schema():
    cfg = configurazione(plants=[impianto("a", "podc", TERZO)])
    assert cfg.plants[0].investitore == TERZO


def test_gruppo_richiede_edificio():
    with pytest.raises(ValidationError, match="edificio"):
        configurazione(tipo="gruppo", edificio_id_gruppo=None)


def test_regione_sconosciuta():
    with pytest.raises(ValidationError, match="Regione"):
        configurazione(regione="Atlantide")


def test_piu_punti_per_membro():
    cfg = configurazione(
        members=[membro("comune", "ente_territoriale")],
        cps=[
            punto("municipio", "comune", tipologia_profilo="pa_municipio", kwh_annui=30000),
            punto("scuola", "comune", tipologia_profilo="scuola", kwh_annui=20000),
        ],
        plants=[impianto("fv", "scuola", "comune")],
        tipo="CER",
    )
    assert [c.titolare for c in cfg.connection_points] == ["comune", "comune"]


def test_consumi():
    assert punto("p", "t").kwh_effettivi == DEFAULT_KWH_DOMESTICO
    assert punto("p", "t").kwh_da_default
    with pytest.raises(ValidationError, match="consumo annuo"):
        punto("p", "t", tipologia_profilo="pmi")
    with pytest.raises(ValidationError, match="5%"):
        punto("p", "t", kwh_annui=3000, fasce=Fasce(f1=1000, f23=1000))
    p = punto("p", "t", fasce=Fasce(f1=1000, f23=1700))
    assert p.kwh_effettivi == 2700 and not p.kwh_da_default


def test_fasce():
    with pytest.raises(ValidationError):
        Fasce(f1=1000, f2=500)  # manca F3
    with pytest.raises(ValidationError):
        Fasce(f1=1000, f2=500, f3=500, f23=1000)  # entrambe le forme
    assert Fasce(f1=1000, f2=500, f3=700).totale == 2200


def test_punto_sola_immissione():
    with pytest.raises(ValidationError, match="sola immissione"):
        ConnectionPoint(id="p", titolare="t", ruolo="sola_immissione", kwh_annui=100)
    with pytest.raises(ValidationError, match="non ha un impianto"):
        configurazione(cps=[punto("pod1", "fam1"), ConnectionPoint(id="pod_fv", titolare="cond", ruolo="sola_immissione")],
                       plants=[impianto("fv", "pod1", "cond")])


def test_potenza_nominale_gse_e_date():
    p = impianto("a", "podc", "cond", kwp=210, kw_ac=180)
    assert p.potenza_nominale_gse == 180
    assert p.max_moduli_kwp == 210
    assert p.inizio_incentivazione == p.decorrenza_servizio == p.decorrenza_vendita == date(2027, 5, 1)
    with pytest.raises(ValidationError, match="precede"):
        impianto("a", "podc", "cond", data_decorrenza_servizio_cacer=date(2026, 1, 1))


def test_contributo_capitale():
    with pytest.raises(ValidationError, match="intensità"):
        CapitalGrant(importo_eur=10000, estremi_atto="n. 1")
    with pytest.raises(ValidationError, match="scadenzario"):
        CapitalGrant(importo_eur=10000, intensita=0.4, estremi_atto="n. 1",
                     scadenzario_incassi=[Incasso(data=date(2027, 6, 1), importo_eur=3000)])
    ok = CapitalGrant(importo_eur=10000, fattore_F=0.5, estremi_atto="n. 1",
                      scadenzario_incassi=[Incasso(data=date(2027, 6, 1), importo_eur=3000),
                                           Incasso(data=date(2028, 6, 1), importo_eur=7000)])
    assert ok.fattore_F == 0.5
