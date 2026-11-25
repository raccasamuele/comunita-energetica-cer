"""Profilo energetico della casa: lettura, scenari applicati a un contatore, batteria di casa nel bilancio, riesportazione."""

import json
from datetime import date

import numpy as np
import pytest

from cersim.curva_calcolata import esporta
from cersim.eligibility import check
from cersim.model import BatteriaCasa, CurvaMisurata, NaturaCurva
from cersim.profilo import ESCLUSI, FORMATO, applica_scenario, esporta_profilo, leggi_profilo, sintesi
from cersim.simulate import batteria_di_casa, simulate_year
from cersim.timebase import TZ, year_index
from conftest import configurazione, impianto, membro, punto
from test_curva_calcolata import casa


def _ore(serie) -> dict:
    e = esporta(serie)
    return {"kwh_annui": e["kwh_annui"], "ore": e["ore"]}


def _fv_ora(a: int = 2025):
    """Un FV da 3 kWp a mezzogiorno (kWh per ora), per costruire prelievi coerenti."""
    idx = year_index(a)
    ora = np.asarray(idx.tz_convert(TZ).hour)
    return np.clip(np.sin((ora - 6) / 12 * np.pi), 0, None) * 2.0


def profilo_casa(**cambi) -> dict:
    consumi = casa()
    prelievi = (consumi - _fv_ora()).clip(lower=0)
    base = {"id": "base", "nome": "Situazione attuale", "attuale": True,
            "consumi": {"natura": "calcolato", "stato": "documentato", **_ore(consumi),
                        "usi": {"altri_usi_kwh": 2700.0, "pompa_di_calore_kwh": float(consumi.sum()) - 2700.0}},
            "fv": None, "batteria": None, "prelievi": _ore(consumi)}
    con_fv = {"id": "P", "nome": "FV 3 kWp e batteria", "attuale": False,
              "consumi": {"natura": "calcolato", "stato": "documentato", **_ore(consumi)},
              "fv": {"kwp": 3.0, "inclinazione": 35, "orientamento": 0, "perdite_pct": 14, "esistente": False},
              "batteria": {"capacita_kwh": 5.0, "potenza_kw": 3.0, "rendimento_pct": 90, "riserva_pct": 10},
              "prelievi": _ore(prelievi), "stima": {"immissioni_kwh": 2100.0, "autoconsumo_kwh": 1500.0}}
    dati = {"formato": FORMATO, "versione": 1, "fonte": "simulatore-casa", "motore": "casa-1R1C 0.5.0",
            "data": "2026-11-03", "descrizione": "Torino",
            "comune": {"codice_istat": "001272", "nome": "Torino", "lat": 45.07, "lon": 7.68},
            "scenari": [base, con_fv], "esclusi": list(ESCLUSI)}
    dati.update(cambi)
    return dati


def _file(dati: dict) -> bytes:
    return json.dumps(dati).encode()


def test_legge_scenari_e_sintesi():
    p = leggi_profilo(_file(profilo_casa()))
    assert p.comune.nome == "Torino" and p.data == date(2026, 11, 3)
    righe = sintesi(p)
    assert [r["id"] for r in righe] == ["base", "P"]
    assert righe[0]["attuale"] and righe[0]["fv_kwp"] is None
    assert righe[1]["fv_kwp"] == 3.0 and righe[1]["batteria_kwh"] == 5.0
    assert righe[1]["prelievi_kwh"] < righe[1]["consumi_kwh"]


@pytest.mark.parametrize("cambio, messaggio", [
    ({"formato": "curva-consumi"}, "Non è un profilo"),
    ({"versione": 3}, "aggiorna il simulatore"),
    ({"extra": 1}, "campi non previsti"),
    ({"scenari": []}, "da 1 a 20 scenari"),
    ({"comune": {"codice_istat": "12", "nome": "X", "lat": 45, "lon": 7}}, "sei cifre"),
])
def test_rifiuta_file_non_validi(cambio, messaggio):
    with pytest.raises(ValueError, match=messaggio):
        leggi_profilo(_file(profilo_casa(**cambio)))


def test_rifiuta_scenari_incoerenti():
    dati = profilo_casa()
    dati["scenari"][1]["fv"] = None  # batteria senza FV
    with pytest.raises(ValueError, match="manca il FV"):
        leggi_profilo(_file(dati))
    dati = profilo_casa()
    dati["scenari"][0]["prelievi"]["kwh_annui"] *= 1.5  # senza FV, prelievi diversi dai consumi
    with pytest.raises(ValueError, match="non torna con la curva"):
        leggi_profilo(_file(dati))
    dati = profilo_casa()
    dati["scenari"][1]["attuale"] = True
    with pytest.raises(ValueError, match="Al massimo uno scenario"):
        leggi_profilo(_file(dati))


