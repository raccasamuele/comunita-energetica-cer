from datetime import date

import pytest

from cersim.eligibility import Stato, UnsupportedConfigurationError, assert_supported, check
from cersim.model import TERZO, CapitalGrant, TipoSoggetto
from cersim.normativa import classificazione_soggetti
from conftest import configurazione, impianto, membro, punto


def _cer(aree=("AC001",) * 4, members=None, **kw):
    cps = [
        punto("pod1", "fam1", area_convenzionale=aree[0]),
        punto("pod2", "fam2", area_convenzionale=aree[1]),
        punto("pod3", "fam3", area_convenzionale=aree[2]),
        punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=4000, area_convenzionale=aree[3]),
    ]
    return configurazione(tipo="CER", cps=cps, members=members, **kw)


def test_classificazione_caricata_e_completa():
    soggetti = classificazione_soggetti().soggetti
    assert set(soggetti) == {t.value for t in TipoSoggetto}
    assert soggetti["grande_impresa"].ammissibile_socio_CER == "non_ammesso"
    assert soggetti["persona_fisica"].soggetto_esente_F == "si"  # RO luglio 2025
    assert soggetti["condominio"].soggetto_esente_F == "no"
    assert soggetti["pmi"].impresa_ai_fini_eccedenza == "si"


def test_cer_tutto_verificato():
    rep = check(_cer())
    assert rep.stato_configurazione is Stato.AMMESSO
    assert rep.impianti["fv1"].tip.ammesso and rep.impianti["fv1"].cacv.ammesso
    assert not rep.condizionale and rep.supportata


def test_cabina_non_verificata_rende_condizionale():
    rep = check(_cer(aree=("AC001", None, "AC001", "AC001")))
    assert rep.configurazione["cabina_primaria"].stato is Stato.SCONOSCIUTO
    assert "pod2" in rep.configurazione["cabina_primaria"].motivo
    assert rep.condizionale
    assert rep.impianti["fv1"].cacv.stato is Stato.SCONOSCIUTO


def test_cabine_diverse_non_ammesso():
    rep = check(_cer(aree=("AC001", "AC002", "AC001", "AC001")))
    assert rep.configurazione["cabina_primaria"].stato is Stato.NON_AMMESSO
    assert rep.impianti["fv1"].tip.stato is Stato.NON_AMMESSO


def test_grande_impresa_non_puo_stare_in_cer():
    members = [membro("fam1", "grande_impresa"), membro("fam2"), membro("fam3"), membro("cond", "condominio")]
    rep = check(_cer(members=members))
    assert rep.configurazione["soci"].stato is Stato.NON_AMMESSO
    # nel gruppo il requisito sui soci della CER non si applica
    assert check(configurazione(members=members)).configurazione["soci"].ammesso


def test_soggetto_non_classificato_e_sconosciuto():
    members = [membro("fam1", "altro"), membro("fam2"), membro("fam3"), membro("cond", "condominio")]
    assert check(_cer(members=members)).configurazione["soci"].stato is Stato.SCONOSCIUTO


def test_impianto_prima_della_costituzione():
    rep = check(_cer(plants=[impianto("fv1", "podc", "cond", entrata=date(2026, 6, 1))]))
    assert rep.impianti["fv1"].tip.stato is Stato.SCONOSCIUTO
    assert rep.impianti["fv1"].cacv.ammesso
    rep = check(_cer(data_costituzione=None))
    assert rep.impianti["fv1"].tip.stato is Stato.SCONOSCIUTO


def test_tip_non_ammessa_dopo_il_termine_del_2027():
    rep = check(_cer(plants=[impianto("fv1", "podc", "cond", entrata=date(2028, 1, 1))]))
    assert rep.impianti["fv1"].tip.stato is Stato.NON_AMMESSO and "31/12/2027" in rep.impianti["fv1"].tip.motivo
    assert rep.impianti["fv1"].cacv.ammesso  # la valorizzazione ARERA non ha questo termine
    assert check(_cer(plants=[impianto("fv1", "podc", "cond", entrata=date(2027, 12, 31))])).impianti["fv1"].tip.ammesso


def test_casi_non_supportati():
    esistente = configurazione(plants=[impianto("fv1", "podc", "cond", entrata=date(2020, 3, 1))])
    with pytest.raises(UnsupportedConfigurationError, match="16/12/2021"):
        assert_supported(check(esistente))

    oltre_1mw = configurazione(plants=[impianto("fv1", "podc", "cond", kwp=1100, kw_ac=1050)])
    assert not check(oltre_1mw).supportata
    sotto_1mw_ac = configurazione(plants=[impianto("fv1", "podc", "cond", kwp=1100, kw_ac=900)])
    assert check(sotto_1mw_ac).supportata  # conta min(DC, AC)

    fuori_edificio = configurazione(plants=[impianto("fv1", "podc", "cond", nell_edificio=False)])
    assert any("fuori dall'edificio" in m for m in check(fuori_edificio).non_supportati)

    cps = [punto("pod1", "fam1", edificio_id="altro_edificio"), punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=4000)]
    pod_esterno = configurazione(cps=cps)
    assert any("pod1" in m for m in check(pod_esterno).non_supportati)


def test_contributo_capitale():
    grant = CapitalGrant(importo_eur=10000, intensita=0.4, estremi_atto="Decreto GSE n. 123")
    rep = check(configurazione(plants=[impianto("fv1", "podc", "cond", contributo_capitale=grant)]))
    assert rep.impianti["fv1"].contributo_capitale.ammesso
    rep = check(configurazione(plants=[impianto("fv1", "podc", TERZO, contributo_capitale=grant)]))
    assert rep.impianti["fv1"].contributo_capitale.stato is Stato.NON_AMMESSO
    assert check(configurazione()).impianti["fv1"].contributo_capitale is None


def test_checklist_da_verificare():
    assert any("statuto" in v.lower() for v in check(_cer()).da_verificare)
    assert any("stesso edificio" in v for v in check(configurazione()).da_verificare)
