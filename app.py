"""Interfaccia web del simulatore CER (Streamlit).

    streamlit run app.py      (dalla cartella del progetto, per usare .streamlit/config.toml)

Percorso in 5 passi, preceduto da "Prima di iniziare" (quali dati servono e dove trovarli): luogo e tipo,
membri e consumi, impianti, economia e prezzi, risultati. Con ?modulo=famiglia l'app mostra solo la scheda
dei consumi da compilare: il link si gira a famiglie e attività, che rimandano un file da caricare al passo 2.
Tutta la logica è nel pacchetto `cersim`; qui solo l'interfaccia.
Nessun dato viene salvato sul server: i risultati restano nella sessione del browser.
Tema e regole visive: .streamlit/config.toml e DESIGN.md.
"""

import hashlib
import io
from datetime import date
from pathlib import Path
from html import escape

import altair as alt
import folium
import pandas as pd
import requests
import streamlit as st
from branca.element import MacroElement
from folium.plugins import Draw
from folium.template import Template
from streamlit_folium import st_folium

from cersim import __version__
from cersim.analisi import (
    analizza,
    anno_rappresentativo,
    cassa_cumulata,
    chi_riceve_cosa,
    fonti_prezzi,
    giorno_tipo,
    mensile,
    nomi_leggibili,
    scenari_dimensionamento,
)
from cersim.curva_calcolata import leggi_curva_calcolata
from cersim.economics import ParametriEconomici
from cersim.guida import (
    CODICE_POD,
    COSA_SERVE,
    ETICHETTE_SOGGETTO_ATTIVITA,
    KWH_FAMIGLIA_TIPO,
    MAX_CONTATORI,
    MAX_TESTO,
    MODULO,
    PORTALE_CONSUMI,
    PRIVACY_SCHEDA,
    PROFILI,
    SOGGETTI_ATTIVITA,
    TIPOLOGIE_ATTIVITA,
    TIPOLOGIE_ENTE,
    Contatore,
    Scheda,
    controlla,
    crea_scheda,
    leggi_scheda,
    link_famiglie,
    nome_file,
    unisci_schede,
)
from cersim.geo import REGIONI, geocode, zona_mercato
from cersim.misure import curva_da_file, descrivi
from cersim.normativa import assunzioni_economiche
from cersim.prices import anno_dei_prezzi, prezzi_da_csv
from cersim.proposta import (
    QUOTA_PROVVISORIA,
    SceltaTetto,
    entrata_predefinita,
    nome_impianto,
    proponi,
    tabella_impianto,
)
from cersim.report import (
    AVVISO_PRELIMINARE,
    COLORI_GRAFICI,
    NOTA_INTERVALLI,
    QUALITA,
    STATO_ETICHETTA,
    avvertenze,
    cifre,
    confronto,
    dati_da_migliorare,
    euro,
    frase_confronto,
    frase_precisione,
    frase_sintesi,
    kwh,
    report_excel,
    report_pdf,
    requisiti,
    scheda_famiglia_pdf,
)
from cersim.sizing import dimensiona
from cersim.tetto import (
    ATTRIBUZIONE,
    FORME,
    FOTO_AEREA_ATTRIBUZIONE,
    FOTO_AEREA_URL,
    INCLINAZIONE,
    LIVELLI_OMBRE,
    M2_PER_KWP,
    PRIVACY_FOTO,
    disegno_svg,
    est_ovest,
    falda_opposta,
    link_google_earth,
    scarica_edifici,
    tetto_disegnato,
)
from cersim.ui_model import (
    COLONNE_IMPIANTI,
    COLONNE_PUNTI,
    INVESTITORE_ESTERNO,
    SOLA_IMMISSIONE,
    TIPI_SOGGETTO,
    TIPOLOGIE,
    Generale,
    configurazione_da_tabelle,
    esporta_json,
    famiglie_tipo,
    impianti_vuoti,
    importa_json,
    punti_vuoti,
    tabelle_da_configurazione,
    tipizza_impianti,
    tipizza_punti,
)

st.set_page_config(page_title="Simulatore CER", page_icon=":material/solar_power:", layout="wide")

IPOTESI = assunzioni_economiche()
VIDEO_TETTO = Path(__file__).parent / "static" / "video_tetto.mp4"

# Poche regole mirate: passi numerati, un pannello bianco per il passo aperto, numeri tabulari,
# misura delle righe di testo, etichette di stato e cifre. Niente bordi laterali colorati né gradienti;
# ombre appena accennate, solo per staccare il pannello dallo sfondo.
STILE = """
<style>
:root {
  --testo: #172026; --tenue: #55626a; --bordo: #d6dee2; --bordo-forte: #b9c4ca; --pannello: #eaf0f2;
  --tenue-sf: #f7fafb; --superficie: #ffffff; --accento: #1f5f6b; --accento-scuro: #164852; --accento-sf: #e3eff1;
  --ok: #346c42; --ok-sf: #e1f5e4; --no: #a83630; --no-sf: #ffe7e4; --forse: #845a0f; --forse-sf: #fcedcd;
  --ombra: 0 1px 2px rgba(23, 32, 38, .04), 0 6px 20px -10px rgba(23, 32, 38, .10);
}
[data-testid="stMainBlockContainer"] { max-width: 1320px; padding-top: 4.5rem; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { max-width: 72ch; }
[data-testid="stMetricValue"], [data-testid="stDataFrame"], .cifre td, .riquadro .valore {
  font-variant-numeric: tabular-nums; }
.intestazione { display: flex; align-items: center; justify-content: space-between; gap: 1rem 1.5rem; flex-wrap: wrap;
  margin-bottom: 1rem; }
.intestazione .titolo { display: flex; align-items: center; gap: .875rem; flex: 1 1 36rem; min-width: 0; }
.marchio { flex: none; width: 2.75rem; height: 2.75rem; border-radius: .75rem; background: var(--accento);
  display: grid; place-items: center; }
.marchio::before, .nota::before { content: ""; flex: none; background: currentColor;
  -webkit-mask: var(--icona) center / contain no-repeat; mask: var(--icona) center / contain no-repeat; }
.marchio::before { width: 1.375rem; height: 1.375rem; color: #fff; --icona: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round'%3E%3Ccircle cx='12' cy='12' r='4'/%3E%3Cpath d='M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41'/%3E%3C/svg%3E"); }
.nota::before { width: .875rem; height: .875rem; --icona: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2.25' stroke-linecap='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpath d='M12 16v-4M12 8h.01'/%3E%3C/svg%3E"); }
.intestazione h1 { font-size: 1.625rem; margin: 0; padding: 0; letter-spacing: -0.015em; line-height: 1.25; }
.intestazione .sottotitolo { color: var(--tenue); margin: .125rem 0 0; max-width: 72ch; font-size: .9375rem; }
.nota { display: inline-flex; align-items: center; gap: .375rem; font-size: .8125rem; font-weight: 500;
  color: var(--forse); background: var(--forse-sf); border: 1px solid #ecd9ae; border-radius: 999px;
  padding: .3125rem .75rem; }
/* i passi: numero in un cerchio e linea di avanzamento fino al passo aperto (solo le schede dei passi,
   non quelle dei grafici annidate nei Risultati) */
.st-key-passo > div > [role="tablist"] { counter-reset: passo -1; gap: 0; padding: 0 0 .875rem; }
.st-key-passo > div > [role="tablist"]::after,
.st-key-passo > div > [role="tablist"] .react-aria-SelectionIndicator { display: none; }
.st-key-passo > div > [role="tablist"] > [role="tab"] {
  counter-increment: passo; flex: 1 1 auto; display: flex; align-items: center; gap: .5rem; height: auto;
  padding: .25rem .5rem .25rem 0; color: var(--tenue); border: 0; background: none; }
.st-key-passo > div > [role="tablist"] > [role="tab"]:last-child { flex: none; }
.st-key-passo > div > [role="tablist"] > [role="tab"] p { color: inherit; font-size: .9375rem; white-space: nowrap; }
.st-key-passo > div > [role="tablist"] > [role="tab"]::before {
  content: counter(passo); flex: none; width: 1.75rem; height: 1.75rem; border-radius: 999px; display: grid;
  place-items: center; font-size: .8125rem; font-weight: 620; border: 1.5px solid var(--bordo-forte);
  background: var(--superficie); color: var(--tenue);
  transition: background-color .15s ease-out, border-color .15s ease-out, color .15s ease-out; }
.st-key-passo > div > [role="tablist"] > [role="tab"]:first-child::before { content: "i"; font-weight: 700; }
.st-key-passo > div > [role="tablist"] > [role="tab"]:not(:last-child)::after {
  content: ""; flex: 1 1 1.5rem; min-width: .75rem; height: 2px; border-radius: 2px; background: var(--bordo);
  margin-left: .25rem; }
.st-key-passo > div > [role="tablist"] > [role="tab"]:hover { color: var(--testo); }
.st-key-passo > div > [role="tablist"] > [role="tab"]:hover::before { border-color: var(--accento); }
.st-key-passo > div > [role="tablist"] > [role="tab"]:has(~ [aria-selected="true"])::before {
  background: var(--accento-sf); border-color: var(--accento); color: var(--accento); }
.st-key-passo > div > [role="tablist"] > [role="tab"]:has(~ [aria-selected="true"])::after {
  background: var(--accento); }
.st-key-passo > div > [role="tablist"] > [aria-selected="true"] { color: var(--testo); }
.st-key-passo > div > [role="tablist"] > [aria-selected="true"] p { font-weight: 600; }
.st-key-passo > div > [role="tablist"] > [aria-selected="true"]::before {
  background: var(--accento); border-color: var(--accento); color: #fff; }
.st-key-passo > div > [role="tablist"] > [role="tab"]:focus-visible {
  outline: 2px solid var(--accento); outline-offset: 2px; border-radius: .5rem; }
/* il passo aperto in un pannello bianco */
.st-key-passo > div > [role="tabpanel"] { background: var(--superficie); border: 1px solid var(--bordo);
  border-radius: 1rem; box-shadow: var(--ombra); padding: 1.75rem 2rem 2rem; }
@media (max-width: 760px) { .st-key-passo > div > [role="tabpanel"] { padding: 1.125rem 1rem 1.25rem; }
  .st-key-passo > div > [role="tablist"] > [role="tab"]:not([aria-selected="true"]) p { display: none; } }
[data-testid="stExpander"] details { border-radius: .75rem; background: var(--superficie); }
[data-testid="stExpander"] summary:hover { color: var(--accento); }
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-secondary"], [data-testid="stPopoverButton"] {
  transition: background-color .15s ease-out, border-color .15s ease-out,
  color .15s ease-out, box-shadow .15s ease-out; }
[data-testid="stBaseButton-primary"] { box-shadow: 0 1px 2px rgba(23, 32, 38, .14); }
[data-testid="stBaseButton-primary"]:hover { background: var(--accento-scuro); border-color: var(--accento-scuro); }
[data-testid="stBaseButton-secondary"], [data-testid="stPopoverButton"] { background: var(--superficie);
  box-shadow: 0 1px 2px rgba(23, 32, 38, .05); }
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stPopoverButton"]:hover {
  border-color: var(--accento); color: var(--accento); }
[data-testid="stSidebar"] { border-right: 1px solid var(--bordo); }
/* accessibilità: la barra laterale chiusa esce dall'ordine del tasto Tab; didascalie a 4,5:1 anche sul bianco
   (il grigio di Streamlit arriva a 4,4:1); focus ben visibile; niente ancore dei titoli, che prendono il focus
   restando invisibili */
[data-testid="stSidebar"][data-collapsed="true"] { visibility: hidden; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--tenue); opacity: 1; }
[data-testid^="stBaseButton"]:focus-visible, [data-testid="stPopoverButton"]:focus-visible,
[data-testid="stExpander"] summary:focus-visible, [data-testid="stSkipToContent"]:focus-visible,
[data-testid="stMain"] a:focus-visible { outline: 2px solid var(--accento); outline-offset: 2px; }
[data-testid="stHeaderActionElements"] { display: none; }
[class*="st-key-script_"] { display: none; }
h2.laterale { font-size: 1.25rem; font-weight: 600; line-height: 1.4; margin: 0; padding: 0; }
h2.laterale.minore { font-size: 1rem; }
.solo-lettori { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { font-size: .8125rem; line-height: 1.55; }
.riquadri { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; margin: .25rem 0 1.25rem; }
.riquadro { background: var(--tenue-sf); border: 1px solid var(--bordo); border-radius: .75rem; padding: 1rem 1.125rem; }
.riquadro .voce { font-size: .875rem; font-weight: 500; color: var(--tenue); margin: 0; }
.riquadro .valore { font-size: 1.75rem; font-weight: 650; letter-spacing: -0.015em; line-height: 1.2;
  margin: .375rem 0 .25rem; }
.riquadro .intervallo { font-size: .8125rem; color: var(--tenue); margin: 0; }
@media (max-width: 760px) { .riquadri { grid-template-columns: 1fr; } .riquadro .valore { font-size: 1.5rem; } }
.etichetta { display: inline-block; font-size: .8125rem; font-weight: 600; line-height: 1.4; padding: .0625rem .5rem;
  border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
.etichetta.ok { color: var(--ok); background: var(--ok-sf); }
.etichetta.no { color: var(--no); background: var(--no-sf); }
.etichetta.forse { color: var(--forse); background: var(--forse-sf); }
.controlli { list-style: none; padding: 0; margin: 0 0 .5rem; }
.controlli li { display: grid; grid-template-columns: 10.5rem 1fr; gap: .75rem; align-items: baseline;
  padding: .5rem 0; border-bottom: 1px solid var(--bordo); max-width: none; }
.controlli li:last-child { border-bottom: 0; }
.controlli .motivo { color: var(--tenue); }
.sintesi { font-size: 1.125rem; line-height: 1.6; max-width: 68ch; margin: .25rem 0 1.25rem; }
.cifre { width: 100%; border-collapse: separate; border-spacing: 0; margin-bottom: .75rem;
  border: 1px solid var(--bordo); border-radius: .75rem; overflow: hidden; }
.cifre th { text-align: left; font-size: .8125rem; font-weight: 600; color: var(--tenue); background: var(--tenue-sf);
  padding: .625rem .875rem; border-bottom: 1px solid var(--bordo); }
.cifre td { padding: .75rem .875rem; border-bottom: 1px solid var(--bordo); vertical-align: top; }
.cifre tbody tr:last-child td { border-bottom: 0; }
.cifre td.voce { font-weight: 600; width: 24%; }
.cifre td.valore { font-size: 1.25rem; font-weight: 620; white-space: nowrap; width: 18%; }
.cifre td.intervallo { white-space: nowrap; color: var(--tenue); width: 22%; }
.cifre td.significato { color: var(--tenue); }
ul.guida { list-style: none; padding: 0; margin: 0 0 .75rem; }
ul.guida li { display: grid; margin: 0; gap: .125rem; padding: .5rem 0; border-bottom: 1px solid var(--bordo); max-width: 72ch; }
ul.guida li:last-child { border-bottom: 0; }
.guida span { color: var(--tenue); }
@media (max-width: 760px) { .cifre td.significato, .cifre th.significato { display: none; } }
/* schermi stretti e zoom forte: ogni riga della tabella diventa un blocco, senza scorrimento orizzontale */
@media (max-width: 560px) {
  .cifre, .cifre tbody, .cifre tr, .cifre td { display: block; width: auto; }
  .cifre thead { display: none; }
  .cifre tr { padding: .75rem .875rem; border-bottom: 1px solid var(--bordo); }
  .cifre tbody tr:last-child { border-bottom: 0; }
  .cifre td, .cifre td.voce, .cifre td.valore, .cifre td.intervallo { width: auto; padding: 0; border: 0;
    white-space: normal; }
  .cifre td.valore { font-size: 1.125rem; margin: .125rem 0; }
  .cifre td.intervallo:not(:empty)::before { content: attr(data-etichetta) ": "; }
  .controlli li { grid-template-columns: minmax(0, 1fr); gap: .25rem; } }
/* telefono: l'intestazione non deve prendere mezzo schermo */
@media (max-width: 640px) { .intestazione h1 { font-size: 1.375rem; } .intestazione .sottotitolo { display: none; }
  .nota { border-radius: .5rem; }
  .sintesi { font-size: 1rem; } }
ol.percorso { list-style: none; counter-reset: passo; padding: 0; margin: 0 0 .5rem; max-width: 72ch; }
ol.percorso li { counter-increment: passo; display: grid; grid-template-columns: 2rem 1fr; column-gap: .75rem;
  padding: .5rem 0; border-bottom: 1px solid var(--bordo); }
ol.percorso li:last-child { border-bottom: 0; }
ol.percorso li::before { content: counter(passo); grid-row: span 2; width: 1.75rem; height: 1.75rem; border-radius: 999px;
  border: 1.5px solid var(--accento); background: var(--accento-sf); color: var(--accento); display: grid;
  place-items: center; font-size: .8125rem; font-weight: 620; }
ol.percorso span { color: var(--tenue); }
/* schede dei passi leggibili anche in proiezione */
[data-testid="stTab"] [data-testid="stMarkdownContainer"] p { font-size: 1rem; }
/* testi del caricamento file in italiano (Streamlit li ha solo in inglese) */
[data-testid="stFileUploaderDropzone"] button [data-testid="stMarkdownContainer"] p { font-size: 0; }
[data-testid="stFileUploaderDropzone"] button [data-testid="stMarkdownContainer"] p::after {
  content: "Scegli il file"; font-size: .875rem; }
[data-testid="stFileUploaderDropzoneInstructions"] span { font-size: 0; }
[data-testid="stFileUploaderDropzoneInstructions"] span::after { content: "oppure trascinalo qui, fino a 5 MB";
  font-size: .8125rem; }
</style>
"""


