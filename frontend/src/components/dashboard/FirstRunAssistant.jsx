import { Fragment, useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import { useAuth } from "../../auth/authContext";
import { useActivationContext } from "../../hooks/activationContext";
import { Icon } from "../icons";

// Hitos de READINESS: pacientes → datos de la clínica → servicios. El onboarding mide
// "clínica lista para operar", NO "ya usó el sistema" — por eso NO incluye cita ni
// consulta (dependen de que llegue un cliente real y mantendrían el onboarding activo
// días; ver dashboard_activation: `completed` = has_patients AND has_clinic_contact AND
// has_services). Se completa en la primera sesión (3-5 min). Cada paso se deriva de la
// EXISTENCIA real (endpoint activation/), nunca de un flag. `done` = etiqueta de la
// micro-celebración.
//
// ORDEN (no reordenar sin justificar): abre con PACIENTES, que es donde está el valor
// visible — nunca con un formulario. Luego IDENTIDAD (contacto) y al final CONFIGURACIÓN
// OPERATIVA: el servicio cierra como final de readiness (decisión previa, preservada).
const STEPS = [
  {
    key: "has_patients",
    title: "Agrega tu primer paciente",
    lead: "Importa tu clínica desde Excel o registra el primero a mano.",
    done: "Primer paciente agregado",
    actions: [
      { label: "Agregar paciente", to: "/pets", variant: "primary" },
      { label: "Importar desde Excel", to: "/imports", perm: "import.create", variant: "link" },
    ],
  },
  {
    // Señal = `Organization.phone`. Es el número que el asistente de WhatsApp da en
    // su plantilla de URGENCIA: sin él, un cliente que reporta una emergencia recibe
    // "acude de inmediato a la clínica" sin a dónde llamar.
    key: "has_clinic_contact",
    title: "¿Cómo pueden encontrarte tus clientes?",
    lead: "El teléfono al que te llaman, el WhatsApp por el que te escriben y la dirección a la que llegan. Es lo que el asistente les comparte cuando preguntan cómo llegar — y el número que da si hay una emergencia.",
    done: "Datos de tu clínica listos",
    actions: [{ label: "Capturar datos de la clínica", to: "/config", section: "clinic", variant: "primary" }],
  },
  {
    key: "has_services",
    title: "Configura tus servicios",
    lead: "Consulta, vacunación, estética… lo que ofrece tu clínica.",
    done: "Servicios configurados",
    actions: [{ label: "Configurar servicios", to: "/config", section: "services", variant: "primary" }],
  },
];

// ── Previews del módulo (columna derecha, no interactivas) ────────────────────
// Representaciones simplificadas y elegantes del resultado de cada paso — no son
// mockups ni capturas reales. Puramente decorativas (la columna va `aria-hidden`).
const PV_PATIENTS = [
  { name: "Max", meta: "Perro · Labrador" },
  { name: "Luna", meta: "Gato · Siamés" },
  { name: "Rocky", meta: "Perro · Bulldog" },
];
const PV_SERVICES = [
  { name: "Consulta", price: "$350" },
  { name: "Vacunación", price: "$250" },
  { name: "Cirugía", price: "$1,200" },
  { name: "Estética", price: "$400" },
  { name: "Desparasitación", price: "$180" },
];
const PV_CLINIC = [
  { label: "Teléfono", value: "55 1234 5678" },
  { label: "WhatsApp", value: "55 1234 5678" },
  { label: "Dirección", value: "Av. Reforma 120, Centro" },
];

const PreviewPatients = () => (
  <div className="fp-pv">
    <span className="fp-pv-label">Pacientes</span>
    <div className="fp-pv-rows">
      {PV_PATIENTS.map((p) => (
        <div key={p.name} className="fp-pv-row">
          <span className="fp-pv-avatar">{p.name[0]}</span>
          <span className="fp-pv-name">{p.name}</span>
          <span className="fp-pv-meta">{p.meta}</span>
        </div>
      ))}
    </div>
  </div>
);

const PreviewServices = () => (
  <div className="fp-pv">
    <span className="fp-pv-label">Servicios</span>
    <div className="fp-pv-rows">
      {PV_SERVICES.map((s) => (
        <div key={s.name} className="fp-pv-row fp-pv-row--between">
          <span className="fp-pv-name">{s.name}</span>
          <span className="fp-pv-price">{s.price}</span>
        </div>
      ))}
    </div>
  </div>
);

const PreviewClinic = () => (
  <div className="fp-pv">
    <span className="fp-pv-label">Datos de tu clínica</span>
    <div className="fp-pv-rows">
      {PV_CLINIC.map((f) => (
        <div key={f.label} className="fp-pv-row fp-pv-row--between">
          <span className="fp-pv-field">{f.label}</span>
          <span className="fp-pv-value">{f.value}</span>
        </div>
      ))}
    </div>
  </div>
);

const STEP_PREVIEW = {
  has_patients: PreviewPatients,
  has_clinic_contact: PreviewClinic,
  has_services: PreviewServices,
};

/**
 * Barra de progreso conectada (estilo Stripe): nodos unidos por tramos. Comunica
 * continuidad, no pasos independientes. No verbaliza "Paso N de N".
 */
const Progress = ({ activation, currentIndex }) => {
  const doneCount = STEPS.filter((s) => activation[s.key]).length;
  return (
    <div
      className="firstrun-progress"
      role="progressbar"
      aria-label="Progreso de configuración"
      aria-valuemin={0}
      aria-valuemax={STEPS.length}
      aria-valuenow={doneCount}
    >
      {STEPS.map((s, i) => {
        const done = !!activation[s.key];
        const prevDone = i > 0 && !!activation[STEPS[i - 1].key];
        return (
          <Fragment key={s.key}>
            {i > 0 && <span className={`fp-track${prevDone ? " is-filled" : ""}`} />}
            <span
              className={`fp-node${done ? " is-done" : ""}${i === currentIndex ? " is-current" : ""}`}
            />
          </Fragment>
        );
      })}
    </div>
  );
};

/**
 * FirstRunAssistant — experiencia de primer uso (estilo Linear/Notion/Stripe).
 *
 * Overlay full-screen que reemplaza el dashboard mientras la clínica no complete los
 * hitos de readiness (paciente + servicio). Muestra UN SOLO paso a la vez (el primer
 * hito incompleto), con jerarquía tipográfica (sin cajas/bordes). Al completar
 * desaparece para siempre.
 *
 * Dueño de TODA la lógica de UI del onboarding (celebración, cierre, animaciones).
 * El `ActivationProvider` es solo la fuente de verdad — ver su docstring.
 *
 * Gate por CAPABILITY (`service.create`), no por rol: el onboarding representa el
 * setup de la clínica; un VET/ASISTENTE no debe ver CTAs a lugares sin permiso.
 */
const FirstRunAssistant = ({ onComplete }) => {
  const { activation } = useActivationContext();
  const { can, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const prefersReduced = useReducedMotion();

  // Paso recién completado → micro-celebración. El signal llega por router state
  // desde el auto-redirect del módulo (createPet/Service/Appointment). No es estado
  // persistente: se consume una vez y se limpia.
  const [celebrateKey, setCelebrateKey] = useState(null);
  // Momento de cierre al completar readiness (paciente + servicio).
  const [closing, setClosing] = useState(false);
  const [fadeOut, setFadeOut] = useState(false);
  const closedRef = useRef(false);
  // Latch: ¿este montaje llegó a mostrar un paso incompleto? Solo entonces el cierre
  // tiene sentido (evita mostrar "tu clínica ya está lista" a una clínica ya activada).
  const sawStepRef = useRef(false);

  const gated = !can?.("service.create");

  // Consumir el signal de celebración una sola vez y limpiar el router state. El
  // timer de auto-ocultado vive en OTRO effect (keyed en celebrateKey): si estuviera
  // aquí, el re-render que provoca el propio `navigate` limpiaría el timer.
  useEffect(() => {
    const step = location.state?.onboardingStep;
    if (!step) return;
    // El signal PRUEBA que el usuario venía del flujo de onboarding. Levantar el latch
    // aquí (además de en el render de un paso) hace que el cierre sea robusto al
    // desmontaje/re-montaje del módulo: si al volver la activación YA está completa
    // (no hay paso que renderizar), el latch igual permite disparar el momento final.
    sawStepRef.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- consume una señal de un solo uso que llega por el estado del router
    setCelebrateKey(step);
    navigate(location.pathname, { replace: true, state: {} });
  }, [location.state, location.pathname, navigate]);

  // Auto-ocultar la celebración.
  useEffect(() => {
    if (!celebrateKey) return;
    const t = setTimeout(() => setCelebrateKey(null), 1600);
    return () => clearTimeout(t);
  }, [celebrateKey]);

  // Detectar la TRANSICIÓN a completado (solo si este montaje llegó a ver un paso
  // incompleto → no dispara en una clínica ya activada). Sin timer aquí (evita que un
  // refetch de activation lo cancele); el timeline de cierre vive en otro effect.
  useEffect(() => {
    if (gated || !activation) return;
    if (activation.completed && sawStepRef.current && !closedRef.current) {
      closedRef.current = true;
      setClosing(true);
    }
  }, [activation, gated]);

  // Timeline del cierre: momento (~1 s) → fade + onComplete.
  useEffect(() => {
    if (!closing) return;
    const t = setTimeout(() => {
      setFadeOut(true);
      onComplete?.();
    }, prefersReduced ? 0 : 1000);
    return () => clearTimeout(t);
  }, [closing, onComplete, prefersReduced]);

  // Tras el fade del overlay, desmontar.
  useEffect(() => {
    if (!fadeOut) return;
    const t = setTimeout(() => setClosing(false), prefersReduced ? 0 : 450);
    return () => clearTimeout(t);
  }, [fadeOut, prefersReduced]);

  if (gated || !activation) return null;
  if (activation.completed && !closing) return null;

  const currentIndex = STEPS.findIndex((s) => !activation[s.key]);
  const current = currentIndex >= 0 ? STEPS[currentIndex] : null;
  // eslint-disable-next-line react-hooks/refs -- latch que solo pasa de false a true; no cambia lo que se renderiza
  if (current) sawStepRef.current = true;

  const orgName = user?.organization_name;
  // `section` deep-linkea dentro de /config (Clínica vs Servicios): sin esto ambos
  // CTAs caían en la sección por defecto y el usuario tenía que buscar la correcta.
  const go = ({ to, section }) =>
    navigate(to, { state: { fromOnboarding: true, ...(section ? { section } : {}) } });

  // Entrada orquestada (escalonada). `useReducedMotion` desactiva todo el movimiento.
  const ease = [0.22, 0.61, 0.36, 1];
  const enter = (delay = 0) =>
    prefersReduced
      ? { initial: false }
      : {
          initial: { opacity: 0, y: 12 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.5, delay, ease },
        };
  const enterX = (delay = 0) =>
    prefersReduced
      ? { initial: false }
      : {
          initial: { opacity: 0, x: 16 },
          animate: { opacity: 1, x: 0 },
          exit: { opacity: 0, x: -10 },
          transition: { duration: 0.5, delay, ease },
        };
  const blockExit = prefersReduced ? {} : { exit: { opacity: 0, y: -8 }, transition: { duration: 0.3, ease } };

  // Solo en el estado de "paso" mostramos progreso, ETA y la preview del módulo.
  const showStep = !closing && !celebrateKey && !!current;
  const Preview = current ? STEP_PREVIEW[current.key] : null;

  return (
    <motion.div
      className="dash-firstrun"
      initial={prefersReduced ? false : { opacity: 0 }}
      animate={{ opacity: fadeOut ? 0 : 1 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      {/* Marca discreta: ancla la pantalla como producto (no un formulario). */}
      <motion.div className="firstrun-brand" {...enter(0.05)}>
        <Icon.Stethoscope s={18} c="var(--c-primary)" />
        <span>SaaslyVet</span>
      </motion.div>

      <div className="firstrun-shell">
        {/* Columna izquierda: el flujo (idéntico). El objetivo domina la jerarquía. */}
        <div className="firstrun-main">
          <motion.header className="firstrun-welcome" {...enter(0.12)}>
            <h1 className="firstrun-hello">Hola{orgName ? `, ${orgName}` : ""}</h1>
            <p className="firstrun-sub">Terminemos de poner tu clínica en marcha.</p>
          </motion.header>

          <AnimatePresence mode="wait">
            {closing ? (
              <motion.div key="closing" className="firstrun-closing" initial={false} {...blockExit}>
                <motion.p className="firstrun-closing-title" {...enter(0.04)}>Todo listo.</motion.p>
                <motion.p className="firstrun-closing-org" {...enter(0.14)}>
                  {orgName ? `${orgName} ya está lista.` : "Tu clínica está lista para comenzar."}
                </motion.p>
                <span className="firstrun-check" aria-hidden="true">✓</span>
              </motion.div>
            ) : celebrateKey ? (
              <motion.div key={`cel-${celebrateKey}`} className="firstrun-celebrate" initial={false} {...blockExit}>
                <span className="firstrun-check" aria-hidden="true">✓</span>
                <motion.span {...enter(0.12)}>{STEPS.find((s) => s.key === celebrateKey)?.done}</motion.span>
              </motion.div>
            ) : current ? (
              <motion.div key={current.key} className="firstrun-step" initial={false} {...blockExit}>
                <motion.span className="firstrun-eyebrow" {...enter(0.04)}>Primeros pasos</motion.span>
                <motion.h2 className="firstrun-step-title" {...enter(0.12)}>{current.title}</motion.h2>
                <motion.p className="firstrun-lead" {...enter(0.2)}>{current.lead}</motion.p>
                <motion.div className="firstrun-actions" {...enter(0.28)}>
                  {current.actions
                    .filter(
                      (a) =>
                        (!a.perm || can?.(a.perm)) &&
                        !(user?.is_demo && a.to === "/imports")
                    )
                    .map((a) =>
                      a.variant === "link" ? (
                        <button key={a.label} className="firstrun-link" onClick={() => go(a)}>
                          {a.label}
                        </button>
                      ) : (
                        <button
                          key={a.label}
                          className="btn btn-primary btn-md firstrun-cta"
                          onClick={() => go(a)}
                        >
                          {a.label}
                        </button>
                      )
                    )}
                </motion.div>
              </motion.div>
            ) : null}
          </AnimatePresence>

          {showStep && (
            <>
              <motion.div {...enter(0.36)}>
                <Progress activation={activation} currentIndex={currentIndex} />
              </motion.div>
              <motion.p className="firstrun-eta" {...enter(0.44)}>
                Menos de 3 minutos para comenzar.
              </motion.p>
            </>
          )}
        </div>

        {/* Columna derecha: preview elegante del módulo (focal, no interactiva). */}
        <div className="firstrun-aside" aria-hidden="true">
          <AnimatePresence mode="wait">
            {showStep && Preview && (
              <motion.div key={current.key} className="firstrun-preview" {...enterX(0.16)}>
                <Preview />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
};

export default FirstRunAssistant;
