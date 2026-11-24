# Auditoría de producto — Módulo Equipo

**Fecha:** 2026-11-23
**Tipo:** auditoría de producto, madurez y benchmark (no es plan de implementación ni ADR)
**Alcance:** `frontend/src/pages/staff.jsx`, app `backend/apps/users`, RBAC y uso del equipo en
Citas, Historial clínico, agente de WhatsApp, Inbox y Caja.
**Relación:** actualiza [`analisis-modulo-equipo-2026-11-19.md`](analisis-modulo-equipo-2026-11-19.md),
que quedó parcialmente obsoleto tras el [plan Equipo](plan-equipo-corregir-revertir-2026-11-19.md).

Leyenda: **[E]** verificado en código · **[D]** solo documentación · **[I]** inferencia ·
**NV** no verificado.

---

## 1. Resumen ejecutivo

- Equipo = **gestor de cuentas de acceso sólido y seguro**. Todavía no es gestor de equipo clínico.
- Madurez general: **2.3/5 (Básico alto / Intermedio bajo)**. Seguridad y ciclo de vida ≈ Avanzado;
  supervisión, disponibilidad y operación clínica ≈ Deficiente/Básico.
- Suficiente para clínica de 1–3 personas con dueño que administra. Corto cuando: recepción agenda,
  el agente de WhatsApp agenda, alguien cambia de puesto, falta un veterinario.
- Brecha con el mercado no es "más pantallas". Son 3 conceptos que los competidores modelan y
  SaaSLyVet no: **función clínica separada del permiso**, **disponibilidad por profesional**,
  **estado de acceso visible**.
- **Ningún P0 de seguridad en Equipo.** Posible P0 operativo vecino: Citas deja a recepción en modo
  lectura por chequeo de rol.

---

## 2. Estado actual reconstruido

### Backend [E]

| Pieza | Estado |
|---|---|
| Modelo `User` | `role` (ADMIN/VET/ASSISTANT), nombre, correo único global sin distinguir mayúsculas, `specialty` (texto libre), `license_number` (5–10 dígitos, CHECK en DB), `is_active`, `password_must_change`, `password_temp_issued_at`, `session_version`. `date_joined`/`last_login` heredados pero **no expuestos**; `last_login` **nunca se actualiza** (sin `UPDATE_LAST_LOGIN` en `SIMPLE_JWT`). Sin teléfono, título, función clínica, fecha ni autor de baja. |
| Endpoints | `GET /staff/` (`?archived=true` exige `staff.reactivate`; `?role=` sin uso en UI) · `POST` alta · `PATCH` solo nombre/apellido/correo/especialidad/cédula (otra clave → 400) · `DELETE` = desactivar · `POST reset-password/` (temporal 24 h, `no-store`) · `POST reactivate/` |
| Servicios | Desactivar, reactivar, restablecer y editar en `services.py` con bloqueo ordenado y re-chequeo. **El alta no pasa por servicio**: vive en `CreateEmployeeSerializer.create` y no emite evento. |
| Invariantes | No autodesactivarse; último ADMIN activo (INV-J, locks por pk); tokens previos invalidados (ADR p65); 404-as-403 para otra clínica, ADMIN_SAAS y cuentas de servicio; semillas de la demo protegidas (salvo en reactivar). |
| RBAC | 6 códigos `staff.*`, todos sensibles, solo ADMIN. VET y ASSISTANT: `staff.list`. Roles = listas literales (ADR p63). `Role`/`UserRole` existen en DB, **sin UI ni API** para editarlos. **Rol inmutable tras el alta.** |
| Auditoría | Eventos JSON a stdout: `STAFF_DEACTIVATED`, `STAFF_REACTIVATED`, `ADMIN_PASSWORD_RESET_ISSUED`, `STAFF_PROFILE_UPDATED`. **Sin `STAFF_CREATED`.** Nada persistido ni visible en producto. |
| Pruebas | ~256 métodos en `users/tests` (ciclo de vida, concurrencia del último ADMIN, versión de sesión, gates estáticos). El alta tiene poca cobertura propia. |

### Frontend [E] (`pages/staff.jsx`)

- Tabla de 7 columnas: Nombre (+«Tú»), @usuario, Correo, Rol, Especialidad, Cédula y 3 botones
  visibles por fila (Editar, Restablecer, Desactivar).