# Streamlit dichiara la pagina in inglese e ha qualche etichetta in inglese: lingua e nomi accessibili in
# italiano (WCAG 3.1.1 e 3.1.2), perché il lettore di schermo legga con la pronuncia giusta. Lo script passa
# alla pagina principale e si installa una sola volta; un osservatore rimette tutto a posto a ogni ridisegno.
ITALIANO = """<script>
function installa() {
  const voci = {"Skip to main content": "Vai al contenuto principale", "Expand sidebar": "Apri la barra laterale",
    "Collapse sidebar": "Chiudi la barra laterale", "Sidebar": "Barra laterale", "Main menu": "Menu principale",
    "Show data": "Mostra i dati", "Fullscreen": "Schermo intero", "Close fullscreen": "Chiudi lo schermo intero",
    "Download as CSV": "Scarica in CSV", "Search": "Cerca", "Copy Vega-Lite spec": "Copia la specifica del grafico",
    "file upload": "Caricamento del file", "Open": "Apri", "Choose date": "Scegli la data",
    "Copy to clipboard": "Copia negli appunti"};
  const prefissi = [["Help for ", "Aiuto: "], ["day, ", "giorno, "], ["month, ", "mese, "], ["year, ", "anno, "]];
  const radice = document.documentElement;
  const traduci = () => {
    if (radice.lang !== "it") radice.lang = "it";
    for (const e of document.querySelectorAll("[aria-label]")) {
      const nome = e.getAttribute("aria-label");
      const prefisso = prefissi.find(([en]) => nome.startsWith(en));
      const t = voci[nome] || (prefisso && prefisso[1] + nome.slice(prefisso[0].length));
      if (t) e.setAttribute("aria-label", t);
    }
    const salta = document.querySelector("[data-testid=stSkipToContent]");
    if (salta && voci[salta.textContent.trim()]) salta.textContent = voci[salta.textContent.trim()];
  };
  let previsto = false;
  new MutationObserver(() => {
    if (!previsto) { previsto = true; requestAnimationFrame(() => { previsto = false; traduci(); }); }
  }).observe(radice, {subtree: true, childList: true, attributes: true, attributeFilter: ["aria-label", "lang"]});
  traduci();
}
const pagina = window.parent.document;
if (!pagina.getElementById("cersim-italiano")) {
  const s = pagina.createElement("script");
  s.id = "cersim-italiano";
  s.textContent = "(" + installa.toString() + ")();";
  pagina.head.appendChild(s);
}
</script>"""


def titolo_nascosto(testo: str):
    """Titolo di secondo livello per i soli lettori di schermo: tiene in ordine la gerarchia dei titoli."""
    st.html(f'<h2 class="solo-lettori">{escape(testo)}</h2>')


def etichetta(testo: str, tono: str) -> str:
    return f'<span class="etichetta {tono}">{escape(testo)}</span>'


def intestazione(titolo: str, sottotitolo: str, nota: str | None = None) -> str:
    """Titolo della pagina con il marchio; `sottotitolo` è HTML già sicuro, la nota è un avviso a destra.

    Le icone del marchio e della nota sono nello stile: st.html toglie gli SVG scritti nella pagina."""
    avviso = f'<span class="nota">{escape(nota)}</span>' if nota else ""
    return (f'<div class="intestazione"><div class="titolo"><div class="marchio" aria-hidden="true"></div><div>'
            f'<h1>{escape(titolo)}</h1><p class="sottotitolo">{sottotitolo}</p></div></div>{avviso}</div>')


@st.cache_data(max_entries=20, show_spinner=False)
def _leggi_prezzi(dati: bytes, nome: str, regione: str):
    anno = anno_dei_prezzi(io.BytesIO(dati))
    file = io.BytesIO(dati)
    file.name = nome
    return prezzi_da_csv(file, zona_mercato(regione, anno), anno)


@st.cache_data(max_entries=20, show_spinner=False)
def _curva(contenuti: tuple[bytes, ...]):
    """Curva misurata da uno o più file dei consumi, con gli avvisi di lettura."""
    return curva_da_file(list(contenuti))


@st.cache_data(max_entries=20, show_spinner=False)
def _curva_calcolata(contenuto: bytes):
    """Curva calcolata dal file JSON del simulatore della casa, con gli avvisi di lettura."""
    return leggi_curva_calcolata(contenuto)


@st.cache_data(max_entries=10, show_spinner=False)
def _scheda_pdf(configurazione: str | None, link: str) -> bytes:
    return scheda_famiglia_pdf(configurazione, link)


def _impronta_prezzi(prezzi: dict) -> tuple:
    """Anno, fonte e contenuto di ogni serie: un file diverso dello stesso anno cambia l'impronta."""
    return tuple(sorted((a, s.fonte, hashlib.sha1(s.eur_mwh.to_numpy().tobytes()).hexdigest()) for a, s in prezzi.items()))


# --- stato della sessione -------------------------------------------------------------
def _init():
    ss = st.session_state
    ss.setdefault("punti_base", punti_vuoti())
    ss.setdefault("impianti_base", impianti_vuoti())
    ss.setdefault("generale", {"nome": "", "tipo": "gruppo", "indirizzo": "", "lat": 45.07, "lon": 7.69,
                               "regione": "Piemonte", "data_costituzione": None})
    ss.setdefault("parametri", {})
    ss.setdefault("versione_editor", 0)
    ss.setdefault("curve_misurate", {})  # etichetta del contatore → CurvaMisurata


def _carica(config, parametri):
    generale, punti, impianti = tabelle_da_configurazione(config)
    st.session_state.generale = {"nome": generale.nome, "tipo": generale.tipo, "indirizzo": generale.indirizzo or "",
                                 "lat": generale.lat, "lon": generale.lon, "regione": generale.regione,
                                 "data_costituzione": generale.data_costituzione}
    st.session_state.punti_base = punti
    st.session_state.impianti_base = impianti
    st.session_state.parametri = parametri
    st.session_state.config_base = config  # i campi che le tabelle non mostrano si riprendono da qui
    st.session_state.curve_misurate = {c.id: c.curva_misurata for c in config.connection_points if c.curva_misurata}
    st.session_state.versione_editor += 1  # forza il ricaricamento delle tabelle
    st.session_state.pop("analisi", None)


def _esempio_torino():
    consumi = [1800, 2200, 2700, 2700, 3100, 3500, 2400, 1600, 2900, 3300, 2000, 2600]
    punti = famiglie_tipo(12)
    punti["kWh annui"] = consumi
    punti["F1 kWh"] = [round(c * 0.33) for c in consumi]
    punti["F23 kWh"] = [c - round(c * 0.33) for c in consumi]
    extra = pd.DataFrame([
        {"Punto": "Panetteria", "Membro": "Panetteria", "Tipo soggetto": "PMI", "Tipologia consumo": "Ufficio / negozio",
         "kWh annui": 14000, "F1 kWh": 8400, "F23 kWh": 5600, "Tensione": "BT"},
        {"Punto": "Parti comuni", "Membro": "Condominio", "Tipo soggetto": "Condominio",
         "Tipologia consumo": "Municipio / uffici pubblici", "kWh annui": 4500, "F1 kWh": 2000, "F23 kWh": 2500,
         "Tensione": "BT"},
    ], columns=COLONNE_PUNTI)
    impianti = pd.DataFrame([{
        "Impianto": "FV tetto", "Punto": "Parti comuni", "kWp moduli": 20.0, "kW inverter": 18.0,
        "kWp max installabili": 35.0, "Inclinazione °": 25.0, "Orientamento °": 10.0,
        "Entrata in esercizio": date(2027, 4, 1), "Investitore": "Condominio",
    }], columns=COLONNE_IMPIANTI)
    st.session_state.generale = {"nome": "Condominio Via Esempio 1, Torino", "tipo": "gruppo",
                                 "indirizzo": "Piazza Castello, Torino", "lat": 45.0703, "lon": 7.6869,
                                 "regione": "Piemonte", "data_costituzione": date(2027, 1, 15)}
    st.session_state.punti_base = tipizza_punti(pd.concat([punti, extra], ignore_index=True))
    st.session_state.impianti_base = tipizza_impianti(impianti)
    st.session_state.pop("config_base", None)
    st.session_state.curve_misurate = {}
    st.session_state.versione_editor += 1
    st.session_state.pop("analisi", None)


