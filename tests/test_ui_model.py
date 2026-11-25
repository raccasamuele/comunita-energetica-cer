import json
from datetime import date

import pandas as pd
import pytest

from cersim.model import TERZO, CapitalGrant, Fasce, Incasso, Ruolo
from conftest import configurazione, impianto, punto
from cersim.ui_model import (
    INVESTITORE_ESTERNO,
    MAX_JSON_BYTE,
    SOLA_IMMISSIONE,
    Generale,
    configurazione_da_tabelle,
    esporta_json,
    famiglie_tipo,
    impianti_vuoti,
    importa_json,
    tabelle_da_configurazione,
    tipizza_impianti,
    tipizza_punti,
)

GENERALE = Generale(nome="Prova", tipo="gruppo", lat=45.07, lon=7.69, regione="Piemonte",
                    data_costituzione=date(2027, 1, 1))


def _punti():
    df = famiglie_tipo(3)
    extra = pd.DataFrame([{"Punto": "Parti comuni", "Membro": "Condominio Via Roma", "Tipo soggetto": "Condominio",
                           "Tipologia consumo": "Municipio / uffici pubblici", "kWh annui": 4000, "Tensione": "BT"}])
    return tipizza_punti(pd.concat([df, extra], ignore_index=True))


def _impianti(**modifiche):
    riga = {"Impianto": "FV tetto", "Punto": "Parti comuni", "kWp moduli": 20, "kW inverter": 18,
            "Entrata in esercizio": date(2027, 5, 1), "Investitore": "Condominio Via Roma"}
    riga.update(modifiche)
    return tipizza_impianti(pd.DataFrame([riga]))


def test_tabelle_in_configurazione():
    esito = configurazione_da_tabelle(GENERALE, _punti(), _impianti())
    assert esito.errori == []
    cfg = esito.config
    assert len(cfg.members) == 4 and len(cfg.connection_points) == 4
    assert {c.edificio_id for c in cfg.connection_points} == {"edificio"}
    assert cfg.plants[0].potenza_nominale_gse == 18
    assert cfg.connection_points[0].kwh_da_default  # famiglia senza consumo → famiglia tipo ARERA


def test_tipi_per_l_editor():
    vuoti = impianti_vuoti()
    assert str(vuoti["kWp moduli"].dtype) == "float64"
    assert str(vuoti["Entrata in esercizio"].dtype).startswith("datetime64")
    assert str(famiglie_tipo(2)["kWh annui"].dtype) == "float64"


def test_membro_con_piu_punti_e_nomi_strani():
    punti = _punti()
    punti.loc[len(punti)] = {"Punto": "Garage", "Membro": "Condominio Via Roma", "Tipo soggetto": "Condominio",
                             "Tipologia consumo": "PMI / laboratorio", "kWh annui": 500, "Tensione": "BT"}
    punti.loc[0, "Membro"] = "Rossi & figli, n°1 (àèì)"
    esito = configurazione_da_tabelle(GENERALE, tipizza_punti(punti), _impianti())
    assert esito.errori == []
    titolari = [c.titolare for c in esito.config.connection_points]
    assert titolari.count(esito.config.members[-1].id) == 2


def test_membro_chiamato_come_un_conto_esterno():
    punti = _punti()
    punti.loc[0, "Membro"] = "GSE"
    esito = configurazione_da_tabelle(GENERALE, punti, _impianti())
    assert esito.errori == []
    gse = next(m for m in esito.config.members if m.nome == "GSE")
    assert gse.id == "GSE_2"


def test_errori_leggibili():
    punti = _punti()
    punti.loc[1, "Tipo soggetto"] = None
    errori = configurazione_da_tabelle(GENERALE, punti, _impianti()).errori
    assert any("tipo di soggetto" in e for e in errori)

    errori = configurazione_da_tabelle(GENERALE, _punti(), _impianti(Investitore=None)).errori
    assert any("investitore" in e for e in errori)

    punti = _punti()
    punti.loc[0, "F1 kWh"] = 900
    errori = configurazione_da_tabelle(GENERALE, punti, _impianti()).errori
    assert any("F23" in e for e in errori)

    errori = configurazione_da_tabelle(GENERALE, _punti(), _impianti(**{"kWp moduli": None})).errori
    assert any("kWp" in e for e in errori)

    assert configurazione_da_tabelle(GENERALE, tipizza_punti(pd.DataFrame()), _impianti()).errori


def test_righe_vuote_ignorate():
    punti = _punti()
    punti.loc[len(punti)] = {c: None for c in punti.columns}
    assert configurazione_da_tabelle(GENERALE, tipizza_punti(punti), _impianti()).errori == []


def test_pod_dedicato_e_investitore_esterno():
    esito = configurazione_da_tabelle(GENERALE, _punti(), _impianti(Punto=SOLA_IMMISSIONE))
    assert esito.errori == []
    cp = esito.config.connection_point(esito.config.plants[0].connection_point)
    assert cp.ruolo is Ruolo.SOLA_IMMISSIONE

    esterno = configurazione_da_tabelle(GENERALE, _punti(), _impianti(Investitore=INVESTITORE_ESTERNO))
    assert esterno.config.plants[0].investitore == TERZO
    assert configurazione_da_tabelle(GENERALE, _punti(),
                                     _impianti(Investitore=INVESTITORE_ESTERNO, Punto=SOLA_IMMISSIONE)).errori