def test_senza_fv_si_legge_come_una_curva_consumi():
    p = leggi_profilo(_file(profilo_casa()))
    a = applica_scenario(p, "base", conta_fv=True)
    assert a.impianto is None and a.batteria is None
    assert a.curva.natura is NaturaCurva.CALCOLATA and a.curva.fv_sottratto_kwp is None
    assert a.curva.ore == tuple(profilo_casa()["scenari"][0]["consumi"]["ore"])


def test_conta_il_fv_consumi_prima_del_fv_e_batteria():
    p = leggi_profilo(_file(profilo_casa()))
    a = applica_scenario(p, "P", conta_fv=True)
    assert a.curva.kwh_annui == p.scenario("P").consumi_kwh and a.curva.fv_sottratto_kwp is None
    assert a.batteria == BatteriaCasa(capacita_kwh=5, potenza_kw=3, rendimento_pct=90, riserva_pct=10)
    assert a.impianto == {"kwp": 3.0, "inclinazione": 35, "orientamento": 0, "perdite_pct": 14, "esistente": False}
    assert a.profilo.conta_fv and a.profilo.consumi is None
    assert any("entra nella comunità" in x for x in a.avvisi)


def test_solo_prelievi_come_curva_consumi_versione_3():
    p = leggi_profilo(_file(profilo_casa()))
    a = applica_scenario(p, "P", conta_fv=False)
    assert a.impianto is None and a.batteria is None
    assert a.curva.fv_sottratto_kwp == 3.0 and a.curva.batteria_kwh == 5.0
    assert a.curva.kwh_annui == p.scenario("P").prelievi_kwh
    assert any("già tolto un fotovoltaico" in x for x in a.avvisi)


def test_batteria_di_casa_come_nel_simulatore_della_casa():
    b = BatteriaCasa(capacita_kwh=4, potenza_kw=2, rendimento_pct=81, riserva_pct=25)  # η = 0,9 per verso, minimo 1 kWh
    surplus = np.array([3.0, 3.0, 0.0, 0.0, 0.0])
    deficit = np.array([0.0, 0.0, 1.0, 5.0, 1.0])
    carica, scarica = batteria_di_casa(surplus, deficit, b)
    # ora 0: potenza 2 kWh → +1,8; ora 1: spazio 4 − 2,8 = 1,2 kWh → carica 1,2/0,9
    np.testing.assert_allclose(carica, [2.0, 1.2 / 0.9, 0, 0, 0])
    # ora 2: scarica 1 → −1/0,9; ora 3: potenza 2 ma resta 4 − 1 − 1,111 = 1,889 sopra il minimo → 1,7; ora 4: vuota
    np.testing.assert_allclose(scarica, [0, 0, 1.0, (4 - 1 - 1 / 0.9) * 0.9, 0], atol=1e-12)


def test_bilancio_con_batteria_coerente_e_meno_condivisa():
    members = [membro("casa"), membro("fam")]
    batteria = BatteriaCasa(capacita_kwh=5, potenza_kw=3, rendimento_pct=90, riserva_pct=10)
    curva = CurvaMisurata(ore=tuple([0.5] * 864), natura=NaturaCurva.CALCOLATA, kwh_annui=4380, fonte="prova")

    def cfg(con_batteria):
        cps = [punto("pc", "casa", curva_misurata=curva, batteria=batteria if con_batteria else None),
               punto("pf", "fam", kwh_annui=3000)]
        return configurazione(members=members, cps=cps, plants=[impianto("fvc", "pc", "casa", kwp=3)])

    idx = year_index(2028)[:48]
    ora = np.asarray(idx.tz_convert(TZ).hour)
    produzione = {"fvc": np.clip(np.sin((ora - 6) / 12 * np.pi), 0, None) * 2.5}
    carichi = {"pc": np.where((ora >= 18) & (ora < 23), 1.5, 0.3), "pf": np.full(48, 0.4)}
    senza = simulate_year(cfg(False), check(cfg(False)), idx, carichi, produzione)
    con = simulate_year(cfg(True), check(cfg(True)), idx, carichi, produzione)
    assert con.violazioni_invarianti() == []
    assert con.carica.sum() > 0 and con.scarica.sum() > 0
    assert con.SC.sum() > senza.SC.sum()
    assert con.I.sum() < senza.I.sum() and con.W.sum() < senza.W.sum()
    assert con.EACV.sum() < senza.EACV.sum()  # la batteria privata toglie energia alla comunità
    assert con.totali()["scarica_batterie_kwh"] == pytest.approx(con.scarica.sum())


