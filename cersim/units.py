"""Unità di misura del progetto.

Convenzione unica: energia in kWh, potenza in kW, prezzi e tariffe in €/MWh
(come nelle fonti normative). Ogni prodotto prezzo × energia passa da `eur`,
così la conversione kWh → MWh non può essere dimenticata.
"""

import numpy as np

KWH_PER_MWH = 1000.0


def eur(kwh, eur_per_mwh):
    """Importo in euro di un'energia in kWh valorizzata a un prezzo in €/MWh.

    Accetta scalari o array numpy (anche orari, con broadcasting).
    """
    return np.asarray(kwh, dtype=float) / KWH_PER_MWH * np.asarray(eur_per_mwh, dtype=float)
