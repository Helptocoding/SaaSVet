# Análisis de producto y UX — Módulo Equipo

**Fecha:** 2026-11-19
**Tipo:** análisis de producto (no es un plan de implementación ni un ADR)
**Alcance:** `frontend/src/pages/staff.jsx`, app `backend/apps/users`, RBAC y uso del equipo
en Citas, Historial clínico, Caja, Notificaciones y el agente de WhatsApp.

> No se recibió la captura de la interfaz. La evaluación UX se hizo sobre el código de la
> página. Todo lo marcado como "existe" está verificado en el repositorio, no solo en la
> documentación.

---

## Resumen ejecutivo

Equipo resuelve bien lo que hace hoy: alta con contraseña de un solo uso, reset con
contraseña temporal y revocación de sesiones, y desactivación que corta también los refresh
tokens. Lo que le falta no es "más pantalla", sino tres cosas:

1. **Poder corregir y revertir.** Hoy hay operaciones de un solo sentido: desactivar no tiene
   vuelta desde la UI y el correo de la persona queda inutilizado para siempre; nombre, correo
   y rol no se pueden editar.
2. **Separar la función clínica del rol.** Un ADMIN que atiende pacientes (el dueño
   veterinario de una clínica pequeña) existe para la UI y la firma, pero no para el agente.
3. **Mostrar las consecuencias** antes de cortar un acceso (citas futuras, consultas abiertas,
   caja abierta).

**Siguiente iteración recomendada:** paquete "corregir y revertir" (editar identidad +
ver/reactivar inactivos) junto con los arreglos de contrato del frontend. Si hay que elegir
una sola funcionalidad: **reactivación**.

---

## 1. Diagnóstico del módulo actual

### Capacidades existentes

| Capacidad | Dónde | ¿Visible en UI? |
|---|---|---|
| Listar miembros activos (excluye `ADMIN_SAAS` y cuentas de servicio) | `backend/apps/users/views.py:88` | Sí |
| Filtro `?role=` en el listado | `backend/apps/users/views.py:93` | **No** (Equipo no lo usa) |
| Alta con contraseña de un solo uso (`password_must_change=True`) | `backend/apps/users/serializers.py:173` | Sí |
| Edición limitada a especialidad y cédula (cualquier otra clave → 400) | `backend/apps/users/serializers.py:204` | Sí |
| Reset de contraseña: temporal de 24 h + revocación de todas las sesiones | `backend/apps/users/services.py:221` | Sí |
| Desactivación: `is_active=False` + blacklist de refresh tokens | `backend/apps/users/services.py:352` | Sí (con icono de basura) |
| Eventos `STAFF_DEACTIVATED`, `ADMIN_PASSWORD_RESET_ISSUED`, `STAFF_PROFILE_UPDATED` | `backend/apps/users/services.py` | **No** (solo stdout, no persisten en DB) |
| Snapshot de nombre, especialidad y cédula del veterinario al cerrar consulta | `backend/apps/medical_records/services.py:124-130` | Indirecto (PDFs) |
| Cierre administrativo de caja ajena (`force_closed`) | `backend/apps/cash/services.py:156` | En Caja |
| Directorio de asignables para la bandeja de WhatsApp | `inbox/assignable-users/` | En Inbox |

### Cómo usan el equipo los demás módulos

- **Citas:** la agenda trata como veterinarios a VET **y** ADMIN
  (`frontend/src/pages/appointments.jsx:1058`), con filtro y color por persona.
- **Agente de WhatsApp:** solo considera `role='VET'` al ofrecer huecos
  (`backend/apps/agent/tools.py:1015`) y rechaza otro rol al crear o reagendar
  (`backend/apps/appointments/creation.py:158`, `backend/apps/appointments/mutations.py:200`).
- **Historial clínico:** solo el VET asignado o un ADMIN puede modificar o cerrar una consulta
  (`backend/apps/medical_records/policies.py:45`). La cédula la exige quien firma,
  independientemente del rol (ADR p64).
- **Notificaciones:** solo avisos de stock y de diferencia de caja, dirigidos por capacidad
  (`backend/apps/notifications/services.py`). Nada por persona.
- **Disponibilidad:** solo existe el horario de la clínica (`OrganizationSchedule`, por
  organización). No hay disponibilidad ni ausencias por veterinario.
- **Especialidad:** se imprime en los PDF de consulta y receta, y el agente la cruza contra el
  catálogo de servicios para ofrecer especialidades (`backend/apps/agent/tools.py:718-754`).