def test_batteria_senza_impianto_sul_punto_rifiutata():
    batteria = BatteriaCasa(capacita_kwh=5, potenza_kw=3, rendimento_pct=90)
    curva = CurvaMisurata(ore=tuple([0.5] * 864), natura=NaturaCurva.CALCOLATA, kwh_annui=4380, fonte="prova")
    with pytest.raises(ValueError, match="nessun impianto"):
        configurazione(members=[membro("casa")], cps=[punto("pc", "casa", curva_misurata=curva, batteria=batteria)],
                       plants=[])


def _punto_da_profilo(a):
    return punto("pc", "casa", curva_misurata=a.curva, batteria=a.batteria, profilo=a.profilo)


@pytest.mark.parametrize("conta_fv", [True, False])
def test_andata_e_ritorno_senza_perdite(conta_fv):
    originale = profilo_casa()
    p = leggi_profilo(_file(originale))
    a = applica_scenario(p, "P", conta_fv=conta_fv)
    cp = _punto_da_profilo(a)
    uscita = esporta_profilo(cp, conta_fv, oggi=date(2026, 11, 4))
    assert uscita["fonte"] == "cersim" and uscita["comune"] == originale["comune"]
    assert uscita["scenari"] == [originale["scenari"][1]]
    di_nuovo = leggi_profilo(_file(uscita))
    assert di_nuovo.scenario("P") == p.scenario("P")


BOLLETTA = {"eur_kwh": 0.28, "stato": "documentato"}


def test_prezzo_della_bolletta_sul_contatore_e_nel_ritorno():
    originale = profilo_casa(versione=2, bolletta=BOLLETTA)
    p = leggi_profilo(_file(originale))
    assert p.bolletta.eur_kwh == 0.28 and p.bolletta.fasce is None
    a = applica_scenario(p, "P", conta_fv=True)
    assert a.profilo.bolletta == p.bolletta
    assert any("prezzo della sua bolletta (0,280 €/kWh" in x for x in a.avvisi)
    uscita = esporta_profilo(_punto_da_profilo(a), True, oggi=date(2026, 11, 25))
    assert uscita["bolletta"] == BOLLETTA and uscita["versione"] == 2
    # solo prelievi: niente autoconsumo sul punto, quindi nessun avviso, ma il prezzo resta per il ritorno
    b = applica_scenario(p, "P", conta_fv=False)
    assert b.profilo.bolletta == p.bolletta and not any("bolletta" in x for x in b.avvisi)


def test_prezzo_della_bolletta_per_fasce_e_sconosciuto():
    fasce = {"F1": 0.31, "F2": 0.29, "F3": 0.26}
    p = leggi_profilo(_file(profilo_casa(versione=2, bolletta={**BOLLETTA, "fasce": fasce})))
    assert p.bolletta.fasce == fasce
    a = applica_scenario(p, "P", conta_fv=True)
    assert any("F1 0,310 / F2 0,290 / F3 0,260 €/kWh" in x for x in a.avvisi)
    ignoto = leggi_profilo(_file(profilo_casa(versione=2, bolletta={"eur_kwh": 0, "stato": "sconosciuto"})))
    assert ignoto.bolletta is None
    assert any("prezzo della bolletta nel profilo è sconosciuto" in x for x in applica_scenario(ignoto, "P", True).avvisi)
    uscita = esporta_profilo(_punto_da_profilo(applica_scenario(ignoto, "P", True)), True)
    assert "bolletta" not in uscita and uscita["versione"] == 1  # leggibile anche dai lettori della versione 1


def test_la_bolletta_non_e_un_campo_della_versione_1():
    with pytest.raises(ValueError, match="campi non previsti dalla versione 1: bolletta"):
        leggi_profilo(_file(profilo_casa(bolletta=BOLLETTA)))


@pytest.mark.parametrize("bolletta, messaggio", [
    ({"eur_kwh": 2, "stato": "documentato"}, "eur_kwh"),
    ({"eur_kwh": 0.28}, "mancano i campi stato"),
    ({"eur_kwh": 0.28, "stato": "documentato", "fasce": {"F1": 0.3}}, "F1, F2 e F3"),
    ({"eur_kwh": 0.28, "stato": "documentato", "importo": 900}, "campi non previsti"),
    ({"eur_kwh": 0.28, "stato": "boh"}, "stato del prezzo"),
])
def test_prezzo_della_bolletta_non_valido(bolletta, messaggio):
    with pytest.raises(ValueError, match=messaggio):
        leggi_profilo(_file(profilo_casa(versione=2, bolletta=bolletta)))


