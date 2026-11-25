import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cersim.economics import ParametriEconomici
from cersim.proposta import SceltaTetto, entrata_predefinita, proponi, scegli_taglie, tabella_impianto
from cersim.pv import synthetic_profile
from cersim.simulate import pv_profiles_for
from cersim.sizing import PuntoCurva
from cersim.ui_model import (
    COLONNE_PUNTI,
    Generale,
    configurazione_da_tabelle,
    famiglie_tipo,
    perdite_con_ombre,
    tabelle_da_configurazione,
    tipizza_punti,
)

APP = str(Path(__file__).resolve().parents[1] / "app.py")
GENERALE = Generale("Condominio di prova", "gruppo", 45.07, 7.69, "Piemonte", data_costituzione=date(2027, 1, 1))


def punti():
    famiglie = famiglie_tipo(6, kwh=2700)
    comuni = pd.DataFrame([{"Punto": "Parti comuni", "Membro": "Condominio", "Tipo soggetto": "Condominio",
                            "Tipologia consumo": "Municipio / uffici pubblici", "kWh annui": 4000, "Tensione": "BT"}],
                          columns=COLONNE_PUNTI)
    return tipizza_punti(pd.concat([famiglie, comuni], ignore_index=True))


def scelta(kwp_max=20.0, ombre=4.0, azimut=0, azimut_2=None):
    return SceltaTetto(kwp_max=kwp_max, inclinazione=20, azimut=azimut, ombre_pct=ombre, punto="Parti comuni",
                       investitore="Condominio", entrata=date(2027, 5, 1), azimut_2=azimut_2)


def est_ovest(kwp_max=40.0):
    return scelta(kwp_max=kwp_max, azimut=-90, azimut_2=90)


def punto(kwp, van, inv=1.0, membri=100.0, costo_kwp=1500.0):
    return PuntoCurva(potenza_moduli_kwp=kwp, potenza_nominale_gse_kw=kwp, van_consolidato_mediano=van,
                      van_consolidato_min=van * 0.8, van_consolidato_max=van * 1.2, van_investitore_mediano=inv,
                      quota_condivisa_su_immessa=0.5, copertura_consumi=0.3, euro_anno_membri=membri,
                      costo_eur=kwp * costo_kwp)


def test_tre_taglie_quando_il_beneficio_cresce_fino_al_tetto():
    curva = [punto(5, 8_000), punto(10, 20_000), punto(20, 30_000), punto(30, 38_000), punto(32, 40_000)]
    taglie = dict(scegli_taglie(curva))
    assert list(taglie) == ["Prudente", "Intermedia", "Consigliata"]
    assert taglie["Consigliata"].potenza_moduli_kwp == 30  # la più piccola entro il 5% del massimo
    assert taglie["Prudente"].potenza_moduli_kwp == 10  # il miglior rendimento per euro


def test_tutto_il_tetto_quando_il_massimo_e_prima():
    curva = [punto(5, 8_000), punto(10, 20_000), punto(20, 30_000), punto(40, 22_000)]
    assert [n for n, _ in scegli_taglie(curva)] == ["Prudente", "Consigliata", "Tutto il tetto"]


def test_consigliata_conviene_a_entrambi():
    # la taglia più grande rende di più ma chi paga ci perde: si consiglia quella in cui vincono tutti e due
    curva = [punto(5, 8_000), punto(10, 20_000), punto(20, 30_000, inv=-500)]
    assert dict(scegli_taglie(curva))["Consigliata"].potenza_moduli_kwp == 10


def test_entrata_predefinita():
    assert entrata_predefinita(date(2027, 1, 15), date(2026, 10, 23)) == date(2027, 5, 1)
    assert entrata_predefinita(None, date(2026, 10, 23)).day == 1


def test_riga_impianto_porta_le_ombre_nelle_perdite():
    esito = configurazione_da_tabelle(GENERALE, punti(), tabella_impianto(scelta(), 12.34))
    assert not esito.errori
    impianto = esito.config.plants[0]
    assert impianto.potenza_moduli_kwp == 12.3 and impianto.potenza_moduli_max_kwp == 20
    assert impianto.perdite_pct == perdite_con_ombre(4.0) > 14
    _, _, impianti = tabelle_da_configurazione(esito.config)  # salvataggio e ricaricamento
    assert impianti["Ombre %"].iloc[0] == pytest.approx(4.0)


def test_riga_impianto_con_due_falde():
    esito = configurazione_da_tabelle(GENERALE, punti(), tabella_impianto(est_ovest(), 30))
    assert not esito.errori
    impianto = esito.config.plants[0]
    assert impianto.azimut == -90 and impianto.azimut_2 == 90 and impianto.potenza_moduli_max_kwp == 40
    _, _, impianti = tabelle_da_configurazione(esito.config)  # salvataggio e ricaricamento
    assert impianti["Seconda falda °"].iloc[0] == 90
    una = configurazione_da_tabelle(GENERALE, punti(), tabella_impianto(scelta(), 10)).config.plants[0]
    assert una.azimut_2 is None