# --- modulo per famiglie e attività (dal link del passo 2) --------------------------------
def _voci_guida(voci) -> str:
    righe = "".join(f"<li><strong>{escape(v.cosa)}</strong><span>{escape(v.dove)}</span></li>" for v in voci)
    return f'<ul class="guida">{righe}</ul>'


def _modulo_famiglia():
    """Pagina semplice per chi riceve il link: che cosa serve, dove trovarlo, i propri consumi, un file da mandare."""
    per = (st.query_params.get("per") or "").strip()[:MAX_TESTO]
    st.html(intestazione("I consumi di luce", f'{"Per " + escape(per) + ". " if per else ""}Servono a valutare un '
                         "impianto fotovoltaico da condividere tra vicini, un gruppo di autoconsumatori o una comunità "
                         "energetica. Bastano pochi minuti e una bolletta."))
    titolo_nascosto("La scheda dei consumi")
    st.subheader("Che cosa serve")
    st.html(_voci_guida(COSA_SERVE["famiglia"].voci[:2]))
    st.caption(PORTALE_CONSUMI + " " + CODICE_POD)

    st.subheader("I tuoi dati")
    profilo = st.radio("Chi sei", list(PROFILI))
    tipo_soggetto, tipologia = PROFILI[profilo]
    if tipo_soggetto is None:
        tipo_soggetto = st.selectbox("Che tipo di attività è", SOGGETTI_ATTIVITA,
                                     format_func=ETICHETTE_SOGGETTO_ATTIVITA.get)
    famiglia = profilo == "Una famiglia"
    membro = st.text_input("Il nome con cui vuoi comparire", max_chars=MAX_TESTO,
                           placeholder="Rossi, interno 3" if famiglia else "Panetteria Bianchi")
    n = int(st.number_input("Quanti contatori della luce hai", min_value=1, max_value=MAX_CONTATORI, value=1,
                            help="Di solito uno: una bolletta della luce per ogni contatore"))
    contatori = []
    for i in range(n):
        if n > 1:
            st.markdown(f"**Contatore {i + 1}**")
            nome = st.text_input("Nome del contatore", value=f"Contatore {i + 1}", max_chars=MAX_TESTO, key=f"nome_{i}",
                                 help="Per esempio 'Negozio' o 'Magazzino'")
        else:
            nome = "Contatore"
        tipo_consumo = tipologia
        if tipo_consumo is None:
            opzioni = TIPOLOGIE_ENTE if tipo_soggetto == "Ente territoriale (es. Comune)" else TIPOLOGIE_ATTIVITA
            tipo_consumo = st.selectbox("Come si usa l'energia", opzioni, key=f"tipologia_{i}")
        c1, c2, c3 = st.columns(3)
        kwh_annui = c1.number_input("Consumo dell'ultimo anno, kWh", min_value=0.0, max_value=10_000_000.0, step=100.0,
                                    format="%.0f", value=None, key=f"kwh_{i}")
        f1 = c2.number_input("di cui in F1, kWh", min_value=0.0, max_value=10_000_000.0, step=100.0, format="%.0f",
                             value=None, key=f"f1_{i}", help="Facoltativo")
        f23 = c3.number_input("di cui in F2+F3, kWh", min_value=0.0, max_value=10_000_000.0, step=100.0, format="%.0f",
                              value=None, key=f"f23_{i}", help="Facoltativo: somma di F2 e F3")
        tensione = "BT"
        if not famiglia:
            tensione = st.radio("Tensione della fornitura", ["BT", "MT"], horizontal=True, key=f"tensione_{i}",
                                format_func=lambda t: "Bassa tensione" if t == "BT" else "Media tensione",
                                help="In bolletta, nei dati della fornitura")
        file_misure = st.file_uploader(
            "Facoltativo: i consumi ora per ora", type=["csv"], accept_multiple_files=True, key=f"misure_{i}",
            help="Il file letture.csv del Portale Consumi (pulsante Scarica letture) oppure i file mensili della curva "
                 "di carico di e-distribuzione. Rendono la simulazione più precisa. Il file non viene salvato e il "
                 "codice POD non viene letto: nella scheda va solo la forma media dei consumi")
        curva = None
        if file_misure:
            try:
                curva, _ = _curva(tuple(f.getvalue() for f in file_misure))
                st.success(f"Consumi letti: {descrivi(curva)}.", icon=":material/check_circle:")
            except ValueError as e:
                st.error(str(e), icon=":material/error:")
        contatori.append(Contatore(nome=nome, tipologia=tipo_consumo, kwh_annui=kwh_annui, f1_kwh=f1, f23_kwh=f23,
                                   tensione=tensione, curva=curva))

    scheda = Scheda(membro=membro, tipo_soggetto=tipo_soggetto, contatori=contatori, configurazione=per or None)
    errori = controlla(scheda)
    st.subheader("Consegna")
    if not membro.strip():
        st.markdown("Scrivi il nome con cui vuoi comparire: poi potrai scaricare la scheda.")
    elif errori:
        st.warning("Prima di scaricare la scheda:\n\n" + "\n".join(f"- {e}" for e in errori),
                   icon=":material/edit_note:")
    else:
        if any(c.kwh_annui is None and c.curva is None for c in contatori):
            st.caption(f"Senza consumo annuo si userà quello di una famiglia tipo, {kwh(KWH_FAMIGLIA_TIPO)} all'anno.")
        st.download_button("Scarica la scheda da mandare", crea_scheda(scheda), file_name=nome_file(scheda),
                           mime="application/json", type="primary", icon=":material/download:", on_click="ignore")
        st.markdown("Poi manda il file a chi coordina, per email o messaggio. Non serve fare altro.")
    st.caption(PRIVACY_SCHEDA)


_init()
ss = st.session_state
st.html(STILE)
with st.container(key="script_lingua"):  # contenitore nascosto dallo stile: lo script gira comunque
    st.iframe(ITALIANO, height=1, tab_index=-1)
if st.query_params.get("modulo") == MODULO:
    _modulo_famiglia()  # chi riceve il link vede solo la propria scheda
    st.stop()

# --- intestazione ---------------------------------------------------------------------
st.html(intestazione(
    "Simulatore di comunità energetiche",
    "Per comuni e condomini: energia condivisa, contributi GSE e chi ci guadagna, in una comunità energetica "
    "rinnovabile o in un gruppo di autoconsumatori.",
    AVVISO_PRELIMINARE,
))

# il numero di ogni passo è la sua posizione nell'elenco; nelle schede lo disegna lo stile, in un cerchio
PASSI = ["Prima di iniziare", "Luogo", "Membri e consumi", "Impianti", "Economia", "Risultati"]


def _vai(passo: str):
    """Apre un passo dal codice (pulsanti Avanti e "Vai al passo") e riporta la pagina in cima."""
    ss.passo = passo
    ss.torna_su = ss.get("torna_su_n", 0) + 1  # un numero nuovo ricarica lo script anche se la pagina non cambia
    ss.torna_su_n = ss.torna_su


def _avanti(dal: int, nota: str | None = None):
    """Fondo di un passo: che cosa manca, se manca qualcosa, e il pulsante per il passo successivo."""
    st.divider()
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    if nota:
        c1.caption(nota)
    c2.button(f"Avanti: {dal + 1}. {PASSI[dal + 1]}", on_click=_vai, args=(PASSI[dal + 1],), key=f"avanti_{dal}",
              icon=":material/arrow_forward:", width="stretch")


def _vai_a(passo: str, testo: str):
    st.button(testo, on_click=_vai, args=(passo,), key=f"vai_{passo}_{testo}", icon=":material/arrow_back:")


def _esempio_e_inizia():
    _esempio_torino()
    _vai(PASSI[1])


def _riprendi(caricato):
    if caricato is not None and ss.get("ultimo_json") != caricato.file_id:
        try:
            _carica(*importa_json(caricato.getvalue()))
            ss.ultimo_json = caricato.file_id
            st.rerun()
        except ValueError as e:
            st.error(str(e))


with st.sidebar:  # titoli di secondo livello: la barra viene prima del titolo della pagina
    st.html('<h2 class="laterale">Il tuo lavoro</h2>')
    if st.button("Carica l'esempio di Torino", icon=":material/apartment:", width="stretch",
                 help="Condominio con 12 famiglie, un negozio e 20 kWp sul tetto"):
        _esempio_torino()
        st.rerun()
    _riprendi(st.file_uploader("Riprendi un lavoro salvato", type=["json"], key="carica_json"))
    slot_salva = st.empty()  # riempito dopo la lettura delle tabelle
    st.divider()
    st.html('<h2 class="laterale minore">Privacy</h2>')
    st.caption(
        "L'indirizzo va a OpenStreetMap solo se premi *Cerca*. La foto aerea arriva dai server di Esri solo se premi "
        "*Apri la foto aerea*; le coordinate del tetto vanno al servizio Overpass di OpenStreetMap solo se premi "
        "*Stima le ombre dagli edifici vicini*. Le coordinate arrotondate (circa 1 km) vanno a PVGIS della "
        "Commissione europea; la risposta resta in cache sul server per 90 giorni. Nomi, consumi, prezzi e "
        "risultati non vengono salvati sul server: restano nella tua sessione. Per conservarli usa *Salva il "
        "lavoro*."
    )
    st.caption(f"cersim {__version__} · © 2026 Samuele Racca · codice open source, licenza MIT (vedi LICENZA.md)")

guida_tab, *passi = st.tabs(PASSI, key="passo", on_change="rerun")
if salto := ss.pop("torna_su", None):  # dopo un pulsante Avanti: il nuovo passo si legge dall'inizio
    # il focus va sulla scheda del nuovo passo: chi usa tastiera o lettore di schermo riparte da lì
    with st.container(key="script_torna_su"):
        st.iframe(f"<script>/* {salto} */ const d = window.parent.document; [100, 400, 800].forEach(t => "
                  "setTimeout(() => d.querySelector('[data-testid=stMain]')?.scrollTo(0, 0), t)); "
                  "setTimeout(() => d.querySelector('.st-key-passo [role=tab][aria-selected=true]')"
                  "?.focus({preventScroll: true}), 400)</script>",
                  height=1, tab_index=-1)

