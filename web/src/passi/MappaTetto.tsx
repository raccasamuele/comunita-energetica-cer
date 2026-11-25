// La foto aerea del passo 3, con il disegno del tetto: un clic per ogni angolo, poi si chiude cliccando sul primo
// angolo o con "Chiudi il tetto". Leaflet si carica solo qui (import pigro da Impianti.tsx), quando si apre la mappa.
// Il disegno resta in questo browser; la foto arriva dai server di Esri.

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export type Angolo = [number, number]; // [lon, lat], come GeoJSON e come cersim.tetto.tetto_disegnato

export default function MappaTetto(props: {
  lat: number;
  lon: number;
  angoli: Angolo[];
  chiuso: boolean;
  aggiungi: (a: Angolo) => void;
  chiudi: () => void;
  urlFoto: string;
  attribuzione: string;
}) {
  const contenitore = useRef<HTMLDivElement>(null);
  const mappa = useRef<L.Map | null>(null);
  const disegno = useRef<L.LayerGroup | null>(null);
  const azioni = useRef(props);
  azioni.current = props;

  useEffect(() => {
    const m = L.map(contenitore.current!, { center: [props.lat, props.lon], zoom: 19, maxZoom: 21, keyboard: true });
    L.tileLayer(props.urlFoto, { maxNativeZoom: 19, maxZoom: 21, attribution: props.attribuzione }).addTo(m);
    L.control.scale({ imperial: false }).addTo(m);
    m.attributionControl.setPrefix(false);
    disegno.current = L.layerGroup().addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => {
      if (!azioni.current.chiuso) azioni.current.aggiungi([e.latlng.lng, e.latlng.lat]);
    });
    mappa.current = m;
    return () => {
      m.remove();
      mappa.current = null;
    };
    // la mappa si crea una volta: luogo e foto sono quelli dell'apertura
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const gruppo = disegno.current;
    if (!gruppo) return;
    gruppo.clearLayers();
    const punti = props.angoli.map(([lon, lat]) => L.latLng(lat, lon));
    const stile = { color: "#5b21b6", weight: 3 };
    if (props.chiuso && punti.length >= 3) L.polygon(punti, { ...stile, fillOpacity: 0.25 }).addTo(gruppo);
    else if (punti.length >= 2) L.polyline(punti, { ...stile, dashArray: "6 6" }).addTo(gruppo);
    punti.forEach((p, i) => {
      const primo = i === 0 && !props.chiuso && punti.length >= 3;
      const angolo = L.circleMarker(p, {
        radius: primo ? 9 : 6, color: "#ffffff", weight: 2, fillColor: "#5b21b6", fillOpacity: 1, bubblingMouseEvents: false,
      }).addTo(gruppo);
      if (primo) {
        angolo.bindTooltip("Clicca qui per chiudere il tetto", { direction: "top" });
        angolo.on("click", () => azioni.current.chiudi());
      }
    });
  }, [props.angoli, props.chiuso]);

  return <div ref={contenitore} className="mappa-tetto" role="application" aria-label="Foto aerea: clicca sugli angoli del tetto per disegnarlo" />;
}