def test_profilo_di_un_contatore_misurato_senza_impianto():
    curva = CurvaMisurata(ore=tuple(esporta(casa())["ore"]), kwh_annui=round(float(casa().sum()), 1), giorni=365,
                          dal=date(2025, 1, 1), al=date(2025, 12, 31), fonte="Portale Consumi")
    uscita = esporta_profilo(punto("pc", "casa", curva_misurata=curva, codice_pod="IT001E12345678"), False)
    s = uscita["scenari"][0]
    assert s["attuale"] and s["consumi"]["natura"] == "misurato" and s["consumi"]["giorni"] == 365
    assert s["prelievi"]["ore"] == s["consumi"]["ore"] and s["fv"] is None
    p = leggi_profilo(_file(uscita))
    a = applica_scenario(p, "attuale", conta_fv=True)
    assert a.curva.natura is NaturaCurva.CALCOLATA  # nella CER un profilo vale come stima
    assert any("qualità resta B" in x for x in a.avvisi)


def test_nessun_dato_personale_nel_profilo():
    curva = CurvaMisurata(ore=tuple(esporta(casa())["ore"]), kwh_annui=round(float(casa().sum()), 1), giorni=365,
                          dal=date(2025, 1, 1), al=date(2025, 12, 31), fonte="Portale Consumi di Mario Rossi")
    testo = json.dumps(esporta_profilo(punto("pc", "mario", curva_misurata=curva, codice_pod="IT001E12345678"), False))
    for vietato in ("IT001E", "Mario", "Rossi", "mario", "@", "Portale"):
        assert vietato not in testo


def test_impianto_senza_profilo_non_si_esporta():
    curva = CurvaMisurata(ore=tuple([0.5] * 864), natura=NaturaCurva.CALCOLATA, kwh_annui=4380, fonte="prova")
    with pytest.raises(ValueError, match="ha un impianto"):
        esporta_profilo(punto("pc", "casa", curva_misurata=curva), True)


# --- nell'interfaccia: passo 2, passo 3, salvataggio e analisi ---------------------------------------
def _file_web(dati: dict) -> list[dict]:
    import base64
    return [{"nome": "profilo-energetico_casa.json", "base64": base64.b64encode(_file(dati)).decode()}]


def _bozza_con_profilo(conta_fv=True, batteria=True):
    from cersim.web import famiglie, leggi_consumi
    from test_web import LUOGO
    dati = profilo_casa()
    if not batteria:
        dati["scenari"][1]["batteria"] = None
    letto = leggi_consumi(_file_web(dati), scenario="P", conta_fv=conta_fv, data_costituzione="2027-01-15",
                          contatore="Famiglia 1")
    assert letto["ok"], letto
    impianti = []
    if letto["impianto"]:
        riga = {k: v for k, v in letto["impianto"].items() if k != "esistente"}
        impianti = [{**riga, "Investitore": "Famiglia 1"}]
    voce = {k: letto[k] for k in ("curva", "descrizione", "calcolata", "batteria", "profilo") if k in letto}
    return {"generale": dict(LUOGO), "punti": famiglie(2), "impianti": impianti, "curve": {"Famiglia 1": voce},
            "parametri": {"quota_membri": 0.5}}, letto


def test_passo_2_prima_gli_scenari_poi_il_contatore():
    from cersim.web import leggi_consumi
    scelta = leggi_consumi(_file_web(profilo_casa()))
    assert scelta["ok"] and scelta["scegli"] and scelta["comune"] == "Torino"
    assert [s["id"] for s in scelta["scenari"]] == ["base", "P"]
    tabelle, letto = _bozza_con_profilo()
    assert letto["batteria"]["capacita_kwh"] == 5 and letto["profilo"]["conta_fv"]
    assert letto["impianto"]["Punto"] == "Famiglia 1" and letto["impianto"]["Entrata in esercizio"]
    assert letto["impianto"]["kWp moduli"] == 3.0 and letto["impianto"]["Ombre %"] is None
    sbagliato = leggi_consumi(_file_web(profilo_casa()), scenario="X")
    assert not sbagliato["ok"] and "scenario" in sbagliato["errore"]


