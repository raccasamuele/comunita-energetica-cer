# Formato `curva-consumi`: consumi calcolati da importare in cersim

Per portare la casa intera (situazione attuale e scenari, con il fotovoltaico che può entrare nella comunità e la
batteria) c'è anche il [profilo energetico](formato_profilo_energetico.md); questo formato resta valido.

Questo formato porta in cersim i consumi elettrici di un contatore **calcolati da un modello**, per esempio il
simulatore della casa (modello termico orario, pompa di calore, fotovoltaico). Serve a vedere come cambia l'energia
condivisa di una comunità energetica quando i membri installano una pompa di calore. Il lettore è
`cersim/curva_calcolata.py`; `esporta` nello stesso modulo è l'esportazione di riferimento.

cersim usa la curva calcolata **come una curva misurata**: decide ora e quantità dei consumi di quel contatore,
consumo annuo e fasce della tabella non si usano, le varianti dei consumi non si applicano. La qualità dei dati invece
**non è quella dei consumi reali**: un contatore con curva calcolata vale qualità **B**, come uno con consumo e fasce
dalla bolletta, e non conta mai per la qualità A (che richiede tre quarti dei consumi da curve misurate). Vedi
[consumi_misurati.md](consumi_misurati.md).

## Esempio

Un file JSON in UTF-8 (il BOM è ammesso), estensione `.json`. Le 864 celle sono accorciate:

```json
{
  "formato": "curva-consumi",
  "versione": 2,
  "natura": "calcolato",
  "unita": "kWh",
  "fonte": "simulatore-casa",
  "motore": "casa-1R1C 0.4",
  "descrizione": "Casa Rossi, pompa di calore aria-acqua",
  "fv_sottratto_kwp": 0,
  "kwh_annui": 6139.6,
  "ore": [0.85, 0.85, 0.85, 0.85, 0.85, 0.85, 2.25, 2.25, 2.25, 0.85, "… 864 valori in tutto …"]
}
```

Un file completo, **inventato**, è in [esempi/curva_consumi_esempio.json](../esempi/curva_consumi_esempio.json).

## Campi

Tutti i campi sono obbligatori tranne `motore` e `descrizione`. Un campo non previsto fa rifiutare il file: un campo
nuovo richiede una nuova versione.

| Campo | Tipo | Valore |
|---|---|---|
| `formato` | testo | sempre `"curva-consumi"` |
| `versione` | intero | `2`, oppure `3` se la casa ha una batteria; cersim legge anche la `1`, che non ha `fv_sottratto_kwp`. Una versione che cersim non conosce fa rifiutare il file |
| `natura` | testo | sempre `"calcolato"`. I consumi misurati si caricano con i file del distributore, non con questo formato |
| `unita` | testo | sempre `"kWh"` |
| `fonte` | testo | chi ha calcolato la curva: nome breve in minuscolo, cifre e trattini, al massimo 40 caratteri. Per il simulatore della casa `"simulatore-casa"` |
| `motore` | testo o `null` | modello e versione, al massimo 80 caratteri, per esempio `"casa-1R1C 0.4"` |
| `descrizione` | testo o `null` | che cosa rappresenta la curva, al massimo 200 caratteri, per esempio `"Casa Rossi, pompa di calore aria-acqua"` |
| `fv_sottratto_kwp` | numero | dalla versione 2: i kWp di fotovoltaico già tolti dai consumi, cioè la curva sono i prelievi dalla rete. `0` se la casa non ha FV. cersim avvisa di non inserire di nuovo lo stesso impianto sul punto, perché verrebbe contato due volte. Da 0 a 10.000 |
| `batteria_kwh` | numero | solo nella versione 3, obbligatorio: la capacità utile in kWh della batteria di casa già considerata nei prelievi. cersim avvisa che una batteria privata riduce l'energia condivisa: si scarica la sera, proprio nelle ore in cui la comunità potrebbe coprire quei consumi. Da 0 a 1.000 |
| `kwh_annui` | numero | consumo elettrico annuo del contatore in kWh: la somma delle ore dell'anno simulato. Maggiore di zero, al massimo 10.000.000 |
| `ore` | elenco di 864 numeri | la forma media, in kWh, nell'ordine descritto sotto |