def test_contributo_dalla_tabella():
    imp = _impianti(**{"Contributo concesso €": 8000, "Fattore F": 0.5, "Estremi atto": "Decreto 1",
                       "Data incasso contributo": date(2027, 9, 1)})
    grant = configurazione_da_tabelle(GENERALE, _punti(), imp).config.plants[0].contributo_capitale
    assert grant.fattore_F == 0.5 and grant.scadenzario_incassi[0].importo_eur == 8000


def test_cer_con_area_convenzionale():
    punti = _punti()
    punti["Area convenzionale GSE"] = "AC123"
    gen = Generale(nome="CER", tipo="CER", lat=45.07, lon=7.69, regione="Piemonte")
    cfg = configurazione_da_tabelle(gen, punti, _impianti()).config
    assert {c.area_convenzionale for c in cfg.connection_points} == {"AC123"}
    assert cfg.edificio_id_gruppo is None


def test_andata_e_ritorno_tabelle_e_json():
    cfg = configurazione_da_tabelle(GENERALE, _punti(), _impianti()).config
    generale, punti, impianti = tabelle_da_configurazione(cfg)
    di_nuovo = configurazione_da_tabelle(generale, punti, impianti).config
    assert di_nuovo.model_dump() == cfg.model_dump()

    testo = esporta_json(cfg, {"quota_membri": 0.5, "campo_estraneo": 1})
    cfg2, parametri = importa_json(testo)
    assert cfg2 == cfg and parametri == {"quota_membri": 0.5}


def _avanzata():
    """Configurazione creata dalla libreria, con campi che le tabelle non mostrano."""
    grant = CapitalGrant(importo_eur=2000, intensita=0.3, estremi_atto="Det. 1/2027",
                         scadenzario_incassi=[Incasso(data=date(2027, 6, 1), importo_eur=1000),
                                              Incasso(data=date(2028, 6, 1), importo_eur=1000)])
    cps = [punto("pod1", "fam1", codice_pod="IT001E00000001", fasce=Fasce(f1=900, f2=800, f3=1000)),
           punto("pod2", "fam2"), punto("pod3", "fam3"),
           punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=4000)]
    return configurazione(cps=cps, plants=[impianto(
        "fv1", "podc", "cond", contributo_capitale=grant, produttore="fam1", perdite_pct=12,
        data_decorrenza_servizio_cacer=date(2027, 9, 1), costo_preventivo_eur=25_000)])


def test_ricaricare_un_lavoro_non_cambia_la_configurazione():
    cfg = _avanzata()
    caricata, _ = importa_json(esporta_json(cfg, {}))
    di_nuovo = configurazione_da_tabelle(*tabelle_da_configurazione(caricata), base=caricata).config
    assert di_nuovo == cfg
    # anche un impianto fuori dall'edificio resta tale (e quindi non supportato nel gruppo)
    fuori = configurazione(plants=[impianto("fv1", "podc", "cond", nell_edificio=False)])
    assert not configurazione_da_tabelle(*tabelle_da_configurazione(fuori), base=fuori).config.plants[0].nell_edificio


def test_modifiche_in_tabella_prevalgono_sulla_base():
    cfg = _avanzata()
    generale, punti, impianti = tabelle_da_configurazione(cfg)
    impianti.loc[0, "kWp moduli"] = 30.0
    p = configurazione_da_tabelle(generale, punti, impianti, base=cfg).config.plants[0]
    assert p.potenza_moduli_kwp == 30 and p.produttore == "fam1"  # il resto non cambia
    assert len(p.contributo_capitale.scadenzario_incassi) == 2
    impianti.loc[0, "Contributo concesso €"] = 3000.0
    impianti.loc[0, "Fattore F"] = 0.2
    p = configurazione_da_tabelle(generale, punti, impianti, base=cfg).config.plants[0]
    assert p.contributo_capitale.importo_eur == 3000 and len(p.contributo_capitale.scadenzario_incassi) == 1


def test_costo_da_preventivo_dalla_tabella():
    cfg = configurazione_da_tabelle(GENERALE, _punti(), _impianti(**{"Costo da preventivo €": 24000})).config
    assert cfg.plants[0].costo_preventivo_eur == 24000


@pytest.mark.parametrize("contenuto, messaggio", [
    ("non è json", "JSON"),
    (json.dumps({"schema": 99}), "non riconosciuto"),
    (json.dumps({"schema": 1, "configurazione": {"nome": "x"}}), "non valida"),
])
def test_json_non_valido(contenuto, messaggio):
    with pytest.raises(ValueError, match=messaggio):
        importa_json(contenuto)


def test_json_troppo_grande():
    with pytest.raises(ValueError, match="grande"):
        importa_json("x" * (MAX_JSON_BYTE + 1))