- Segmento Activos/Inactivos (si `staff.reactivate`) con acción Reactivar.
- Alta en modal de 8 campos; **el ADMIN inventa la contraseña inicial**.
- Modal de edición (identidad + datos profesionales, aviso al cambiar correo) y modal de contraseña
  temporal con copia de credenciales (bien resuelto).
- Usa `can()`, `handleFormError`, `useConfirm`, skeleton. 22 pruebas.
- Falta: búsqueda, orden, ficha del integrante, estado de acceso, conteos, descripción de roles,
  guarda de acción en curso por fila.
- El menú lateral muestra Equipo solo a quien gestiona personal, pero la ruta `/staff` no se
  bloquea: VET/ASSISTANT por URL ven correos y cédulas de colegas (vía `staff.list`).

### Integración con otros módulos [E]

| Módulo | Cómo usa Equipo | Problema |
|---|---|---|
| Citas | Lista activos con rol VET o ADMIN; filtro por veterinario; VET fijo a sí mismo | `canCreate = user.role !== "ASSISTANT"` (`appointments.jsx:1039`) → recepción en «Modo lectura» aunque RBAC le da `appointment.create`. `canEdit` también por rol. Al crear, la API acepta como veterinario a cualquier usuario activo de la clínica (no valida rol; la UI filtra). |
| Agente WhatsApp | Solo `role='VET'` (`agent/tools.py:1015`, `appointments/creation.py:158`, `appointments/mutations.py:200`) | ADMIN que atiende es invisible al agente → `no_vet` en clínica cuyo único veterinario es el dueño. |
| Historial clínico | Modifica/cierra el VET asignado o un ADMIN; el firmante exige cédula; nombre y cédula se copian al cerrar | Un ADMIN que atiende descubre la falta de cédula al cerrar la consulta, no en Equipo. |
| Disponibilidad | Solo `OrganizationSchedule` (horario de la clínica) | Sin ausencias ni horario por veterinario: se agenda a quien está de vacaciones. |
| Desactivar | No revisa nada | Citas futuras quedan asignadas a inactivo; el diálogo solo dice «revisa en Citas». |
| Inbox | `assignable-users` por `agentinbox.send` | Correcto. |

### Discrepancias documentación ↔ código

- `system-reference.md` (§1, 403 al dispensar): «asignarlo… desde la sección de Roles» → **esa
  sección no existe**.
- `analisis-modulo-equipo-2026-11-19.md`: ya resueltos `can()`, `handleFormError`, reactivación,
  edición de identidad; la paleta de colores por veterinario ya se retiró. Siguen vigentes los
  hallazgos de Citas/ASSISTANT, agente/ADMIN, impacto de baja y estado de acceso.
- `frontend.md` (tabla de rutas) dice que `/staff` es «por capacidad»: solo lo es el ítem del menú,
  no la ruta.

---

## 3. Score de madurez

Escala: 1 Deficiente · 2 Básico · 3 Intermedio · 4 Avanzado · 5 Profesional.

| Dimensión | Nivel | Limitación principal | Impacto en la clínica | Para subir un nivel |
|---|---|---|---|---|
| Gestión de personal | 3 Intermedio | Sin cambio de rol; el correo único impide recrear a la persona | Ascender a una asistente a ADMIN es imposible | Cambio de rol con guardas |
| Identidad profesional | 2 Básico | Sin función clínica ni título; especialidad en texto libre | Agenda, agente y firma deducen la función del rol | Marca «atiende pacientes» + título |
| Organización del equipo | 2 Básico | 7 columnas que solo dicen quién existe | Suficiente para 2–15 personas, pero no informa nada más | Columnas útiles (acceso, datos profesionales) |
| Roles y responsabilidades | 2 Básico | Rol inmutable, sin explicación en UI, mezcla permisos y función | Admin asigna a ciegas; dueño-vet como ADMIN fuera del agente | Descripción de roles + función separada |
| Permisos | 3 Intermedio | No configurables (decisión correcta para el segmento) | Ninguno relevante | No subir (§10) |
| Operación clínica | 2 Básico | 3 módulos deciden por `role` | Recepción sin agendar; agente sin el dueño-vet | Una sola fuente de «quién atiende» |
| Agenda y disponibilidad | 1 Deficiente | Solo horario de clínica | Citas imposibles de atender, peor con agente | Ausencias por veterinario |
| Colaboración | 2 Básico | Solo asignación en Inbox | No es carencia real | — |
| Supervisión | 1 Deficiente | No se sabe quién entró, quién no activó, temporales por vencer | Cuentas dormidas, altas olvidadas | Columna «Acceso» |
| Auditoría | 2 Básico | Solo stdout; alta sin evento; sin fecha de baja | «¿Quién desactivó a X y cuándo?» sin respuesta en producto | Eventos persistidos + historial mínimo |
| UX/UI | 2.5 | Poca información útil, 3 botones por fila, errores de edición en toast | Se percibe como «lista de usuarios» | Rediseño de tabla (§8) |
| Escalabilidad | 2 Básico | Sin búsqueda ni paginación | Irrelevante con menos de 20 personas | Búsqueda solo con más de 20 |
| Seguridad | 4 Avanzado | Sin MFA; admin conoce la contraseña inicial; política de 8 caracteres | Riesgo bajo | Contraseña generada |
| Integración | 2 Básico | Rol, capacidad y flag usados de forma inconsistente | Comportamientos distintos según pantalla | Función clínica única |
| Autonomía operativa | 3 Intermedio | Cambiar rol requiere tocar la base | Tickets de soporte ante cambios de puesto | Cambio de rol en UI |

