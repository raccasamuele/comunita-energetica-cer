# Formato `profilo-energetico`: la casa in un file, da Casa alla CER e ritorno

Il profilo energetico è il file comune fra il simulatore della casa (casa.raccasamuele.it) e cersim. Porta in un solo
file la situazione attuale della casa e gli scenari con gli interventi (pompa di calore, serramenti, fotovoltaico,
batteria): per ognuno i consumi elettrici **prima** del fotovoltaico, il FV, la batteria e i prelievi dalla rete dopo
FV e batteria. Il lettore è `cersim/profilo.py`, che contiene anche lo scrittore di cersim (`esporta_profilo`).

Il profilo **affianca** il formato [`curva-consumi`](formato_curva_consumi.md), che resta valido: i prelievi di ogni
scenario sono lo stesso contenuto di un file `curva-consumi` dello stesso pacchetto.

## Perché i consumi prima del FV

Con `curva-consumi` la CER riceve solo i prelievi: il FV della casa è già tolto e non può entrare nella comunità. Con il
profilo, se si sceglie **«Entra nella comunità»**, cersim mette sul contatore i consumi prima del FV, aggiunge
l'impianto della casa al passo 3 e la batteria sul contatore, e rifà il bilancio orario con **il suo meteo** (PVGIS
2021–2023, lo stesso degli altri impianti della comunità). Così le ore di sole della casa coincidono con quelle degli
altri impianti. Le immissioni calcolate dal simulatore della casa (anno meteo tipico) restano solo come totali annui,
per confronto.

## Esempio

Un file JSON in UTF-8 (il BOM è ammesso), estensione `.json`, al massimo 2 MB. Le 864 celle sono accorciate:

```json
{
  "formato": "profilo-energetico",
  "versione": 1,
  "fonte": "simulatore-casa",
  "motore": "casa-1R1C 0.5.0",
  "data": "2026-11-03",
  "descrizione": "Casa a Milano",
  "comune": {"codice_istat": "015146", "nome": "Milano", "lat": 45.46841, "lon": 9.17312},
  "scenari": [
    {
      "id": "base", "nome": "Situazione attuale", "attuale": true,
      "consumi": {"natura": "calcolato", "stato": "documentato", "kwh_annui": 2700, "ore": ["… 864 valori …"],
                  "usi": {"altri_usi_kwh": 2700}},
      "fv": null, "batteria": null,
      "prelievi": {"kwh_annui": 2700, "ore": ["… 864 valori …"]}
    },
    {
      "id": "HP", "nome": "PDC + FV", "attuale": false,
      "consumi": {"natura": "calcolato", "stato": "documentato", "kwh_annui": 7604.4, "ore": ["…"],
                  "usi": {"altri_usi_kwh": 2700, "pompa_di_calore_kwh": 4904.4}},
      "fv": {"kwp": 4, "inclinazione": 35, "orientamento": 0, "perdite_pct": 14, "esistente": false},
      "batteria": {"capacita_kwh": 5, "potenza_kw": 5, "rendimento_pct": 90, "riserva_pct": 5},
      "prelievi": {"kwh_annui": 4868.5, "ore": ["…"]},
      "stima": {"immissioni_kwh": 2615.7, "autoconsumo_kwh": 2736}
    }
  ],
  "esclusi": ["codice POD", "nomi e indirizzo", "codice cliente", "letture del contatore con le date", "importi"]
}
```

Un file completo, scritto dal simulatore della casa con il suo esempio, è in
[esempi/profilo_energetico_esempio.json](../esempi/profilo_energetico_esempio.json).

## Campi

Un campo non previsto fa rifiutare il file: un campo nuovo richiede una nuova versione. I testi sono puliti come in
`curva-consumi` (niente caratteri di controllo né segni di Markdown o HTML).

**Radice**

