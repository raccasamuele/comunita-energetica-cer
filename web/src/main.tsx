import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { SchedaFamiglia } from "./scheda/SchedaFamiglia";
import { apreLaScheda } from "./scheda/scheda";
import "@fontsource/poppins/400.css";
import "@fontsource/poppins/500.css";
import "@fontsource/poppins/600.css";
import "./stile/casa.css";
import "./stile/cer.css";

const App = lazy(() => import("./App"));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* chi riceve il link per i consumi (?modulo=famiglia) vede solo la sua scheda, senza il motore */}
    {apreLaScheda() ? <SchedaFamiglia /> : <Suspense fallback={<p className="app" role="status">Apertura della comunità energetica…</p>}><App /></Suspense>}
  </StrictMode>,
);