**General: 2.3/5.** Base técnica Avanzada; producto Básico.

---

## 4. Fortalezas comprobadas

1. **Ciclo de vida reversible.** Desactivar revoca también los access tokens vigentes, nada se
   borra, reactivar emite temporal. En revocación supera lo que documentan los competidores.
2. **Siempre queda un ADMIN.** Invariante protegido con bloqueos y probado forzando el entrelazado.
3. **Aislamiento multi-tenant consistente** y sin escalación: rol y organización no escribibles
   desde el cliente; ADMIN_SAAS y agente fuera de la superficie.
4. **Cédula validada y copiada a documentos cerrados**: editar a una persona no reescribe la
   historia clínica.
5. **Disciplina del frontend**: `can()`, confirmaciones, modal de credenciales de un solo uso.
6. Cobertura de pruebas del ciclo de vida alta, con gates estáticos.

---

## 5. Debilidades y problemas

| # | Problema | Tipo | Prioridad |
|---|---|---|---|
| D1 | Recepción no puede agendar desde la UI porque Citas decide por rol | [E], fuera de Equipo | **P0 si no es intencional** |
| D2 | Rol inmutable; correo único impide recrear a la persona | [E] | P1 |
| D3 | Función clínica deducida del rol; ADMIN que atiende no existe para el agente | [E] | P1 (P0 antes de abrir la escritura del agente) |
| D4 | Cero visibilidad del estado de acceso | [E] | P1 |
| D5 | El ADMIN elige la contraseña inicial | [E] | P1 |
| D6 | Se desactiva sin ver citas futuras, consultas abiertas ni caja | [E] | P1 |
| D7 | Alta sin servicio ni evento de auditoría | [E] | P2 |
| D8 | Sin ausencias por veterinario | [E] | P2 (P1 con agente activo) |
| D9 | Selector de rol sin explicar qué permite cada uno | [E] | P2 |
| D10 | Errores de edición en toast; empty state antiguo en activos; sin guarda de acción en curso | [E] | P2 |
| D11 | Tabla de 7 columnas; `.table-wrap` con `overflow:hidden` y sin reglas móviles en `staff.module.css` | [E] / [I] recorte no probado en navegador | P2 |
| D12 | `/staff` abierto por URL para VET/ASSISTANT | [E] | P3 |
| D13 | `reactivate_staff` no protege las semillas de la demo | [E] (hallazgo abierto previo) | P3 |

---

## 6. Benchmark de competidores

Los competidores venden a hospitales y grupos en EE. UU. y Europa; SaaSLyVet a clínicas pequeñas en
México. **La comparación no es homogénea.**

