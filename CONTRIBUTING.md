# Come contribuire

Grazie dell'interesse. È un progetto personale, curato nel tempo libero: le risposte possono richiedere qualche
giorno. Partecipando accetti il [codice di comportamento](CODE_OF_CONDUCT.md).

## Prima di tutto: niente dati personali

Il simulatore lavora con bollette, letture dei contatori e indirizzi. **Non allegare mai dati veri** nelle issue,
nelle pull request o nei test: niente codici POD, nomi, indirizzi o curve di consumo di persone reali. Se serve un
file d'esempio, inventa o cambia nomi e numeri (gli esempi del repository usano `IT001E00000000` e «Via Esempio 1»).

## Segnalare un problema

- **Un errore o un numero che non torna**: apri una [issue](../../issues/new/choose) con il modello «Qualcosa non
  funziona». Scrivi che cosa hai fatto, che cosa ti aspettavi e che cosa è successo, con la versione del motore
  (`cersim`), che il sito mostra in fondo ai Risultati.
- **Una regola normativa o un valore da aggiornare** (DM 414/2023, Regole Operative GSE, delibere ARERA): usa il
  modello «Regola o valore da aggiornare» e indica la fonte ufficiale, con data, articolo o paragrafo.
- **Un problema di sicurezza**: non aprire una issue pubblica. Segui [SECURITY.md](SECURITY.md).

## Proporre una modifica

1. Per modifiche grandi apri prima una issue, così ne parliamo prima che tu ci lavori.
2. Fai un fork, crea un ramo e lavora lì.
3. Prima della pull request fai girare le prove (sotto) e aggiorna la documentazione toccata.
4. Apri la pull request e compila il modello: che cosa cambia, perché, come l'hai provato.

Le pull request devono passare i controlli automatici di GitHub (`tests`).

## Ambiente e prove

Serve Python 3.11 o più recente; per il sito e l'intermediario Node.js 22.

```bash
python -m pip install -e ".[dev]"     # oppure: pip install -r requirements.txt
python -m pytest                      # motore e app; i test non usano la rete

cd web && npm ci && npm run typecheck && npm test && npm run build
cd ../intermediario && npm ci && npm test
```

## Regole del progetto

- **Lingua**: testi dell'interfaccia, documenti, commenti, commit e pull request in **italiano semplice**, adatto a
  sindaci e amministratori di condominio, non solo a tecnici.
- **Regole normative**: formule, soglie, requisiti e termini stanno in `cersim/data/*.yaml`, ciascuno con la fonte
  accanto. Non si cambiano senza una fonte ufficiale citata, e la modifica va descritta in
  [docs/fonti_normative.md](docs/fonti_normative.md).
- **Casi non supportati**: si rifiutano con un messaggio chiaro, non si approssimano.
- **Dati di terzi**: non aggiungere al repository prezzi del GME, serie PVGIS, foto aeree o estratti di
  OpenStreetMap. Le condizioni sono in [LICENZA.md](LICENZA.md).
- **Stile**: quello di Casa, in `web/src/stile/casa.css`, che non si modifica (le aggiunte vanno in `cer.css`).

## Licenza dei contributi

Il codice è distribuito con licenza [MIT](LICENSE). Inviando un contributo accetti che sia distribuito con la
stessa licenza.