with guida_tab:
    titolo_nascosto(PASSI[0])
    st.html("<p class=\"sintesi\">In circa mezz'ora ottieni uno <strong>scenario preliminare</strong> di gruppo di "
            "autoconsumatori o di comunità energetica: quanta energia si condivide, quanti contributi GSE arrivano, "
            "chi paga e chi ci guadagna. Alla fine scarichi un report da portare in assemblea o in consiglio.</p>")
    c1, c2, c3 = st.columns(3, gap="medium")
    c1.button("Inizia dal passo 1", type="primary", icon=":material/arrow_forward:", on_click=_vai,
              args=(PASSI[1],), width="stretch")
    c2.button("Prova con l'esempio di Torino", icon=":material/apartment:", on_click=_esempio_e_inizia,
              width="stretch", help="Condominio con 12 famiglie, un negozio e 20 kWp sul tetto: puoi cambiare tutto")
    with c3.popover("Riprendi un lavoro salvato", icon=":material/folder_open:", width="stretch"):
        _riprendi(st.file_uploader("Il file salvato con *Salva il lavoro*", type=["json"], key="riprendi_json"))

    st.subheader("Come funziona")
    st.html(
        '<ol class="percorso">'
        "<li><strong>Luogo</strong><span>L'indirizzo e che cosa volete fare: un gruppo nello stesso edificio o una "
        "comunità energetica tra edifici diversi.</span></li>"
        "<li><strong>Membri e consumi</strong><span>Una riga per ogni contatore. Non serve raccogliere le bollette: "
        "mandi un link e ognuno ti rimanda i suoi consumi.</span></li>"
        "<li><strong>Impianti</strong><span>Per un condominio disegni il tetto sulla foto aerea e scegli tra tre "
        "taglie. Se hai un preventivo, usi i suoi dati.</span></li>"
        "<li><strong>Economia</strong><span>Decidi come dividere i contributi tra i membri e chi paga "
        "l'impianto.</span></li>"
        "<li><strong>Risultati</strong><span>Le cifre con il loro intervallo, i requisiti da verificare e il report "
        "PDF.</span></li></ol>"
    )

    st.subheader("Che cosa tenere a portata di mano")
    st.html(
        '<ul class="guida">'
        "<li><strong>L'indirizzo dell'edificio</strong><span>O degli edifici, per una comunità energetica.</span></li>"
        "<li><strong>La data prevista di costituzione</strong><span>Dal calendario dell'assemblea o del consiglio."
        "</span></li>"
        "<li><strong>Il preventivo dell'impianto, se c'è</strong><span>Costo, kWp dei moduli e kW dell'inverter. "
        "Senza, si usa un costo di riferimento alto.</span></li></ul>"
    )
    st.caption("Tutto il resto si inserisce nei passi. Dove mancano dati il simulatore usa valori tipici e lo dice "
               "con la qualità dei dati: A, B o C.")
    with st.expander("Tutti i dati che servono e dove trovarli", icon=":material/checklist:"):
        c1, c2 = st.columns(2, gap="large")
        for colonna, chiavi in ((c1, ("coordina",)), (c2, ("famiglia", "attivita", "parti_comuni"))):
            with colonna:
                for chiave in chiavi:
                    gruppo = COSA_SERVE[chiave]
                    st.markdown(f"**{gruppo.titolo}**")
                    st.html(_voci_guida(gruppo.voci))
                    if gruppo.nota:
                        st.caption(gruppo.nota)
        st.markdown(f"**Dove trovare i consumi.** {PORTALE_CONSUMI} {CODICE_POD}")

# --- passo 1 ----------------------------------------------------------------------------
with passi[0]:
    titolo_nascosto(f"Passo 1: {PASSI[1]}")
    g = ss.generale
    g["nome"] = st.text_input("Nome della configurazione", value=g["nome"], placeholder="Condominio Via Roma 1")
    g["tipo"] = st.radio(
        "Che cosa vuoi simulare",
        ["gruppo", "CER"],
        index=0 if g["tipo"] == "gruppo" else 1,
        format_func=lambda t: "Gruppo di autoconsumatori (condominio)" if t == "gruppo"
        else "Comunità energetica rinnovabile (CER)",
        captions=[
            "Tutti nello stesso edificio. Basta un contratto tra i partecipanti; l'impianto è sull'edificio.",
            "Membri anche in edifici diversi, sotto la stessa cabina primaria. Serve un soggetto giuridico con "
            "statuto; le grandi imprese non possono partecipare.",
        ],
    )

    st.subheader("Dove si trova")
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    g["indirizzo"] = c1.text_input("Indirizzo", value=g["indirizzo"], placeholder="Via Roma 1, Torino")
    errore_luogo = None
    if c2.button("Cerca", icon=":material/search:", help="Invia l'indirizzo a OpenStreetMap per trovare coordinate e regione"):
        try:
            luogo = geocode(g["indirizzo"])
            g.update(lat=round(luogo.lat, 4), lon=round(luogo.lon, 4), regione=luogo.regione)
            st.success(f"Trovato: {luogo.descrizione}")
        except Exception as e:  # rete assente, indirizzo non trovato…
            errore_luogo = f"Ricerca non riuscita ({e}). Inserisci coordinate e regione qui sotto."
            st.error(errore_luogo)
    posizione = st.empty()  # riempito dopo l'eventuale correzione a mano
    with st.expander("Correggi la posizione a mano", icon=":material/edit_location_alt:",
                     expanded=errore_luogo is not None):
        c1, c2, c3 = st.columns(3)
        g["lat"] = c1.number_input("Latitudine", value=float(g["lat"]), min_value=35.0, max_value=48.0, format="%.4f")
        g["lon"] = c2.number_input("Longitudine", value=float(g["lon"]), min_value=6.0, max_value=19.0, format="%.4f")
        regioni = list(REGIONI)
        g["regione"] = c3.selectbox("Regione", regioni,
                                    index=regioni.index(g["regione"]) if g["regione"] in regioni else 0)
    posizione.caption(f"Posizione usata: {g['regione']}, coordinate {g['lat']:.4f} e {g['lon']:.4f}".replace(".", ",")
                      + ".")
    g["data_costituzione"] = st.date_input(
        "Data, anche prevista, di costituzione", value=g["data_costituzione"], format="DD/MM/YYYY",
        help="Gli impianti devono entrare in esercizio dopo la costituzione, salvo deroghe.")
    _avanti(1, None if g["indirizzo"] else "Scrivi l'indirizzo e premi Cerca: serve a stimare quanto produce il sole.")

# --- passo 2 ----------------------------------------------------------------------------
def _togli_curva(etichetta: str):
    ss.curve_misurate.pop(etichetta, None)


CALCOLATI = ("Sono consumi **calcolati** dal simulatore della casa, non misurati: la simulazione li usa ora per ora, "
             "ma la qualità di questo contatore resta **B**, come con la bolletta, e non conta per la qualità A.")


def _leggi_consumi(file) -> tuple:
    """Curva dai file scelti: i CSV del distributore, oppure un solo file JSON del simulatore della casa."""
    calcolati = [f for f in file if f.name.lower().endswith(".json")]
    if not calcolati:
        return _curva(tuple(f.getvalue() for f in file))
    if len(file) > 1:
        raise ValueError("Il file del simulatore della casa va caricato da solo, senza altri file")
    return _curva_calcolata(calcolati[0].getvalue())


def _consumi_misurati(punti_df: pd.DataFrame):
    """Curve per contatore: chi coordina carica i file del distributore o del simulatore della casa, oppure arrivano
    con le schede delle famiglie."""
    etichette = [str(x) for x in punti_df["Punto"].dropna() if str(x).strip()]
    curve = ss.curve_misurate
    titolo = "Consumi ora per ora" + (f": {len(curve)} contator{'e' if len(curve) == 1 else 'i'}" if curve
                                      else " (facoltativo)")
    with st.expander(titolo, icon=":material/monitoring:", expanded=bool(curve)):
        st.markdown("Con i file dei consumi a quarti d'ora la simulazione usa le **ore vere** di ogni contatore invece "
                    "di una curva tipica. Se coprono almeno 11 mesi e tre quarti dei consumi, la qualità sale ad **A**.")
        st.caption("Vanno bene il file letture.csv del Portale Consumi (pulsante *Scarica letture*), i file mensili "
                   "ExportData della curva di carico di e-distribuzione e i file che l'app di e-distribuzione manda "
                   "per email. I file non vengono salvati e il codice POD non viene letto: resta solo la forma media "
                   "dei consumi. Le famiglie possono anche allegarli alla loro scheda.")
        st.caption("Va bene anche il file JSON dei consumi esportato dal simulatore della casa, per esempio per vedere "
                   "che cosa cambia con una pompa di calore. È una stima, non una misura: la qualità resta B.")
        c1, c2 = st.columns([1, 2])
        contatore = c1.selectbox("Contatore", etichette, key="curva_contatore", index=None,
                                 placeholder="Scegli il contatore")
        versione = ss.get("versione_curve", 0)
        file = c2.file_uploader("File dei consumi, anche più mesi insieme", type=["csv", "json"],
                                accept_multiple_files=True, key=f"curva_file_{versione}")
        if st.button("Usa questi consumi", icon=":material/upload_file:", disabled=not (file and contatore)):
            try:
                curva, avvisi = _leggi_consumi(file)
                curve[contatore] = curva
                ss.versione_curve = versione + 1  # svuota la scelta dei file
                ss.esito_curva = ("ok" if curva.misurata else "calcolata", f"{contatore}: {descrivi(curva)}.", avvisi)
            except ValueError as e:
                ss.esito_curva = ("errore", str(e), [])
            st.rerun()
        if esito := ss.pop("esito_curva", None):
            tono, testo, avvisi = esito
            if tono == "calcolata":
                st.info(f"{testo}\n\n{CALCOLATI}", icon=":material/calculate:")
            else:
                (st.success if tono == "ok" else st.error)(testo)
            if avvisi:
                st.caption("Da controllare: " + "; ".join(avvisi[:5]) + (" …" if len(avvisi) > 5 else ""))
        for etichetta, curva in curve.items():
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            fuori = "" if etichetta in etichette else " (contatore non più nella tabella)"
            c1.markdown(f"**{etichetta}**{fuori}: {descrivi(curva)}")
            c2.button("Togli", key=f"togli_curva_{etichetta}", on_click=_togli_curva, args=(etichetta,),
                      type="tertiary", icon=":material/close:")
        if curve:
            st.caption("Per questi contatori consumo annuo e fasce della tabella non si usano: valgono le curve "
                       "caricate.")



with passi[1]:
    titolo_nascosto(f"Passo 2: {PASSI[2]}")
    st.markdown("Una riga per ogni **contatore (POD)**. Un membro con più contatori, come un Comune con municipio "
                "e scuola, compare in più righe con lo stesso nome. Consumo annuo e fasce sono in bolletta; se per "
                "una famiglia manca il consumo, si usa la famiglia tipo ARERA da 2.700 kWh/anno.")
    with st.expander("Raccogli i consumi con un link", icon=":material/share:"):
        st.markdown("Manda questo link a ogni famiglia e attività, per email o messaggio. Ognuno legge che cosa serve, "
                    "inserisce i suoi consumi e ti rimanda un piccolo file. Carica qui sotto i file ricevuti: la tabella "
                    "si compila da sola e una scheda rimandata aggiorna le righe di chi l'ha mandata.")
        link = link_famiglie(st.context.url or "http://localhost:8501/", ss.generale["nome"])
        st.caption("Copia il link con il pulsante a destra del riquadro.")
        st.code(link, language=None, wrap_lines=True)
        c1, c2 = st.columns(2)
        c1.link_button("Apri la scheda come la vedrà una famiglia", link, icon=":material/open_in_new:")
        c2.download_button("Scheda da stampare (PDF)", _scheda_pdf(ss.generale["nome"] or None, link),
                           file_name="scheda_consumi.pdf", mime="application/pdf", icon=":material/print:",
                           on_click="ignore", help="Una pagina con le stesse spiegazioni, il link e una tabella da "
                                                   "compilare a mano")
        ricevute = st.file_uploader("Schede ricevute", type=["json"], accept_multiple_files=True, key="schede_ricevute")
        gia_lette = ss.setdefault("schede_lette", set())
        nuove = [f for f in ricevute or [] if f.file_id not in gia_lette]
        if nuove:
            schede, esito = [], []
            nome_cfg = (ss.generale["nome"] or "").strip()[:MAX_TESTO]
            for f in nuove:
                gia_lette.add(f.file_id)
                try:
                    scheda = leggi_scheda(f.getvalue())
                except ValueError as e:
                    esito.append(f"{f.name}: {e}")
                    continue
                schede.append(scheda)
                if scheda.configurazione and nome_cfg and scheda.configurazione != nome_cfg:
                    esito.append(f"{f.name}: la scheda era per '{scheda.configurazione}'. Aggiunta lo stesso.")
            if schede:
                attuali = ss.get(f"punti_editati_{ss.versione_editor}", ss.punti_base)
                ss.punti_base, messaggi = unisci_schede(attuali, schede, curve=ss.curve_misurate)
                ss.versione_editor += 1
                esito = messaggi + esito
            ss.esito_schede = esito
            st.rerun()
        for messaggio in ss.pop("esito_schede", []):
            (st.success if messaggio.startswith("Contatori aggiunti") else st.warning)(messaggio)
    c1, c2 = st.columns([1, 3], vertical_alignment="bottom")
    n_famiglie = c1.number_input("Famiglie da aggiungere", min_value=1, max_value=100, value=10)
    if c2.button("Aggiungi famiglie tipo", icon=":material/group_add:"):
        attuali = ss.get(f"punti_editati_{ss.versione_editor}", ss.punti_base)
        ss.punti_base = tipizza_punti(pd.concat([attuali, famiglie_tipo(int(n_famiglie), inizio=len(attuali) + 1)],
                                                ignore_index=True))
        ss.versione_editor += 1
        st.rerun()
    colonne_punti = {
        "Punto": st.column_config.TextColumn("Contatore", help="Un nome a scelta, per esempio 'Interno 3' o 'Scuola'",
                                             required=True),
        "Membro": st.column_config.TextColumn("Membro", required=True),
        "Tipo soggetto": st.column_config.SelectboxColumn("Tipo di soggetto", options=list(TIPI_SOGGETTO), required=True),
        "Tipologia consumo": st.column_config.SelectboxColumn("Tipo di consumo", options=list(TIPOLOGIE), required=True),
        "kWh annui": st.column_config.NumberColumn("kWh all'anno", min_value=0, max_value=10_000_000, format="%.0f"),
        "F1 kWh": st.column_config.NumberColumn("di cui F1", min_value=0, format="%.0f", help="Consumo in fascia F1, dalla bolletta"),
        "F23 kWh": st.column_config.NumberColumn("di cui F2+F3", min_value=0, format="%.0f", help="Consumo in F2 e F3, dalla bolletta"),
        "Area convenzionale GSE": st.column_config.TextColumn(
            "Area convenzionale", help="Solo per le CER: codice dalla mappa delle cabine primarie del GSE"),
        "Tensione": st.column_config.SelectboxColumn("Tensione", options=["BT", "MT"], default="BT"),
    }
    if ss.generale["tipo"] == "gruppo":
        colonne_punti["Area convenzionale GSE"] = None  # non serve nel condominio
    punti_df = st.data_editor(ss.punti_base, num_rows="dynamic", column_config=colonne_punti,
                              key=f"punti_editor_{ss.versione_editor}", hide_index=True)
    ss[f"punti_editati_{ss.versione_editor}"] = punti_df
    if ss.generale["tipo"] == "CER":
        st.caption("Il codice dell'area convenzionale si trova sulla mappa interattiva delle cabine primarie del GSE, "
                   "cercando per indirizzo o per codice POD. Se manca, i contributi risultano condizionali.")
    _consumi_misurati(punti_df)
    n_contatori = sum(bool(str(x).strip()) for x in punti_df["Punto"].dropna())
    _avanti(2, None if n_contatori else "Aggiungi almeno un contatore: con il link, con le famiglie tipo o "
                                         "scrivendo nella tabella.")

