// Prove del ponte da Casa (src/ponte.ts): npm test, con Node 22.18 o successivo (toglie da sé i tipi TypeScript).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { deflateRawSync } from "node:zlib";
import { leggiArrivo, datiDelPonte, MAX_FRAMMENTO } from "../src/ponte.ts";

const profilo = readFileSync(new URL("../../esempi/profilo_energetico_esempio.json", import.meta.url), "utf8");
const curva = readFileSync(new URL("../../esempi/curva_consumi_esempio.json", import.meta.url), "utf8");
const b64url = (b: Uint8Array) => Buffer.from(b).toString("base64url");
const z = (testo: string) => `#profilo-casa=z.${b64url(deflateRawSync(Buffer.from(testo)))}`;
const j = (testo: string) => `#profilo-casa=j.${b64url(Buffer.from(testo))}`;

test("un frammento che non viene da Casa si ignora", async () => {
  assert.equal(datiDelPonte(""), null);
  assert.equal(datiDelPonte("#t-orari"), null);
  assert.equal(await leggiArrivo("#modulo=famiglia"), null);
});

test("il profilo energetico compresso arriva intero, con il nome del file", async () => {
  const letto = await leggiArrivo(z(profilo));
  assert.deepEqual(letto, { nome: "profilo-energetico_casa.json", testo: profilo });
});

test("anche senza compressione, e per un file curva-consumi", async () => {
  assert.deepEqual(await leggiArrivo(j(profilo)), { nome: "profilo-energetico_casa.json", testo: profilo });
  assert.deepEqual(await leggiArrivo(z(curva)), { nome: "curva-consumi_casa.json", testo: curva });
});

test("dati rovinati, formati sconosciuti e frammenti enormi danno un errore leggibile", async () => {
  for (const hash of [
    "#profilo-casa=z.AAAA",
    "#profilo-casa=x.e30",
    "#profilo-casa=j.%%%",
    j("[1,2]"),
    j('{"formato":"constructor"}'),
    z('{"formato":"progetto-cer"}'),
    j("non è JSON"),
    `#profilo-casa=j.${"A".repeat(MAX_FRAMMENTO)}`,
  ]) {
    const letto = await leggiArrivo(hash);
    assert.ok(letto && "errore" in letto, hash.slice(0, 40));
  }
});
