/**
 * Recorrido de Agenda — datos de los pasos + cita demo. Narrativa: la visita de un
 * paciente (Luna) EN VIVO sobre la UI real. Cada paso resalta un elemento real vía
 * `target` (selector CSS) y su `onEnter(actions)` maneja la página (abrir el formulario,
 * inyectar la cita demo, abrir el modal de detalle real…). Glosario es-MX.
 */
export const AGENDA_TOUR_KEY = "agenda_tour_seen";

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
  const { setWeekOffset, setSelectedSlot, setViewAppt, setTourDemoAppt } = actions;
  const demo = makeDemoLuna();
  const clearAll = () => { setViewAppt(null); setTourDemoAppt(null); setSelectedSlot(null); };

  return [
    {
      target: null,
      tag: "Recorrido",
      title: "Acompañemos a Luna",
      body: "Llegó Luna a la clínica. En menos de un minuto verás cómo funciona tu Agenda acompañando su visita.",
      onEnter: () => { clearAll(); },
    },
    {
      target: "[data-tour='agenda-calendar']",
      tag: "Calendario",
      title: "Tu calendario",
      body: "Aquí ves las citas del día y navegas entre fechas con las flechas.",
      onEnter: () => { setViewAppt(null); setTourDemoAppt(null); setWeekOffset(0); },
    },
    {
      target: "[data-tour='agenda-form']",
      tag: "Crear cita",
      title: "Crea una cita",
      body: "La mayoría de tus citas empiezan aquí: eliges el horario, la mascota y el motivo.",
      onEnter: () => { setViewAppt(null); setSelectedSlot(makeDemoSlot()); },
    },
    {
      target: "#new-appt-pet",
      tag: "Búsqueda",
      title: "Busca a la mascota",
      body: "Escribe el nombre y las coincidencias aparecen al instante — sin cargar toda la lista.",
    },
    {
      target: "[data-tour='agenda-quickadd']",
      tag: "Registro rápido",
      title: "¿Paciente nuevo?",
      body: "Regístralo aquí mismo, sin salir de la Agenda: cliente, mascota y cita en un solo paso.",
    },
    {
      target: "[data-tour='agenda-walkin']",
      tag: "Sin cita",
      title: "Atención sin cita",
      body: "Si un paciente llega sin cita previa, su atención empieza de inmediato, sin ocupar un horario.",
      onEnter: () => { setSelectedSlot(null); },
    },
    {
      target: "[data-tour='agenda-appt-demo']",
      tag: "Su cita",
      title: "Llegó el día de Luna",
      body: "El día de su visita, Luna aparece en la agenda lista para pasar a consulta.",
      onEnter: () => { setViewAppt(null); setWeekOffset(0); setTourDemoAppt(demo); },
    },
    {
      target: "[data-tour='agenda-detail']",
      tag: "Detalle",
      title: "El detalle de la cita",
      body: "Toda su información en un lugar: mascota, cliente y veterinario.",
      onEnter: () => { setTourDemoAppt(demo); setViewAppt(demo); },
    },
    {
      target: "[data-tour='agenda-attend']",
      tag: "Atender",
      title: "Atiéndela ahora",
      body: "Con un clic pasas de la cita a su consulta médica. Su estado avanza: Programada → En consulta → Completada.",
      onEnter: () => { setViewAppt(demo); },
    },
    {
      target: null,
      tag: "Listo",
      title: "Consulta completada",
      body: "Ya conoces lo esencial de Agenda. Conforme uses el sistema irás descubriendo funciones más avanzadas, como la atención sin cita o dar de alta pacientes nuevos.",
      onEnter: () => { clearAll(); },
    },
  ];
}