# --- passo 3: proposta dell'impianto (condominio) --------------------------------------------
DIREZIONI = [(-180, "nord"), (-135, "nord-est"), (-90, "est"), (-45, "sud-est"), (0, "sud"), (45, "sud-ovest"),
             (90, "ovest"), (135, "nord-ovest"), (180, "nord")]


def _direzione(azimut: float) -> str:
    return min(DIREZIONI, key=lambda d: abs(d[0] - azimut))[1]


@st.cache_data(ttl=3600, max_entries=50, show_spinner=False)
def _elementi_osm(lat: float, lon: float) -> list[dict]:
    return scarica_edifici(lat, lon)


def _parametri_proposta() -> tuple[ParametriEconomici, bool]:
    """Parametri del passo 4; se il riparto non è ancora scelto, uno provvisorio (detto nella proposta)."""
    p = ss.parametri
    quota = p.get("quota_membri")
    return ParametriEconomici(
        quota_membri=QUOTA_PROVVISORIA if quota is None else quota,
        costo_evitabile_eur_kwh=p.get("costo_evitabile_eur_kwh"), tasso_sconto=p.get("tasso_sconto"),
        regime_vendita=p.get("regime_vendita", "RID"), om_assicurazione_quota_anno=p.get("om_assicurazione_quota_anno"),
        gestione_eur_anno=p.get("gestione_eur_anno"), costituzione_eur=p.get("costituzione_eur"),
    ), quota is None


def _grafico_proposta(proposta) -> alt.Chart:
    curva = pd.DataFrame([{"kWp": q.potenza_moduli_kwp, "minimo": q.van_consolidato_min,
                           "mediana": q.van_consolidato_mediano, "massimo": q.van_consolidato_max}
                          for q in proposta.curva])
    scelte = pd.DataFrame([{"kWp": o.punto.potenza_moduli_kwp, "mediana": o.punto.van_consolidato_mediano,
                            "opzione": o.nome} for o in proposta.opzioni])
    asse_y = alt.Y("mediana:Q", title="Beneficio complessivo su 25 anni (€)",
                   axis=alt.Axis(format=",.0f", labelExpr="replace(datum.label, /,/g, '.')"))
    banda = alt.Chart(curva).mark_area(color="#e6ac3d", opacity=0.25).encode(
        x=alt.X("kWp:Q", title="Taglia dell'impianto (kWp)"), y="minimo:Q", y2="massimo:Q")
    linea = alt.Chart(curva).mark_line(color="#1f5f6b").encode(x="kWp:Q", y=asse_y)
    punti = alt.Chart(scelte).mark_point(filled=True, size=90, color="#172026").encode(
        x="kWp:Q", y="mediana:Q", tooltip=["opzione", "kWp"])
    etichette = alt.Chart(scelte).mark_text(dy=-12, color="#172026", fontSize=12).encode(
        x="kWp:Q", y="mediana:Q", text="opzione")
    return (banda + linea + punti + etichette).properties(height=260)


class _DisegnoInItaliano(MacroElement):
    """Testi dello strumento di disegno della mappa in italiano: da aggiungere alla mappa prima di `Draw`."""

    _template = Template("""
        {% macro script(this, kwargs) %}
        L.drawLocal.draw.toolbar.buttons.polygon = "Disegna il tetto";
        L.drawLocal.draw.toolbar.actions = {title: "Annulla il disegno", text: "Annulla"};
        L.drawLocal.draw.toolbar.finish = {title: "Chiudi il tetto", text: "Fine"};
        L.drawLocal.draw.toolbar.undo = {title: "Togli l'ultimo angolo", text: "Togli l'ultimo angolo"};
        L.drawLocal.draw.handlers.polygon.tooltip = {
            start: "Clicca sul primo angolo del tetto",
            cont: "Clicca sull'angolo successivo",
            end: "Clicca sul primo angolo per chiudere, oppure premi Fine"};
        L.drawLocal.draw.handlers.polyline.error = "<strong>Attenzione:</strong> i lati non possono incrociarsi";
        L.drawLocal.edit.toolbar.buttons.remove = "Cancella il disegno";
        L.drawLocal.edit.toolbar.buttons.removeDisabled = "Niente da cancellare";
        L.drawLocal.edit.toolbar.actions.save = {title: "Conferma", text: "Fatto"};
        L.drawLocal.edit.toolbar.actions.cancel = {title: "Annulla", text: "Annulla"};
        L.drawLocal.edit.toolbar.actions.clearAll = {title: "Cancella tutto", text: "Cancella tutto"};
        L.drawLocal.edit.handlers.remove.tooltip.text = "Clicca sul disegno da cancellare";
        {% endmacro %}
    """)


