/** Attribuzione chiesta dalla licenza ODbL di OpenStreetMap, con il collegamento alla pagina dei diritti
 * (https://osmfoundation.org/wiki/Licence/Attribution_Guidelines): va accanto a ogni dato che ne deriva. */
export const URL_COPYRIGHT_OSM = "https://www.openstreetmap.org/copyright";

export function CreditiOsm({ cosa }: { cosa: string }) {
  return (
    <span className="small muted crediti-osm">
      {cosa}{" "}
      <a href={URL_COPYRIGHT_OSM} target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>, licenza ODbL.
    </span>
  );
}
