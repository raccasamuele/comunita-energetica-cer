# cersim: simulatore di comunità energetiche per comuni e condomini

Simulatore open source di **comunità energetiche rinnovabili (CER)** e **gruppi di autoconsumatori** (condomini).
Da pochi dati di bolletta e un indirizzo produce uno **scenario preliminare**: quanta energia si condivide ora per
ora, quanti contributi GSE arrivano, chi paga e chi ci guadagna, con l'intervallo di incertezza e un report da
portare in assemblea o in consiglio. Non sostituisce uno studio di fattibilità.

Pensato per sindaci, funzionari comunali e amministratori di condominio: testi in italiano corrente, numeri sempre
con il loro intervallo e la qualità dei dati.

- **Provalo:** <https://cer.raccasamuele.it>. Si usa nel browser, senza account: consumi e dati dei membri restano
  nel browser e il calcolo si fa sul dispositivo.
- **Per gli agenti AI:** un server MCP locale con lo stesso motore del sito ([docs/GUIDA-MCP.md](docs/GUIDA-MCP.md)).
- Fa parte di **Energia in chiaro**, con il simulatore della casa
  ([efficienza-energetica-casa](https://github.com/raccasamuele/efficienza-energetica-casa)).

## Che cosa fa

L'app (`app.py`, Streamlit) guida in cinque passi, preceduti da *Prima di iniziare*:

1. **Luogo:** indirizzo, tipo di configurazione (gruppo nello stesso edificio o comunità energetica tra edifici
   diversi), data di costituzione.
2. **Membri e consumi:** una riga per contatore. I consumi si raccolgono con un link: ogni famiglia o attività
   compila la sua scheda e manda un piccolo file a chi coordina.
3. **Impianti:** si disegna il tetto sulla foto aerea; il simulatore ricava superficie e orientamento (anche due
   falde a est e a ovest) e propone tre taglie. In una comunità energetica si procede un tetto alla volta, su
   edifici diversi. In alternativa si inseriscono i dati di un preventivo.
4. **Economia:** come dividere i contributi tra i membri e chi paga l'impianto; valori avanzati e prezzi orari
   facoltativi.
5. **Risultati:** frase di sintesi, cifre con intervallo, confronto con il solo fotovoltaico, requisiti, grafici,
   chi paga e chi riceve, *Come rendere la stima più precisa*, report PDF ed Excel.

Un esempio completo, lo stesso condominio come gruppo e come comunità energetica, è in
[docs/caso_studio_torino.md](docs/caso_studio_torino.md).

## Come funziona il calcolo

Tutto si calcola **ora per ora** per 25 anni, con il meteo reale di tre anni (2021, 2022, 2023), come fa il GSE per
l'energia condivisa.

**Energia** (`cersim/simulate.py`), per ogni ora e ogni contatore:

- produzione `P` da PVGIS per 1 kWp, moltiplicata per i kWp dei moduli e limitata dalla potenza dell'inverter;
  con due falde, media dei due profili;
- consumo `L` da una curva tipica per tipo di utenza (feriale, sabato, festivo, mese per mese), adattata al
  consumo annuo e alle fasce F1 e F2+F3 della bolletta;
- autoconsumo fisico `SC = min(L, P)` al contatore dell'impianto, immissione `I = P − SC`, prelievo `W = L − SC`;
- energia condivisa `EACV = min(Σ I, Σ W)` sui membri, e `EACI` per la tariffa premio, considerando per ogni
  impianto solo le ore in cui è in esercizio e incentivato.

**Euro** (`cersim/incentives.py`, `cersim/economics.py`):

- tariffa premio per 20 anni: `min(CAP; base + max(0; 180 − Pz)) + correzione geografica`, per l'energia
  condivisa, ridotta del fattore F se c'è un contributo in capitale; base e tetto dipendono dalla potenza
  (80/120 €/MWh fino a 200 kW);
- valorizzazione ARERA: `TRASE × EACV`; per il gruppo anche le perdite di rete evitate;
- vendita dell'energia immessa al prezzo zonale orario `Pz` (Ritiro dedicato o mercato);
- risparmio in bolletta: autoconsumo fisico × costo evitato per kWh;
- costi: impianto, manutenzione e assicurazione, sostituzione dell'inverter, smaltimento, costituzione e gestione
  della configurazione;
- un registro di tutti i movimenti (chi paga, chi riceve, quanto, quando), da cui si ricavano il valore attuale
  netto per la configurazione e per chi investe, il rientro e il netto per ogni membro.

**Scenari:** 3 anni meteo × 3 livelli di prezzo × consumi tipici, più di giorno o più la sera. I risultati mostrano
la mediana e l'intervallo tra minimo e massimo. Il dimensionamento prova diverse taglie dell'impianto sugli stessi
scenari.

Le regole sui contributi sono verificate sulle fonti in [docs/fonti_normative.md](docs/fonti_normative.md) e
raccolte in pacchetti versionati con scadenza (`cersim/data/`). Quando il pacchetto normativo scade, l'app smette
di calcolare gli euro finché non viene rivisto.

## Qualità dei dati

Ogni risultato riporta una qualità, la peggiore tra produzione, consumi e prezzi:

| Qualità | Che cosa serve |
|---|---|
| **C** | almeno un dato tipico: un consumo da famiglia tipo, un prezzo costante o la produzione senza PVGIS |
| **B** | consumo annuo e fasce dalla bolletta (o una curva misurata) per ogni contatore, produzione da PVGIS, prezzi orari da file |
| **A** | come B, e almeno tre quarti dei consumi da curve misurate di almeno 11 mesi |

Le curve misurate si caricano al passo 2 dai file del Portale Consumi o di e-distribuzione, oppure arrivano con le
schede delle famiglie: formati, uso e privacy in [docs/consumi_misurati.md](docs/consumi_misurati.md). Allo
stesso passo si può caricare una curva **calcolata** dal simulatore della casa, per esempio con una pompa di calore
([docs/formato_curva_consumi.md](docs/formato_curva_consumi.md)): la simulazione la usa ora per ora, ma vale
qualità B e non conta per la A. Con il **profilo energetico** della casa
([docs/formato_profilo_energetico.md](docs/formato_profilo_energetico.md)) si sceglie lo scenario e il fotovoltaico
della casa può entrare nella comunità, con la sua batteria simulata sul contatore.

Più dati reali si inseriscono, più l'intervallo si stringe. L'app elenca i dati mancanti in ordine di importanza
nei risultati e nel report.

## Ipotesi e limiti

- **Curve di consumo tipiche.** Senza consumi misurati l'ora dei consumi è un'ipotesi del modello, tarata su
  consumo annuo e fasce: è la principale fonte di incertezza dell'energia condivisa. Con i file del Portale Consumi
  o di e-distribuzione si usano le ore vere.
- **Prezzi costanti di base.** Senza un file di prezzi orari si usano tre livelli medi costanti (80, 110 e 140
  €/MWh): la vendita nelle ore di sole risulta sovrastimata. I prezzi orari del GME si possono caricare solo per
  uso personale.
- **Costo dell'impianto.** Senza preventivo si usa il costo massimo di riferimento del DM 414/2023 per kWp di moduli:
  una stima alta.
- **Valori predefiniti:** costo evitato 0,15 €/kWh, tasso di sconto reale 4%, degrado dei moduli 0,5% all'anno,
  vita utile 25 anni, manutenzione e assicurazione 1,8% del costo all'anno, inverter sostituito al 12° anno,
  costituzione e gestione 600 € e 300 € all'anno per un gruppo, 2.500 € e 1.200 € per una comunità energetica.
  Tutti modificabili nell'app (`cersim/data/assunzioni_economiche.yaml`).
- **Tetto e ombre.** Superficie e orientamento dal disegno sulla foto aerea; ombre stimate dagli edifici vicini
  di OpenStreetMap, senza alberi e camini. Serve il sopralluogo di un installatore.
- **Esclusi:** imposte (IVA, imposte sui contributi e sui ricavi), detrazioni fiscali, finanziamento
  dell'investimento, batterie, impianti esistenti, più impianti sullo stesso contatore, impianti oltre 1 MW.
- **Requisiti.** Il controllo è sui dati dichiarati, non sui documenti: cabina primaria, soggetti ammessi e
  contributi vanno verificati con un professionista.

## Fonti

- Regole dei contributi: DM MASE 414/2023, Regole Operative GSE CACER, delibere ARERA (dettaglio in
  [docs/fonti_normative.md](docs/fonti_normative.md)).
- Produzione: [PVGIS](https://re.jrc.ec.europa.eu/pvg_tools/) della Commissione europea.
- Indirizzi ed edifici vicini: © OpenStreetMap contributors (ODbL). Foto aerea: Esri World Imagery.
- Prezzi orari: forniti dall'utente (dati GME, solo uso personale).

## Provarlo

Serve Python 3.11 o più recente. Conviene creare l'ambiente virtuale fuori da cartelle sincronizzate (OneDrive, Dropbox).

```bash
python -m venv ~/.venvs/cersim
~/.venvs/cersim/Scripts/python -m pip install -r requirements.txt   # su Linux/macOS: ~/.venvs/cersim/bin/python
~/.venvs/cersim/Scripts/python -m pytest                           # i test non usano la rete
~/.venvs/cersim/Scripts/python -m streamlit run app.py             # l'app su http://localhost:8501
```

Esempi da riga di comando (scaricano i dati PVGIS la prima volta):

```bash
~/.venvs/cersim/Scripts/python esempi/caso_studio_torino.py         # gruppo contro comunità energetica
~/.venvs/cersim/Scripts/python esempi/condominio_torino.py          # energia, euro, scenari, dimensionamento
~/.venvs/cersim/Scripts/python esempi/bilancio_condominio_torino.py # solo energia
```

Il motore si usa anche dalla riga di comando, con il file di progetto che esporta il sito o l'app. Le uscite sono
JSON nel formato descritto in [docs/formato_progetto_cer.md](docs/formato_progetto_cer.md), pensato anche per altri
programmi e per gli agenti AI:

```bash
~/.venvs/cersim/Scripts/python -m pip install -e .                  # una volta: aggiunge il comando cersim
cersim valida web/public/esempi/torino.json                         # controlla il file e lo riassume
cersim analizza web/public/esempi/torino.json -o esito.json         # analisi completa (formato esito-cer)
cersim analizza progetto.json --parametro quota_membri=0.6 --senza-rete
cersim report web/public/esempi/torino.json -o scenario.pdf         # anche .xlsx
cersim schema progetto                                              # lo schema JSON (o: cersim schema esito)
```

Senza installare, `python -m cersim.cli` al posto di `cersim`.

Negli agenti AI (Claude Code, Claude Desktop e altri compatibili con MCP): `pip install -e .`, poi
`claude mcp add --scope user cer -- <percorso di python> -m cersim.mcp.server`. Per Claude Desktop c'è anche
l'estensione da installare con un doppio clic (`python estensione/crea_pacchetto.py` crea `dist/cer-<versione>.mcpb`),
con i risultati in una scheda con i grafici nella chat. Dettagli in [docs/GUIDA-MCP.md](docs/GUIDA-MCP.md).

## Struttura del codice

| File | Che cosa contiene |
|---|---|
| `app.py` | l'interfaccia Streamlit; nessun calcolo |
| `cersim/model.py` | membri, contatori, impianti, configurazione |
| `cersim/eligibility.py` | requisiti della configurazione e degli impianti |
| `cersim/pv.py`, `cersim/loads.py` | produzione (PVGIS, con cache) e curve di consumo |
| `cersim/misure.py` | lettura dei consumi misurati (Portale Consumi, e-distribuzione) |
| `cersim/curva_calcolata.py` | lettura delle curve calcolate dal simulatore della casa (formato `curva-consumi`) |
| `cersim/profilo.py` | profilo energetico della casa: lettura, scenari applicati a un contatore, riesportazione ([formato](docs/formato_profilo_energetico.md)) |
| `cersim/simulate.py` | bilancio energetico orario |
| `cersim/incentives.py`, `cersim/economics.py` | contributi, vendite, costi, registro dei movimenti, VAN |
| `cersim/scenari.py`, `cersim/sizing.py` | scenari, sensibilità, dimensionamento |
| `cersim/tetto.py`, `cersim/proposta.py` | tetto dalla foto aerea e proposta delle tre taglie |
| `cersim/guida.py` | scheda dei consumi per le famiglie |
| `cersim/report.py`, `cersim/analisi.py` | testi dei risultati, report PDF ed Excel |
| `cersim/data/` | pacchetti normativo, economico e classificazione dei soggetti |
| `cersim/web.py` | ingresso del motore per l'interfaccia web (Pyodide nel browser) |
| `cersim/schema.py`, `cersim/schemi/` | schemi JSON del progetto (ingresso) e dell'esito (uscita) ([formato](docs/formato_progetto_cer.md)) |
| `cersim/cli.py` | riga di comando `cersim`: valida, analizza, report, schema |
| `cersim/mcp/` | server MCP per gli agenti AI (`cersim-mcp`): le operazioni di `web.py`, con PVGIS scaricato dal server e la scheda con i grafici nella chat (`scheda.html`, MCP Apps) ([guida](docs/GUIDA-MCP.md)) |
| `estensione/` | estensione per Claude Desktop: `crea_pacchetto.py` crea il file `.mcpb` da installare con un doppio clic |
| `web/` | l'interfaccia web pubblicata su cer.raccasamuele.it: React, stile comune con il simulatore della casa, motore nel browser ([docs/web_architettura.md](docs/web_architettura.md)) |
| `intermediario/` | Worker di Cloudflare che inoltra a PVGIS le richieste del sito, con cache ([README](intermediario/README.md)) |

## Stato

Il sito è online su <https://cer.raccasamuele.it>. Prima di considerare affidabili i risultati mancano la revisione
di un caso di comunità energetica e di un caso condominiale da parte di un esperto esterno, la prova dei consumi
misurati con file reali e i prezzi orari nell'app pubblica, che richiedono l'autorizzazione del GME. L'app Streamlit
(`app.py`) resta nel repository finché il sito non la sostituisce del tutto.

## Privacy

Nomi, consumi, prezzi e risultati restano nella sessione del browser e non vengono salvati sul server; per
conservarli si usa *Salva il lavoro*. Escono dall'app solo l'indirizzo (a OpenStreetMap, se si preme *Cerca*), le
coordinate del tetto (a OpenStreetMap, se si stimano le ombre), le coordinate arrotondate a circa 1 km (a PVGIS,
con cache sul server per 90 giorni) e le richieste della foto aerea (a Esri, dal browser).

## Contribuire

Segnalazioni e proposte sono benvenute: le regole sono in [CONTRIBUTING.md](CONTRIBUTING.md) e vale il
[codice di comportamento](CODE_OF_CONDUCT.md). Non allegare mai dati personali veri (bollette, POD, indirizzi).

## Sicurezza

Un problema di sicurezza si segnala in privato, non con una issue pubblica: scrivi a **sicurezza@raccasamuele.it** o
usa «Report a vulnerability» nella scheda *Security* del repository. Dettagli in [SECURITY.md](SECURITY.md).

## Licenza

- **Il codice è distribuito con licenza [MIT](LICENSE)**, © 2026 Samuele Racca, come il simulatore della casa:
  si può usare, modificare e ridistribuire, anche per scopi commerciali, conservando l'avviso di copyright.
- **I dati e il software di terzi tengono le loro licenze**, elencate in [LICENZA.md](LICENZA.md): PVGIS (© Unione
  Europea, JRC; riuso con riconoscimento della fonte), OpenStreetMap (ODbL 1.0), foto aerea Esri (termini di Esri,
  non inclusa nel repository), font Geist e Poppins (OFL).
- I **prezzi del GME** restano per uso privato finché il GME non lo autorizza: la licenza MIT non si estende a quei
  dati.