def test_salvataggio_con_batteria_e_profilo_ricaricato_uguale():
    from cersim.web import progetto_da_tabelle, scarica_profilo, tabelle_da_progetto
    tabelle, _ = _bozza_con_profilo()
    esito = progetto_da_tabelle(json.loads(json.dumps(tabelle)))
    assert esito["ok"], esito
    ricaricato = tabelle_da_progetto(esito["progetto"])["tabelle"]
    voce = ricaricato["curve"]["Famiglia_1"]
    assert voce["batteria"] == tabelle["curve"]["Famiglia 1"]["batteria"]
    assert voce["profilo"] == tabelle["curve"]["Famiglia 1"]["profilo"]
    assert json.loads(progetto_da_tabelle(json.loads(json.dumps(ricaricato)))["progetto"]) == json.loads(esito["progetto"])
    scaricato = scarica_profilo(voce, True)
    assert scaricato["ok"] and scaricato["profilo"]["scenari"] == [profilo_casa()["scenari"][1]]


def test_senza_impianto_la_batteria_ferma_il_passo_2():
    from cersim.web import progetto_da_tabelle
    tabelle, _ = _bozza_con_profilo()
    esito = progetto_da_tabelle({**tabelle, "impianti": []})
    assert not esito["ok"] and any("nessun impianto" in e for e in esito["errori"])


def _analisi(tabelle):
    from cersim.web import analizza_web, progetto_da_tabelle, richieste_pvgis
    from test_web import risposta_pvgis
    progetto = progetto_da_tabelle(json.loads(json.dumps(tabelle)))["progetto"]
    serie = {r["chiave"]: risposta_pvgis(r["parametri"]) for r in richieste_pvgis(progetto)}
    return analizza_web(progetto, serie, n_anni=3)


def test_conta_fv_uguale_all_impianto_inserito_a_mano():
    tabelle, letto = _bozza_con_profilo(batteria=False)
    a_mano = json.loads(json.dumps(tabelle))
    a_mano["curve"]["Famiglia 1"] = {k: v for k, v in a_mano["curve"]["Famiglia 1"].items() if k != "profilo"}
    a_mano["impianti"] = [{"Impianto": "Il mio FV", "Punto": "Famiglia 1", "kWp moduli": 3.0, "kW inverter": 3.0,
                           "Inclinazione °": 35, "Orientamento °": 0, "Entrata in esercizio": letto["impianto"]["Entrata in esercizio"],
                           "Investitore": "Famiglia 1"}]
    dal_profilo, manuale = _analisi(tabelle), _analisi(a_mano)
    assert dal_profilo["ok"] and manuale["ok"]
    assert dal_profilo["bande"] == manuale["bande"]


def test_analisi_completa_con_la_batteria_di_casa():
    import time
    tabelle, _ = _bozza_con_profilo()
    senza, _ = _bozza_con_profilo(batteria=False)
    t = time.perf_counter()
    con = _analisi(tabelle)
    durata = time.perf_counter() - t
    assert con["ok"], con
    assert durata < 30  # misura indicativa: la batteria si simula ora per ora in Python
    condivisa = lambda r: r["bande"]["EACV_kwh"]["mediana"] if "EACV_kwh" in r["bande"] else None
    if condivisa(con) is not None:
        assert condivisa(con) < condivisa(_analisi(senza))


def test_il_profilo_d_esempio_del_simulatore_della_casa():
    """esempi/profilo_energetico_esempio.json lo scrive il simulatore della casa (tests/profilo.test.ts, SCRIVI_ESEMPI=1)."""
    from pathlib import Path
    esempio = Path(__file__).resolve().parents[1] / "esempi" / "profilo_energetico_esempio.json"
    p = leggi_profilo(esempio.read_bytes())
    assert p.fonte == "simulatore-casa" and p.comune is not None
    attuale = [s for s in p.scenari if s.attuale]
    assert len(attuale) == 1 and attuale[0].id == "base" and attuale[0].fv is None
    con_fv = [s for s in p.scenari if s.fv]
    assert con_fv and all(s.prelievi_kwh < s.consumi_kwh for s in con_fv)
    for s in p.scenari:
        a = applica_scenario(p, s.id, conta_fv=True)
        assert (a.impianto is not None) == (s.fv is not None) and a.curva.kwh_annui == s.consumi_kwh
        if s.fv:
            b = applica_scenario(p, s.id, conta_fv=False)
            assert b.curva.fv_sottratto_kwp == s.fv.kwp and b.curva.kwh_annui == s.prelievi_kwh