def _proposta_impianto(punti_df: pd.DataFrame):
    g = ss.generale
    cer = g["tipo"] == "CER"
    st.markdown("Disegna il tetto sulla foto aerea: il simulatore calcola superficie e orientamento e propone **tre "
                "taglie** dell'impianto, con il beneficio per chi paga e per i membri. Ogni valore si può correggere; "
                "la scelta finale si fa con un installatore.")
    if cer:
        st.markdown("In una comunità energetica gli impianti possono stare su **edifici diversi**, uno per contatore. "
                    "Si procede un tetto alla volta: disegna il primo, scegli una taglia, poi cancella il disegno e "
                    "ripeti per il tetto successivo. Ogni nuova proposta tiene conto degli impianti già scelti.")
    st.subheader("Il tetto")
    with st.expander("Come disegnare il tetto, passo per passo", icon=":material/help:"):
        if VIDEO_TETTO.exists():
            c1, _ = st.columns([3, 2])  # il video non deve coprire la pagina
            c1.video(str(VIDEO_TETTO))
        st.markdown(
            "1. Premi **Apri la foto aerea**: la mappa si apre sull'indirizzo del passo 1. Se il tetto non è al centro, "
            "spostala trascinandola e ingrandisci con la rotellina o con il tasto **+**.\n"
            "2. Premi il pentagono **Disegna il tetto** a sinistra della mappa.\n"
            "3. Clicca sugli angoli del tetto, uno dopo l'altro, seguendo il bordo. Per chiudere clicca di nuovo sul "
            "primo angolo oppure premi **Fine**. Se sbagli un angolo, **Togli l'ultimo angolo**.\n"
            "4. Sotto la mappa compaiono superficie e orientamento. Per rifare il disegno usa il cestino a sinistra "
            "della mappa oppure **Cancella il disegno**.\n"
            "5. Con **Guarda in 3D su Google Earth** controlli se edifici o alberi più alti stanno a sud, est o ovest "
            "del tetto: servono a scegliere quanta ombra c'è.")
    if not ss.get("mappa_aperta"):
        if st.button("Apri la foto aerea", icon=":material/satellite_alt:"):
            ss.mappa_aperta = True
            st.rerun()
        st.caption(PRIVACY_FOTO)
    else:
        mappa = folium.Map(location=[g["lat"], g["lon"]], zoom_start=19, max_zoom=21, tiles=None, control_scale=True)
        folium.TileLayer(tiles=FOTO_AEREA_URL, attr=FOTO_AEREA_ATTRIBUZIONE, name="Foto aerea", max_native_zoom=19,
                         max_zoom=21).add_to(mappa)
        _DisegnoInItaliano().add_to(mappa)
        Draw(draw_options={"polygon": {"allowIntersection": False, "showArea": True,
                                       "shapeOptions": {"color": "#1f5f6b", "weight": 3}},
                           "polyline": False, "rectangle": False, "circle": False, "marker": False,
                           "circlemarker": False},
             edit_options={"edit": False, "remove": True}, show_geometry_on_click=False).add_to(mappa)
        risultato = st_folium(mappa, key=f"mappa_tetto_{ss.get('versione_mappa', 0)}", height=430,
                              use_container_width=True, returned_objects=["all_drawings"])
        poligoni = [d["geometry"]["coordinates"][0] for d in (risultato or {}).get("all_drawings") or []
                    if d.get("geometry", {}).get("type") == "Polygon"]
        if poligoni and poligoni[-1] != ss.get("tetto_angoli"):
            ss.tetto_angoli = poligoni[-1]
        c1, c2 = st.columns(2)
        if ss.get("tetto_angoli") and c1.button("Cancella il disegno", icon=":material/delete:"):
            ss.pop("tetto_angoli", None)
            ss.versione_mappa = ss.get("versione_mappa", 0) + 1
            st.rerun()
        c2.link_button("Guarda in 3D su Google Earth", link_google_earth(g["lat"], g["lon"]),
                       icon=":material/3d_rotation:")
        st.caption(PRIVACY_FOTO)

    angoli = ss.get("tetto_angoli")
    impronta = hashlib.sha1(str(angoli).encode()).hexdigest()[:8] if angoli else "manuale"
    c1, c2, c3 = st.columns(3)
    forma = c1.radio("Tipo di tetto", FORME, horizontal=True, index=1, key="tetto_forma",
                     help="Su un tetto piano i moduli vanno su file inclinate e distanziate")
    piani = c2.number_input("Piani dell'edificio", min_value=1, max_value=40, step=1, value=None, key="tetto_piani",
                            help="Servono a stimare le ombre degli edifici vicini")
    inclinazione = c3.number_input("Inclinazione dei moduli, gradi", min_value=0.0, max_value=60.0, step=1.0,
                                   format="%.0f", key=f"tetto_incl_{forma}", value=INCLINAZIONE[forma])
    tetto = None
    if angoli:
        try:
            tetto = tetto_disegnato(angoli, forma=forma, piani=int(piani) if piani else None, inclinazione=inclinazione,
                                    elementi_osm=ss.get("osm_elementi"))
        except ValueError as e:
            st.warning(str(e), icon=":material/draw:")

    c1, c2, c3 = st.columns(3)
    sotto = st.container()  # la scelta delle due falde, a tutta larghezza sotto i tre campi
    azimut = c2.number_input(
        "Orientamento, gradi", min_value=-180.0, max_value=180.0, step=5.0, format="%.0f",
        key=f"tetto_az_{impronta}_{forma}", value=float(tetto.azimut) if tetto else 0.0,
        help="0 = sud, -90 = est, 90 = ovest. Dal disegno si prende la falda più rivolta a sud, con il colmo lungo il "
             "lato lungo; se il colmo è sul lato corto, correggi qui. Per un tetto piano i moduli guardano a sud")
    due_falde = False
    if forma == "a falde" and est_ovest(azimut):
        due_falde = sotto.toggle(
            "Usa entrambe le falde (est e ovest)", value=True, key=f"tetto_due_falde_{impronta}",
            help="Le falde rivolte a est e a ovest rendono quasi uguali, circa l'85–90% di una falda a sud. Usarle "
                 "tutte e due raddoppia i kWp e la produzione dura di più al mattino e alla sera, quando ci sono più "
                 "consumi da condividere. Metà dei moduli va su ogni falda")
    azimut_2 = falda_opposta(azimut) if due_falde else None
    if due_falde:
        c2.caption(f"Moduli rivolti verso {_direzione(azimut)} e verso {_direzione(azimut_2)}, metà per falda")
    else:
        c2.caption(f"Moduli rivolti verso {_direzione(azimut)}")
    # anche con l'orientamento corretto a mano: le due falde coprono tutta la pianta disegnata
    da_disegno = tetto.superficie_utile_m2 * (2 if due_falde else 1) if tetto is not None else None
    superficie = c1.number_input(
        "Superficie utile del tetto, m²", min_value=0.0, max_value=20_000.0, step=10.0, format="%.0f",
        key=f"tetto_sup_{impronta}_{forma}_{inclinazione:g}_{due_falde}",
        value=float(round(da_disegno)) if da_disegno is not None else None,
        help="Parte del tetto libera da bordi, camini, lucernari e locali tecnici. Dal disegno: per un tetto a falde "
             "metà della superficie, quella della falda migliore, oppure tutta se usi entrambe le falde; il 60% per "
             "un tetto piano")
    kwp_max = (superficie or 0.0) / M2_PER_KWP[forma]
    if superficie:
        c3.markdown(f"**Circa {kwp_max:.0f} kWp installabili**  \ntra {kwp_max * 0.8:.0f} e {kwp_max * 1.2:.0f} kWp"
                    + (" sulle due falde" if due_falde else "") + ", da verificare con un installatore")
    if tetto is not None:
        c3.caption(f"Tetto disegnato: {tetto.area_terra_m2:,.0f} m² in pianta.".replace(",", "."))

    stimate = None
    if tetto is not None and ss.get("osm_elementi") is not None:
        stimate = tetto.ombre_pct_due_falde if due_falde and tetto.est_ovest else tetto.ombre_pct
    livelli = dict(LIVELLI_OMBRE)
    if stimate is not None:
        livelli = {f"Stimate dagli edifici vicini: {stimate:.1f}%".replace(".", ","): stimate} | livelli
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    scelta_ombre = c1.radio("Ombre sul tetto", list(livelli), key=f"tetto_ombre_{impronta}_{stimate}",
                            help="Energia persa in un anno per le ombre di edifici e alberi vicini")
    ombre = livelli[scelta_ombre]
    if c2.button("Stima le ombre dagli edifici vicini", icon=":material/apartment:",
                 help="Usa le altezze degli edifici su OpenStreetMap. Alberi e camini non sono considerati",
                 disabled=not angoli):
        with st.spinner("Chiedo a OpenStreetMap gli edifici vicini: al massimo mezzo minuto"):
            try:
                ss.osm_elementi = _elementi_osm(round(tetto.lat, 5) if tetto else g["lat"],
                                                round(tetto.lon, 5) if tetto else g["lon"])
                st.rerun()
            except requests.RequestException:
                st.warning("OpenStreetMap non risponde in questo momento: scegli tu il livello di ombre, aiutandoti con "
                           "la vista 3D di Google Earth.", icon=":material/cloud_off:")
    if tetto is not None and ss.get("osm_elementi") is not None:
        with st.expander("Gli edifici vicini sulla mappa", icon=":material/map:"):
            st.image(disegno_svg(tetto))  # come immagine: st.html toglie gli SVG
            st.caption("In blu petrolio il tetto disegnato, in scuro gli edifici più alti che possono fare ombra. "
                       + " ".join(tetto.note) + f" {ATTRIBUZIONE}.")

    etichette = [str(x) for x in punti_df["Punto"].dropna() if str(x).strip()]
    membri = list(dict.fromkeys(str(x) for x in punti_df["Membro"].dropna() if str(x).strip()))
    # chi di solito ospita e paga l'impianto: il condominio, oppure il Comune in una comunità energetica
    ospite = "Ente territoriale (es. Comune)" if cer else "Condominio"
    condominio = next((str(r["Membro"]) for _, r in punti_df.iterrows() if r.get("Tipo soggetto") == ospite), None)
    punto_cond = next((str(r["Punto"]) for _, r in punti_df.iterrows() if r.get("Membro") == condominio), None)
    c1, c2, c3 = st.columns(3)
    punto = c1.selectbox("Collegato al contatore", etichette, key=f"tetto_punto_{ss.versione_editor}",
                         index=etichette.index(punto_cond) if punto_cond in etichette else 0 if etichette else None,
                         help="Il contatore dell'edificio su cui sta l'impianto: lì l'energia prodotta si usa subito "
                              "(autoconsumo). Quella che avanza va in rete e, nelle ore in cui gli altri membri la "
                              "consumano, conta come energia condivisa e riceve i contributi GSE. "
                              + ("Di solito il contatore di un edificio del Comune." if cer
                                 else "Di solito quello delle parti comuni."))
    investitore = c2.selectbox("Chi paga l'impianto", membri, key=f"tetto_investitore_{ss.versione_editor}",
                               index=membri.index(condominio) if condominio in membri else 0 if membri else None)
    entrata = c3.date_input("Entrata in esercizio prevista", format="DD/MM/YYYY",
                            key=f"tetto_entrata_{g['data_costituzione']}",
                            value=entrata_predefinita(g["data_costituzione"]),
                            help="La tariffa premio spetta agli impianti in esercizio entro il 31/12/2027")

    params, provvisoria = _parametri_proposta()
    if not superficie or not punto or not investitore or entrata is None:
        st.info("Indica superficie del tetto, contatore, chi paga e data per avere la proposta.",
                icon=":material/info:")
        return
    scelta = SceltaTetto(kwp_max=round(kwp_max, 1), inclinazione=inclinazione, azimut=azimut, ombre_pct=ombre,
                         punto=punto, investitore=investitore, entrata=entrata, azimut_2=azimut_2,
                         nome=nome_impianto(g["tipo"], punto))
    altri = ss.impianti_base if cer else None  # nel condominio c'è un solo tetto: la proposta lo sostituisce
    firma = (punti_df.to_json(), tuple(sorted((k, c.model_dump_json()) for k, c in ss.curve_misurate.items())), scelta, params, _impronta_prezzi(ss.get("prezzi", {})),
             (g["lat"], g["lon"], g["regione"], g["data_costituzione"]), None if altri is None else altri.to_json(date_format="iso"))
    if st.button("Proponi tre taglie", type="primary", icon=":material/solar_power:"):
        with st.spinner("Provo diverse taglie su 3 anni di meteo e 3 livelli di prezzo: circa 15–30 secondi"):
            generale = Generale(nome=g["nome"], tipo=g["tipo"], lat=g["lat"], lon=g["lon"], regione=g["regione"],
                                indirizzo=g["indirizzo"] or None, data_costituzione=g["data_costituzione"])
            try:
                ss.proposta = {"firma": firma, "proposta": proponi(generale, punti_df, scelta, params, ss.get("prezzi"),
                                                                  quota_provvisoria=provvisoria, altri=altri,
                                                                  curve=ss.curve_misurate),
                               "altri": altri}
            except ValueError as e:
                ss.pop("proposta", None)
                st.error(str(e), icon=":material/error:")
    salvata = ss.get("proposta")
    if salvata is None:
        return
    if salvata["firma"] != firma:
        st.warning("Hai cambiato i dati dopo la proposta: premi di nuovo *Proponi tre taglie* quando hai finito.",
                   icon=":material/sync_problem:")
        return
    proposta = salvata["proposta"]
    testo_q, tono_q, spiegazione_q = QUALITA[proposta.qualita]
    st.html(f"<p>{etichetta(testo_q, tono_q)} <span style=\"color:var(--tenue)\">{escape(spiegazione_q)}. "
            f"{escape(NOTA_INTERVALLI)}</span></p>")
    colonne = st.columns(len(proposta.opzioni))
    for colonna, opzione in zip(colonne, proposta.opzioni):
        q = opzione.punto
        with colonna.container(border=True):
            titolo = etichetta(opzione.nome, "ok") if opzione.nome == "Consigliata" else f"<strong>{opzione.nome}</strong>"
            kwp_testo = f"{q.potenza_moduli_kwp:.1f}".replace(".", ",")
            st.html(f"<p>{titolo}</p><p style=\"font-size:1.5rem;font-weight:620;margin:0\">{kwp_testo} kWp</p>")
            st.markdown(f"Costo stimato **{euro(q.costo_eur)}**  \n"
                        f"Beneficio complessivo {euro(q.van_consolidato_min)} – {euro(q.van_consolidato_max)}  \n"
                        f"Ai membri circa {euro(q.euro_anno_membri)} all'anno")
            st.caption(opzione.commento)
            if not opzione.conviene_a_entrambi:
                st.caption("Con il riparto attuale non conviene a tutti e due: vedi il passo 4.")
            if st.button("Usa questa taglia", key=f"usa_{opzione.nome}", icon=":material/check:"):
                ss.impianti_base = tabella_impianto(proposta.scelta, q.potenza_moduli_kwp, salvata.get("altri"))
                ss.versione_editor += 1
                if g["tipo"] == "CER":  # pronto per il tetto del prossimo edificio
                    ss.pop("proposta", None)
                    ss.pop("tetto_angoli", None)
                    ss.versione_mappa = ss.get("versione_mappa", 0) + 1
                ss.pop("analisi", None)
                ss.taglia_scelta = f"{opzione.nome}, {q.potenza_moduli_kwp:.1f} kWp".replace(".", ",")
                st.rerun()
    st.altair_chart(_grafico_proposta(proposta))
    st.caption("La linea è il beneficio complessivo mediano per ogni taglia provata, la fascia va dal minimo al "
               "massimo degli scenari. Il costo è il massimo di riferimento del DM 414/2023, una stima alta: con un "
               "preventivo i benefici salgono.")
    for nota in proposta.note:
        st.caption(nota)


# --- passo 3 ----------------------------------------------------------------------------
with passi[2]:
    titolo_nascosto(f"Passo 3: {PASSI[3]}")
    _proposta_impianto(punti_df)
    if "taglia_scelta" in ss:
        st.success(f"Impianto impostato: {ss.pop('taglia_scelta')}. Controlla i dati qui sotto, poi vai al passo 4"
                   + (" oppure disegna il tetto di un altro edificio." if ss.generale["tipo"] == "CER" else "."),
                   icon=":material/check_circle:")
    st.subheader("Dati degli impianti" if ss.generale["tipo"] == "CER" else "Dati dell'impianto")
    st.markdown("Scegli una taglia qui sopra oppure inserisci i dati di un preventivo. Impianti fotovoltaici nuovi (in "
                "esercizio dopo il 16/12/2021), fino a 1 MW, al massimo uno per contatore.")
    etichette_punti = [str(p) for p in punti_df["Punto"].dropna().tolist() if str(p).strip()]
    membri_nomi = sorted({str(m) for m in punti_df["Membro"].dropna().tolist() if str(m).strip()})
    colonne_impianti = {
        "Impianto": st.column_config.TextColumn("Impianto", required=True),
        "Punto": st.column_config.SelectboxColumn("Collegato al contatore", options=etichette_punti + [SOLA_IMMISSIONE],
                                                  required=True),
        "kWp moduli": st.column_config.NumberColumn("kWp moduli", min_value=0.5, max_value=5000, format="%.1f"),
        "kW inverter": st.column_config.NumberColumn("kW inverter", min_value=0.5, max_value=5000, format="%.1f",
                                                     help="Se vuoto, uguale ai kWp"),
        "kWp max installabili": st.column_config.NumberColumn("kWp max sul tetto", min_value=0.5, format="%.1f",
                                                              help="Serve al dimensionamento"),
        "Inclinazione °": st.column_config.NumberColumn("Inclinazione °", min_value=0, max_value=90, default=30),
        "Orientamento °": st.column_config.NumberColumn("Orientamento °", min_value=-180, max_value=180, default=0,
                                                        help="0 = sud, -90 = est, 90 = ovest"),
        "Seconda falda °": st.column_config.NumberColumn(
            "Seconda falda °", min_value=-180, max_value=180,
            help="Solo per i moduli su due falde, di solito est e ovest: orientamento della seconda falda. Metà dei "
                 "moduli va su ogni falda. Vuoto se c'è una sola falda"),
        "Ombre %": st.column_config.NumberColumn("Ombre %", min_value=0, max_value=40, format="%.1f",
                                                 help="Energia persa per le ombre di edifici vicini. Se vuoto, nessuna"),
        "Entrata in esercizio": st.column_config.DateColumn("Entrata in esercizio", format="DD/MM/YYYY"),
        "Investitore": st.column_config.SelectboxColumn("Chi paga", options=membri_nomi + [INVESTITORE_ESTERNO]),
        "Costo da preventivo €": st.column_config.NumberColumn(
            "Costo da preventivo €", min_value=0, format="%.0f",
            help="Costo complessivo IVA esclusa (moduli, inverter, strutture, connessione, pratiche). Se vuoto si usa il "
                 "costo massimo di riferimento del DM 414/2023, una stima alta"),
        "Contributo concesso €": st.column_config.NumberColumn("Contributo concesso €", min_value=0, format="%.0f",
                                                               help="Solo se già concesso con un atto: lo sportello PNRR è chiuso"),
        "Fattore F": st.column_config.NumberColumn("Fattore F", min_value=0.0, max_value=0.5, format="%.2f",
                                                   help="Dall'atto di concessione"),
        "Estremi atto": st.column_config.TextColumn("Estremi dell'atto"),
        "Data incasso contributo": st.column_config.DateColumn("Incasso del contributo", format="DD/MM/YYYY",
                                                               help="Senza data il contributo resta fuori dal VAN"),
    }
    # colonne che servono di rado: nascoste finché non si chiedono o non contengono già un valore
    poco_usate = ["Seconda falda °", "Contributo concesso €", "Fattore F", "Estremi atto", "Data incasso contributo"]
    if not st.toggle("Mostra anche seconda falda e contributo PNRR già concesso", key=f"colonne_rare_{ss.versione_editor}",
                     value=bool(ss.impianti_base[poco_usate].notna().any().any())):
        colonne_impianti |= dict.fromkeys(poco_usate)
    impianti_df = st.data_editor(ss.impianti_base, num_rows="dynamic", column_config=colonne_impianti,
                                 key=f"impianti_editor_{ss.versione_editor}", hide_index=True)
    _avanti(3, None if len(impianti_df.dropna(how="all")) else
            "Aggiungi un impianto: scrivi nella tabella i dati di un preventivo"
            + (" oppure scegli una taglia qui sopra." if ss.generale["tipo"] == "gruppo" else "."))

