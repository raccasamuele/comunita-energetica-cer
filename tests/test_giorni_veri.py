"""La curva misurata conserva pochi giorni veri e la simulazione li pesca: stessi totali della media, picchi veri."""
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from cersim.loads import load_profile
from cersim.misure import Letture, curva_misurata
from cersim.model import CELLE_GIORNI_VERI, GIORNI_PER_CELLA, ConnectionPoint, CurvaMisurata
from cersim.report import QUALITA
from cersim.timebase import local_frame, year_index

ANNO = 2023


def _letture(casuale: bool = True) -> Letture:
    indice = pd.date_range(year_index(ANNO)[0], periods=len(year_index(ANNO)) * 4, freq="15min")
    rng = np.random.default_rng(7)
    giorni = np.repeat(rng.gamma(2.0, 0.5, len(indice) // 96 + 1), 96)[:len(indice)] if casuale else 1.0
    picco = np.tile(np.r_[np.full(72, 0.02), np.full(16, 0.25), np.full(8, 0.02)], len(indice) // 96 + 1)[:len(indice)]
    return Letture(pd.Series(picco * giorni, index=indice), "prova")


def _punto(curva: CurvaMisurata, id_: str = "m1") -> ConnectionPoint:
    return ConnectionPoint(id=id_, titolare="x", tipologia_profilo="domestico", curva_misurata=curva)


@pytest.fixture(scope="module")
def curva() -> CurvaMisurata:
    return curva_misurata(_letture())


def test_la_curva_tiene_pochi_giorni_senza_date(curva):
    assert curva.giorni_veri
    conteggio = pd.Series([c for c, _ in curva.giorni_veri]).value_counts()
    assert conteggio.max() <= GIORNI_PER_CELLA
    assert set(conteggio.index) <= set(range(CELLE_GIORNI_VERI))
    assert all(len(v) == 24 for _, v in curva.giorni_veri)
    # nessuna data nei giorni salvati
    assert all(isinstance(c, int) for c, _ in curva.giorni_veri)


def test_il_salvataggio_conserva_i_giorni(curva):
    assert CurvaMisurata.model_validate(curva.model_dump(mode="json")) == curva


def test_annuo_e_totali_per_mese_come_la_media(curva):
    pescati = load_profile(_punto(curva), year_index(ANNO))
    media = load_profile(_punto(curva.model_copy(update={"giorni_veri": ()})), year_index(ANNO))
    assert pescati.sum() == pytest.approx(media.sum())
    mesi = local_frame(year_index(ANNO))["month"].to_numpy()
    for mese in range(1, 13):
        assert pescati[mesi == mese].sum() == pytest.approx(media[mesi == mese].sum(), rel=1e-6)


def test_i_giorni_veri_riportano_i_picchi_che_la_media_toglie(curva):
    pescati = load_profile(_punto(curva), year_index(ANNO))
    media = load_profile(_punto(curva.model_copy(update={"giorni_veri": ()})), year_index(ANNO))
    assert pescati.std() > media.std()
    assert pescati.max() > media.max()


def test_stessa_sequenza_a_parita_di_contatore_e_anno_diversa_fra_contatori(curva):
    uno = load_profile(_punto(curva), year_index(ANNO))
    assert np.array_equal(uno, load_profile(_punto(curva), year_index(ANNO)))
    assert not np.array_equal(uno, load_profile(_punto(curva, "m2"), year_index(ANNO)))


def test_un_vecchio_salvataggio_senza_giorni_usa_la_media(curva):
    vecchia = curva.model_dump(mode="json")
    del vecchia["giorni_veri"]
    profilo = load_profile(_punto(CurvaMisurata.model_validate(vecchia)), year_index(ANNO))
    assert profilo.sum() == pytest.approx(_punto(curva).kwh_effettivi)
    assert np.array_equal(profilo, load_profile(_punto(curva.model_copy(update={"giorni_veri": ()})), year_index(ANNO)))


def test_una_cella_senza_giorni_veri_resta_la_media(curva):
    solo_gennaio = tuple(g for g in curva.giorni_veri if g[0] % 12 == 0)
    pescati = load_profile(_punto(curva.model_copy(update={"giorni_veri": solo_gennaio})), year_index(ANNO))
    media = load_profile(_punto(curva.model_copy(update={"giorni_veri": ()})), year_index(ANNO))
    mesi = local_frame(year_index(ANNO))["month"].to_numpy()
    assert np.allclose(pescati[mesi == 7], media[mesi == 7], rtol=1e-6)


def test_giorni_a_zero_non_rompono_il_conto(curva):
    a_zero = tuple((c, (0.0,) * 24) for c, _ in curva.giorni_veri)
    profilo = load_profile(_punto(curva.model_copy(update={"giorni_veri": a_zero})), year_index(ANNO))
    assert np.isfinite(profilo).all() and profilo.sum() == pytest.approx(_punto(curva).kwh_effettivi)


@pytest.mark.parametrize("giorni", [((99, (0.1,) * 24),), ((0, (0.1,) * 5),), ((0, (-1.0,) * 24),),
                                    ((0, (float("inf"),) * 24),), ((0, (float("nan"),) * 24),),
                                    tuple((0, (0.1,) * 24) for _ in range(GIORNI_PER_CELLA + 1))])
def test_un_file_manomesso_e_rifiutato(curva, giorni):
    dati = curva.model_dump()
    dati["giorni_veri"] = giorni
    with pytest.raises(ValidationError):
        CurvaMisurata.model_validate(dati)


def test_il_nome_non_promette_una_garanzia():
    testo, _, spiegazione = QUALITA["A"]
    assert testo == "Curva completa" and "non è una garanzia" in spiegazione
