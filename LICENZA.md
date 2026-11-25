# Licenza e componenti di terzi

## Licenza del codice

- **Il codice di questo repository è distribuito con licenza MIT**, © 2026 Samuele Racca, testo in [LICENSE](LICENSE).
  Scelta il 24/11/2026, come per il simulatore della casa
  ([efficienza-energetica-casa](https://github.com/raccasamuele/efficienza-energetica-casa)). Vale per tutto il codice
  scritto per il progetto: il motore `cersim`, l'app Streamlit (`app.py`), l'interfaccia `web/`, l'intermediario
  `intermediario/`, gli script, i test e i file di esempio.
- In breve: chiunque può usare, copiare, modificare e ridistribuire il codice, anche per scopi commerciali, purché
  conservi l'avviso di copyright e il testo della licenza. Il software è fornito «così com'è», senza garanzie.
  Questa pagina è un riassunto: vale il testo inglese di [LICENSE](LICENSE).
- **I dati e il software di terzi conservano le loro licenze e condizioni**, elencate qui sotto: la licenza MIT non
  si estende a loro. Chi riusa il progetto deve rispettarle, in particolare le attribuzioni e le condizioni del GME.

## Materiale nel repository

| Materiale | Licenza o condizioni | Dove |
|---|---|---|
| Codice del progetto (motore, app, sito, intermediario, script, test) | MIT | tutto il repository salvo le righe seguenti |
| Parametri normativi (DM MASE 414/2023, Regole Operative GSE, delibere ARERA, DM 24/12/2014) | Valori ricavati da atti e documenti pubblici, con la fonte accanto a ogni valore; gli atti normativi non sono protetti dal diritto d'autore (art. 5 L. 633/1941) | `cersim/data/*.yaml`, [docs/fonti_normative.md](docs/fonti_normative.md) |
| Foglio di stile comune con Casa | MIT, stesso autore (copia di `src/styles.css` di Casa) | `web/src/stile/casa.css` |
| Icone del sito | Generate per il progetto (prompt e post-produzione in `docs/interfaccia-2026-10-29/icone/`), MIT con il codice | `web/public/icons/`, `docs/interfaccia-2026-10-29/icone/`, `estensione/icona.png` |
| Video del disegno del tetto | Realizzato per il progetto con un'interfaccia illustrata, senza immagini aeree né edifici veri; MIT con il codice | `static/video_tetto.mp4` |
| Esempi | Inventati o calcolati dal simulatore della casa (MIT); nessun dato personale | `esempi/`, `web/public/esempi/` |
| Font Geist | SIL Open Font License 1.1 | `static/Geist-*`, testo in [static/Geist-OFL.txt](static/Geist-OFL.txt) |

Il repository **non contiene** prezzi del GME, serie PVGIS, foto aeree né estratti di OpenStreetMap: si scaricano
quando servono, come spiegato sotto.

## Dati di terzi usati dal programma

- **PVGIS** (© Unione Europea, Joint Research Centre): produzione oraria per 1 kWp, scaricata a richiesta e tenuta in
  cache (in locale e nell'intermediario per 90 giorni). Riuso consentito citando la fonte, secondo le
  [condizioni d'uso PVGIS](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/general-information/usage-conditions-data-protection_en).
- **OpenStreetMap** (Nominatim per gli indirizzi, Overpass per gli edifici vicini): © OpenStreetMap contributors,
  [ODbL 1.0](https://www.openstreetmap.org/copyright). L'attribuzione compare nella ricerca dell'indirizzo, sotto la
  pianta degli edifici vicini e, per le ombre, nel report PDF ed Excel. Le
  [regole d'uso di Nominatim](https://operations.osmfoundation.org/policies/nominatim/) valgono per chiunque pubblichi
  una copia dell'intermediario: identificare l'applicazione, al massimo una richiesta al secondo.
- **Foto aerea Esri World Imagery** (Esri, Maxar, Earthstar Geographics e comunità GIS): le immagini arrivano dai
  server di Esri al browser, con l'attribuzione sulla mappa; non sono nel repository. Il loro uso segue i
  [termini di Esri](https://www.esri.com/en-us/legal/terms/full-master-agreement): chi pubblica una copia del sito deve
  verificarli per il proprio uso.
- **Prezzi del GME**: li fornisce l'utente, da un file suo. Le condizioni del GME ne consentono **solo l'uso
  privato** e vietano ridistribuzione e download automatico; per mostrarli nel sito pubblico serve un'autorizzazione
  scritta del GME, ancora da chiedere (dettagli in [docs/fonti_normative.md](docs/fonti_normative.md)). La licenza MIT
  del codice non cambia queste condizioni.

## Software di terzi

- Python: numpy, pandas, pydantic, PyYAML, requests, tzdata, matplotlib (BSD, MIT, Apache-2.0, PSF), fpdf2
  (LGPL-3.0), openpyxl (MIT), Streamlit, folium e streamlit-folium (Apache-2.0, MIT) per l'app.
- Sito: Pyodide (MPL-2.0, caricato dalla sua CDN), React (MIT), Vite (MIT), Lucide (ISC), Leaflet (BSD-2-Clause),
  il font Poppins (SIL OFL 1.1). Il sito serve senza modifiche i pacchetti dei report fpdf2 (LGPL-3.0), openpyxl ed
  et_xmlfile (MIT) e defusedxml (PSF).
- Intermediario: strumenti di Cloudflare e TypeScript (MIT, Apache-2.0), solo per sviluppo e pubblicazione.

Sono tutte licenze compatibili con la distribuzione del progetto sotto MIT: le licenze permissive chiedono di
conservare i propri avvisi; MPL-2.0 e LGPL-3.0 riguardano i file di quelle librerie, che il progetto usa senza
modificarli e che restano sotto la loro licenza.

## Versioni precedenti

Fino al 29/10/2026 il repository dichiarava la licenza AGPL-3.0-or-later; dal 29/10/2026 al 24/11/2026 la PolyForm
Strict License 1.0.0 con un permesso aggiuntivo per l'uso del sito ufficiale. Dal 24/11/2026 vale la licenza MIT, che
l'autore concede anche per le versioni precedenti del codice.
