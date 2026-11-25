"""Riga di comando di cersim: lo stesso motore del sito, su un file di progetto.

    cersim schema progetto|esito          lo schema JSON dell'ingresso o dell'uscita
    cersim valida PROGETTO                controlla il file e riassume che cosa contiene
    cersim analizza PROGETTO [-o ESITO]   l'analisi completa, come JSON (formato esito-cer)
    cersim report PROGETTO -o FILE        il report PDF o il file Excel

PROGETTO è il file esportato dal sito o dall'app (`-` per leggerlo dallo standard input); i formati sono in
docs/formato_progetto_cer.md. Le uscite sono JSON su standard output, i messaggi per le persone su standard error.
Codici di uscita: 0 tutto bene, 1 dati non validi o analisi non riuscita, 2 comando scritto male.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

from cersim import __version__, schema, web
from cersim.eligibility import check
from cersim.pv import pv_profile, synthetic_profile
from cersim.ui_model import LIMITI_PARAMETRI, REGIMI_VENDITA, esporta_json, importa_json

OK, NON_RIUSCITO, USO = 0, 1, 2


def _leggi(percorso: str) -> str:
    if percorso == "-":
        return sys.stdin.read()
    try:
        return Path(percorso).read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ValueError(f"Non riesco a leggere {percorso}: {e.strerror}") from None


def _scrivi(dati: dict, uscita: str | None) -> None:
    testo = json.dumps(dati, ensure_ascii=False, indent=2) + "\n"
    if uscita in (None, "-"):
        sys.stdout.write(testo)
    else:
        Path(uscita).write_text(testo, encoding="utf-8")
        print(f"Scritto {uscita}", file=sys.stderr)


def _valore(testo: str):
    if testo in REGIMI_VENDITA:
        return testo
    if testo.lower() in ("", "null", "vuoto"):
        return None
    try:
        return float(testo.replace(",", "."))
    except ValueError:
        raise ValueError(f"Valore non numerico: {testo}") from None


def _con_parametri(testo: str, cambi: list[str]) -> str:
    """Il progetto con i parametri economici cambiati da `--parametro chiave=valore`."""
    if not cambi:
        return testo
    config, parametri = importa_json(testo)
    ammessi = (*LIMITI_PARAMETRI, "regime_vendita")
    for cambio in cambi:
        chiave, uguale, valore = cambio.partition("=")
        if not uguale or chiave.strip() not in ammessi:
            raise ValueError(f"Parametro sconosciuto: {cambio}. Si scrive chiave=valore; chiavi: {', '.join(ammessi)}")
        parametri[chiave.strip()] = _valore(valore.strip())
    return esporta_json(config, parametri)


def _prezzi(file: list[str], testo: str) -> dict | None:
    """I prezzi orari dai CSV dell'utente, come li tiene la bozza del sito (`web.leggi_prezzi`)."""
    if not file:
        return None
    config, _ = importa_json(testo)
    letti = web.leggi_prezzi([{"nome": Path(f).name, "base64": base64.b64encode(Path(f).read_bytes()).decode()}
                              for f in file], config.regione)
    for errore in letti["errori"]:
        print(f"Prezzi: {errore}", file=sys.stderr)
    if not letti["ok"]:
        raise ValueError("Nessun file di prezzi leggibile")
    return letti["prezzi"]


def _analisi(args) -> tuple[dict, object]:
    testo = _con_parametri(_leggi(args.progetto), args.parametro)
    config, _ = importa_json(testo)
    fetch = synthetic_profile if args.senza_rete else pv_profile
    risultato = web.risultati(testo, {}, _prezzi(args.prezzi, testo), n_anni=args.anni, fetch_pv=fetch)
    return risultato, config


def comando_schema(args) -> int:
    _scrivi(schema.schema_progetto() if args.quale == "progetto" else schema.schema_esito(), args.output)
    return OK


