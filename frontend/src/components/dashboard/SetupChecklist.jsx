import { useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/authContext";
import { Icon } from "../icons";

// Hitos de arranque en orden de producto: pacientes → servicios → cita → consulta.
// Cada paso se deriva de la EXISTENCIA real (endpoint activation/), no de un flag.
const STEPS = [
  {
    key: "has_patients",
    icon: Icon.PawPrint,
    title: "Agrega o importa tus pacientes",
    desc: "El núcleo de tu clínica. Importa tu Excel anterior o agrega el primero.",
    actions: [
      { label: "Importar Excel", to: "/imports", perm: "import.create", variant: "secondary" },
      { label: "Agregar paciente", to: "/pets", variant: "primary" },
    ],
  },
  {
    key: "has_services",
    icon: Icon.Settings,
    title: "Configura tus servicios",
    desc: "Define lo que cobras (consulta, vacunación…) para poder facturar.",
    actions: [{ label: "Ir a Configuración", to: "/config", variant: "primary" }],
  },
  {
    key: "has_appointments",
    icon: Icon.CalendarClock,
    title: "Agenda tu primera cita",
    desc: "Programa una cita o registra una atención sin cita previa.",
    actions: [{ label: "Ir a Citas", to: "/appointments", variant: "primary" }],
  },
  {
    key: "has_consultations",
    icon: Icon.FileHeart,
    title: "Registra una consulta",
    desc: "Abre el historial clínico y documenta la atención.",
    actions: [{ label: "Ir a Historial", to: "/medical-records", variant: "primary" }],
  },
];

/**
 * Checklist de activación del primer uso. Se muestra en el dashboard mientras la
 * clínica no haya completado los cuatro hitos; se oculta solo cuando todos están
 * en True (estado real, sin localStorage ni flag por usuario).
 */
const SetupChecklist = ({ activation }) => {
  const navigate = useNavigate();
  const { can } = useAuth();

  // El checklist representa el SETUP INICIAL DE LA CLÍNICA, no el onboarding
  // individual de un usuario. Solo debe verlo quien puede configurar la clínica:
  // un VET/ASISTENTE no debe ver CTAs hacia lugares sin permiso (ej. /config).
  // Gateamos por CAPABILITY, nunca por `role === "ADMIN"`. Usamos
  // `service.create` como proxy: representa el acceso a la configuración inicial
  // (catálogo de servicios en /config) y hoy lo tiene ADMIN pero no VET/ASSISTANT.
  // No existe una capability única dedicada a "ajustes de la organización" (ese
  // endpoint usa HybridPermission genérico), por eso service.create es el proxy
  // más representativo disponible.
  if (!can?.("service.create")) return null;

  if (!activation || activation.completed) return null;

  const doneCount = STEPS.filter((s) => activation[s.key]).length;

  return (
    <section className="card setup-checklist">
      <div className="setup-head">
        <div>
          <h2 className="setup-title">Pon en marcha tu clínica</h2>
          <p className="setup-sub">Completa estos pasos para empezar a operar.</p>
        </div>
        <span className="setup-progress">{doneCount} de {STEPS.length}</span>
      </div>

      <ol className="setup-steps">
        {STEPS.map((step, i) => {
          const done = !!activation[step.key];
          const StepIcon = step.icon;
          return (
            <li key={step.key} className={`setup-step${done ? " is-done" : ""}`}>
              <span className="setup-marker">
                {done ? (
                  <Icon.CheckCircle s={20} c="var(--c-success-text)" />
                ) : (
                  <span className="setup-num">{i + 1}</span>
                )}
              </span>
              <div className="setup-body">
                <div className="setup-step-title">
                  <StepIcon s={15} c={done ? "var(--c-text-3)" : "var(--c-primary)"} />
                  <span>{step.title}</span>
                </div>
                {!done && (
                  <>
                    <p className="setup-step-desc">{step.desc}</p>
                    <div className="setup-actions">
                      {step.actions
                        .filter((a) => !a.perm || can?.(a.perm))
                        .map((a) => (
                          <button
                            key={a.to}
                            className={`btn btn-${a.variant || "secondary"} btn-sm`}
                            onClick={() => navigate(a.to)}
                          >
                            {a.label}
                          </button>
                        ))}
                    </div>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
};

export default SetupChecklist;