`motore` e `descrizione` compaiono nell'interfaccia di cersim: caratteri di controllo e segni di Markdown o HTML
(`` ` * _ [ ] < > # | ~ ! \ ``) vengono tolti, il testo troppo lungo viene accorciato.

## Le 864 celle

Ogni cella è il **consumo medio in kWh di un'ora** (l'energia prelevata dalla rete in quell'ora, non una potenza)
per un tipo di giorno, un mese e un'ora civile:

```
indice = (tipo_giorno × 12 + (mese − 1)) × 24 + ora
```

- `tipo_giorno`: 0 feriale (da lunedì a venerdì), 1 sabato, 2 festivo (domenica e festività nazionali). Le
  festività sono quelle delle fasce ARERA: 1 gennaio, 6 gennaio, Pasquetta, 25 aprile, 1 maggio, 2 giugno,
  15 agosto, 1 novembre, 8 dicembre, 25 e 26 dicembre. Una festività di sabato è festivo.
- `mese`: da 1 (gennaio) a 12.
- `ora`: da 0 a 23, **ora civile Europe/Rome**, cioè quella dell'orologio, con l'ora legale. La cella dell'ora 7 è
  l'energia tra le 07:00 e le 08:00 dell'orologio, d'inverno e d'estate.

Quindi l'indice 0 è feriale, gennaio, 00:00-01:00; il 7 è feriale, gennaio, 07:00-08:00; il 288 è sabato, gennaio,
00:00-01:00; l'863 è festivo, dicembre, 23:00-24:00. Nei messaggi di errore cersim indica sia l'indice sia la cella
in parole.

Il valore di una cella è la **media** sulle ore dell'anno simulato che cadono in quel tipo di giorno, mese e ora.
Per esempio la cella feriale, gennaio, ore 7 è la media delle 07:00-08:00 dei feriali di gennaio. Nel giorno del
passaggio all'ora legale (ultima domenica di marzo) l'ora 2 non esiste e quel giorno non entra nella media dell'ora
2; nel ritorno all'ora solare (ultima domenica di ottobre) l'ora 2 si ripete ed entrano entrambe.

## Validazione in cersim

Il file è trattato come **non fidato**. cersim lo rifiuta, con un messaggio in italiano, se:

- supera 200 kB, non è UTF-8 o non è un JSON valido;
- `formato` non è `"curva-consumi"`, `versione` non è un intero tra quelli letti (`1`, `2` e `3`), mancano campi
  obbligatori o ce ne sono di non previsti;
- `natura`, `unita` o `fonte` non hanno il valore richiesto;
- `ore` non ha esattamente 864 elementi, o un elemento non è un numero finito e non negativo. `NaN`, `Infinity`,
  numeri come testo (`"0,4"`), `true` e `null` non sono ammessi; la curva tutta a zero nemmeno;
- `kwh_annui` non è un numero maggiore di zero e al massimo 10.000.000;
- `kwh_annui` **non torna con la curva**: cersim ricalcola il consumo annuo della forma media sul calendario del 2023
  e lo confronta con quello dichiarato. Uno scarto fino al 2% è normale (anno simulato con un calendario diverso,
  anno bisestile) ed è ammesso; oltre lo 0,5% compare un avviso. Oltre il 2% il file è incoerente, di solito per celle
  in ordine sbagliato, in un'altra unità o non medie. Se è ammesso, vale il consumo dichiarato: la forma media si
  tara su quello.

I valori si arrotondano a 5 decimali (0,01 Wh).

## Come esportarla dal simulatore della casa

1. Simulare un anno intero, ora per ora, e prendere il consumo elettrico del contatore in kWh per ogni ora:
   pompa di calore più gli altri usi. Se in casa c'è un fotovoltaico, serve il **prelievo dalla rete** (consumi meno
   autoconsumo), perché cersim confronta i prelievi con la produzione degli impianti della comunità. I kWp di quel
   FV vanno in `fv_sottratto_kwp`; conviene dirlo anche in `descrizione`, per esempio "prelievi dalla rete, con FV 3 kWp".
   Se c'è anche una batteria, i prelievi sono quelli **dopo** la batteria e il file è la versione 3, con la capacità
   utile in `batteria_kwh`. Senza batteria il simulatore della casa scrive ancora la versione 2.
2. Assegnare a ogni ora tipo di giorno, mese e ora **dell'orologio italiano**. Se il modello lavora in UTC o in ora
   solare tutto l'anno (come i dati meteo di PVGIS, in UTC), bisogna convertire: tra l'ultima domenica di marzo e
   l'ultima domenica di ottobre l'ora civile è UTC+2, altrimenti UTC+1. Il calendario (giorni della settimana e
   festività) è quello dell'anno simulato; se il modello usa un anno meteo tipico senza un anno vero, va bene un anno
   qualsiasi, per esempio il 2023.
3. Per ogni tipo di giorno, mese e ora, fare la media delle ore: sono le 864 celle, nell'ordine sopra.
4. `kwh_annui` è la somma delle ore dell'anno simulato.

In TypeScript, da un anno di consumi orari con l'istante di inizio di ogni ora:

```ts
const FESTE = ["01-01", "01-06", "04-25", "05-01", "06-02", "08-15", "11-01", "12-08", "12-25", "12-26"];

function pasquetta(anno: number): string {
  // Pasqua con l'algoritmo gregoriano anonimo, più un giorno
  const a = anno % 19, b = Math.floor(anno / 100), c = anno % 100, d = Math.floor(b / 4), e = b % 4;
  const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  const pasqua = new Date(Date.UTC(anno, Math.floor((h + l - 7 * m + 114) / 31) - 1, ((h + l - 7 * m + 114) % 31) + 1));
  pasqua.setUTCDate(pasqua.getUTCDate() + 1);
  return pasqua.toISOString().slice(5, 10);
}

const ORA_ROMA = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Rome", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", weekday: "short",
  hourCycle: "h23",
});