| Producto | Confirmado | Inferido | No verificado |
|---|---|---|---|
| ezyVet (IDEXX) | Roles de permisos configurables; roles predefinidos en sitios nuevos; permisos específicos para editar roles; alta = cuenta básica + roles; calendario («calendar resource») por usuario; «planning guides» definen disponibilidad; reasignación masiva de citas a otro recurso; monitoreo de inicios de sesión (IP, navegador); change log por registro; cuentas se deshabilitan, no se borran | La disponibilidad por persona alimenta la reserva en línea (Vello) | Registro de cambios administrativos sobre cuentas |
| Provet Cloud | Crear/editar/archivar/restaurar; archivar cierra sesiones; contraseña por enlace al correo o manual; **work role** (Veterinarian/Support/Administrative/Technical) separado del **permission group** (4 por defecto + personalizados); solo el work role Veterinarian es agendable y responsable de consultas; ID veterinario, ID prescriptor, título, cualificaciones, áreas de experiencia visibles en calendario; locums limitados a fechas y sedes; expiración de cuenta; permisos por sede; facturación por usuario | — | Horario o turnos por usuario |
| Vetspire | Admin > Staff: Users + User Roles; rol obligatorio; migración del interruptor «Administrator» a permisos granulares (2025–26); correo de verificación con enlace de 72 h; posición en agenda, límites de tipos de cita, activo/inactivo; permiso para bloquear edición de agenda | Turnos de disponibilidad por clínico (artículo de un tercero) | — |
| Digitail | Solo Administrator gestiona usuarios; roles = colecciones de permisos, personalizables salvo Administrator; roles por sede; horario individual o el de la clínica; descansos bloquean reservas; **turnos generados automáticamente desde el horario de la clínica**; tope de turnos para medio tiempo | — | Tipo «veterinario» con reglas propias |
| Shepherd | Roles por defecto + personalizados por puesto; ~40 permisos; el alta requiere acceso a Roles | — | Disponibilidad por persona |
| Covetrus Pulse | — | Existe capacitación «Employee Setup & Management» | Roles, permisos, horarios: **NV** |
| Okvet / QVET (LatAm) | — | «Control de empleados» en fichas comerciales | Roles y agenda por veterinario: **NV** |

### Patrones aplicables (no para copiar)

- **Separar «qué puede hacer» de «qué función cumple»** (Provet). Resuelve D3 directamente.
- **Disponibilidad por excepción**: el horario de la clínica como base y la persona solo registra lo
  que cambia (Digitail, ezyVet). Evita capturar horarios completos en clínicas pequeñas.
- **Activación sin que el admin conozca la contraseña** (Provet, Vetspire).
- **Visibilidad de inicios de sesión** (ezyVet).
- Roles personalizados: universales en ese mercado, pero pensados para equipos de 20 a 200 personas.

---

## 7. Matriz SaaSLyVet vs. mercado

| Capacidad | SaaSLyVet | Referencia | Nivel de mercado | Brecha | Prioridad |
|---|---|---|---|---|---|
| Baja reversible con cierre de sesiones | Sí, robusta | Provet, ezyVet | Estándar | Ninguna (mejor en revocación) | — |
| Activación sin contraseña conocida por el admin | No | Provet, Vetspire | Estándar | Media | P1 (generada) / P3 (enlace) |
| Cambio de rol | No | Todos | Estándar | Alta | P1 |
| Función clínica separada del permiso | No (rol) | Provet | Estándar avanzado | Alta | P1 |
| Explicación de cada rol | No | ezyVet, Shepherd | Estándar | Media | P2 |
| Roles personalizados | No (ADR p63) | Los 5 verificados | Estándar en el segmento grande | No aplica | P4 |
| Identificadores profesionales | Cédula | Provet: ID vet, prescriptor, título, cualificaciones | Estándar | Baja | P3 (título) |
| Disponibilidad / ausencias por profesional | No | ezyVet, Digitail | Estándar | Alta | P2 → P1 |
| Monitoreo de acceso | No | ezyVet | Avanzado | Media | P1 (versión mínima) |
| Auditoría de cambios de cuenta | Solo stdout | ezyVet (change log de registros) | Intermedio | Media | P2 |
| Multi-sede, locums, expiración de cuenta | No (ADR p48) | Provet, Digitail | Avanzado | No aplica | P4 |
| MFA | No | NV | — | — | P3 |

---

## 8. Brechas de UX/UI

Percepción actual: **«SaaS funcional»**, todavía no «SaaS profesional».