# --- passo 4 ----------------------------------------------------------------------------
with passi[3]:
    titolo_nascosto(f"Passo 4: {PASSI[4]}")
    p = ss.parametri
    st.subheader("Come si dividono i contributi")
    st.markdown("I contributi GSE arrivano alla configurazione. Tolti i costi di gestione, una quota va ai **membri**, "
                "in proporzione all'energia condivisa con i loro consumi, e il resto a **chi ha pagato l'impianto**. "
                "Lo decidono statuto o contratto: non esiste una quota giusta in assoluto.")
    opzioni = {0.0: "0% ai membri", 0.5: "50% ai membri", 1.0: "100% ai membri"}
    didascalie = ["Tutto a chi investe, che recupera prima la spesa", "Metà ai membri, metà a chi investe",
                  "Tutto ai membri, che ne beneficiano di più", "Indica tu la percentuale"]
    quota_salvata = p.get("quota_membri")
    scelta = st.radio("Quota del netto ai membri", list(opzioni) + ["altro"], horizontal=True,
                      index=(list(opzioni).index(quota_salvata) if quota_salvata in opzioni else
                             (3 if quota_salvata is not None else None)),
                      format_func=lambda o: opzioni.get(o, "Altra quota"), captions=didascalie)
    if scelta == "altro":
        quota = st.slider("Quota ai membri", 0, 100, int(round((quota_salvata or 0.3) * 100)), format="%d%%") / 100
    else:
        quota = scelta
    p["quota_membri"] = quota

    st.subheader("Prezzi dell'energia")
    medie = IPOTESI.prezzi.media_eur_mwh
    st.markdown(f"Si simulano tre livelli medi: {medie['basso']:.0f}, {medie['base']:.0f} e {medie['alto']:.0f} €/MWh. "
                "Senza un file di prezzi orari il prezzo è costante e i risultati sono di qualità C. Basta un anno di "
                "prezzi orari per avere la forma reale della giornata, con i prezzi più bassi nelle ore di sole.")
    with st.expander("Carica prezzi orari, per uso personale", icon=":material/upload_file:"):
        st.caption("I dati del GME si possono usare solo per uso personale e non sono inclusi nell'app. Formato: "
                   "colonna `inizio` con data e ora e fuso orario (es. 2024-03-31T02:00:00+02:00) e una colonna per "
                   "zona (NORD, CNOR, CSUD, SUD, CALA, SICI, SARD) in €/MWh. Puoi caricare più anni: il 2021, il 2022 "
                   "e il 2023 si abbinano al meteo dello stesso anno; per gli anni senza file si usa il file più recente.")
        file_prezzi = st.file_uploader("File CSV dei prezzi, uno per anno", type=["csv"], key="file_prezzi",
                                       accept_multiple_files=True)
        prezzi_caricati = {}
        for f in file_prezzi or []:
            try:
                serie = _leggi_prezzi(f.getvalue(), f.name, ss.generale["regione"])
                if serie.year in prezzi_caricati:
                    raise ValueError(f"c'è già un file per il {serie.year}")
                prezzi_caricati[serie.year] = serie
            except ValueError as e:
                st.error(f"{f.name}: {e}")
        if prezzi_caricati:
            ss.prezzi = prezzi_caricati
            st.success("Prezzi caricati: " + "; ".join(f"{a}, zona {s.zona}, media {s.media:.0f} €/MWh"
                                                       for a, s in sorted(prezzi_caricati.items())))
        else:
            ss.pop("prezzi", None)

    with st.expander("Valori avanzati: bollette, vendita, costi e tasso di sconto", icon=":material/tune:"):
        st.caption("Sono già impostati su valori tipici: cambiali solo se hai dati migliori.")
        c1, c2, c3 = st.columns(3)
        p["costo_evitabile_eur_kwh"] = c1.number_input(
            "Risparmio in bolletta per kWh autoconsumato (€)", min_value=0.0, max_value=1.0, step=0.01,
            value=float(p.get("costo_evitabile_eur_kwh", IPOTESI.bolletta.costo_evitabile_eur_kwh)),
            help="Quota energia più oneri variabili della bolletta, non il prezzo medio totale.")
        p["tasso_sconto"] = c2.number_input(
            "Tasso di sconto reale", min_value=0.0, max_value=0.2, step=0.005, format="%.3f",
            value=float(p.get("tasso_sconto", IPOTESI.finanza.tasso_sconto_reale)),
            help="Quanto renderebbe il denaro in un altro investimento, al netto dell'inflazione: serve a confrontare "
                 "euro di anni diversi.")
        p["regime_vendita"] = c3.radio("Vendita dell'energia immessa", ["RID", "mercato"],
                                       index=0 if p.get("regime_vendita", "RID") == "RID" else 1,
                                       format_func=lambda r: "Ritiro dedicato GSE" if r == "RID" else "A un trader")
        tipo_cfg = ss.generale["tipo"]
        om_default = IPOTESI.impianto.om_quota_capex_anno + IPOTESI.impianto.assicurazione_quota_capex_anno
        st.markdown("**Costi da preventivo**")
        st.caption("Lascia vuoto per usare i valori predefiniti, indicati in grigio. Il costo di ogni impianto si "
                   "inserisce al passo 3, nella colonna *Costo da preventivo €*.")
        c1, c2, c3 = st.columns(3)
        om = c1.number_input("Manutenzione e assicurazione, % del costo all'anno", min_value=0.0, max_value=10.0,
                             step=0.1, format="%.1f", placeholder=f"{om_default:.1%}".replace(".", ","),
                             value=None if p.get("om_assicurazione_quota_anno") is None
                             else p["om_assicurazione_quota_anno"] * 100)
        p["om_assicurazione_quota_anno"] = None if om is None else om / 100
        p["gestione_eur_anno"] = c2.number_input(
            "Gestione della configurazione, €/anno", min_value=0.0, max_value=100_000.0, step=50.0, format="%.0f",
            value=p.get("gestione_eur_anno"), placeholder=euro(IPOTESI.configurazione.gestione_eur_anno[tipo_cfg]),
            help="Contabilità, piattaforma, referente")
        p["costituzione_eur"] = c3.number_input(
            "Costituzione, € una tantum", min_value=0.0, max_value=100_000.0, step=100.0, format="%.0f",
            value=p.get("costituzione_eur"), placeholder=euro(IPOTESI.configurazione.costituzione_eur[tipo_cfg]),
            help="Atto costitutivo e statuto per una CER, contratto tra i partecipanti per un gruppo")

    _avanti(4, None if p.get("quota_membri") is not None else "Scegli quanta parte dei contributi va ai membri: "
                                                                 "senza questa scelta lo scenario non si calcola.")


# --- passo 5 ----------------------------------------------------------------------------
def _parametri() -> ParametriEconomici | None:
    p = ss.parametri
    if p.get("quota_membri") is None:
        return None
    return ParametriEconomici(quota_membri=p["quota_membri"], costo_evitabile_eur_kwh=p["costo_evitabile_eur_kwh"],
                              tasso_sconto=p["tasso_sconto"], regime_vendita=p["regime_vendita"],
                              om_assicurazione_quota_anno=p.get("om_assicurazione_quota_anno"),
                              gestione_eur_anno=p.get("gestione_eur_anno"), costituzione_eur=p.get("costituzione_eur"))


def _requisiti(analisi):
    voci = "".join(
        f'<li><span>{etichetta(*STATO_ETICHETTA[stato])}</span><span><strong>{escape(nome)}</strong>. '
        f'<span class="motivo">{escape(motivo)}</span></span></li>'
        for nome, stato, motivo in requisiti(analisi, tutti=False)
    )
    st.html(f'<ul class="controlli">{voci}</ul>')


def _intervallo(minimo: float, massimo: float, formato) -> str:
    return "" if minimo == massimo else f"{formato(minimo)} – {formato(massimo)}"


def _tabella_cifre(intestazioni: list[str], righe: list[tuple[str, str, str, str]]) -> str:
    """Tabella delle cifre: voce, valore, intervallo e significato (nascosto sotto i 760 px)."""
    testa = "".join(f"<th>{escape(t)}</th>" for t in intestazioni[:-1])
    nome_intervallo = escape(intestazioni[2])  # su schermi stretti l'intestazione è nascosta: la ripete la cella
    corpo = "".join(
        f'<tr><td class="voce">{escape(voce)}</td><td class="valore">{valore}</td>'
        f'<td class="intervallo" data-etichetta="{nome_intervallo}">{intervallo}</td>'
        f'<td class="significato">{escape(significato)}</td></tr>'
        for voce, valore, intervallo, significato in righe
    )
    return (f'<table class="cifre"><thead><tr>{testa}<th class="significato">{escape(intestazioni[-1])}</th></tr>'
            f"</thead><tbody>{corpo}</tbody></table>")


def _frase(analisi):
    frase = "".join(f"<strong>{escape(t)}</strong>" if grassetto else escape(t) for t, grassetto in frase_sintesi(analisi))
    st.html(f'<p class="sintesi">{frase}</p>')


def _riquadro(voce: str, valore: str, intervallo: str) -> str:
    sotto = f"tra {intervallo.replace(' – ', ' e ')} negli scenari" if intervallo else "un solo scenario"
    return (f'<div class="riquadro"><p class="voce">{escape(voce)}</p><p class="valore">{valore}</p>'
            f'<p class="intervallo">{escape(sotto)}</p></div>')


def _cifre(analisi, nomi):
    """In alto le tre cifre chiave in riquadri, sotto la tabella completa con il significato di ognuna."""
    righe = []
    for c in cifre(analisi, nomi):
        formato = euro if c.unita == "€" else kwh
        righe.append((c.voce, formato(c.valore), _intervallo(c.minimo, c.massimo, formato), c.significato))
    st.html('<div class="riquadri">' + "".join(_riquadro(*r[:3]) for r in righe[:3]) + "</div>")
    st.html(_tabella_cifre(["Indicatore", "Valore centrale", "Intervallo degli scenari", "Che cosa significa"], righe))


def _migliorare(analisi):
    """I dati che mancano, dal più importante, con il passo in cui si inseriscono."""
    with st.container(border=True):
        st.markdown("**Come rendere la stima più precisa**")
        st.markdown(frase_precisione(analisi))
        for i, m in enumerate(dati_da_migliorare(analisi), start=1):
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.markdown(f"**{i}. {m.cosa}**  \n{m.perche}")
            if m.passo is not None:
                c2.button(f"Vai al passo {m.passo}", on_click=_vai, args=(PASSI[m.passo],), key=f"migliora_{i}",
                          type="tertiary", icon=":material/arrow_back:")