| Campo | Valore |
|---|---|
| `formato` | sempre `"profilo-energetico"` |
| `versione` | `1`, oppure `2` se c'è `bolletta`. Una versione che cersim non conosce fa rifiutare il file |
| `fonte` | chi ha scritto il file: nome breve in minuscolo (`"simulatore-casa"`, `"cersim"`) |
| `motore` | facoltativo: modello e versione |
| `data` | data del file, `AAAA-MM-GG` |
| `descrizione` | facoltativo, al massimo 200 caratteri. **Non** il nome del progetto o della famiglia |
| `comune` | `null` oppure codice ISTAT (sei cifre), nome e coordinate **del comune** (centroide), non dell'indirizzo |
| `scenari` | da 1 a 20 scenari; al massimo uno con `attuale` vero |
| `esclusi` | elenco, per chi legge il file, dei dati che non contiene |
| `bolletta` | solo versione 2, facoltativo: il prezzo dell'elettricità nella bolletta della casa, vedi sotto |

**Bolletta** (versione 2)

| Campo | Valore |
|---|---|
| `eur_kwh` | prezzo variabile per kWh prelevato, €/kWh tra 0 e 1, **imposte comprese** (quota energia, oneri variabili, accise e IVA): è quello che la famiglia non paga per ogni kWh che consuma dal proprio FV. Non la spesa totale divisa per i kWh, che contiene anche le quote fisse |
| `stato` | come per i consumi: `documentato` (dalla bolletta), `misurato`, `ipotizzato`, `sconosciuto`. Con `sconosciuto` cersim non lo usa |
| `fasce` | facoltativo: prezzi F1, F2 e F3 della bolletta, stesse unità. Se ci sono, ogni ora usa la sua fascia ARERA (festività nazionali comprese) al posto di `eur_kwh` |

Il prezzo per kWh non è un importo della bolletta: `esclusi` continua a valere.

**Scenario**

| Campo | Valore |
|---|---|
| `id` | lettere, cifre e trattini, al massimo 20 caratteri; unico nel file |
| `nome` | il nome leggibile, per esempio `"PDC + FV"` |
| `attuale` | vero per la situazione di oggi |
| `consumi.natura` | `"calcolato"` o `"misurato"`; con `"misurato"` servono anche `giorni`, `dal`, `al` del periodo delle misure |
| `consumi.stato` | stato del consumo annuo come nei dati di Casa: `documentato`, `misurato`, `ipotizzato`, `sconosciuto` |
| `consumi.kwh_annui`, `consumi.ore` | consumi elettrici **prima del FV**, 864 celle come in `curva-consumi` |
| `consumi.usi` | facoltativo: di cui `altri_usi_kwh`, `pompa_di_calore_kwh`, `raffrescamento_kwh` |
| `fv` | `null` oppure kWp, inclinazione (0–90°), orientamento (convenzione PVGIS: 0 sud, −90 est, 90 ovest), perdite totali per PVGIS in % (di sistema più ombre), `esistente` (già installato o nuovo) |
| `batteria` | `null` oppure capacità utile kWh, potenza kW (uguale in carica e scarica), rendimento di andata e ritorno %, riserva %. Richiede il FV |
| `prelievi` | kWh annui e 864 celle dei prelievi dalla rete **dopo** FV e batteria; senza FV coincidono con i consumi |
| `stima` | facoltativo: immissioni e autoconsumo annui stimati da chi ha scritto il file, solo per confronto |