---

## 2. Problemas y limitaciones detectadas

### Operaciones de un solo sentido (lo más grave)

1. **Desactivar no tiene vuelta desde la UI.** Los inactivos desaparecen del listado y no
   existe endpoint de reactivación. El propio diálogo dice "Esta acción se puede revertir desde
   la base de datos" (`frontend/src/pages/staff.jsx:135`).
2. **El correo es único global, incluidos los inactivos** (`backend/apps/users/models.py:76`).
   Un empleado que regresa (pasantes de servicio social, personal temporal) no puede volver a
   darse de alta con su correo: "Este correo no está disponible"
   (`backend/apps/users/serializers.py:104`).
3. **Nombre, apellido, correo y rol no son editables** (`backend/apps/users/serializers.py:204`).
   Un error de captura en el nombre aparece en documentos clínicos todavía abiertos. Cambiar el
   rol (ascender a una asistente a ADMIN) exigiría desactivar y recrear, cosa que el punto 2
   impide.

### Rol y función clínica mezclados

4. Un ADMIN que atiende pacientes aparece en la agenda y puede firmar, pero **el agente nunca
   le ofrece huecos**: si es el único veterinario de la clínica, el agente responde `no_vet`.
   Además, la cédula solo se exige en el alta para el rol VET, así que a un ADMIN que atiende
   el error le aparece hasta el momento de **cerrar una consulta**.

### Desactivación sin ver el impacto

5. `deactivate_staff` no revisa citas futuras asignadas, consultas abiertas ni caja abierta.
   Las citas siguen apuntando a un usuario inactivo, que además desaparece del filtro y la
   paleta de colores de la agenda; sus consultas abiertas solo las puede cerrar un ADMIN.

### Estado de acceso invisible

6. `password_must_change` y `password_temp_issued_at` no se exponen: el ADMIN no sabe si un
   alta ya entró por primera vez. `last_login` no se actualiza porque `SIMPLE_JWT` no activa
   `UPDATE_LAST_LOGIN` (`backend/config/settings.py:399`).

### Incumplimientos de contrato del frontend

7. `isAdmin = user.role === "ADMIN"` (`frontend/src/pages/staff.jsx:59`) y el sidebar por rol
   (`frontend/src/components/Sidebar.jsx:51`) contradicen la regla "usar `can()`". Reset y
   desactivar no se condicionan con `can("staff.reset_password")` / `can("staff.destroy")`.
8. El alta no usa `handleFormError` (`frontend/src/pages/staff.jsx:113`); el contrato lo exige
   en todo POST/PATCH.
9. El placeholder de contraseña dice "Mínimo 6 caracteres"; la regla es 8
   (`frontend/src/pages/staff.jsx:515`).
10. La fila propia muestra "Desactivar" y "Resetear", que el backend rechaza
    (`backend/apps/users/services.py:263`, `:393`). En el reset, el toast dice "No tienes
    permiso", que confunde.
11. Estilos inline y hex `#fbbf24` en el modal de contraseña temporal
    (`frontend/src/pages/staff.jsx:352-375`), contra la regla de tokens y CSS modules.
12. El badge `ADMIN_SAAS` es código muerto: el listado ya excluye ese rol.

### Hallazgos de otros módulos (confirmar con producto)

- **Citas en modo lectura para la recepción:** `canCreate = user?.role !== "ASSISTANT"`
  (`frontend/src/pages/appointments.jsx:1052`) muestra "Modo lectura — sin permiso para crear
  citas", aunque el RBAC concede `appointment.create`/`update` a ASSISTANT
  (`backend/apps/core/permissions_codes.py:304`). Si no es intencional, la recepcionista no
  puede agendar desde la UI.
- `AgentSettings.default_veterinarian` no tiene pantalla en el frontend.
- La paleta de colores por veterinario se asigna por posición en la lista
  (`frontend/src/pages/appointments.jsx:1084`): cambia cuando entra o sale alguien.

---

## 3. Oportunidades funcionales

### A — Alto valor y baja complejidad

#### A1. Corregir datos de identidad (nombre, apellido, correo)

