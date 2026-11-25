"""Scheda nella chat (MCP Apps, estensione `io.modelcontextprotocol/ui`, specifica stabile 2026-01-26).

Come mcp/scheda.ts di Casa: i client che la supportano (Claude Desktop, claude.ai) mostrano `scheda.html` insieme
al risultato degli strumenti, con i numeri principali, i grafici e i pulsanti per il passo successivo. Gli altri
client la ignorano e usano il testo, che resta completo.
"""

from importlib.resources import files

from cersim.mcp.protocollo import ResourceDef

SCHEDA_URI = "ui://cer/scheda.html"
MIME_MCP_APP = "text/html;profile=mcp-app"

# Da mettere nel `_meta` di uno strumento. La chiave piatta «ui/resourceUri» è quella vecchia, per i client di prima.
SCHEDA_META = {"ui": {"resourceUri": SCHEDA_URI}, "ui/resourceUri": SCHEDA_URI}


def _html() -> str:
    return files("cersim.mcp").joinpath("scheda.html").read_text(encoding="utf-8")


SCHEDA = ResourceDef(
    uri=SCHEDA_URI,
    name="scheda",
    title="Scheda del simulatore CER",
    description="Riquadro con la frase di sintesi, i numeri con gli intervalli, i grafici dell'energia e dei soldi, "
                "i requisiti, la qualità dei dati e l'avvertenza di un progetto del simulatore CER.",
    mime_type=MIME_MCP_APP,
    text=_html,
    # Nessun accesso alla rete né a risorse esterne: la CSP predefinita del client basta. Il bordo è già nella scheda.
    meta={"ui": {"prefersBorder": False}},
)