Le 864 celle e i controlli (kWh finiti e non negativi, consumo annuo che torna con la forma entro il 2% sul calendario
del 2023) sono quelli di [`curva-consumi`](formato_curva_consumi.md#le-864-celle).

## In cersim

Al passo 2, riquadro *Consumi ora per ora*, si sceglie il contatore e si carica il file, da solo. cersim mostra gli
scenari; si sceglie quello da usare e, se lo scenario ha un FV:

- **Entra nella comunità**: consumi prima del FV sul contatore; batteria di casa sul contatore; al passo 3 una riga
  «FV di casa (contatore)» con kWp, falda e ombre, investitore il membro del contatore e data di entrata in esercizio
  proposta per un FV nuovo, **da indicare** per uno esistente. Le regole di ammissione non cambiano: un impianto entrato
  in esercizio prima del 16/12/2021 non è supportato nella v1 e va caricato con «Solo prelievi».
- **Solo prelievi**: come un file `curva-consumi` di versione 2 o 3, con gli stessi avvisi.

Nel bilancio orario la batteria di casa si carica solo dal surplus dell'impianto dello stesso contatore e si scarica
sui suoi consumi, con le regole del simulatore della casa: rendimento diviso in parti uguali fra carica e scarica,
riserva, potenza massima. Parte dalla riserva il 1° gennaio di ogni anno e non perde capacità negli anni (con il calo
reale l'energia condivisa sarebbe un po' più alta). Una batteria senza impianto sul contatore è un errore.

Se il profilo porta `bolletta`, il risparmio in bolletta dell'energia che la casa consuma dal proprio FV (autoconsumo
fisico del contatore, solo con «Entra nella comunità») usa quel prezzo, ora per ora con le fasce, al posto del
«Risparmio in bolletta per kWh autoconsumato» del passo Economia, che resta per gli altri contatori. Il prezzo serve
solo al risparmio in bolletta: TIP, ritiro dedicato e perdite evitate usano sempre i prezzi zonali orari, perché lo
chiede la regola del GSE. La sensibilità «costo evitabile in bolletta ±30%» scala anche il prezzo della casa.

La qualità dei consumi resta **B** anche se il profilo porta consumi misurati: il file è uno scambio, per la qualità A
servono i file del distributore.

Per riscaricare, ogni contatore con la curva oraria ha il pulsante **Profilo**: per un contatore caricato da un profilo
si riscrive lo scenario così com'era; per un contatore con la sola curva (misurata o calcolata) e senza impianto si
scrive la situazione attuale. Il file non contiene nome del membro, POD, indirizzo né i giorni veri della curva.

## Nel simulatore della casa

Nei risultati, «Scarica il profilo energetico» scrive la situazione attuale e ogni pacchetto valido. «Importa un
progetto o un profilo» apre un profilo come progetto nuovo: comune, consumo elettrico (gli altri usi), la curva
misurata se c'è e il FV già installato, dalla situazione attuale; il resto parte dalle ipotesi di un progetto nuovo.
Se il prezzo variabile dell'elettricità della casa è noto, Casa lo scrive in `bolletta` (versione 2, senza fasce:
Casa usa un solo prezzo per kWh); importando un profilo con `bolletta`, quel prezzo diventa il prezzo variabile
dell'elettricità del progetto nuovo.

## «Porta nella CER»: il profilo senza scaricarlo

In «Le mie case» di Casa, il pulsante **Porta nella CER** apre questo sito in una nuova scheda con il profilo
energetico della casa nel frammento dell'indirizzo:

```
https://cer.raccasamuele.it/#profilo-casa=z.<dati>
```

`<dati>` è il JSON del profilo compresso con *deflate-raw* e scritto in base64url senza `=` finali; con `j.` al posto
di `z.` il JSON non è compresso (browser senza `CompressionStream`). Il frammento, la parte dopo `#`, non viene mai
mandato al server: il profilo passa da un sito all'altro dentro il browser. Un profilo tipico compresso sta in
circa 12 kB.

Il sito (`web/src/ponte.ts`) legge il frammento all'apertura e lo toglie subito dall'indirizzo, apre il passo 2 e
mette il profilo come file già scelto in «Consumi ora per ora»: da lì si sceglie il contatore e lo scenario come per
un file caricato a mano, con gli stessi controlli del motore. Accetta solo i formati `profilo-energetico` e
`curva-consumi`; un frammento rovinato o troppo grande dà un avviso che invita a scaricare il file.

## Versioni

- **1** (novembre 2026): prima versione.
- **2** (novembre 2026): aggiunge `bolletta`, facoltativo. Chi scrive usa la 2 solo se c'è il prezzo, così i file
  senza prezzo restano leggibili dai lettori della versione 1. cersim legge la 1 e la 2.