| | |
|---|---|
| **Problema** | Errores de captura permanentes que se imprimen en documentos clínicos. |
| **Cómo funciona** | El modal "Editar" agrega estos campos a especialidad y cédula. |
| **Usuario** | ADMIN. |
| **Beneficio** | Corrige sin soporte técnico ni acceso a base de datos. |
| **Complejidad** | Baja. |
| **Dependencias** | Ninguna nueva. Las consultas cerradas no cambian: conservan su snapshot. |
| **Requiere** | Ampliar `EDITABLE_FIELDS`; reutilizar validadores de nombre y unicidad de correo (excluyendo al propio usuario). Permiso `staff.update` existente. Sin migración. |
| **Impacto en el flujo** | Mínimo. |
| **Riesgos** | Cambiar el correo cambia el identificador de login; avisarlo en la UI. |

#### A2. Ver inactivos y reactivar acceso

| | |
|---|---|
| **Problema** | Desactivación por error o empleado que regresa: hoy no hay salida. |
| **Cómo funciona** | Segmento "Activos / Inactivos" y acción "Reactivar acceso", que emite una contraseña temporal reutilizando el flujo de reset. |
| **Usuario** | ADMIN. |
| **Beneficio** | Elimina la única operación irreversible del módulo. |
| **Complejidad** | Baja-media. |
| **Dependencias** | Flujo de reset existente. |
| **Requiere** | Parámetro de listado, endpoint y servicio espejo de `deactivate_staff`. Opcional: `deactivated_at`/`deactivated_by` (migración aditiva, mismo patrón que `Organization`). Permiso: reutilizar `staff.destroy` o crear `staff.reactivate` (sensible). |
| **Impacto en el flujo** | Bajo. |
| **Riesgos** | Reactivar no debe saltarse que la organización esté desactivada (ver `docs/modules/organizations.md`). |

#### A3. Estado de acceso

| | |
|---|---|
| **Problema** | El ADMIN no sabe si una alta ya entró ni detecta cuentas dormidas. |
| **Cómo funciona** | Columna "Acceso": "Pendiente de primer acceso", "Contraseña temporal: vence en X h", "Último acceso hace N días". |
| **Usuario** | ADMIN. |
| **Beneficio** | Seguimiento de altas y detección de cuentas sin uso (seguridad). |
| **Complejidad** | Baja. |
| **Requiere** | Serializar dos campos existentes y activar `UPDATE_LAST_LOGIN`. Sin migración. |
| **Riesgos** | Privacidad entre compañeros: mostrarlo solo a quien tenga `staff.update`. |

#### A4. Alta con contraseña generada por el sistema

| | |
|---|---|
| **Problema** | El ADMIN inventa la contraseña inicial (predecible, y el placeholder es incorrecto). |
| **Cómo funciona** | El alta genera `token_urlsafe(16)` y la muestra una sola vez, con el mismo modal del reset. |
| **Usuario** | ADMIN. |
| **Beneficio** | Contraseñas iniciales fuertes y un flujo único para entregar credenciales. |
| **Complejidad** | Baja. |
| **Riesgos** | Ninguno relevante; mantener que la contraseña inicial no caduque. |

#### A5. Impacto antes de desactivar

| | |
|---|---|
| **Problema** | Citas asignadas a un usuario inactivo, consultas abiertas sin dueño y cajas abiertas. |
| **Cómo funciona** | Antes de confirmar: "Tiene 4 citas futuras, 1 consulta abierta y caja abierta", con enlaces a la agenda filtrada y a Caja. Advierte sin bloquear, salvo caja abierta (exigir el cierre administrativo, que ya existe). |
| **Usuario** | ADMIN. |
| **Beneficio** | Bajas ordenadas sin pendientes huérfanos. |
| **Complejidad** | Media-baja. |
| **Dependencias** | Citas, Historial clínico, Caja (solo lectura). |
| **Requiere** | GET de solo lectura con conteos. Sin modelos nuevos. |
| **Riesgos** | Boundary: `users` no debe importar modelos de otros dominios. Cada dominio expone su conteo, o el GET vive en una capa de composición como `dashboard`. |

### B — Alto valor, requieren diseño o arquitectura

#### B1. "Atiende pacientes" independiente del rol

| | |
|---|---|
| **Problema** | Punto 4 de la sección 2: el rol decide permisos **y** función clínica. |
| **Cómo funciona** | Flag booleano en `User`. Cédula obligatoria si el flag está activo. Agenda, agente y firma leen el flag, no el rol. |
| **Usuario** | ADMIN (configura); agente y recepción (consumen). |
| **Beneficio** | Coherencia entre UI, agente y firma para el dueño veterinario. |
| **Complejidad** | Media. |
| **Dependencias** | Agente (`tools.py`), creación y mutaciones de citas, agenda, validación de cédula. |
| **Requiere** | Migración aditiva; revisar los usos de `role='VET'`; tests del agente. **Requiere ADR** porque toca contratos congelados del agente. |
| **Alternativa descartada** | Multi-rol vía `UserRole` (ya es M2M), pero `User.role` está en todo el código. |
| **Riesgos** | Regresiones en la selección de veterinarios del agente. |

