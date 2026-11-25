// Numeri all'italiana, come nel motore (cersim.report.euro, kwh).

// "always": in italiano Intl non raggruppa i numeri di quattro cifre (2125), il motore sì (2.125)
const intero = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 0, useGrouping: "always" });

export const kwh = (x: number | null | undefined) => (x == null ? "–" : `${intero.format(x)} kWh`);
export const euro = (x: number | null | undefined) => (x == null ? "–" : `${intero.format(x)} €`);
export const secondi = (x: number) => `${x.toLocaleString("it-IT", { maximumFractionDigits: 1 })} s`;
export const megabyte = (x: number) => `${x.toLocaleString("it-IT", { maximumFractionDigits: 1 })} MB`;
