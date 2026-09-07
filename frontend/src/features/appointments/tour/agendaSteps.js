/**
 * Recorrido de Agenda — datos de los pasos + cita demo. Narrativa: la visita de un
 * paciente (Luna) EN VIVO sobre la UI real. Cada paso resalta un elemento real vía
 * `target` (selector CSS) y su `onEnter(actions)` maneja la página (abrir el formulario,
 * inyectar la cita demo, abrir el modal de detalle real…). Glosario es-MX.
 */
// Se versiona para que quienes ya completaron el recorrido anterior reciban
// automáticamente la explicación de la nueva agenda.
export const AGENDA_TOUR_KEY = "agenda_tour_seen_v2";

const DEMO_ID = "__demo__";

function todayStr() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Cita demo con la forma de una cita real — se inyecta SOLO en el estado local del grid
// (nunca se envía al backend) y se limpia al terminar. `public_id="__demo__"` la marca.
export function makeDemoLuna() {
  return {
    id: DEMO_ID,
    public_id: DEMO_ID,
    date: todayStr(),
    start_time: "09:00:00",
    end_time: "09:30:00",
    status: "scheduled",
    reason: "Vacunación",
    pet_name: "Luna",
    owner_name: "María García",
    veterinarian: null,
    veterinarian_name: "Dr. Ramírez",
    pet_is_generic: false,
    pet_public_id: DEMO_ID,
    walk_in: false,
  };
}

// Slot demo para resaltar el chip del formulario (paso "Crear cita").
function makeDemoSlot() {
  return { date: new Date(), hour: 9, label: "Hoy · 09:00" };
}

export function buildAgendaSteps(actions) {
  const {
    setWeekOffset,
    setSelectedSlot,
    setViewAppt,
    setTourDemoAppt,
    setCalendarView = () => {},
    goToToday = () => {},
    openCreateModal = () => {},
    closeCreateModal = () => {},
  } = actions;
  const demo = makeDemoLuna();
  const clearAll = () => {
    setViewAppt(null);
    setTourDemoAppt(null);
    setSelectedSlot(null);
    closeCreateModal();
  };

  return [
    {
      target: null,
      tag: "Recorrido",
      title: "Acompañemos a Luna",
      body: "En menos de un minuto conocerás la nueva Agenda: filtra, encuentra un horario y gestiona la visita de Luna.",
      onEnter: () => { clearAll(); setCalendarView("month"); },
    },
    {
      target: "[data-tour='agenda-filters']",
      tag: "Filtros",
      title: "Encuentra lo que necesitas",
      body: "Busca por mascota, cliente o motivo. También puedes filtrar por veterinario, estado y categoría; los filtros se mantienen en todas las vistas.",
      onEnter: () => { clearAll(); setCalendarView("month"); },
    },
    {
      target: "[data-tour='agenda-calendar']",
      tag: "Calendario",
      title: "Elige un día y horario",
      body: "Navega con las flechas y pulsa una celda disponible para preparar una cita. Las citas existentes se abren para consultar su detalle.",
      onEnter: () => { clearAll(); setCalendarView("month"); setWeekOffset(0); goToToday(); },
    },
    {
      target: "[data-tour='agenda-past-dates']",
      tag: "Fechas protegidas",
      title: "No se agenda en el pasado",
      body: "Las fechas pasadas no se pueden seleccionar. Al pasar sobre ellas se distinguen del resto y, si intentas abrirlas, verás un aviso.",
      onEnter: () => { clearAll(); setCalendarView("month"); },
    },
    {
      target: "[data-tour='agenda-create-modal']",
      tag: "Nueva cita",
      title: "Todo ocurre en un modal",
      body: "Desde “Nueva cita” o una celda disponible, eliges el horario, la mascota, el motivo y la categoría sin salir del calendario.",
      onEnter: () => { clearAll(); setCalendarView("month"); openCreateModal(makeDemoSlot()); },
    },
    {
      target: "[data-tour='agenda-calendar']",
      tag: "Vistas",
      title: "Cambia la perspectiva",
      body: "Usa Día para revisar la jornada, Semana para los horarios, Mes para la planeación general y Lista para consultar el historial visible.",
      onEnter: () => { clearAll(); setCalendarView("month"); },
    },
    {
      target: "[data-tour='agenda-list']",
      tag: "Lista",
      title: "Consulta por fecha",
      body: "La Lista agrupa las citas por día y pagina los resultados. Puedes volver a Día, Semana o Mes desde el selector superior.",
      onEnter: () => { clearAll(); setCalendarView("list"); },
    },
    {
      target: "[data-tour='agenda-walkin']",
      tag: "Sin cita",
      title: "Atención sin cita",
      body: "Si un paciente llega sin cita previa, su atención empieza de inmediato sin ocupar un horario en el calendario.",
      onEnter: () => { clearAll(); setCalendarView("month"); },
    },
    {
      target: "[data-tour='agenda-appt-demo']",
      tag: "Su cita",
      title: "Llegó el día de Luna",
      body: "En Semana, cada cita ocupa su horario real. Pulsa una para revisar la información y continuar con la atención.",
      onEnter: () => { clearAll(); setCalendarView("week"); setWeekOffset(0); goToToday(); setTourDemoAppt(demo); },
    },
    {
      target: "[data-tour='agenda-detail']",
      tag: "Detalle",
      title: "Toda la información, en un lugar",
      body: "El detalle reúne paciente, cliente, veterinario, horario y estado. Desde ahí también puedes editar o crear una cita relacionada.",
      onEnter: () => { closeCreateModal(); setCalendarView("week"); setTourDemoAppt(demo); setViewAppt(demo); },
    },
    {
      target: "[data-tour='agenda-attend']",
      tag: "Atender",
      title: "Inicia la consulta",
      body: "Con un clic pasas de la cita a la consulta médica. El estado avanza de Programada a En consulta y después a Completada.",
      onEnter: () => { setViewAppt(demo); },
    },
    {
      target: null,
      tag: "Listo",
      title: "Consulta completada",
      body: "Ya conoces lo esencial de la nueva Agenda: filtrar, navegar, crear citas y atender pacientes con o sin cita previa.",
      onEnter: () => { clearAll(); setCalendarView("month"); },
    },
  ];
}