| Cambio | Por qué |
|---|---|
| Columnas de 7 a 5: **Integrante** (nombre, correo debajo, «Tú») · **Rol** · **Datos profesionales** (especialidad · cédula, chip «Sin cédula: no puede firmar») · **Acceso** · ⋯ | @usuario ya no identifica el login (ADR p48); especialidad y cédula ocupan dos columnas casi vacías; la tabla cabe en móvil |
| Columna **Acceso**: «Pendiente de primer acceso», «Temporal · vence en 6 h», «Último acceso hace 3 días», «Inactivo desde 12-nov» | Hoy no hay forma de saberlo; convierte la lista en equipo supervisado |
| «Editar» visible; Restablecer y Desactivar en menú ⋯ con texto | 3 botones por fila, uno rojo, en todas las filas |
| Selector de rol con una línea de qué permite cada uno, derivada de la lista real de permisos | El ADMIN asigna a ciegas |
| Alta: correo primero, usuario sugerido desde el correo, **sin campo de contraseña** (se genera y se muestra con el modal existente) | Elimina el campo más débil del flujo |
| Errores de edición en el campo (no en toast); `EmptyState` en activos; fila deshabilitada mientras corre una acción | Coherencia con el contrato del frontend |
| Subtítulo «6 activos · 1 inactivo · 1 pendiente de primer acceso» | Lectura en un vistazo |

Sin StatTiles, sin tarjetas, sin búsqueda: con 2 a 15 personas no aportan.

---

## 9. Funcionalidades recomendadas

Ordenadas por valor real.

1. **Estado de acceso.** Activar `UPDATE_LAST_LOGIN`; exponer `password_must_change`,
   `password_temp_issued_at`, `last_login` y `date_joined` solo a quien tenga `staff.update`.
   Complejidad baja, sin migración. [I] Verificar antes que `update_last_login` conviva con el
   `save()` restringido de `User` (usa `update_fields=['last_login']`).
2. **Contraseña inicial generada por el sistema**, reutilizando `_issue_temporary_password` y su
   modal. Complejidad baja. Decidir si la inicial caduca.
3. **Impacto antes de desactivar**: citas futuras, consultas abiertas, caja abierta, con enlace a la
   agenda filtrada. Cada dominio expone su conteo (frontera entre dominios). Complejidad media-baja.
4. **Cambio de rol + función clínica en un solo ADR.** Servicio atómico (`role` + `UserRole` +
   `bump_session_version` + INV-J) y marca «atiende pacientes» que leen agenda, agente, firma y
   obligatoriedad de cédula. Complejidad media. Diseñarlos juntos evita tocar dos veces los mismos
   puntos del código.
5. **Auditoría mínima persistente.** Mover el alta a un servicio con `STAFF_CREATED`; guardar fecha
   y autor de la baja; historial por integrante (alta, rol, baja, reactivación, restablecimiento).
   Complejidad media-baja.
6. **Ausencias por veterinario.** Dominio de Citas; entrada desde la ficha y desde la agenda; el
   agente las respeta. Complejidad media-alta.
7. **Rediseño de tabla y acciones** (§8). Complejidad baja.

---

## 10. Funcionalidades que no vale la pena agregar todavía

| Idea | Motivo |
|---|---|
| Editor de roles y permisos personalizados | ADR p63; ~90 códigos con varios sensibles; alto riesgo de dejar a alguien fuera o escalar privilegios; clínicas de 2–15 personas no lo piden; los competidores lo tienen porque venden a hospitales |
| Nómina, checador, saldo de vacaciones, contratos, documentos del empleado | Recursos humanos: mantenimiento alto y datos personales sensibles |
| Horario semanal completo por veterinario como primera versión | Captura costosa; horario de clínica + ausencias cubre la mayoría de los casos [I] |
| Productividad o ingresos por veterinario | Analítica excluida del piloto; el ingreso no se atribuye por veterinario; incentivos dañinos |
| Multi-sede, permisos por sede, locums | ADR p48: un usuario pertenece a una sola clínica; sin demanda |
| Chat interno o tareas | Duplica Inbox y agenda |
| Invitación por correo | No hay correo transaccional en el código; la contraseña generada resuelve el mismo problema |
| Verificación SEP, autoservicio de perfil | Descartados en ADR p64 |
| Vista de agenda por columnas por veterinario | Pertenece a Citas; las vistas por recurso de FullCalendar son de pago |
| Cuenta para pantalla de sala, expiración automática de cuentas | Casos de hospital |

---

## 11. Roadmap de evolución priorizado

