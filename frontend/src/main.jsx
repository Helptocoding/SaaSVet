import React from "react";
import ReactDOM from "react-dom/client";
import * as Sentry from "@sentry/react";
import "./index.css";
import App from "./App";
import { scrubEvent } from "./utils/sentryScrub";

// Sentry — si VITE_SENTRY_DSN no está definida, init() no hace nada.
// Obtener DSN en https://sentry.io → tu proyecto → Settings → Client Keys
if (import.meta.env.VITE_SENTRY_DSN) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    // P1-5 A4: separa prod/staging/dev en Sentry. Default al modo de Vite.
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE,
    // P1-5 A4/A5: agrupa issues por deploy y habilita la resolución de source
    // maps subidos con el mismo release. Patrón: SHA git corto del build.
    release: import.meta.env.VITE_SENTRY_RELEASE || undefined,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: 0.2,
    // P1-5 A4: scrubbing de privacidad — nunca enviar PII clínica/financiera.
    beforeSend: scrubEvent,
    // Propagar traces a requests hacia el backend (dev + prod)
    tracePropagationTargets: [
      "localhost",
      "127.0.0.1",
      /^https:\/\/api\./,  // ajustar al dominio de producción
    ],
  });
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <App />
);