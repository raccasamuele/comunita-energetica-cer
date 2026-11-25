// Copia lo stile del simulatore Casa in src/stile/casa.css, senza modificarlo: la CER ne usa token e componenti.
// Le aggiunte della CER stanno in src/stile/cer.css. Da rilanciare quando cambiano i token di Casa:
//
//   npm run sincronizza-stile -- "<cartella del progetto Casa>"
//
// Senza argomento usa la variabile d'ambiente CASA_DIR, altrimenti una cartella efficienza-energetica-casa accanto a questo repository.

import { copyFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const casa = process.argv[2] ?? process.env.CASA_DIR ?? join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "efficienza-energetica-casa");
const sorgente = join(casa, "src", "styles.css");
if (!existsSync(sorgente)) {
  console.error(`Non trovo ${sorgente}: indica la cartella del progetto Casa.`);
  process.exit(1);
}
const destinazione = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "stile", "casa.css");
copyFileSync(sorgente, destinazione);
console.log(`Copiato ${sorgente} in ${destinazione}`);
