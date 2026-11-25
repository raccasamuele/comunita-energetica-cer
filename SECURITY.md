# Sicurezza

*English: to report a security issue, email **sicurezza@raccasamuele.it** or use GitHub's private vulnerability
reporting (Security tab → "Report a vulnerability"). Please do not open a public issue. I aim to reply within 7 days;
English is fine.*

Se trovi un problema di sicurezza nel simulatore della comunità energetica, scrivimelo in privato. **Non aprire una
issue pubblica**: finché il problema non è corretto, potrebbe usarlo qualcun altro.

## Come segnalare

- **Email:** **sicurezza@raccasamuele.it**.
- **GitHub:** nella scheda *Security* di questo repository, «Report a vulnerability». La segnalazione resta privata
  fra te e me.

## Che cosa scrivere

- che cosa succede, e che cosa ti aspettavi;
- i passi per rifarlo: la pagina o lo strumento, il file usato, il browser o l'agente AI;
- la versione del motore (`cersim`), che il sito mostra in fondo ai Risultati, il report riporta in prima pagina e il
  server MCP scrive in ogni risposta;
- che cosa può fare chi sfrutta il problema.

Non mandare dati personali veri: bollette, letture del contatore, codici POD, indirizzi. Se serve un file d'esempio,
togli o inventa nomi e numeri.

## Che cosa succede dopo

- **Cerco di risponderti entro 7 giorni**, anche solo per dire che ho ricevuto la segnalazione.
- Ti scrivo se è un problema vero e quando conto di correggerlo.
- La correzione si pubblica sul sito e nel repository. Se vuoi, nelle note della correzione ti ringrazio per nome.
- Ti chiedo di aspettare la correzione prima di parlarne in pubblico.

È un progetto personale, senza ricompense per le segnalazioni.

## Che cosa riguarda

**Sì:**
- il sito <https://cer.raccasamuele.it> e il suo codice in questo repository (`web/`, `cersim/`), compresi i file che
  il sito legge (progetti salvati, file dei consumi e dei prezzi, link per raccogliere i consumi delle famiglie);
- l'intermediario (`intermediario/`), che inoltra le richieste a PVGIS e alla ricerca dell'indirizzo;
- il server MCP per gli agenti AI (`cersim/mcp/`) e l'estensione per Claude Desktop (`estensione/`): per esempio un
  file che gli fa leggere o scrivere dati che non dovrebbe;
- la riga di comando `cersim` e l'app Streamlit (`app.py`), finché è nel repository;
- la pubblicazione: il Worker `cer-sito` e i workflow di GitHub Actions.

**No:**
- gli altri siti di raccasamuele.it (il portale e il simulatore della casa): non sono in questo repository;
- i servizi di terzi in sé (Cloudflare, GitHub, PVGIS, OpenStreetMap, Esri);
- attacchi che puntano solo a sovraccaricare il sito con molte richieste, o che chiedono di ingannare una persona;
- numeri che sembrano sbagliati: non sono un problema di sicurezza, ma una issue normale è benvenuta.

Si corregge solo la versione più recente: quella pubblicata sul sito e il ramo `main`.