def comando_valida(args) -> int:
    try:
        config, parametri = importa_json(_leggi(args.progetto))
    except ValueError as e:
        _scrivi({"ok": False, "errore": str(e)}, args.output)
        return NON_RIUSCITO
    report = check(config)
    avvisi = []
    if parametri.get("quota_membri") is None:
        avvisi.append("Manca quota_membri: senza il riparto l'analisi economica non si calcola "
                      "(si può dare con --parametro quota_membri=0.5).")
    _scrivi({"ok": report.supportata, "schema": schema.VERSIONE_SCHEMA, "nome": config.nome,
             "tipo": config.tipo.value, "riepilogo": web._riepilogo(config) | {"impianti": len(config.plants)},
             "parametri": parametri, "non_supportati": report.non_supportati, "da_verificare": report.da_verificare,
             "avvisi": avvisi}, args.output)
    return OK if report.supportata else NON_RIUSCITO


def comando_analizza(args) -> int:
    try:
        risultato, config = _analisi(args)
    except ValueError as e:
        _scrivi(schema.esito({"ok": False, "errore": str(e)}), args.output)
        return NON_RIUSCITO
    _scrivi(schema.esito(risultato, config), args.output)
    return OK if risultato.get("ok") else NON_RIUSCITO


def comando_report(args) -> int:
    formato = args.formato or Path(args.output).suffix.lstrip(".").lower()
    if formato not in ("pdf", "xlsx"):
        print("Formato sconosciuto: usa --formato pdf oppure xlsx", file=sys.stderr)
        return USO
    try:
        risultato, _ = _analisi(args)
    except ValueError as e:
        print(e, file=sys.stderr)
        return NON_RIUSCITO
    if not risultato.get("ok"):
        print(risultato.get("errore") or "; ".join(risultato.get("non_supportati") or []) or "Analisi non riuscita",
              file=sys.stderr)
        return NON_RIUSCITO
    fatto = web.report(formato)
    if not fatto["ok"]:
        print(fatto["errore"], file=sys.stderr)
        return NON_RIUSCITO
    Path(args.output).write_bytes(base64.b64decode(fatto["base64"]))
    print(f"Scritto {args.output}", file=sys.stderr)
    return OK


def _opzioni_analisi(p: argparse.ArgumentParser) -> None:
    p.add_argument("progetto", help="file di progetto (- per lo standard input)")
    p.add_argument("--senza-rete", action="store_true",
                   help="non scaricare la produzione da PVGIS: modello semplificato, qualità C")
    p.add_argument("--prezzi", nargs="+", default=[], metavar="CSV",
                   help="prezzi orari zonali (CSV del GME, uno per anno); restano fuori dal progetto")
    p.add_argument("--parametro", action="append", default=[], metavar="CHIAVE=VALORE",
                   help="cambia un parametro economico, per esempio quota_membri=0.5 (ripetibile)")
    p.add_argument("--anni", type=int, default=None, help="anni da simulare (predefinito: tutto il periodo)")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cersim", description="Simulatore di comunità energetiche rinnovabili e "
                                "gruppi di autoconsumatori. Scenari preliminari, non studi di fattibilità.")
    p.add_argument("--version", action="version", version=f"cersim {__version__}")
    sotto = p.add_subparsers(dest="comando", required=True, metavar="COMANDO")

    s = sotto.add_parser("schema", help="scrive lo schema JSON del progetto o dell'esito")
    s.add_argument("quale", choices=("progetto", "esito"))
    s.add_argument("-o", "--output", help="file di uscita (predefinito: standard output)")
    s.set_defaults(funzione=comando_schema)

    v = sotto.add_parser("valida", help="controlla un file di progetto e lo riassume")
    v.add_argument("progetto", help="file di progetto (- per lo standard input)")
    v.add_argument("-o", "--output", help="file di uscita (predefinito: standard output)")
    v.set_defaults(funzione=comando_valida)

    a = sotto.add_parser("analizza", help="analisi completa, come JSON nel formato esito-cer")
    _opzioni_analisi(a)
    a.add_argument("-o", "--output", help="file di uscita (predefinito: standard output)")
    a.set_defaults(funzione=comando_analizza)

    r = sotto.add_parser("report", help="report PDF o file Excel dell'analisi")
    _opzioni_analisi(r)
    r.add_argument("-o", "--output", required=True, help="file da scrivere (.pdf o .xlsx)")
    r.add_argument("--formato", choices=("pdf", "xlsx"), help="predefinito: dall'estensione del file")
    r.set_defaults(funzione=comando_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.funzione(args)


if __name__ == "__main__":
    sys.exit(main())
