"""
agent/clinic_context.py — Datos de clínica y horario para el agente (ADR p53).

Fuente ÚNICA de verdad: la configuración de clínica que edita el ADMIN en
`/config` — `Organization` (identidad, contacto, ubicación) y
`OrganizationSchedule` (horario semanal). No hay segunda fuente.

`AgentSettings.business_hours` existió como fallback mientras la pantalla de
Configuración no estaba conectada; se eliminó al comprobar que sí lo está
(`config/ScheduleSection.jsx` → `PUT /organizations/schedule/`). Dos superficies
que escriben el horario significaban que un ADMIN podía configurarlo en un lado
y el agente usar el otro.

`AgentSettings.faq_facts` sobrevive SOLO para hechos que no tienen campo propio
(estacionamiento, aviso de privacidad…): el serializer rechaza las claves que
duplican la configuración de clínica.

Es DEFENSIVO por diseño: cualquier fallo leyendo la config no puede tumbar una
conversación en vivo.
"""
_WD_LABEL = {1: 'lun', 2: 'mar', 3: 'mié', 4: 'jue', 5: 'vie', 6: 'sáb', 7: 'dom'}


def _hhmm(t):
    return t.strftime('%H:%M') if t else ''


def _schedule_rows(organization):
    """{weekday(1-7): OrganizationSchedule} de la org, o {} si no hay/ falla."""
    try:
        from apps.organizations.models import OrganizationSchedule
        return {r.weekday: r for r in
                OrganizationSchedule.objects.filter(organization=organization)}
    except Exception:
        return {}


def weekday_ranges(organization, weekday_index):
    """[[open, close]…] de un día (weekday_index 0=lunes) para el scheduling.

    Respeta `is_closed` y el descanso (que produce dos ventanas). Sin filas de
    horario → lista vacía: el agente dice que no tiene huecos, jamás inventa un
    horario (G1)."""
    rows = _schedule_rows(organization)
    row = rows.get(weekday_index + 1)  # OrganizationSchedule: 1=lunes
    if row is None or row.is_closed or not (row.opens_at and row.closes_at):
        return []
    opens, closes = _hhmm(row.opens_at), _hhmm(row.closes_at)
    if row.has_break and row.break_start and row.break_end:
        return [[opens, _hhmm(row.break_start)],
                [_hhmm(row.break_end), closes]]
    return [[opens, closes]]


_WD_KEY = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def effective_business_hours(organization, agent_settings=None):
    """Horario semanal como dict `{'mon': [[open, close], …], …}`.

    Punto único para todas las superficies que preguntan "¿estamos abiertos?"
    (slots, aviso de fuera de horario, saludo). `agent_settings` se acepta por
    compatibilidad de firma y ya no influye.
    """
    if not _schedule_rows(organization):
        # Sin horario configurado: dict vacío → `is_open_now` devuelve None y
        # el caller NO antepone el aviso de cierre. Distinto de "configurado
        # pero cerrado hoy", que sí debe avisar.
        return {}
    return {key: weekday_ranges(organization, index)
            for index, key in enumerate(_WD_KEY)}


def clinic_phone(organization, agent_settings=None):
    """Teléfono público de la clínica (config de clínica). Lo usa la plantilla
    de urgencia, la de mayor riesgo del sistema."""
    return clinic_facts(organization).get('teléfono', '')


def humanize_schedule(organization):
    """'lun 09:00 a 14:00; mar …' desde OrganizationSchedule, o None si no hay."""
    rows = _schedule_rows(organization)
    if not rows:
        return None
    parts = []
    for wd in range(1, 8):
        row = rows.get(wd)
        if row is None or row.is_closed or not (row.opens_at and row.closes_at):
            continue
        if row.has_break and row.break_start and row.break_end:
            span = (f"{_hhmm(row.opens_at)} a {_hhmm(row.break_start)} y "
                    f"{_hhmm(row.break_end)} a {_hhmm(row.closes_at)}")
        else:
            span = f"{_hhmm(row.opens_at)} a {_hhmm(row.closes_at)}"
        parts.append(f"{_WD_LABEL[wd]} {span}")
    return '; '.join(parts) if parts else None


def clinic_facts(organization):
    """Datos identitarios/contacto/ubicación desde Organization (config nueva).
    Solo incluye lo que está capturado — nunca inventa (G1). Defensivo ante
    campos ausentes si la migración p53 no corrió."""
    facts = {}
    try:
        get = lambda f: (getattr(organization, f, '') or '').strip()
        if get('phone'):
            facts['teléfono'] = organization.phone
        if get('whatsapp'):
            facts['whatsapp'] = organization.whatsapp
        if get('email'):
            facts['correo'] = organization.email
        if get('website'):
            facts['sitio_web'] = organization.website
        addr = ', '.join(p for p in (
            get('address_line1'), get('address_line2'), get('district'),
            get('city'), get('state'), get('postal_code'),
        ) if p)
        if addr:
            facts['dirección'] = addr
        if get('google_maps_url'):
            facts['mapa'] = organization.google_maps_url
        if get('arrival_instructions'):
            facts['indicaciones'] = organization.arrival_instructions
    except Exception:
        return {}
    return facts
