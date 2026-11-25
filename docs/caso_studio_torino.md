# Caso studio: un condominio di Torino, gruppo o comunità energetica?

Lo stesso condominio simulato due volte, cambiando solo il tipo di configurazione. I numeri sono uno
**scenario preliminare** con dati di qualità C: servono a capire l'ordine di grandezza e che cosa pesa di più,
non a decidere un investimento.

Per rifare il calcolo:

```bash
python esempi/caso_studio_torino.py
```

## I dati

È l'esempio che si carica nell'app con *Prova con l'esempio di Torino*.

- **Dove:** Piazza Castello, Torino (Piemonte, zona di mercato Nord).
- **Chi:** 12 famiglie (da 1.600 a 3.500 kWh all'anno, 33% in fascia F1), una panetteria (14.000 kWh, 60% in F1)
  e le parti comuni del condominio (4.500 kWh). In tutto 49.300 kWh all'anno, tutti con consumo e fasce dalla
  bolletta.
- **L'impianto:** 20 kWp di moduli e un inverter da 18 kW sul tetto, inclinati di 25° e rivolti quasi a sud (10°
  verso ovest), collegati al contatore delle parti comuni. Entra in esercizio il 1° aprile 2027 e lo paga il
  condominio.
- **Scelte economiche:** metà dei contributi ai membri, Ritiro dedicato del GSE per l'energia venduta, costo
  dell'impianto stimato con il massimo di riferimento del DM 414/2023 (nessun preventivo), costi di costituzione
  e gestione predefiniti.
- **Solo nella comunità energetica:** un'area convenzionale fittizia, uguale per tutti i contatori (in un caso
  vero si legge sulla mappa delle cabine primarie del GSE).

## I risultati

Intervalli tra il minimo e il massimo degli scenari simulati: 3 anni meteo (2021, 2022, 2023), 3 livelli di prezzo
dell'energia (80, 110 e 140 €/MWh) e consumi più di giorno o più la sera. Non sono probabilità.

| | Gruppo di autoconsumatori | Comunità energetica |
|---|---|---|
| Qualità dei dati | C | C |
| Energia condivisa all'anno | 15.890 kWh – 17.095 kWh | 15.890 kWh – 17.095 kWh |
| Tariffa premio all'anno | 2.066 € – 2.222 € | 2.066 € – 2.222 € |
| Valorizzazione ARERA all'anno | 232 € – 277 € | 189 € – 203 € |
| Costituzione (una tantum) | 600 € | 2.500 € |
| Gestione all'anno | 300 € | 1.200 € |
| Beneficio netto della configurazione, 25 anni | 21.648 € – 47.825 € | 4.445 € – 30.165 € |
| Beneficio netto del condominio, che paga | 8.370 € – 33.364 € | -2.121 € – 22.670 € |
| Rientro del condominio, scenario base | 8 anni | 11 anni |
| In più rispetto al solo fotovoltaico | 26.428 € – 29.274 € | 9.224 € – 11.601 € |

Calcolo del 23/10/2026, cersim 0.1.0, pacchetto normativo del 15/10/2026, produzione da PVGIS.

## Come leggerli

- **L'energia condivisa e la tariffa premio sono identiche.** Dipendono dalle stesse ore di produzione e di
  consumo: per l'energia non conta come ci si organizza.
- **La valorizzazione ARERA è più alta nel gruppo.** Oltre alla parte uguale per tutti, il gruppo riceve le
  perdite di rete evitate, perché produzione e consumi stanno nello stesso edificio.
- **La differenza la fanno i costi.** Una comunità energetica è un soggetto giuridico con statuto: costa di più
  costituirla (2.500 € contro 600 €) e gestirla (1.200 € all'anno contro 300 €). Su 25 anni il beneficio netto scende
  di circa 17.000–18.000 €.
- **Per un solo condominio il gruppo conviene.** La comunità energetica ha senso quando unisce edifici diversi:
  più membri e più impianti, che dividono gli stessi costi fissi.
- **Il risultato dipende dal riparto.** Con metà dei contributi ai membri, nella comunità energetica il condominio
  che paga rischia di non rientrare nello scenario peggiore (-2.121 €). Al passo 4 si vede fino a quale quota ai
  membri chi paga resta in pari.

## Che cosa manca per una stima migliore

È lo stesso elenco che l'app mostra nei risultati, sotto *Come rendere la stima più precisa*.

1. **Prezzi orari** invece di un prezzo costante: nelle ore di sole i prezzi sono più bassi della media, quindi la
   vendita è sovrastimata (in parte compensata dalla tariffa premio, che in quelle ore sale).
2. **Un preventivo vero:** il costo di riferimento del DM 414/2023 è un massimo, quindi una stima alta.
3. **Curve di consumo misurate:** oggi l'ora dei consumi viene da una curva tipica, adattata a consumo annuo e
   fasce. È la prima fonte di incertezza dell'energia condivisa.

## Ipotesi e limiti

Valgono quelle del [README](../README.md#ipotesi-e-limiti). Le regole sui contributi sono in
[fonti_normative.md](fonti_normative.md).