#### B2. Cambio de rol

| | |
|---|---|
| **Problema** | Ascensos o cambios de función sin salida (punto 3). |
| **Cómo funciona** | Servicio atómico: `User.role` + swap del `UserRole` de sistema + invalidar caché de permisos. |
| **Usuario** | ADMIN. |
| **Beneficio** | Evita duplicar personas y partir su historial. |
| **Complejidad** | Media. |
| **Guardas** | No degradar al último ADMIN activo; no cambiarse el rol a uno mismo; cédula al pasar a VET; aviso si hay consultas abiertas o citas futuras. |
| **Riesgos** | RBAC y bloqueo de acceso (lockout). Frecuencia baja, pero sin alternativa cuando ocurre. |

#### B3. Ausencias de veterinario (días completos)

| | |
|---|---|
| **Problema** | El agente y la recepción agendan a un veterinario de vacaciones, en congreso o enfermo. |
| **Cómo funciona** | El ADMIN registra rangos de fechas. El agente excluye a ese veterinario; crear una cita en esas fechas avisa o rechaza; se listan las citas existentes dentro del rango para reprogramar. |
| **Usuario** | ADMIN y recepción. |
| **Beneficio** | Evita citas imposibles de atender. |
| **Complejidad** | Media-alta. |
| **Dependencias** | Citas (validación), agente (cálculo de huecos), calendario. |
| **Requiere** | Modelo nuevo (organización, usuario, rango, motivo). Dueño del dominio: **appointments**, no `users`. Entrada desde la ficha del miembro y desde la agenda. |
| **Riesgos** | Su valor depende de que el agente escriba en producción; hoy WRITE sigue cerrado y la activación pendiente. |

#### B4. Ficha del colaborador con pendientes operativos (solo lectura)

| | |
|---|---|
| **Problema** | No hay un lugar para ver qué tiene a su cargo cada persona. |
| **Cómo funciona** | Próximas citas, consultas sin cerrar y caja abierta. Versión persistente de A5. |
| **Usuario** | ADMIN. |
| **Datos existentes** | `Appointment.veterinarian`, `MedicalRecord.veterinarian`/`closed_by`, `Prescription.veterinarian`, `VaccineRecord.applied_by`, `Payment.actor`, `CashSession.opened_by`, `AppointmentStatusChange.changed_by`. |
| **Complejidad** | Media. |
| **Riesgos** | Deriva hacia analítica (excluida del piloto) y solapamiento con "Pendientes clínicos" del Dashboard. Solo pendientes, nunca rankings. |

---

## 4. Mejoras UX/UI (C)

**La tabla sigue siendo la estructura correcta.** Una clínica tiene entre 2 y 15 personas. No
se justifica cambiar a tarjetas, un rediseño ni agregar indicadores arriba (StatTiles aquí
sería decorativo).

### Búsqueda y filtros

- Sin búsqueda: no aporta con este volumen.
- Un solo filtro útil: el segmento **Activos / Inactivos**, una vez exista A2.
- El filtro por rol no es necesario.

### Columnas propuestas

| Columna | Contenido |
|---|---|
| Miembro | Nombre en negrita, correo debajo en gris, etiqueta "Tú" en la fila propia. |
| Rol | Badge actual. |
| Datos profesionales | Especialidad · cédula. Aviso "Sin cédula: no puede firmar" solo si atiende pacientes. |
| Acceso | Estado de A3. |
| ⋯ | Menú de acciones. |

El `@usuario` pasa al detalle: desde ADR p48 se entra con el correo y el username es
identidad interna.

### Acciones

- "Editar" visible en la fila.
- "Restablecer contraseña" y "Desactivar acceso" dentro del menú ⋯, con texto y no solo icono.
- Quitar el icono de **basura**: comunica eliminar, y la acción es desactivar. El propio brief
  habla de "eliminar integrantes", que es justo lo que transmite el icono.
- Ocultar las acciones que no aplican a la fila propia.
- Todo condicionado con `can()`.