| Fase | Funcionalidad | Problema | Prioridad | Complejidad | Módulos | Riesgo / justificación |
|---|---|---|---|---|---|---|
| **1 Profesionalización** | Recepción puede agendar (`can()` en Citas) | D1 | P0* | Baja | Citas | *Confirmar que no es intencional; si no lo es, corregir ya |
| 1 | Estado de acceso | D4 | P1 | Baja | users, configuración JWT | Privacidad entre colegas → solo `staff.update` |
| 1 | Contraseña generada | D5 | P1 | Baja | users | Ninguno; reutiliza flujo existente |
| 1 | Rediseño de tabla, acciones y descripción de roles | Percepción | P1 | Baja | frontend | Bajo |
| 1 | Impacto antes de desactivar | D6 | P1 | Media-baja | Citas, Historial clínico, Caja (lectura) | Respetar fronteras entre dominios |
| **2 Eficiencia operativa** | Cambio de rol + función clínica (ADR conjunto) | D2, D3 | P1 | Media | users, Citas, agente, Historial clínico | Regresiones del agente, INV-J; debe preceder la apertura de escritura del agente |
| 2 | Auditoría mínima persistente + alta como servicio | D7 | P2 | Media-baja | users (migración aditiva) | Bajo; natural junto al cambio de rol |
| 2 | Reasignar citas futuras al desactivar | D6 | P2 | Media | Citas (INV-A/INV-D) | Precondiciones; después del impacto de fase 1 |
| **3 Gestión avanzada** | Ausencias por veterinario | D8 | P2 → P1 | Media-alta | Citas, agente | Contrato del agente; cuando el agente agende |
| 3 | Ficha del integrante (pendientes, historial de acceso) | Supervisión | P2 | Media | Lectura multi-dominio | Puede derivar en analítica; después de la auditoría |
| 3 | Título profesional (MVZ, Dr.) en documentos | Identidad | P3 | Baja | users, PDF | Bajo; barato, no urgente |
| **4 Diferenciación** | Disponibilidad real por veterinario para el agente de WhatsApp (ausencias + especialidad) | Agendar sin humanos | P3 | Alta | agente, Citas | Requiere fases 2 y 3 |
| 4 | Activación con enlace de un solo uso enviado por WhatsApp | Entrega de credenciales | P3 | Media-alta | channels | Plantillas aprobadas por Meta |
| 4 | MFA opcional para ADMIN | Cuentas privilegiadas | P3 | Media | autenticación | Riesgo de dejar a alguien sin acceso |
| 4 | Especialidad estructurada ligada a servicios | Enrutar consultas | P3 | Media | services, agente | Bajo |

---

## 12. Top 5 de mejoras con mayor ROI

| # | Mejora | Valor | Costo | Razón |
|---|---|---|---|---|
| 1 | Recepción puede agendar (si D1 es bug) | 10 | 1 | Bloqueo operativo diario; cambio mínimo + prueba |
| 2 | Estado de acceso + contraseña generada | 8 | 2 | Cada alta lo usa; seguridad y supervisión |
| 3 | Rediseño de tabla, acciones y roles | 7 | 2 | Mayor salto de percepción por esfuerzo |
| 4 | Impacto antes de desactivar | 7 | 3 | Evita citas a inactivos y consultas sin dueño |
| 5 | Cambio de rol + función clínica (ADR) | 9 | 6 | Cierra la última operación sin salida y la incoherencia agente/agenda |

---

## 13. Propuesta de alcance ideal del módulo Equipo

**«Quién tiene acceso, qué puede hacer y quién atiende».** No es recursos humanos.

- Directorio supervisado: identidad, rol explicado, función clínica, datos profesionales, estado
  de acceso.
- Ciclo de vida completo y reversible: alta con contraseña generada, cambio de rol, baja con
  impacto visible, reactivación, restablecimiento, historial mínimo.
- Puerta de entrada a las ausencias, aunque el dato viva en Citas.
- Fuera: permisos personalizados, horarios completos, métricas, multi-sede.

---

## 14. Conclusión sobre su nivel de competitividad

1. **Nivel:** 2.3/5. Infraestructura Avanzada, producto Básico.
2. **¿Basta para una clínica pequeña?** Sí, para 1–3 personas con un dueño que administra. No
   cuando la recepción agenda (D1) ni cuando alguien cambia de puesto (D2).
