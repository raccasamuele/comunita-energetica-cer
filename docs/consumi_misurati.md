# Consumi misurati: quali file legge cersim e come li usa

Con i consumi misurati a quarti d'ora la simulazione usa le **ore vere** di un contatore invece di una curva tipica.
È il dato che restringe di più l'intervallo dell'energia condivisa. Il lettore è in `cersim/misure.py`.

## Dove si trovano

Il file lo può scaricare solo l'**intestatario del contratto** della luce: il portale e l'area clienti mostrano
solo le forniture intestate a chi entra.

| Da dove | Come | File |
|---|---|---|
| Portale Consumi di ARERA e Acquirente Unico ([consumienergia.it](https://www.consumienergia.it/)) | si entra con SPID o CIE, si sceglie la fornitura, pulsante *Scarica letture* | `letture.csv`, fino a cinque anni |
| Area clienti di [e-distribuzione](https://www.e-distribuzione.it/servizi/contatore/curve-di-carico.html) | *Le mie misure*, *Curve di carico*, *Scarica il dettaglio del quarto orario* | `ExportData_<mese>.csv`, un mese per file |
| App di e-distribuzione | *Curve di carico*, *Dettaglio mese*, *Invia csv via email* | `FORNUTA<POD>.csv`, un mese per file |

e-distribuzione gestisce i contatori di gran parte d'Italia, non di tutte le città (Milano, Roma e Torino hanno un
distributore diverso). Il Portale Consumi vale per ogni distributore.

## I formati

Ricostruiti da export reali descritti in fonti pubbliche, non da documentazione ufficiale:

- **Portale Consumi:** intestazione `pod;data_lettura;data_ricezione;motivazione;lettura_monoraria;lettura_f1;…;
  tipo_flusso;annomese_riferimento;ea1;…;ea96`, una riga per giorno, kWh per quarto d'ora con il punto decimale.
  A volte mancano giorni; una lettura "sostitutiva" corregge quella dello stesso giorno. Fonte: il codice della
  pagina di analisi dei consumi [tutela.neocities.org/Consumi](https://tutela.neocities.org/Consumi) (pubblico
  dominio, CC0).
- **e-distribuzione, sito:** `Giorno;00:00-00:15;…;23:45-00:00`, poi `"01/08/2026";"0,359";…;` con virgolette e
  virgola decimale, kWh per quarto d'ora. Fonte: il lettore e i test di
  [riccardorossi92/HomeAssistant-Contatore](https://github.com/riccardorossi92/HomeAssistant-Contatore) (licenza
  MIT), verificati contro le letture ufficiali.
- **e-distribuzione, app:** stessa intestazione, data `01/08/2026 00:00`, valori senza virgolette.
- **Cambio d'ora** (export reali di e-distribuzione): a marzo una riga con le colonne 02:00-03:00 a zero, perché
  quell'ora non esiste; a ottobre due righe con la stessa data, la prima in ora legale fino alle 03:00, la seconda
  in ora solare dalle 02:00. Per il Portale Consumi non è documentato: si applica la stessa regola, e con una sola
  riga l'ora ripetuta di ottobre si legge una volta (un avviso lo segnala).

Al primo file reale di ciascun tipo conviene ricontrollare intestazioni e unità: il lettore segnala ogni riga che
non capisce invece di indovinare.

## Come si usano

1. I quarti d'ora diventano ore; un'ora con quarti mancanti si completa in proporzione.
2. Le ore si riducono a una **forma media**: kWh medi per tipo di giorno (feriale, sabato, festivo), mese e ora
   civile. I mesi senza misure prendono la media degli altri mesi dello stesso tipo di giorno.
3. La forma media vale per tutti i 25 anni di progetto, come le curve tipiche; il consumo annuo è la forma media
   sul calendario del 2023.
4. Per un contatore con curva misurata, consumo annuo e fasce della tabella non si usano, e le varianti dei
   consumi (più di giorno, più la sera) non si applicano: l'ora dei consumi è nota.

Servono almeno 28 giorni di misure. Con meno di 330 giorni la curva vale qualità B, da 330 giorni è una curva completa (qualità A).

## Giorni veri al posto delle sole medie

Oltre alla forma media, la curva conserva fino a 6 giorni veri per ogni tipo di giorno e mese, senza data, dal meno al
più consumato. La simulazione pesca da questi: ogni contatore e anno ha sempre la stessa sequenza, e consumo annuo e
totali di ogni tipo di giorno e mese restano quelli della media. La sequenza vera non serve finché la produzione è
stimata e non misurata. I file salvati prima non hanno questi giorni e continuano a usare la media.

Rifatto il confronto dell'audit del 30/10/2026 con i contatori OPSD (11 coppie tedesche, a parità di consumo annuo):
la sovrastima della condivisione va da una mediana di +6,4% a +2,5% e da un massimo di +102% a +47%. Resta una
sovrastima, soprattutto nelle coppie con poca energia in comune.

La scheda che una famiglia manda a chi coordina contiene solo la forma media, senza questi giorni: quei consumi usano
la media e sovrastimano come prima. Chi carica direttamente i file del contatore ha i giorni veri.

## Curva completa (qualità A)

Il nome dice che i dati ci sono, non che il risultato è giusto. I risultati hanno questa qualità quando almeno **tre quarti dei consumi** della configurazione vengono da curve
misurate di almeno 330 giorni, gli altri contatori hanno almeno consumo e fasce dalla bolletta, la produzione viene
da PVGIS e i prezzi sono orari. Non servono le curve di tutti: contano i contatori che consumano di più.

Le curve **calcolate**, per esempio dal simulatore della casa con una pompa di calore, si caricano allo stesso
modo ma non contano per la qualità A: valgono B, come la bolletta. Il formato è in
[formato_curva_consumi.md](formato_curva_consumi.md).

## Privacy

- Il **POD** è nel file del Portale Consumi e nel nome dei file dell'app: il lettore non lo legge e non lo
  restituisce. Resta solo la forma media, 864 numeri senza date né letture puntuali.
- I file non vengono salvati: la forma media resta nella sessione e, se si salva il lavoro, nel file JSON.
- Le famiglie possono allegare il loro file alla scheda dei consumi: a chi coordina arriva solo la forma media.
- `esempi/letture_esempio_sintetico.csv` è un file **inventato** nel formato del Portale Consumi, con un POD finto,
  per provare il caricamento.
