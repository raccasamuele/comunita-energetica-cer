from datetime import date

import pytest
import requests

from cersim.model import Configuration, ConnectionPoint, Member, Plant


@pytest.fixture(autouse=True)
def niente_rete(monkeypatch, tmp_path):
    """Nessun test deve usare la rete né la cache PVGIS della macchina."""

    def vietato(*args, **kwargs):
        raise requests.ConnectionError("rete disabilitata nei test")

    monkeypatch.setattr(requests, "get", vietato)
    monkeypatch.setenv("CERSIM_CACHE_DIR", str(tmp_path / "cache"))


def membro(id_, tipo="persona_fisica"):
    return Member(id=id_, nome=id_.capitalize(), tipo_soggetto=tipo)


def punto(id_, titolare, **kw):
    kw.setdefault("tipologia_profilo", "domestico")
    kw.setdefault("edificio_id", "ed1")
    return ConnectionPoint(id=id_, titolare=titolare, **kw)


def impianto(id_, cp, investitore, kwp=20.0, kw_ac=None, entrata=date(2027, 5, 1), **kw):
    return Plant(
        id=id_,
        nome=id_,
        connection_point=cp,
        potenza_moduli_kwp=kwp,
        potenza_inverter_kw=kw_ac or kwp,
        investitore=investitore,
        data_entrata_esercizio=entrata,
        **kw,
    )


def configurazione(tipo="gruppo", members=None, cps=None, plants=None, **kw):
    """Condominio di Torino: 3 famiglie + parti comuni con FV sul tetto."""
    if members is None:
        members = [membro("fam1"), membro("fam2"), membro("fam3"), membro("cond", "condominio")]
    if cps is None:
        cps = [punto("pod1", "fam1"), punto("pod2", "fam2"), punto("pod3", "fam3"),
               punto("podc", "cond", tipologia_profilo="pa_municipio", kwh_annui=4000)]
    if plants is None:
        plants = [impianto("fv1", "podc", "cond")]
    kw.setdefault("nome", "Condominio di prova")
    kw.setdefault("lat", 45.07)
    kw.setdefault("lon", 7.69)
    kw.setdefault("regione", "Piemonte")
    kw.setdefault("data_costituzione", date(2027, 1, 1))
    if tipo == "gruppo":
        kw.setdefault("edificio_id_gruppo", "ed1")
    return Configuration(tipo=tipo, members=members, connection_points=cps, plants=plants, **kw)
