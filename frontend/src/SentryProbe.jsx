// TEMP P1-7 SENTRY PROBE — DELETE after validation. Do NOT keep in production.
// Throws on render so the wrapping ErrorBoundary catches it, reports to Sentry
// via captureException (with componentStack), and shows the event_id to the user.
// Reachable only by navigating to /__sentry_debug__ (auth-gated by PrivateRoute).
//
// Cleanup: delete this file + remove its import and route in src/App.jsx, rebuild.
export default function SentryProbe() {
  throw new Error("P1-7 Sentry frontend probe — intentional crash, safe to ignore.");
}