function curvaConsumi(ore: { inizio: Date; kwh: number }[], descrizione: string, motore: string) {
  const somma = new Array(864).fill(0), conteggio = new Array(864).fill(0);
  for (const { inizio, kwh } of ore) {
    const p = Object.fromEntries(ORA_ROMA.formatToParts(inizio).map((x) => [x.type, x.value]));
    const anno = Number(p.year), mese = Number(p.month), ora = Number(p.hour), giorno = `${p.month}-${p.day}`;
    const festivo = p.weekday === "Sun" || FESTE.includes(giorno) || giorno === pasquetta(anno);
    const tipo = festivo ? 2 : p.weekday === "Sat" ? 1 : 0;
    const i = (tipo * 12 + mese - 1) * 24 + ora;
    somma[i] += kwh;
    conteggio[i] += 1;
  }
  if (conteggio.some((n) => n === 0)) throw new Error("Serve un anno intero");
  return {
    formato: "curva-consumi", versione: 1, natura: "calcolato", unita: "kWh", fonte: "simulatore-casa",
    motore, descrizione,
    kwh_annui: Math.round(ore.reduce((s, o) => s + o.kwh, 0) * 10) / 10,
    ore: somma.map((s, i) => Math.round((s / conteggio[i]) * 1e5) / 1e5),
  };
}
```

L'implementazione di riferimento in Python è `cersim.curva_calcolata.esporta`; i test in
`tests/test_curva_calcolata.py` verificano l'andata e ritorno: dalla serie oraria al file, dal file alla curva che
usa la simulazione, con lo stesso consumo annuo e la stessa forma.

## In cersim

Nel passo 2 *Membri e consumi*, riquadro *Consumi ora per ora*: si sceglie il contatore e si carica il file `.json`,
da solo (non insieme ai CSV del distributore). cersim mostra "consumi calcolati, non misurati" accanto al contatore
e avverte che la qualità resta B. La curva si salva nel file del lavoro con `"natura": "calcolata"`; i salvataggi
precedenti, senza `natura`, restano curve misurate.

Un contatore ha una sola curva: caricare un file calcolato sostituisce i consumi misurati di quel contatore, e il
contrario. Per confrontare "oggi" e "con la pompa di calore" si salvano due lavori, uno con i consumi misurati o
della bolletta e uno con la curva calcolata.

## Versioni

- **1** (ottobre 2026): prima versione.
- **2** (novembre 2026): `fv_sottratto_kwp`, i kWp di FV già tolti dai consumi.
- **3** (novembre 2026): `batteria_kwh`, la batteria di casa già considerata nei prelievi. I file della versione 2
  restano validi e il simulatore della casa li scrive ancora quando non c'è una batteria.

Una modifica che cambia il significato di un campo, ne aggiunge o ne toglie richiede una nuova versione. cersim
dichiara quali versioni legge (`VERSIONI_LETTE`) e rifiuta le altre con un messaggio che invita ad aggiornarlo.