3. **Distancia a un módulo profesional:** fases 1 y 2, unos 3–4 sprints [I]. Igualar a ezyVet o
   Provet no es el objetivo.
4. **Fortalezas:** seguridad y reversibilidad del acceso, invariante del último ADMIN, aislamiento
   multi-tenant, copia de los datos del firmante en documentos clínicos.
5. **Debilidades:** rol inmutable que además define la función clínica; cero supervisión; cero
   disponibilidad.
6. **Primeras cinco:** las del §12.
7. **No todavía:** roles personalizados, horario semanal completo, métricas por veterinario.
8. **Mayor salto de percepción:** columna «Acceso» + tabla de 5 columnas con descripción de roles.
9. **Mayor impacto operativo:** dejar agendar a la recepción (si es bug). Dentro de Equipo, separar
   la función clínica del rol.
10. **Innecesarias para el posicionamiento actual:** las del §10.
11. **Alcance de la siguiente versión:** el del §13.
12. **Con un solo sprint:** la fase 1 completa. Cinco cambios de complejidad baja o media-baja, sin
    ADR y sin migraciones, que convierten la «lista de usuarios» en un «equipo supervisado». Cambio
    de rol y función clínica no caben: requieren ADR y tocan el agente.

---

## Fuentes

- [ezyVet: about permissions roles](https://docs.ezyvet.com/en/browse-documentation/ezyvet/ezyvet-administration/security-and-access/control-access-to-features-and-functions/permissions-roles/about-permissions-roles)
- [ezyVet: make a permissions role](https://docs.ezyvet.com/en/browse-documentation/ezyvet/ezyvet-administration/security-and-access/control-access-to-features-and-functions/permissions-roles/make-a-permissions-role)
- [ezyVet: general steps to configure user accounts for new staff](https://docs.ezyvet.com/browse-documentation/ezyvet/staff-management/staff-user-accounts/general-steps-to-make-and-configure-user-accounts-for-new-staff)
- [ezyVet: calendar resource for a staff user account](https://docs.ezyvet.com/browse-documentation/ezyvet/appointments/calendar-configuration/configure-a-calendar-resource-for-a-staff-user-account)
- [ezyVet: planning guides](https://docs.ezyvet.com/browse-documentation/ezyvet/appointments/planning-guides)
- [ezyVet: change the staff member of appointments](https://docs.ezyvet.com/en/browse-documentation/ezyvet/appointments/getting-started/make-change-and-cancel-appointments/change-the-staff-member-of-appointments-to-a-different-staff-member)
- [ezyVet: monitor sign-in access](https://docs.ezyvet.com/en/browse-documentation/ezyvet/ezyvet-administration/security-and-access/control-sign-in-access/monitor-sign-in-access-to-ezyvet)
- [ezyVet: change logs](https://docs.ezyvet.com/browse-documentation/ezyvet/getting-started/find-and-show-information/change-logs)
- [ezyVet: make or disable user accounts](https://docs.ezyvet.com/browse-documentation/ezyvet/ezyvet-administration/user-account-configuration/make-or-disable-user-accounts)
- [Provet: Create and Manage User Accounts](https://support.provet.com/hc/en-gb/articles/360011204317)
- [Provet: List of User Permissions](https://support.provet.com/hc/en-gb/articles/17956236954524)
- [Vetspire: User Roles](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/user-roles)
- [Vetspire: Changes to User Role Permissions (2025–2026)](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/about-changes-to-user-role-permissions-2025)
- [Vetspire: Add new staff member](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/add-new-staff-member)
- [Vetspire: User Settings](https://manual.vetspire.com/vetspire-user-manual/ok/Commercial/user-settings)
- [Vetstoria: Vetspire clinician availability shifts](https://vetstoria.freshdesk.com/en/support/solutions/articles/80001042860-vetspire-how-to-create-clinician-availability-shifts-)
- [Digitail: add or update users](https://help.digitail.io/en/articles/5043093-add-or-update-users)
- [Digitail: set roles and permissions](https://help.digitail.io/en/articles/5043095-set-roles-and-permissions)
- [Digitail: set your schedule](https://help.digitail.io/en/articles/5043046-set-your-schedule)
- [Shepherd: permissions](https://help.shepherd.vet/en/articles/5539233-permissions)
- [Covetrus: FAQs](https://covetrus.com/insights/faqs-covetrus-veterinary-software-platform-and-vetsuite-network/)
- [Comparasoftware: Okvet](https://www.comparasoftware.com/okvet)
- [Comparasoftware: QVET](https://www.comparasoftware.com/qvet)

---

## Registro de implementación — Fase 1 Profesionalización (2026-11-23)

Contratos vigentes: [`modules/organizations.md`](modules/organizations.md) § Login / Crear /
Listar staff, [`modules/frontend.md`](modules/frontend.md) § Equipo y ActionMenu, ADR p21
(addendum 2026-11-23).

| Hallazgo | Verificación | Resultado |
|---|---|---|
| D1 · Recepción en modo lectura en Citas | Confirmado: `canCreate` por rol contra `appointment.create` de ASSISTANT (ADR p63) y flujos documentados («recepción crea citas») | Corregido con `can("appointment.create")`. `canEdit` sigue por rol (pendiente) |
| D4 · Sin estado de acceso | Confirmado; derivable de campos existentes | `access` por integrante, solo para quien gestiona personal |
| `last_login` nunca se actualiza | Confirmado. `UPDATE_LAST_LOGIN` descartado: escribe antes de las compuertas del login y no cubre el refresh | `record_user_access` en login y refresh, como máximo una vez por hora |
| D5 · El ADMIN inventa la contraseña | Confirmado | Contraseña generada, devuelta una vez con `no-store` |
| D12 · `/staff` abierto por URL | Confirmado y **más amplio**: `GET /api/staff/` entregaba correo, usuario y cédula de cada colega a VET/ASSISTANT | Directorio mínimo para quien no gestiona + redirección en la ruta |
| Nuevo · Alta no atómica, sin evento, usuario repetido → 500 | Confirmado al inspeccionar el alta | Servicio durable, `STAFF_CREATED`, 400 en el campo |
| D9 · Roles sin explicación | Confirmado | Textos contrastados contra `PERMISSIONS` por una prueba |
| D10/D11 · Toasts de validación, estado vacío antiguo, sin guarda de acción, 7 columnas | Confirmado | Errores en el campo, `EmptyState`, una acción de fila a la vez, 5 columnas apiladas por debajo de 720 px |

**Hallazgo nuevo, sin cambio**: la atención sin cita (`POST /api/appointments/walk-in/`) exige
`appointment.create` a quien llama y `appointment.create_walkin` al veterinario asignado, no a
quien llama; recepción la puede registrar por API, pero la interfaz se la oculta (`canEdit`,
por rol). Se decide junto con `canEdit`.

**Pendientes para fases posteriores** (sin tocar): impacto antes de desactivar; cambio de rol y
función clínica (ADR conjunto); auditoría persistente; ausencias por veterinario;
`reactivate_staff` sin protección de semillas demo; `canEdit` por rol en Citas.

---

## Registro de implementación — Fase 2 Eficiencia operativa (2026-11-24)

Decisiones del PO (2026-11-24) y contratos: [ADR p66](decisions/2026-11-24-p66-funcion-clinica-y-cambio-de-rol.md),
[`modules/organizations.md`](modules/organizations.md) § Función clínica, Cambiar rol, Impacto e historial.

| Alcance | Resultado |
|---|---|
| D2 · Rol inmutable | `POST /api/staff/<uuid>/role/` (`staff.change_role`), INV-J con bloqueo ordenado y reverificación del permiso del actor; sin cierre de sesiones (PO) |
| D3 · Función clínica deducida del rol | `User.attends_patients` + predicado único `is_clinician`/`clinician_q` en agenda, agente (candidatos, alta, reagendado, ejecución) y cédula. Backfill: VET y ADMIN con cédula (PO) |
| D6 · Desactivar sin ver impacto | `GET .../impact/`; **caja abierta bloquea** (`409 open_cash_session`, PO); citas y consultas se avisan |
| D7 · Sin auditoría persistente | `StaffAccessEvent` de solo inserción en todas las operaciones de Equipo (incluido el restablecimiento de plataforma) + `GET .../history/` y modal «Historial» |

Migraciones aditivas: `users.0014` (campo + backfill) y `users.0015` (tabla).

**Fuera de esta fase, a propósito**: reasignación masiva de citas al desactivar (Fase 3, PO); el
camino de staff para crear citas aún acepta a cualquier integrante activo como veterinario;
`canEdit` de Citas por rol; ausencias por veterinario.