def test_profilo_di_due_falde_e_la_media_delle_due():
    richieste = []

    def fetch(lat, lon, tilt, azimut, perdite, anno):
        richieste.append(azimut)
        return synthetic_profile(lat, lon, tilt, azimut, perdite, anno)

    config = configurazione_da_tabelle(GENERALE, punti(), tabella_impianto(est_ovest(), 30)).config
    profilo = pv_profiles_for(config, 2023, fetch=fetch)[config.plants[0].id]
    assert sorted(richieste) == [-90, 90]
    est = synthetic_profile(45.07, 7.69, 20, -90, config.plants[0].perdite_pct, 2023).kw_per_kwp
    ovest = synthetic_profile(45.07, 7.69, 20, 90, config.plants[0].perdite_pct, 2023).kw_per_kwp
    assert profilo.kw_per_kwp.to_numpy() == pytest.approx(((est + ovest) / 2).to_numpy())
    assert profilo.year == 2023 and profilo.qualita == "C" and profilo.avviso
    ore = profilo.kw_per_kwp.index.tz_convert("Europe/Rome").hour
    # la falda a est produce di mattina, quella a ovest di sera: insieme coprono tutte e due
    assert est[ore < 10].sum() > ovest[ore < 10].sum() and ovest[ore > 15].sum() > est[ore > 15].sum()
    sud = synthetic_profile(45.07, 7.69, 20, 0, config.plants[0].perdite_pct, 2023).kw_per_kwp
    assert 0.75 < profilo.producibilita_kwh_kwp / sud.sum() < 0.95


def test_proposta_con_due_falde_parte_dal_massimo():
    proposta = proponi(GENERALE, punti(), est_ovest(40), ParametriEconomici(quota_membri=0.5), n_punti=4, n_anni=3,
                       oggi=date(2026, 10, 23))
    assert max(p.potenza_moduli_kwp for p in proposta.curva) == pytest.approx(40)
    assert any("tutte e due le falde" in n for n in proposta.note)
    assert any("inverter di circa l'80%" in n for n in proposta.note)
    assert proposta.scelta.due_falde
    riga = tabella_impianto(proposta.scelta, 30).iloc[0]
    assert riga["kW inverter"] == 24 and riga["kWp moduli"] == 30  # due falde: inverter all'80%
    assert tabella_impianto(scelta(), 30).iloc[0]["kW inverter"] == 30  # una falda: uguale ai moduli
    una = proponi(GENERALE, punti(), scelta(20), ParametriEconomici(quota_membri=0.5), n_punti=4, n_anni=3,
                  oggi=date(2026, 10, 23))
    assert not any("falde" in n for n in una.note)


def test_proposta_completa_senza_rete():
    proposta = proponi(GENERALE, punti(), scelta(), ParametriEconomici(quota_membri=0.5), quota_provvisoria=True,
                       n_punti=4, n_anni=3, oggi=date(2026, 10, 23))
    nomi = [o.nome for o in proposta.opzioni]
    assert "Consigliata" in nomi and 2 <= len(nomi) <= 3
    assert proposta.qualita == "C" and proposta.investitore == "Condominio" and proposta.n_membri == 6
    assert any("provvisorio" in n for n in proposta.note) and any("qualità C" in n for n in proposta.note)
    for o in proposta.opzioni:
        assert o.commento and o.punto.costo_eur > 0
        assert o.punto.van_consolidato_min <= o.punto.van_consolidato_mediano <= o.punto.van_consolidato_max


def test_proposta_con_dati_incompleti():
    with pytest.raises(ValueError, match="completa i dati"):
        proponi(GENERALE, punti(), SceltaTetto(20, 20, 0, 0, "Contatore inesistente", "Condominio", date(2027, 5, 1)),
                ParametriEconomici(quota_membri=0.5), n_anni=2)


def test_passo_3_guidato_nell_app():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.sidebar.button[0].click().run()  # esempio di Torino: un condominio
    assert not at.exception, at.exception
    superficie = next(n for n in at.number_input if n.label.startswith("Superficie utile"))
    superficie.set_value(150.0).run()
    proponi_btn = next(b for b in at.button if "Proponi tre taglie" in b.label)
    proponi_btn.click().run()
    assert not at.exception, at.exception
    usa = [b for b in at.button if b.label == "Usa questa taglia"]
    assert len(usa) >= 2
    usa[-1].click().run()
    assert not at.exception, at.exception
    impianti = at.session_state["impianti_base"]
    assert len(impianti) == 1 and impianti["Punto"].iloc[0] == "Parti comuni"