def _confronto(analisi):
    righe = [(voce, euro(0 if banda is None else banda.mediana),
              "" if banda is None else _intervallo(banda.minimo, banda.massimo, euro), descrizione)
             for voce, banda, descrizione in confronto(analisi)]
    st.html(f'<p class="sintesi">{escape(frase_confronto(analisi))}</p>' + _tabella_cifre(
        ["Alternativa", "Beneficio netto su 25 anni", "Intervallo degli scenari", "Che cosa comprende"], righe))


with passi[4]:
    titolo_nascosto(f"Passo 5: {PASSI[5]}")
    g = ss.generale
    esito = configurazione_da_tabelle(Generale(nome=g["nome"], tipo=g["tipo"], lat=g["lat"], lon=g["lon"],
                                               regione=g["regione"], indirizzo=g["indirizzo"] or None,
                                               data_costituzione=g["data_costituzione"]), punti_df, impianti_df,
                                      base=ss.get("config_base"), curve=ss.curve_misurate)
    params = _parametri()
    if esito.config is not None:
        slot_salva.download_button("Salva il lavoro", esporta_json(esito.config, ss.parametri),
                                   file_name="configurazione_cer.json", mime="application/json",
                                   icon=":material/download:", width="stretch",
                                   help="Scarica un file da ricaricare in seguito")
    else:
        slot_salva.caption("*Salva il lavoro* sarà disponibile quando i dati dei passi 2 e 3 sono completi.")
    if esito.errori:
        st.markdown("**Prima del calcolo restano da completare:**")
        st.markdown("\n".join(f"- {e}" for e in esito.errori))
        c1, c2, _ = st.columns([1, 1, 2])
        with c1:
            _vai_a(PASSI[2], "Torna al passo 2")
        with c2:
            _vai_a(PASSI[3], "Torna al passo 3")
    elif not esito.config.plants:
        st.markdown("Manca l'impianto: aggiungilo al passo 3, oppure prova con l'esempio di Torino.")
        _vai_a(PASSI[3], "Torna al passo 3")
    elif params is None:
        st.markdown("Manca una scelta: come dividere i contributi tra i membri e chi paga l'impianto.")
        _vai_a(PASSI[4], "Torna al passo 4")
    else:
        config = esito.config
        firma = (config.model_dump_json(), tuple(sorted(ss.parametri.items())), _impronta_prezzi(ss.get("prezzi", {})))
        calcola = st.button("Calcola lo scenario", type="primary", icon=":material/play_arrow:")
        if calcola:
            with st.spinner("Simulo 25 anni ora per ora, con 3 anni meteo, 3 livelli di prezzo e 3 profili di consumo"):
                ss.analisi = analizza(config, params, ss.get("prezzi"))
                ss.firma_analisi = firma
                ss.pop("dimensionamento", None)
        analisi = ss.get("analisi")
        if analisi is None:
            st.caption("Il calcolo richiede pochi secondi. I risultati restano solo in questa sessione.")
        elif ss.get("firma_analisi") != firma:
            # i risultati di dati diversi non si mostrano: tornano visibili se si ripristinano gli stessi dati
            st.warning("I dati sono cambiati dopo l'ultimo calcolo: premi di nuovo *Calcola lo scenario* per vedere "
                       "i risultati aggiornati.", icon=":material/sync_problem:")
            analisi = None
        if analisi is not None:
            nomi = nomi_leggibili(analisi.config)
            rep = analisi.report

            if not analisi.supportata:
                st.error("Questa configurazione non è supportata in questa versione:\n\n- " + "\n- ".join(rep.non_supportati),
                         icon=":material/block:")
                st.stop()

            st.html('<h2 style="margin:1.25rem 0 .25rem">Risultati</h2>')
            if analisi.economia_disabilitata:
                st.error(analisi.economia_disabilitata, icon=":material/gavel:")
            _frase(analisi)  # prima la frase che si può ripetere, poi quanto è affidabile, poi le cifre
            testo_q, tono_q, spiegazione_q = QUALITA[analisi.qualita]
            prezzi_usati = "" if analisi.economia_disabilitata else " Prezzi usati: " + "; ".join(fonti_prezzi(analisi)) + "."
            st.html(f'<p style="max-width:72ch">{etichetta(testo_q, tono_q)} '
                    f'<span style="color:var(--tenue)">{escape(spiegazione_q)}. '
                    f"{NOTA_INTERVALLI}{escape(prezzi_usati)}</span></p>")
            if not analisi.economia_disabilitata:
                _cifre(analisi, nomi)
            _migliorare(analisi)

            st.subheader("Porta i risultati in assemblea")
            if ss.get("report", {}).get("firma") != firma:  # una sola generazione per calcolo
                with st.spinner("Preparo il report e il file Excel"):
                    ss.report = {"firma": firma, "pdf": report_pdf(analisi, params), "xlsx": report_excel(analisi, params)}
            c1, c2, _ = st.columns(3)
            c1.download_button("Scarica il report PDF", ss.report["pdf"], file_name="scenario_cer.pdf",
                               mime="application/pdf", icon=":material/picture_as_pdf:", on_click="ignore",
                               width="stretch",
                               help="3 o 4 pagine da proiettare o stampare: cifre con intervallo, requisiti, grafici, "
                                    "chi paga e chi riceve, ipotesi e avvertenze")
            c2.download_button("Scarica i dati in Excel", ss.report["xlsx"], file_name="scenario_cer.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               icon=":material/table_view:", on_click="ignore", width="stretch",
                               help="Riepilogo, per membro, flussi di cassa anno per anno, tutti i movimenti e manifest")
            st.caption("Il report riporta lo scenario calcolato qui. Come i risultati, è uno scenario preliminare.")

            if not analisi.economia_disabilitata:
                st.subheader("Conviene costituire la configurazione?")
                _confronto(analisi)

            st.subheader("Requisiti")
            _requisiti(analisi)
            with st.expander("Da verificare con un professionista"):
                st.markdown("\n".join(f"- {v}" for v in rep.da_verificare))

            yr = anno_rappresentativo(analisi.energia_base)
            st.subheader("Come si comporta l'energia")
            grafici = st.tabs(["Giorno tipo", "Mese per mese", "Flussi di cassa", "Sensibilità", "Dimensionamento"])
            with grafici[0]:
                mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
                        "settembre", "ottobre", "novembre", "dicembre"]
                mese = st.select_slider("Mese", options=list(range(1, 13)), value=6, format_func=lambda m: mesi[m - 1])
                dati_giorno = giorno_tipo(yr, mese)
                serie = list(dati_giorno.columns)
                # la descrizione è l'alternativa testuale del grafico: il lettore di schermo la legge al posto
                # delle linee, che restano nascoste (aria=False); la stessa frase è anche in didascalia
                descrizione = (f"Energia media ora per ora in un giorno di {mesi[mese - 1]}. " + "; ".join(
                    f"{s}: massimo {dati_giorno[s].max():.1f} kWh alle {int(dati_giorno[s].idxmax())}".replace(".", ",")
                    for s in serie) + ".")
                lunga = dati_giorno.reset_index().melt("ora", var_name="Serie", value_name="kWh")
                st.altair_chart(alt.Chart(lunga, description=descrizione).mark_line(aria=False, strokeWidth=2).encode(
                    x=alt.X("ora:Q", title="ora del giorno", scale=alt.Scale(domain=[0, 23])),
                    y=alt.Y("kWh:Q", title="kWh medi"),
                    color=alt.Color("Serie:N", sort=serie, legend=alt.Legend(title=None, orient="bottom"),
                                    scale=alt.Scale(domain=serie, range=[COLORI_GRAFICI[s] for s in serie])),
                    tooltip=[alt.Tooltip("ora:Q", title="Ora"), alt.Tooltip("Serie:N", title="Serie"),
                             alt.Tooltip("kWh:Q", title="kWh medi", format=".1f")],
                ))
                st.caption(descrizione + " I valori esatti sono in *Mostra i dati*, in alto a destra del grafico.")
            with grafici[1]:
                st.bar_chart(mensile(yr), y_label="kWh", color=["#b44e2e", "#c5d0d6", "#4b9779"])
                st.caption("Energia di ogni mese dell'anno, divisa come nella legenda. I valori esatti sono in "
                           "*Mostra i dati*, in alto a destra del grafico.")
            if not analisi.economia_disabilitata:
                with grafici[2]:
                    st.line_chart(cassa_cumulata(analisi.base), y_label="€ cumulati, non attualizzati",
                                  color=["#1f5f6b", "#b44e2e"])
                    st.caption("Sotto lo zero l'investimento non è ancora ripagato.")
                with grafici[3]:
                    righe = []
                    for v in analisi.sensibilita:
                        righe += [{"parametro": v.parametro, "variazione": v.variazione, "estremo": "valore basso",
                                   "VAN": v.van_consolidato_basso},
                                  {"parametro": v.parametro, "variazione": v.variazione, "estremo": "valore alto",
                                   "VAN": v.van_consolidato_alto}]
                    dati = pd.DataFrame(righe)
                    if not dati.empty:
                        base_van = analisi.base.kpi.van_consolidato
                        dati["VAN €"] = dati["VAN"].map(euro)
                        punti_migliaia = "replace(datum.label, /,/g, '.')"  # 26,000 → 26.000
                        grafico = alt.Chart(dati).mark_bar(height=18).encode(
                            x=alt.X("VAN:Q", title="Beneficio netto della configurazione (€)", scale=alt.Scale(zero=False),
                                    axis=alt.Axis(format=",.0f", labelExpr=punti_migliaia)),
                            x2=alt.datum(base_van),
                            y=alt.Y("parametro:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
                            color=alt.Color("estremo:N", title="Valore del parametro",
                                            scale=alt.Scale(range=["#314968", "#e6ac3d"])),
                            tooltip=[alt.Tooltip("parametro", title="Parametro"), alt.Tooltip("variazione", title="Variazione"),
                                     alt.Tooltip("estremo", title="Valore"), alt.Tooltip("VAN €", title="Beneficio netto")],
                        ).properties(height=44 * len(analisi.sensibilita) + 40)
                        st.altair_chart(grafico)
                        st.caption(f"Ogni barra parte dal beneficio netto dello scenario base, {euro(base_van)} (meteo "
                                   f"{analisi.base.scenario.anno_meteo}, prezzo base), e arriva al valore con il parametro "
                                   "basso o alto. In alto i parametri che contano di più. Il valore centrale della tabella in "
                                   "cima è invece la mediana di tutti gli scenari, per questo può differire di poco.")
                with grafici[4]:
                    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
                    plant_id = c1.selectbox("Impianto da dimensionare", [p_.id for p_ in analisi.config.plants],
                                            format_func=lambda i: next(p_.nome for p_ in analisi.config.plants if p_.id == i))
                    if c2.button("Calcola la curva", icon=":material/show_chart:"):
                        with st.spinner("Provo diverse taglie"):
                            ss.dimensionamento = dimensiona(analisi.config, plant_id, params, analisi.pv,
                                                            ss.get("prezzi") or {}, scenari_dimensionamento(analisi),
                                                            n_punti=8)
                    dim = ss.get("dimensionamento")
                    if dim is None:
                        st.caption("La curva prova diverse taglie dell'impianto, fino al massimo installabile sul tetto.")
                    else:
                        curva = pd.DataFrame([{"kWp": q.potenza_moduli_kwp,
                                               "Beneficio della configurazione": q.van_consolidato_mediano,
                                               "Beneficio di chi investe": q.van_investitore_mediano,
                                               "Non investire": 0.0} for q in dim.curva])
                        st.line_chart(curva.set_index("kWp"), y_label="€", color=["#1f5f6b", "#b44e2e", "#87939a"])
                        st.caption(dim.dicitura)

                st.subheader("Chi paga e chi riceve")
                st.caption(f"Scenario base, anno {anno_rappresentativo(analisi.base.energia).year}.")
                st.dataframe(chi_riceve_cosa(analisi.base, nomi).style.format({"€": euro}), hide_index=True)
                per_membro = pd.DataFrame([{"Membro": nomi[m], "Netto nell'anno": v}
                                           for m, v in analisi.base.kpi.euro_anno_per_membro.items()])
                st.dataframe(per_membro.style.format({"Netto nell'anno": euro}), hide_index=True)
                st.caption("Netto per membro: quota dei contributi, risparmio in bolletta e vendite, meno i costi "
                           "sostenuti. Per chi investe comprende anche la sua quota e le spese dell'impianto.")

            st.subheader("Avvertenze")
            st.markdown("\n".join(f"- {a}" for a in avvertenze(analisi)))
            with st.expander("Dettagli tecnici della simulazione"):
                st.json(analisi.energia_base.manifest)
