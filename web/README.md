# Interfaccia web della CER

React e Vite, con lo stile del simulatore della casa; il motore `cersim` gira nel browser con Pyodide, in un Web
Worker. Architettura, misure della prova di fattibilità, contratto dei messaggi e pubblicazione:
[docs/web_architettura.md](../docs/web_architettura.md).

```
npm install
npm run dev               # http://127.0.0.1:5173 (oppure: npm run dev -- --port 5181)
npm run build             # sito statico in dist/
npm run prova:pyodide     # prova del motore in Pyodide, in Node, con tempi e pesi
npm run sincronizza-stile -- "<cartella del progetto Casa>"
```

In sviluppo le serie PVGIS vengono dalla cache locale di cersim (`~/.cache/cersim/pvgis`); con
`VITE_PVGIS_INTERMEDIARIO` vengono dall'intermediario ([../intermediario](../intermediario/README.md); in locale
`npm run locale` là e `VITE_PVGIS_INTERMEDIARIO=http://127.0.0.1:8787 npm run dev -- --port 5181` qui) e restano
nella Cache Storage del browser. La ricerca dell'indirizzo del passo 1 passa dallo stesso intermediario
(`/geo/cerca`): senza intermediario è spenta e la posizione si scrive a mano. Il piede rimanda a licenza e crediti
(`licenza.txt`, generato da `LICENZA.md` e `LICENSE`).

Passi fatti: 1 (Luogo) e 2 (Membri e consumi, con il link per le schede delle famiglie: `?modulo=famiglia` apre
una pagina leggera, senza motore, in `src/scheda/`; i suoi testi in `src/scheda/testi.json` si rigenerano con
`python -m cersim.web` dalla radice del progetto) e 3 (Impianti: tetto disegnato sulla foto aerea con Leaflet, caricato
solo all'apertura della mappa; ombre dagli edifici vicini, chiesti dal browser a Overpass; proposta delle tre
taglie; tabella degli impianti), 4 (Economia: riparto, prezzi orari per uso personale, valori avanzati) e 5
(Risultati completi con grafici SVG, curva delle taglie, report PDF ed Excel generati nel browser), con la bozza in
`localStorage`, "Importa" ed "Esporta" nel formato di salvataggio dell'app Streamlit (`cersim.ui_model.esporta_json`).
I pacchetti dei report (fpdf2, openpyxl) che Pyodide non ha li scarica `vite.config.ts` da PyPI in `.pacchetti/`, con
l'hash controllato, e li mette nel sito in `motore/pacchetti/`. I controlli e
la lettura dei file li fa il motore nel Worker (`cersim/web.py`, `FUNZIONI`; docs/web_architettura.md, sezione 3).

`public/esempi/torino.json` è il caso di `esempi/caso_studio_torino.py` (come CER, quota ai membri 0,5) salvato con
`cersim.ui_model.esporta_json`.