def test_passo_3_con_le_falde_a_est_e_a_ovest():
    from streamlit.testing.v1 import AppTest

    from cersim.tetto import tetto_disegnato

    lon, lat = 7.6869, 45.0703  # esempio di Torino
    kx, ky = 111_320.0 * math.cos(math.radians(lat)), 110_540.0
    angoli = [[lon + x / kx, lat + y / ky] for x, y in ((-6, -15), (6, -15), (6, 15), (-6, 15), (-6, -15))]
    tetto = tetto_disegnato(angoli)  # colmo da nord a sud
    assert tetto.est_ovest

    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.sidebar.button[0].click().run()  # esempio di Torino
    at.session_state["tetto_angoli"] = angoli
    at.run()
    assert not at.exception, at.exception
    due_falde = next(t for t in at.toggle if t.label == "Usa entrambe le falde (est e ovest)")
    superficie = next(n for n in at.number_input if n.label.startswith("Superficie utile"))
    assert due_falde.value and superficie.value == round(tetto.superficie_utile_due_falde_m2)
    due_falde.set_value(False).run()
    superficie = next(n for n in at.number_input if n.label.startswith("Superficie utile"))
    assert superficie.value == round(tetto.superficie_utile_m2)
    next(t for t in at.toggle if t.label.startswith("Usa entrambe")).set_value(True).run()
    next(b for b in at.button if "Proponi tre taglie" in b.label).click().run()
    assert not at.exception, at.exception
    usa = [b for b in at.button if b.label == "Usa questa taglia"]
    usa[-1].click().run()
    assert not at.exception, at.exception
    impianti = at.session_state["impianti_base"]
    assert sorted((impianti["Orientamento °"].iloc[0], impianti["Seconda falda °"].iloc[0])) == [-90, 90]


def test_comunita_energetica_un_tetto_alla_volta():
    from cersim.proposta import nome_impianto

    cer = Generale("Comunità di prova", "CER", 45.07, 7.69, "Piemonte", data_costituzione=date(2027, 1, 1))
    comune = pd.DataFrame([{"Punto": "Municipio", "Membro": "Comune", "Tipo soggetto": "Ente territoriale (es. Comune)",
                            "Tipologia consumo": "Municipio / uffici pubblici", "kWh annui": 30000, "Tensione": "BT"}],
                          columns=COLONNE_PUNTI)
    tutti = tipizza_punti(pd.concat([punti(), comune], ignore_index=True))
    assert nome_impianto("gruppo", "Parti comuni") == "FV tetto" and nome_impianto("CER", "Municipio") == "FV Municipio"
    primo = SceltaTetto(kwp_max=20, inclinazione=20, azimut=0, ombre_pct=0, punto="Parti comuni",
                        investitore="Condominio", entrata=date(2027, 5, 1), nome=nome_impianto("CER", "Parti comuni"))
    gia_scelti = tabella_impianto(primo, 15)
    secondo = SceltaTetto(kwp_max=40, inclinazione=20, azimut=0, ombre_pct=0, punto="Municipio", investitore="Comune",
                          entrata=date(2027, 5, 1), nome=nome_impianto("CER", "Municipio"))
    insieme = tabella_impianto(secondo, 30, gia_scelti)
    assert list(insieme["Impianto"]) == ["FV Parti comuni", "FV Municipio"]
    assert list(insieme["kWp moduli"]) == [15, 30]
    # un'altra taglia sullo stesso contatore sostituisce la precedente: al massimo un impianto per contatore
    assert list(tabella_impianto(secondo, 25, insieme)["kWp moduli"]) == [15, 25]

    proposta = proponi(cer, tutti, secondo, ParametriEconomici(quota_membri=0.5), altri=gia_scelti, n_punti=4,
                       n_anni=3, oggi=date(2026, 10, 23))
    assert max(p.potenza_moduli_kwp for p in proposta.curva) == pytest.approx(40)  # varia solo il nuovo impianto
    assert proposta.investitore == "Comune"
    assert any("altri 1 impianti già nella tabella" in n for n in proposta.note)


def test_passo_3_per_una_comunita_energetica():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.sidebar.button[0].click().run()  # esempio di Torino: c'è già "FV tetto" sulle parti comuni
    tipo = next(r for r in at.radio if r.label == "Che cosa vuoi simulare")
    tipo.set_value("CER").run()
    assert any("edifici diversi" in m.value for m in at.markdown)
    contatore = next(s for s in at.selectbox if s.label == "Collegato al contatore")
    contatore.set_value("Panetteria").run()
    next(n for n in at.number_input if n.label.startswith("Superficie utile")).set_value(100.0).run()
    next(b for b in at.button if "Proponi tre taglie" in b.label).click().run()
    assert not at.exception, at.exception
    next(b for b in at.button if b.label == "Usa questa taglia").click().run()
    assert not at.exception, at.exception
    impianti = at.session_state["impianti_base"]
    assert list(impianti["Impianto"]) == ["FV tetto", "FV Panetteria"]
    assert "proposta" not in at.session_state  # pronto per il tetto del prossimo edificio