### Gestión de credenciales

- Bien ubicada en el menú de la fila.
- El aviso "NO WhatsApp / SMS" no es realista en México; reemplazarlo por una indicación
  accionable ("entrégala en persona").
- Pasar el modal a tokens y CSS module.

### Alta de miembro

- Descripción corta de cada rol en el selector, alineada con los permisos reales.
- Correo como primer campo; username sugerido desde el correo.
- Contraseña generada (A4).
- Errores por campo con `handleFormError`.

### Detalle de colaborador

No crear una página nueva mientras no exista B4. Con A1 basta un modal de edición más
completo.

---

## 5. No implementar por ahora (D)

| Idea | Motivo |
|---|---|
| Turnos u horario semanal por persona, checador, nómina, saldo de vacaciones | Convierte el módulo en recursos humanos. Para disponibilidad, primero ausencias por día (B3). |
| Editor de roles y permisos personalizados | ADR p63 fija listas explícitas; alto riesgo de escalada o bloqueo. |
| Productividad, ranking o ingresos por veterinario | Analítica excluida del piloto; el ingreso no se atribuye por veterinario; incentiva comparaciones dañinas. |
| Chat interno o tareas | Duplica la bandeja de WhatsApp (tomar/asignar) y la agenda. |
| Invitación o recuperación por correo | No hay correo transaccional en el código productivo. |
| Verificar la cédula contra la SEP | ADR p64 lo descartó explícitamente. |
| Identidad en varias clínicas | ADR p48: un usuario, una clínica. |
| Autoservicio de perfil en `/me` | ADR p64 lo descartó para no tener dos caminos de escritura. |
| Fotos, documentos del empleado, contratos | Cosmético o de recursos humanos; agrega datos personales. |
| Auditoría navegable completa | Baja frecuencia. Bastan los logs actuales más los campos de baja de A2. |
| Notificación "te asignaron una cita" | La agenda ya lo muestra; las notificaciones son por capacidad, no por persona. |
| Horario semanal por veterinario como primera versión de disponibilidad | Excesivo para clínicas de 1 a 3 veterinarios; empezar por ausencias. |

---

## 6. Ranking de las 5 mejores propuestas

Escala 1–10. En complejidad, 10 es lo más difícil.

| # | Propuesta | Valor | Complejidad | Criterio |
|---|---|---|---|---|
| 1 | A2 · Ver inactivos y reactivar | 8 | 3 | Única operación irreversible del módulo; el correo único global la deja sin salida. |
| 2 | A1 · Corregir nombre, apellido y correo | 8 | 2 | El nombre se imprime en documentos clínicos; cambio mínimo y seguro gracias al snapshot. |
| 3 | B1 · "Atiende pacientes" separado del rol | 9 | 6 | Arregla la incoherencia UI/agente/firma para el dueño veterinario, el caso típico de clínica pequeña. Necesita ADR. |
| 4 | A5 · Impacto antes de desactivar | 7 | 4 | Evita citas asignadas a inactivos, consultas abiertas sin dueño y cajas abiertas. |
| 5 | A3 + A4 · Estado de acceso y contraseña generada | 6 | 2 | Se usa en cada alta; mejora la seguridad a costo casi nulo. |

**Cerca del top 5:** B2 · cambio de rol (valor 7, complejidad 5) y B3 · ausencias (valor 8,
complejidad 7). B3 sube al top 3 en cuanto el agente agende en producción.

**Criterio de priorización:** primero lo que hoy no tiene salida, después la coherencia entre
módulos y al final la comodidad, siempre a menor complejidad y dentro de la arquitectura
existente (servicios en `users`, RBAC explícito, sin cruzar dominios).

---

## 7. Recomendación final

Equipo **no debe crecer hacia recursos humanos**. Su función es que la clínica controle
**quién tiene acceso y quién atiende**, con un ciclo de vida reversible.

1. **Siguiente iteración:** paquete "corregir y revertir" (A1 + A2) junto con los arreglos de
   contrato de la sección 2: `can()` en lugar de rol, `handleFormError`, quitar el icono de
   basura y ocultar acciones en la fila propia. Es un backend pequeño, sin migración
   obligatoria, y cierra las dos operaciones de un solo sentido. Si hay que elegir una sola:
   **reactivación**.
2. **Después:** B1, con su ADR, antes de activar la escritura del agente.
3. **Por separado:** confirmar con producto el "modo lectura" de la recepcionista en Citas.
