import numpy as np
import pandas as pd
import pytest

from cersim.prices import anno_dei_prezzi, prezzi_da_csv, prezzo_costante
from cersim.timebase import TZ, year_index


def _scrivi_csv(path, anno, passo="h", con_fuso=True, buchi=0):
    locale = pd.date_range(f"{anno}-01-01", f"{anno + 1}-01-01", freq=passo, tz=TZ, inclusive="left")
    ora = locale.hour
    prezzi = np.where((ora >= 10) & (ora <= 15), 60.0, 140.0)  # ore di sole più economiche
    testo = [t.isoformat() if con_fuso else t.tz_localize(None).isoformat() for t in locale]
    df = pd.DataFrame({"inizio": testo, "NORD": prezzi, "SICI": prezzi + 10})
    if buchi:
        df = df.drop(df.index[1000:1000 + buchi])
    df.to_csv(path, index=False)


def test_csv_orario(tmp_path):
    f = tmp_path / "prezzi.csv"
    _scrivi_csv(f, 2024)
    serie = prezzi_da_csv(f, "NORD", 2024)
    assert len(serie.eur_mwh) == 8784 and serie.qualita == "B"
    locale = serie.eur_mwh.index.tz_convert(TZ)
    assert serie.eur_mwh[locale.hour == 12].mean() == pytest.approx(60)
    assert prezzi_da_csv(f, "SICI", 2024).media == pytest.approx(serie.media + 10)


def test_csv_quartorario_mediato(tmp_path):
    f = tmp_path / "prezzi15.csv"
    _scrivi_csv(f, 2025, passo="15min")
    serie = prezzi_da_csv(f, "NORD", 2025)
    assert len(serie.eur_mwh) == 8760
    assert set(np.unique(serie.eur_mwh.round(6))) <= {60.0, 140.0}


def test_anno_letto_dal_file(tmp_path):
    f = tmp_path / "prezzi.csv"
    _scrivi_csv(f, 2024)  # la prima riga è 2024-01-01T00:00+01:00, cioè 2023-12-31 in UTC
    assert anno_dei_prezzi(f) == 2024


def test_csv_senza_fuso_rifiutato(tmp_path):
    f = tmp_path / "senza_fuso.csv"
    _scrivi_csv(f, 2024, con_fuso=False)
    with pytest.raises(ValueError, match="fuso"):
        prezzi_da_csv(f, "NORD", 2024)


def test_csv_con_troppi_buchi(tmp_path):
    f = tmp_path / "buchi.csv"
    _scrivi_csv(f, 2024, buchi=48)
    with pytest.raises(ValueError, match="Mancano"):
        prezzi_da_csv(f, "NORD", 2024)


def test_zona_e_colonne(tmp_path):
    f = tmp_path / "prezzi.csv"
    _scrivi_csv(f, 2024)
    with pytest.raises(ValueError):
        prezzi_da_csv(f, "LUNA", 2024)
    with pytest.raises(ValueError, match="colonne"):
        prezzi_da_csv(f, "CNOR", 2024)


def test_scalata_mantiene_la_forma(tmp_path):
    f = tmp_path / "prezzi.csv"
    _scrivi_csv(f, 2024)
    serie = prezzi_da_csv(f, "NORD", 2024)
    scalata = serie.scalata(110)
    assert scalata.media == pytest.approx(110)
    np.testing.assert_allclose(scalata.eur_mwh / serie.eur_mwh, 110 / serie.media)


def test_prezzo_costante_e_rimappatura():
    c = prezzo_costante(110, 2023)
    assert c.qualita == "C" and c.media == 110
    assert len(c.per_anno_progetto(2028)) == len(year_index(2028))


@pytest.mark.parametrize("contenuto, messaggio", [
    (b"", "vuoto"),
    (b"PK\x03\x04resto", "Excel"),
    ("inizio,NORD\n".encode("utf-16"), "UTF-16"),
    (bytes(range(256)) * 4, "UTF-8"),
    (b"Data;Ora;PUN;NORD\n20250101;1;100,5;99\n", "GME"),
    (b"prezzo\n1\n", "manca la colonna 'inizio'"),
    (b"inizio,NORD\n", "nessuna data valida"),
])
def test_file_sbagliati_con_messaggi_chiari(tmp_path, contenuto, messaggio):
    """I file sbagliati più comuni danno un messaggio in italiano che dice che cosa fare, non l'errore di pandas."""
    f = tmp_path / "prezzi.csv"
    f.write_bytes(contenuto)
    with pytest.raises(ValueError, match=messaggio):
        anno_dei_prezzi(f)


def test_punto_e_virgola_e_virgola_decimale(tmp_path):
    """Il CSV salvato da Excel in italiano: separatore «;» e virgola decimale."""
    f = tmp_path / "prezzi.csv"
    _scrivi_csv(f, 2024)
    df = pd.read_csv(f)
    df["NORD"] = df["NORD"].map(lambda v: f"{v:.2f}".replace(".", ","))
    df[["inizio", "NORD"]].to_csv(f, index=False, sep=";")
    assert prezzi_da_csv(f, "NORD", 2024).media == pytest.approx(prezzi_da_csv_media_attesa())


def prezzi_da_csv_media_attesa():
    ore = pd.date_range("2024-01-01", "2025-01-01", freq="h", tz=TZ, inclusive="left").hour
    return float(np.where((ore >= 10) & (ore <= 15), 60.0, 140.0).mean())


def test_unita_e_righe_sbagliate(tmp_path):
    f = tmp_path / "prezzi.csv"
    _scrivi_csv(f, 2024)
    df = pd.read_csv(f)
    df.assign(NORD=df["NORD"] / 1000).to_csv(f, index=False)
    with pytest.raises(ValueError, match="€/kWh"):
        prezzi_da_csv(f, "NORD", 2024)
    df.assign(NORD=df["NORD"] * 100).to_csv(f, index=False)
    with pytest.raises(ValueError, match="fuori scala"):
        prezzi_da_csv(f, "NORD", 2024)
    rotto = df.astype({"NORD": object})
    rotto.loc[5, "NORD"] = "n.d."
    rotto.to_csv(f, index=False)
    with pytest.raises(ValueError, match="alla riga 7"):
        prezzi_da_csv(f, "NORD", 2024)
    rotto = df.astype({"inizio": str})
    rotto.loc[9, "inizio"] = "2024-13-01T00:00:00+01:00"
    rotto.to_csv(f, index=False)
    with pytest.raises(ValueError, match="riga 11"):
        prezzi_da_csv(f, "NORD", 2024)
