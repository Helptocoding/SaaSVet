# SaaSlyVet — Análisis de producto para investigación competitiva

> [!NOTE]
> **Corte histórico de producto (2026-07-06).** Las descripciones técnicas de
> Billing reflejan la arquitectura disponible en esa fecha. El lifecycle
> normativo vigente es `MedicalRecord → Checkout → Invoice posted → Payment`
> y está documentado en [Billing](modules/billing.md) y en el
> [ADR p62](decisions/2026-08-30-p62-billing-checkout-lifecycle.md).

**Fecha**: 2026-07-06
**Autor**: Análisis de producto (perspectiva Product Manager Senior, SaaS B2B vertical)
**Fuentes**: código completo del repositorio, `docs/` (14 docs de módulo, 59 ADRs, runbooks, auditorías de cumplimiento, registro de decisiones diferidas DD-001..DD-014, backlog del piloto "Don Carlos").
**Propósito**: base para investigación competitiva y estrategia de precios. NO es un documento técnico de implementación.

---

# 1. Resumen ejecutivo

**Qué es.** SaaSlyVet (nombre interno del proyecto: VetCare / VeterinariaSaaS) es un **SaaS multi-tenant de gestión integral para clínicas veterinarias**, construido específicamente para el mercado mexicano. Cada clínica es un tenant (Organization) con su propia zona horaria, tasa de IVA, usuarios, pacientes, inventario, caja y configuración operativa. Backend Django/DRF + PostgreSQL; frontend React 19 SPA; desplegado en VPS propio (Hetzner) con Docker, Caddy (TLS), Redis y backups cifrados offsite.

**Qué problema resuelve.** La operación diaria completa de una clínica veterinaria pequeña/mediana que hoy vive en papel, Excel o software de escritorio legado: agenda de citas, expediente clínico, recetas, vacunas, inventario con múltiples presentaciones de venta, punto de venta de mostrador, cobro de consultas, devoluciones, corte de caja y métricas del negocio. Incluye además la **migración de datos desde el sistema anterior** (importador CSV/Excel tolerante a datos sucios), que es el mayor obstáculo real de adopción en este segmento.

**Qué tipo de software es.** Un **ERP vertical ligero** para clínica veterinaria: no es solo agenda ni solo expediente — cubre el ciclo operativo completo desde que el cliente llega hasta que el dinero queda cuadrado en caja y reflejado en analítica. Es software de operación (front-office + back-office financiero básico), no de comunicación con el cliente final ni de facturación fiscal.

**Qué necesidades cubre.**
- Operación de recepción: agenda, walk-in, alta rápida de cliente+mascota, POS con escáner de código de barras.
- Operación clínica: consulta single-screen con autosave, signos vitales append-only, recetas, vacunas, PDF de documentos.
- Operación financiera: facturación interna (no fiscal), pagos split con total exacto, dispensación de receta con tope clínico, notas de crédito/devoluciones, corte de caja Z inmutable.
- Operación administrativa: inventario multi-presentación con stock en unidades base, catálogo de servicios, equipo con roles y permisos, importación de datos históricos, dashboard operativo y analítica financiera.
- Necesidades del operador del SaaS: provisioning de tenants, reset de credenciales cross-tenant, demo pública auto-reseteable, backups/DR, observabilidad.

**Propuesta de valor.** "El sistema completo de tu clínica, hecho para México, en el que puedes confiar el dinero y el expediente": integridad financiera y clínica no negociable (nada se borra, todo se audita, los totales los calcula siempre el servidor), migración desde tu Excel viejo sin perder datos, y una UX pensada para ganarle al papel en velocidad de captura.

**Impresión general.** Producto de una seriedad de ingeniería inusual para su etapa (beta cerrada): el rigor en dinero, stock, concurrencia, auditoría y respaldo está a nivel de software financiero. En contraste, toda la capa de **comunicación con el cliente final** (recordatorios, WhatsApp, portal, pagos en línea) y la **facturación fiscal (CFDI/SAT)** no existen todavía. Es un producto profundo y angosto: hace muy bien el núcleo operativo, y aún no hace nada alrededor de él.

---

# 2. Público objetivo

**Tamaño de clínica objetivo: pequeña a mediana (1–10 usuarios, una sucursal).**
Razonamiento con evidencia del proyecto:
- Roles fijos de clínica: ADMIN, VET, ASSISTANT — sin jerarquías intermedias, sin departamentos.
- No existe concepto de sucursal ni multi-ubicación (el importador documenta explícitamente "múltiples sucursales: NO implementado"; caja por terminal/register es decisión diferida DD-004 con trigger "clínicas multi-terminal").
- Umbrales de escala pensados para miles —no cientos de miles— de registros: importador con cap de 2,000 filas por archivo; paginación introducida cuando una clínica real importó 1,500 mascotas (ADR p44); infraestructura de un solo VPS de 2 vCPU.
- El piloto documentado ("Don Carlos", `docs/vetcare-quickwins-don-carlos.md`) es un dueño-veterinario de clínica pequeña que compara el producto contra el papel — el backlog completo de quick wins gira en torno a ganarle al papel en velocidad y confianza.

**Tipo de clínica: clínica general de pequeñas especies con mostrador de venta.**
El catálogo de especies incluye canino, felino, equino, ave, reptil, exótico; los flujos y KPIs (stat-cards "caninos/felinos") están optimizados para perro/gato. El POS con escáner de barcode, presentaciones múltiples (caja/pieza) y venta de mostrador con cliente genérico indican clínicas que también son **farmacia/tienda veterinaria** — el patrón dominante en México.

**País/mercado: México, sin ambigüedad.**
- Teléfono validado a exactamente 10 dígitos "formato de México".
- IVA como `tax_rate` heredado de la organización (ejemplo canónico 16%).
- Moneda única MXN en toda la UI.
- Timezone default `America/Mexico_City`.
- Cumplimiento normativo mexicano citado en decisiones de arquitectura: NOM-007/NOM-046 (retención de expediente clínico y vacunal — razón de los FK PROTECT y del bloqueo de DELETE), NOM-024, LFPDPPP 2025 (aviso de privacidad, proceso ARCO manual, gate de aceptación legal).
- Glosario de UI es-MX obligatorio ("Cobro" no "Factura", "Corte de caja" no "Z-close", "Cliente" no "Propietario", "Atención sin cita" no "Walk-in").

**Perfil del usuario principal: la recepcionista/asistente y el veterinario.**
La recepcionista opera agenda, POS, cobros, caja e importación asistida; el veterinario opera la consulta (pantalla única con autosave, vitales, receta). Muchas optimizaciones están dirigidas a captura rápida no técnica: alta rápida con solo nombre+teléfono, campos opcionales "dato faltante ≠ error", escáner USB como teclado, wizard de inventario con tour interactivo y animación educativa.

**Perfil del comprador: el dueño de la clínica (rol ADMIN), frecuentemente el propio veterinario.**
El ADMIN concentra configuración, equipo, servicios, devoluciones (`billing.refund` solo ADMIN), importador (solo ADMIN) y analítica financiera (`dashboard.financial.view` solo ADMIN). Es compra directa dueño-a-proveedor, no compra por comité: el onboarding es provisioning manual por el operador del SaaS (ADMIN_SAAS) — venta asistida de alto contacto, no self-service.

---

# 3. Modelo de negocio identificado

**Conclusión: el modelo de monetización NO está implementado en el producto.** No existe en el código:
- Módulo de suscripciones, planes o precios.
- Límites por plan (usuarios, registros, features gateadas por tier).
- Self-signup ni checkout; no hay pasarela de pago conectada (la auditoría de cumplimiento registra "PCI DSS N/A hoy — sin pasarela"; Stripe/Conekta aparecen solo como triggers futuros en DD-002).
- Facturación al cliente-clínica (billing del SaaS).

**Señales de la intención de modelo:**
- **Venta por clínica (per-tenant), B2B directa.** El único camino de alta es `POST /api/platform/organizations/` ejecutado por el ADMIN_SAAS (throttle 20/hora): una llamada crea la clínica + su admin. El módulo `platform` declara como roadmap "lifecycle de tenants (futuro: suspend, reactivate, **billing state**)" — es decir, se contempla estado de cobranza a nivel organización, no por usuario ni por veterinario.
- **Sin diferenciación por asiento.** Los roles no tienen costo asociado ni límite; nada sugiere pricing por usuario o por veterinario.
- **Demo pública como motor de adquisición.** Existe un tenant demo real (`Organization.is_demo=True`) con credenciales compartidas, reseteado automáticamente cada 30 minutos (ADR p49), con gate de mantenimiento 503 durante el reset y restricciones para la cuenta demo (no cambia password, no importa datos). Esto es infraestructura de "pruébalo ahora" para una landing pública (`www.saaslyvet.com`, donde también viven términos y aviso de privacidad).
- **Sin freemium ni trial automatizado**: al no haber self-signup, la prueba es la demo compartida o el alta manual.
- **Sin módulos activables comercialmente**: los toggles de `OrganizationSettings` son de comportamiento operativo (flujo de citas, caja obligatoria, walk-in anónimo), no de monetización.

**Lectura de PM**: todo apunta a **SaaS de suscripción por clínica** (mensual o anual, un solo plan o pocos planes), vendido con onboarding asistido que incluye la migración de datos como parte del valor de venta. La ausencia total de infraestructura de cobro del SaaS es una de las brechas go-to-market más grandes (ver §11).

---

# 4. Inventario completo de funcionalidades

Leyenda de columnas — **Estado**: completo / avanzado (completo con profundidad superior al estándar) / parcial / básico. **Valor**: qué gana la clínica. **Complejidad percibida**: baja/media/alta (esfuerzo aparente invertido). **C/D**: Común en el mercado / Diferenciadora.

## 4.1 Autenticación y seguridad de sesión

| Funcionalidad | Qué hace | Estado | Valor para el cliente | Complejidad | C/D |
|---|---|---|---|---|---|
| Login con correo o username | Un solo campo acepta ambos; el correo es identidad global única case-insensitive (ADR p48) | Completo | Menos fricción de acceso | Media | Común |
| JWT access 15 min + refresh 7 días con rotación y blacklist | Sesión de vida corta; refresh rotado; tokens viejos blacklisteados | Avanzado | Sesiones robadas expiran rápido | Alta | Común (bien hecho) |
| "Recordarme" con storage dual | localStorage vs sessionStorage con invariantes de no-coexistencia y máquina de estados de restauración de sesión (ADR p22) | Avanzado | Sesión estable sin bugs de expiración | Alta | Común |
| Cambio forzado de contraseña en primer login | `MustChangePasswordGate` bloquea toda la API hasta cambiar la contraseña temporal | Completo | Higiene de credenciales del equipo | Media | Diferenciadora en el segmento |
| Reset de contraseña por el ADMIN de la clínica | Temp password de 24h, un solo uso, revoca sesiones activas (ADR p21) | Completo | Autoservicio del dueño sin soporte | Media | Común |
| Reset cross-tenant por el operador del SaaS | ADMIN_SAAS resetea a cualquier staff de cualquier clínica; audit log; no funciona contra otros ADMIN_SAAS (ADR p45) | Completo | Recuperación cuando el dueño se bloquea | Media | Diferenciadora (operación SaaS madura) |
| Desactivar usuario corta acceso al instante | Blacklistea todos los refresh tokens del target al desactivar (ADR p47) | Completo | Ex-empleado fuera de inmediato | Media | Diferenciadora |
| Throttling de login fail-closed | 5 intentos/15 min con contador en Redis; si Redis cae, el login se cierra (no se abre) (ADR p41) | Completo | Anti fuerza bruta real | Media | Diferenciadora |
| Gate de aceptación legal | Bloquea la app hasta aceptar Términos (ADMIN) y Aviso de Privacidad (todos); registro append-only con IP/user-agent/versión (ADR p46) | Completo | Cumplimiento LFPDPPP demostrable | Media | Diferenciadora |
| **NO existe**: MFA/2FA, "olvidé mi contraseña" self-service por email, SSO | — | — | — | — | — |

## 4.2 Usuarios, roles y permisos (RBAC)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Roles ADMIN / VET / ASSISTANT | Preconfigurados por organización al crearla (seed automático) | Completo | Arranque sin configurar permisos | Baja | Común |
| RBAC dinámico en DB con fallback estático | `HybridPermission`: permisos por rol persistidos en DB (editables), fallback a catálogo estático; fail-closed (vista sin permiso declarado = denegada) | Avanzado | Permisos ajustables sin redeploy; seguridad por defecto | Alta | Diferenciadora |
| Catálogo de ~60 permisos granulares | `resource.action` (p. ej. `medicalrecord.vitals.create`, `billing.refund`, `import.commit`, `appointment.create_walkin`) | Completo | Control fino: quién dispensa Rx, quién devuelve dinero | Media | Diferenciadora |
| Frontend gateado por capability, no por rol | `can('permiso')` desde `/api/me/`; CTAs se ocultan sin permiso | Completo | UI coherente con permisos reales | Media | Diferenciadora |
| Gestión de equipo (`/staff`) | Alta con contraseña temporal de un solo uso, listado, desactivación (soft) | Completo | Administración del personal | Baja | Común |
| Ownership clínico por policy | VET solo modifica/cierra SUS consultas; ADMIN todas | Completo | Integridad del expediente | Media | Común |

## 4.3 Organización y configuración

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Tenant con timezone y tax_rate propios | Fechas locales por clínica; IVA heredado e inmutable por factura; cambio de TZ auditado | Completo | Correctitud fiscal/horaria | Media | Común |
| 6 toggles de flujo operativo | auto-crear consulta al completar cita, auto-crear cobro, exigir confirmación antes de atender, walk-in anónimo, historial de estados visible, caja obligatoria para cobrar | Completo | El sistema se adapta al proceso de cada clínica (defaults manuales/explícitos) | Media | Diferenciadora |
| Catálogo de servicios | CRUD de procedimientos cobrables (Consulta, Vacuna, Cirugía…), PROTECT si están en uso | Completo | Base del cobro de consultas | Baja | Común |
| Inicialización automática del tenant | Al crear la org: settings, cliente genérico "Público General", paciente genérico "Anónimo", roles RBAC sembrados | Completo | Cero configuración inicial | Media | Diferenciadora |

## 4.4 Pacientes (clientes y mascotas)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| CRUD de clientes (Owner) | Nombre + teléfono 10 dígitos (identidad del cliente); genérico protegido | Completo | Base de datos de clientes | Baja | Común |
| CRUD de mascotas (Pet) | Especie (7 opciones, opcional="pendiente"), raza, sexo, color, fecha de nacimiento opcional | Completo | Expediente base | Baja | Común |
| Datos mínimos para operar | Alta manual con solo lo esencial (nombre+teléfono cliente, nombre mascota); resto opcional — "tan rápido como el papel" | Completo | Velocidad de captura en recepción | Media | Diferenciadora |
| Búsqueda server-side multi-campo | Nombre, especie, raza, nº expediente anterior (legacy_id), nombre y teléfono del dueño; índices trigram (pg_trgm) para búsqueda parcial rápida | Avanzado | Encontrar al cliente por lo que sea que recuerde | Media | Diferenciadora |
| Filtros y paginación server-side | Especie (tolerante a datos sucios), sexo, grupo de edad (cachorro/joven/adulto/senior), por dueño; paginación 25/50/100 | Completo | Escala a miles de mascotas importadas | Media | Común |
| Stats de la clínica | `GET /pets/stats/`: totales, caninos, felinos en una query | Completo | KPIs sin costo | Baja | Común |
| Nº de expediente anterior (legacy_id) | Identificador del sistema viejo, único por org, buscable — la clínica sigue usando SU numeración histórica | Completo | Continuidad operativa post-migración | Media | Diferenciadora |
| Datos importados del sistema anterior (extra_data) | Columnas del Excel sin campo equivalente se preservan como lista read-only visible en la ficha (label, valor, columna origen, fecha import) | Completo | Cero pérdida de datos al migrar | Media | Diferenciadora |
| Prompt "Completar datos" | Ficha detecta opcionales faltantes post-import y ofrece completarlos (sin alertas globales ni "score") | Completo | Mejora gradual de datos sin fricción | Baja | Diferenciadora |
| Protección de borrado | Cliente/mascota con historial → 409 con conteo y muestra de dependencias; genéricos imborrables | Completo | Nadie destruye el expediente por accidente | Media | Diferenciadora |
| Ficha de mascota (`/pets/:id`) | Detalle con historial, vacunas, datos importados | Completo | Vista 360 del paciente | Media | Común |

## 4.5 Agenda / Citas

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Calendario completo (FullCalendar) | Vistas día/semana/mes, creación desde slot, duración default 30 min | Completo | Operación visual de agenda | Media | Común |
| Máquina de estados con auditoría | scheduled→confirmed→in_progress→done; canceled/no_show; cada transición validada y registrada (AppointmentStatusChange append-only, quién/cuándo/motivo) | Avanzado | Trazabilidad total de la agenda | Alta | Diferenciadora |
| Detección de conflictos | No solape por veterinario en estados activos; no citas en el pasado | Completo | Agenda confiable | Media | Común |
| Walk-in (atención sin cita) | Nace en `in_progress`, 30 min, sin validar conflicto; flag persistido | Completo | Refleja la realidad del mostrador | Media | Común |
| Walk-in anónimo + vinculación posterior | Con toggle: atiende sin registrar mascota (paciente genérico); banner "vincular mascota" hasta cerrarla; al vincular actualiza también la consulta abierta | Completo | Cero fricción en urgencias; el expediente se corrige después | Alta | Diferenciadora |
| Registro rápido (cliente+mascota+cita atómico) | Un solo paso desde el formulario de cita; reutiliza cliente por teléfono; rollback total si algo falla | Completo | El caso "cliente nuevo llama" en segundos | Media | Diferenciadora |
| Reprogramación | canceled/no_show → scheduled solo si la fecha no pasó; si pasó, cita nueva | Completo | Reglas claras de replaneación | Baja | Común |
| No-show manual | Marca desde detalle; alimenta analítica de "No asistieron" | Completo | Medición de ausentismo | Baja | Común |
| Cierre automático de cita al cerrar consulta | Cerrar el expediente completa la cita (in_progress→done) en la misma transacción (ADR p34) | Completo | Un paso menos para el veterinario | Media | Diferenciadora |
| Modal de acciones rápidas | Única fuente de acciones por estado (Confirmar/Atender/No asistió/Reprogramar/Cancelar/Ver expediente) usada por dashboard y agenda | Completo | Operación consistente en toda la app | Media | Común |
| **NO existe**: recordatorios/confirmación automática al cliente, agenda por recurso (quirófano), lista de espera formal, citas recurrentes, reserva en línea | — | — | — | — | — |

## 4.6 Consulta médica (historial clínico)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Consulta single-screen | Evaluación (tipo/motivo/diagnóstico) + Tratamiento + Cargos en una sola pantalla, sin stepper | Completo | Captura fluida durante la atención | Media | Común |
| Autosave con borrador recuperable | Guarda ~1s tras la última edición, server-side; indicador Guardando…/Guardado; el primer autosave crea el expediente (lazy) | Completo | Nunca se pierden notas clínicas — clave de confianza del piloto | Alta | Diferenciadora |
| Tipos de consulta | general / vaccine / surgery / emergency, con reglas de cierre distintas (vacuna no exige tratamiento) | Completo | Flexibilidad clínica realista | Baja | Común |
| Signos vitales append-only | Peso, temperatura, FC, FR; inmutables (sin editar/borrar); validaciones clínicas (rangos, coherencia temp/FC, cambio brusco de peso >150% requiere confirmación) | Avanzado | Historial clínico íntegro y defendible | Alta | Diferenciadora |
| Productos usados en consulta | Descuentan stock al consumirse (bajo lock); toggle Insumo (no se cobra) vs Cobrar (genera línea) — `cost_behavior` (ADR p32) | Avanzado | Distinción real costo clínico vs venta | Alta | Diferenciadora |
| Servicios en consulta | Agregar procedimientos; sincronizan la factura draft (lazy) en la misma transacción | Completo | El cobro se arma solo mientras atiendes | Alta | Común |
| Gate de producto con receta | Producto `requires_prescription` no entra a la consulta sin receta activa que lo contenga | Completo | Control de medicamentos controlados | Media | Diferenciadora |
| Cierre explícito e irrevocable | Exige diagnóstico (y tratamiento salvo vacuna); consulta cerrada = inmutable para todos los roles incl. ADMIN; idempotente | Completo | Expediente legalmente sólido (NOM-046) | Media | Diferenciadora |
| Cierre garantiza factura | Toda consulta cerrada aparece en Cobros (mínimo draft $0) — recepción nunca "pierde" un cobro (ADR p30) | Completo | Cero fugas de ingreso | Media | Diferenciadora |
| Panel resumen (summary) | Paciente + últimos vitales + diagnóstico + totales de cobro + próxima vacuna en un solo endpoint | Completo | Contexto completo sin navegar | Media | Común |
| PDF de consulta | Resumen con membrete, tema visual, paginación, fechas en TZ local, nombre de archivo identificable | Completo | Documento entregable al cliente | Media | Común |
| Timeline por mascota | Consultas agrupadas por año/mes, cards expandibles, búsqueda de paciente server-side | Completo | Navegación del historial | Media | Común |
| **NO existe**: plantillas de nota clínica, adjuntos (imágenes/laboratorio), odontograma, hospitalización, anestesia/quirófano, consentimientos quirúrgicos | — | — | — | — | — |

## 4.7 Recetas

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Receta ligada a consulta (1:1) | Solo medicamentos `requires_prescription`; dosis obligatoria; cantidad >0; inmutable tras cerrar consulta | Completo | Prescripción formal | Media | Común |
| Receta ≠ venta (principio de producto) | La receta no descuenta stock ni cobra; recepción dispensa lo que el cliente decide llevar | Completo | Refleja la realidad: el cliente no siempre compra todo | Media | Diferenciadora |
| PDF de receta | Con firma del veterinario + especialidad, paginación correcta para recetas largas | Completo | Documento entregable | Media | Común |
| Página `/prescriptions` | Visor/reimpresión histórica con filtros por especie/sexo/edad sin cargar todo el catálogo | Completo | Consulta histórica | Baja | Común |
| **NO existe**: cédula profesional en la receta (planeado Fase 2), recetario digital con verificación, interacciones medicamentosas | — | — | — | — | — |

## 4.8 Vacunas

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Registro de vacunación (VaccineRecord) | Vacuna, fecha aplicación, próximo refuerzo, aplicada por, ligada opcionalmente a consulta | Completo | Historial vacunal formal | Baja | Común |
| Estado derivado | current / overdue / no_scheduled calculado (no almacenado) | Completo | Semáforo de vacunación honesto | Baja | Común |
| Borrado bloqueado (405) | Documento legal NOM-007/046; corrección vía notas | Completo | Integridad regulatoria | Baja | Diferenciadora |
| **NO existe**: recordatorio automático de refuerzos al cliente, carnet de vacunación imprimible, calendario de vacunación por especie | — | — | — | — | — |

## 4.9 Inventario

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Productos con categorías | medication/food/accessory/other; código interno único autogenerado; flag receta; soft delete | Completo | Catálogo ordenado | Baja | Común |
| Multi-presentación con unidades base | Stock autoritativo a nivel producto en unidad base (pieza/ml/kg); cada presentación (Caja de 3, Pieza) con factor de conversión y precio propio; vender caja descuenta 3 unidades (ADR p31) | Avanzado | El problema real de farmacia veterinaria (fraccionar) resuelto correctamente | Alta | Diferenciadora |
| Wizard de alta con modo simple/multi | Selector de modo, auto-sync de la segunda presentación, tour interactivo de 6 pasos con spotlight y animación educativa (una vez por dispositivo) | Completo | Usuarios no técnicos crean productos complejos | Alta | Diferenciadora |
| Ledger de movimientos append-only | Cada in/out/adjustment registrado con origen (consulta, factura, usuario); paginación cursor para alto volumen | Avanzado | Trazabilidad total del stock | Alta | Diferenciadora |
| Único escritor de stock | `apply_stock_movement()` con lock — imposible drift por caminos alternos; comando de auditoría de integridad (`audit_stock_integrity`) wireado a cron | Avanzado | Inventario en el que se puede confiar | Alta | Diferenciadora |
| Alertas de stock bajo/agotado | Umbral min_stock por producto; card en dashboard; agotado = alerta crítica en top bar | Completo | Nunca quedarse sin lo esencial | Baja | Común |
| Código de barras por presentación | Único por org; lookup exacto para POS | Completo | Escáner USB en mostrador | Media | Común |
| Entrada rápida de stock | Modal para recepción de mercancía con escáner (escanear→cantidad→Enter→siguiente), preview en ambas unidades, razón fija filtrable | Completo | Recepción de proveedor en minutos | Media | Diferenciadora |
| Ajuste manual / reconciliación | Movimiento adjustment como reset absoluto (inventario físico) | Completo | Cuadre periódico | Baja | Común |
| **NO existe**: lotes y caducidades, órdenes de compra/proveedores, costos promedio/PEPS, transferencias entre ubicaciones, inventario cíclico guiado | — | — | — | — | — |

## 4.10 Punto de Venta (POS)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Pantalla dedicada `/pos` (F11) | Venta de mostrador: carrito local → checkout 2 pasos server-driven (totales siempre del backend, sin matemática financiera en el cliente) | Completo | Venta rápida sin errores de redondeo | Alta | Diferenciadora |
| Escáner de barcode | Input único: código exacto agrega qty 1 (re-escaneo incrementa) con fallback a búsqueda por nombre (productos+servicios) | Completo | Mostrador tipo retail | Media | Común |
| Cliente opcional | Genérico "Público General" por default; cliente real y mascota opcionales (ADR p25) | Completo | Venta anónima o con historial | Media | Común |
| Pago split con total exacto | Efectivo+tarjeta+transferencia sumando exactamente el total; cambio calculado en UI (recibido−total) sin persistir; sin pagos parciales jamás (ADR p30) | Avanzado | Caja siempre cuadra | Alta | Diferenciadora |
| Cobro atómico idempotente | `direct-pay` en un solo lock con `X-Idempotency-Key`: reintento de red no duplica el cobro; fallo conserva draft+key | Avanzado | Cero dobles cobros | Alta | Diferenciadora |
| Venta de Rx con receta externa | Producto con receta vendible en mostrador solo con atestación (checkbox + médico prescriptor), permiso especial, registro legal append-only que sobrevive devoluciones (ADR p26) | Completo | Cumplimiento en venta de medicamentos | Alta | Diferenciadora |
| Sin borradores huérfanos | Abandonar el pago cancela el draft automáticamente (auditable) | Completo | Cobros limpio | Media | Diferenciadora |
| **NO existe**: ticket impreso (impresora térmica), cajón de dinero conectado, descuentos/promociones/cupones, precios por lista de cliente | — | — | — | — | — |

## 4.11 Cobros / Facturación interna

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Documento de cobro (Invoice) | Tipos consultation/direct_sale; estados draft→confirmed→paid (+cancelled); IVA heredado inmutable; totales solo backend | Completo | Núcleo del ingreso | Alta | Común |
| Ledger de pagos append-only | Modelo Payment (0..N por factura); estado `paid` es proyección del ledger (`remaining_balance == 0`), no un flag; comando de auditoría de integridad del ledger | Avanzado | Contabilidad interna a prueba de manipulación | Alta | Diferenciadora |
| Anchors analíticos inmutables | paid_at/confirmed_at/cancelled_at `editable=False` con CHECK constraints en DB y único escritor en services — ni el admin de Django puede corromper la analítica | Avanzado | Métricas financieras confiables | Alta | Diferenciadora |
| Dispensación de receta en el cobro | Panel "Receta — dispensar": recepción elige presentación y cantidad de lo recetado; se agrega a la MISMA factura de la consulta; stock se descuenta al confirmar | Avanzado | Un solo ticket consulta+farmacia | Alta | Diferenciadora |
| Tope clínico de dispensación | Dispensado acumulado ≤ recetado, comparado en unidades base entre presentaciones; cubre también edición de línea; el cliente puede llevar menos, nunca más (ADR p37) | Avanzado | Imposible sobre-dispensar un controlado | Alta | Diferenciadora |
| Devoluciones (notas de crédito) | Sobre factura pagada: por concepto, con destino restock/discard, motivo tipificado, dinero devuelto = crédito emitido, idempotente; la factura permanece `paid` (ADR p29) | Avanzado | Devoluciones formales sin romper la contabilidad | Alta | Diferenciadora |
| Reversión de nota de crédito | Contra-asiento (RefundReversal, ≤1 por refund) si la NC fue un error; ajusta caja y métricas | Avanzado | Corrección sin borrar historia | Alta | Diferenciadora |
| Audit log de facturas | Cada transición de estado con quién/cuándo/notas | Completo | Trazabilidad financiera | Media | Diferenciadora |
| Listado con filtros y orden server-side | Por cliente, mascota, estado, fecha de pago/creación (TZ de la org); paginado; sort por fecha/total | Completo | Operación diaria de recepción | Media | Común |
| PDF del cobro | Con marca de agua por estado (BORRADOR/CANCELADO en diagonal) — un borrador impreso no pasa por comprobante | Completo | Comprobante entregable honesto | Media | Diferenciadora |
| **NO existe**: CFDI/timbrado SAT, facturación fiscal, cuentas por cobrar/crédito a clientes, anticipos/saldo a favor (diferido DD-006), presupuestos/cotizaciones | — | — | — | — | — |

## 4.12 Caja (turnos y corte Z)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Turno de caja por usuario | Apertura con fondo inicial; una sola caja abierta por usuario (constraint DB) | Completo | Responsabilidad individual del efectivo | Media | Común |
| Asociación automática de pagos al turno | Todo pago/devolución/reversa del actor se ata a su sesión abierta siempre (con o sin toggle) (ADR p39) | Completo | El Z refleja la realidad | Media | Diferenciadora |
| Toggle "caja obligatoria para cobrar" | Si está activo, cobrar sin caja abierta → bloqueado | Completo | Disciplina de caja configurable | Baja | Común |
| Movimientos manuales del cajón | Depósitos, retiros, gastos menores; append-only (corrección = contra-movimiento); serializados contra el cierre | Completo | El cajón real (feria, gastos) cuadra | Media | Diferenciadora |
| Corte Z congelado | expected = fondo + efectivo − devoluciones + reversas ± movimientos; diferencia vs contado; snapshot JSON inmutable versionado (v1/v2/v3) — el Z histórico jamás se reinterpreta | Avanzado | Corte legal defendible ante conflicto | Alta | Diferenciadora |
| Serialización pago-vs-cierre | Ningún pago "se cuela" después del conteo (lock de cabecera, verificado con tests de concurrencia reales) | Avanzado | Confianza absoluta en el corte | Alta | Diferenciadora |
| Página `/cash` + chip en Cobros | Estado del turno visible donde se cobra; abrir/cerrar desde ambas | Completo | Operación fluida | Baja | Común |
| **NO existe**: caja por terminal física (multi-cajero en una caja, diferido DD-004), arqueo ciego, denominaciones de billetes | — | — | — | — | — |

## 4.13 Dashboard operativo

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| KPIs del día en vivo | Summary con cache 30s + polling: pacientes hoy, ingresos, citas, etc. | Completo | Pulso del negocio al abrir el día | Media | Común |
| Checklist de activación | Guía de primer uso por estado real de datos (pacientes→servicios→cita→consulta), sin flags; desaparece al completarse | Completo | Onboarding autoguiado del dueño | Media | Diferenciadora |
| Agenda del día navegable | Mini-agenda con strip semanal, marcador walk-in, "Pendiente desde hace N min", acciones vía modal único | Completo | Centro de operación matutina | Media | Común |
| Citas por resolver | Citas pasadas aún en scheduled/confirmed (últimos 30 días) con acciones para cerrarlas | Completo | Nada se queda en limbo | Media | Diferenciadora |
| Pendientes clínicos | Consultas abiertas particionadas: listas para cerrar vs sin diagnóstico; navegación directa al expediente | Completo | El vet no deja expedientes abiertos | Media | Diferenciadora |
| Stock crítico en sidebar + alerta top-bar | Solo lo crítico (agotados) alerta arriba; lo demás vive en su card | Completo | Señal sin ruido | Baja | Común |
| Spark de ingresos (solo ADMIN) | Serie con delta, snapshot + hoy live | Completo | Vista financiera rápida | Media | Común |

## 4.14 Analítica (página `/analytics`)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Snapshots diarios inmutables | Job nocturno idempotente por org (advisory lock anti doble-fire); 7 KPIs v1: revenue_paid, revenue_accrual, cobros pagados, citas total/done/no_show, consultas cerradas | Avanzado | Historia financiera/operativa que no cambia bajo tus pies | Alta | Diferenciadora |
| Today siempre live | El día actual se calcula en vivo con la MISMA función que el snapshot (consistencia matemática); cada punto expone su fuente (snapshot/live) y estado de ciclo de vida | Avanzado | Honestidad del dato (nada se sirve en silencio) | Alta | Diferenciadora |
| Ingresos netos con devoluciones | `revenue_paid_net` vía MetricAdjustment en el día del refund (dual-window: snapshots congelados intactos) | Avanzado | Métrica financiera correcta post-devolución | Alta | Diferenciadora |
| Gráficas de actividad y conversión | Área de actividad, embudo "Conversión de citas", "No asistieron", desglose por estado; bitácora del periodo día por día | Completo | Decisiones del dueño con datos | Media | Común |
| Acceso financiero solo ADMIN | `dashboard.financial.view` separado del operativo | Completo | Privacidad de números frente al staff | Baja | Común |
| **NO existe**: reportes exportables (CSV/PDF), reportes por veterinario/comisiones, comparativas entre periodos configurables, cohortes de clientes, reporte de impuestos | — | — | — | — | — |

## 4.15 Importador CSV/Excel (migración)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Wizard de 4 pasos | Subir → Mapear → Validar (dry-run) → Confirmar; clientes+mascotas v1; CSV (3 encodings, sniff de delimitador) y XLSX; caps 5MB/2,000 filas/50 columnas | Completo | La barrera nº1 de adopción, resuelta | Alta | Diferenciadora |
| Auto-mapeo de columnas | Heurística por alias de encabezado ("VetCare entendió tu Excel"); el usuario solo revisa lo dudoso; decisión reversible por columna | Completo | Migración sin consultor | Alta | Diferenciadora |
| Tolerancia a datos sucios | Teléfono/especie/fecha opcionales (warning, no error); especies en texto libre normalizadas al catálogo; fila inválida no aborta el lote (savepoints por fila, cero huérfanos) | Avanzado | Los archivos reales de clínicas SÍ entran | Alta | Diferenciadora |
| Dedup inteligente | Cliente por teléfono (reutiliza), mascota por nombre normalizado ("Max"=="MAX"); conflictos de expediente con confianza alta/incierta y comparación lado a lado | Avanzado | Reimportar no duplica la base | Alta | Diferenciadora |
| Preview honesto | El dry-run predice exactamente lo que hará el commit (misma lógica); pills con conteos, "Mostrando N de M", CSV descargable de filas con problemas | Completo | Confianza antes del botón rojo | Alta | Diferenciadora |
| Preservación de columnas extra | Todo lo que no mapea va a "Datos del sistema anterior" en la ficha | Completo | Cero pérdida de información | Media | Diferenciadora |
| Solo ADMIN + throttle | Operación sensible de migración | Completo | Control | Baja | — |
| **NO existe**: import de historial clínico/citas/inventario/facturas (solo clientes+mascotas), multi-sucursal/multi-origen (documentado como futuro), importación asíncrona en background (síncrona con caps) | — | — | — | — | — |

## 4.16 Documentos PDF

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Capa de tema compartida | Membrete por página, "Página N de M", tipografía y paleta del sistema, fechas en TZ local (ADR p36) | Completo | Imagen profesional consistente | Media | Común |
| Consulta / Receta / Cobro | Tres documentos descargables con nombre identificable (`tipo_id_mascota_fecha.pdf`) | Completo | Entregables al cliente | Media | Común |
| **NO existe**: branding por clínica (logo propio — pendiente Fase 2), carnet de vacunas, envío por correo/WhatsApp | — | — | — | — | — |

## 4.17 Plataforma (operación del SaaS)

| Funcionalidad | Qué hace | Estado | Valor (para el negocio SaaS) | Complejidad | C/D |
|---|---|---|---|---|---|
| Provisioning API de tenants | Org + admin inicial + settings + genéricos + roles RBAC en una transacción; guards anti-escalación de privilegios; audit log con request-id | Completo | Alta de clientes en minutos, auditable | Alta | Diferenciadora |
| Demo pública auto-reset | Tenant demo real reseteado cada 30 min (atómico, con advisory lock, purge+rebuild ~13s); escrituras bloqueadas 503 durante el reset; cuenta demo restringida | Completo | Motor de adquisición sin riesgo | Alta | Diferenciadora |
| Reset de credenciales cross-tenant | Ver §4.1 | Completo | Soporte de primer nivel | Media | Diferenciadora |
| Admin Django ofuscado | Slug secreto por env, `/admin` literal → 404, solo ADMIN_SAAS | Completo | Superficie de ataque mínima | Baja | — |
| **NO existe**: panel de administración SaaS (web) para tenants, suspensión/reactivación, métricas SaaS (MRR/churn), billing del SaaS, impersonación de soporte | — | — | — | — | — |

## 4.18 Backups y disaster recovery

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Backup nocturno cifrado offsite | pg_dump validado + checksum + cifrado asimétrico age (llave privada OFFLINE, zero-knowledge) + subida a Backblaze B2 | Avanzado | Los datos de las clínicas sobreviven al desastre | Alta | Diferenciadora |
| Offsite inmutable | B2 Object Lock; la llave del VPS no puede borrar el histórico → ransomware no destruye los backups | Avanzado | Resistencia real a ransomware | Alta | Diferenciadora |
| Drill mensual de restauración | Cron restaura a DB de prueba + corre auditorías de integridad → "RESTORE VERIFIED"; deadman ping (Healthchecks) solo en éxito | Avanzado | Backups probados, no supuestos | Alta | Diferenciadora |
| Runbook de recuperación total | RUNBOOK-RESTORE.md paso a paso | Completo | RTO predecible | Media | Diferenciadora |
| **NO existe**: PITR/WAL archiving (RPO actual = 24h, diferido DD-011), réplica/standby, multi-región (DD-012) | — | — | — | — | — |

## 4.19 Seguridad y aislamiento

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Multi-tenant estricto | Toda query filtrada por organización; cross-tenant = 404 siempre (nunca lista vacía); validación a nivel objeto con log de intentos | Avanzado | Datos de una clínica invisibles para otra | Alta | Común (crítico) |
| UUIDs públicos en URLs | PKs enteros jamás resolubles desde fuera (anti-enumeración) | Completo | Sin fugas por adivinación de IDs | Media | Diferenciadora |
| Sanitización de entradas | Texto sanitizado + regex restrictivos en nombres/motivos/notas | Completo | Anti-inyección/XSS almacenado | Media | Común |
| Hardening HTTP | HSTS, SSL redirect, cookies secure, CORS/CSRF estrictos, headers de seguridad | Completo | Base sólida | Baja | Común |
| Escaneo de secretos + rotación | gitleaks config, plan de rotación documentado | Completo | Higiene operativa | Baja | — |
| RLS de PostgreSQL | Preparado (ADR p23) pero **no activo** | Parcial | Defensa en profundidad futura | Alta | — |
| **NO existe**: MFA, cifrado en reposo del volumen DB (backups sí cifrados), SIEM/alerting de seguridad, log de lecturas de PII | — | — | — | — | — |

## 4.20 Observabilidad y soporte

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Sentry backend+frontend con scrubbing | Errores y performance con PII/credenciales filtradas antes de salir (invariante: nada clínico/financiero a Sentry); release tags por SHA; source maps privados | Avanzado | Fallas detectadas antes que el cliente, sin fugar datos | Alta | Diferenciadora |
| Correlación end-to-end | X-Request-ID generado en el frontend, propagado a logs/Sentry/respuesta | Completo | Debug de incidentes en minutos | Media | Diferenciadora |
| Logs estructurados JSON por dominio | ~10 loggers de eventos de negocio (RBAC, tenant, pagos dedupeados, caja, provisioning, deprecación…) | Avanzado | Auditoría operativa consultable | Alta | Diferenciadora |
| ErrorBoundary con código de error | El crash de UI muestra un event-id compartible con soporte | Completo | Soporte accionable | Baja | Común |
| Botón "Reportar problema" | FeedbackButton → endpoint de soporte → webhook Discord | Completo | Canal de feedback en producto | Baja | Común |
| Uptime + disco | Probe externo (UptimeRobot/Healthchecks) + alerta de disco >80% | Completo | Operación de un solo VPS vigilada | Baja | — |
| Comandos de auditoría de integridad | `audit_stock_integrity`, `audit_payment_ledger_integrity`, `audit_anchor_integrity`, `audit_orphan_fks` con exit codes wireables a cron | Avanzado | Drift detectado automáticamente | Alta | Diferenciadora |

## 4.21 Cumplimiento legal (LFPDPPP / NOM)

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Versionado y aceptación de documentos legales | Términos/Privacidad/Cookies versionados; aceptación por usuario con IP/UA/timestamp server-side, append-only; gate server-side hasta aceptar; requisito por rol (ADMIN: T&C+Privacidad; staff: Privacidad) | Completo | Consentimiento demostrable | Media | Diferenciadora |
| Proceso ARCO manual documentado | Runbook con ruteo Responsable (staff/clínica) vs Encargado (clientes finales → su clínica), SLA 20 días hábiles, contacto privacidad@ | Parcial (manual) | Cumplimiento operable hoy | Baja | Diferenciadora |
| Retención regulatoria por diseño | PROTECT + append-only + bloqueo de borrado justificado por NOM-007/024/046 en los ADRs | Completo | Defendible ante inspección | Media | Diferenciadora |
| Plan de respuesta a incidentes | `docs/security/incident-response.md` | Completo (doc) | Art. 19 LFPDPPP operable | Baja | — |
| **NO existe**: endpoints ARCO automatizados (export/borrado), DPAs firmados con subprocesadores, designación formal del responsable de datos | — | — | — | — | — |

## 4.22 Infraestructura, API y calidad

| Funcionalidad | Qué hace | Estado | Valor | Complejidad | C/D |
|---|---|---|---|---|---|
| Stack de despliegue | Docker Compose (backend/frontend/Postgres 16/Redis/Caddy TLS automático), VPS Hetzner endurecido, deploy/rollback por script con tags de imagen | Completo | Operación reproducible y reversible | Alta | — |
| CI con gates bloqueantes | Tests backend + frontend (Vitest, 79+ tests), grep-gates anti-patrones (fugas de token en consola, dual-lookup de IDs, manejo de errores) | Avanzado | Regresiones atrapadas antes de prod | Alta | Diferenciadora |
| API REST interna coherente | Errores con shape canónico por `code` (validation/permission/not_found/conflict con conteo de dependencias/sunset/demo_resetting), PATCH parcial, deprecación formal RFC 8594 con Sunset headers y 410 automático | Avanzado | Contratos estables (base para API pública futura) | Alta | Diferenciadora |
| Paginación estratégica | PageNumber u opt-in u cursor según el volumen del recurso; principio documentado de colecciones server-side | Completo | Escala sin sorpresas | Media | — |
| Disciplina documental | 59 ADRs, contratos congelados (modelo de eventos financieros, métricas), registro de decisiones diferidas, deuda técnica clasificada por prioridad, runbooks operativos | Avanzado | Velocidad y seguridad de evolución del producto | Alta | Diferenciadora (interna) |
| **NO existe**: API pública documentada para terceros, webhooks salientes, versionado de API público, entorno de staging documentado | — | — | — | — | — |

---

# 5. Flujo operativo completo

Recorrido de un día real de clínica usando SaaSlyVet, con las pantallas involucradas.

**0. Inicio del día**
1. La recepcionista entra a `/login` ("Correo o usuario" + contraseña; checkbox Recordarme). Si es su primer acceso, el sistema la obliga a cambiar la contraseña temporal y aceptar el Aviso de Privacidad antes de ver cualquier pantalla.
2. Aterriza en el **Dashboard** (`/`): KPIs del día, agenda de hoy, citas por resolver de días anteriores, pendientes clínicos y stock crítico. Si la clínica es nueva, en su lugar domina el checklist de activación (crear pacientes → servicios → primera cita → primera consulta), con CTA a importar su Excel.
3. Abre su turno de **Caja** (`/cash` o el chip en Cobros): registra el fondo inicial. Si la clínica activó "caja obligatoria", ningún cobro procede sin este paso.

**1. Llega un cliente**
- **Con cita**: la cita aparece en la Agenda del día. Opcionalmente se confirmó antes. Clic en la card → modal de acciones → **"Atender ahora"** → la cita pasa a `in_progress` y navega directo a la consulta.
- **Sin cita (walk-in)**: desde Citas (`/appointments`), botón de atención sin cita: se elige veterinario y motivo; la mascota es obligatoria salvo que la clínica permita walk-in anónimo (entonces se usa el "Paciente Anónimo" y queda un banner para vincular al paciente real después).
- **Cliente nuevo por teléfono**: en el formulario de nueva cita, enlace "No encuentro la mascota →" abre el registro rápido: nombre del cliente, teléfono (10 dígitos), nombre y especie de la mascota + los datos de la cita — todo en una sola operación atómica. Si el teléfono ya existe, reutiliza al cliente.
- **Clínica recién migrada**: el cliente se busca por nombre, teléfono o su número de expediente del sistema anterior (búsqueda parcial server-side).

**2. La consulta (pantalla Historial clínico, `/medical-records`)**
4. El veterinario ve el banner del paciente con chips de vitales. Abre el **modal de signos vitales**: peso, temperatura, FC, FR (validaciones clínicas; un cambio de peso brusco pide confirmación explícita). Cada registro es inmutable.
5. Captura **Evaluación** (tipo de consulta, motivo, diagnóstico) y **Tratamiento**. Todo se autoguarda ~1s después de cada edición (indicador "Guardando…/Cambios guardados"); el borrador es recuperable si se cierra el navegador. El primer autosave crea el expediente, ligado a la cita si vino de "Atender ahora".
6. En **Cargos** agrega productos (con toggle Insumo—no se cobra— vs Cobrar) y servicios; el stock se descuenta al momento bajo lock y la factura draft se va armando sola (lazy). Un producto que requiere receta no entra sin receta activa.
7. Opcionalmente emite la **Receta** (medicamentos con dosis y cantidad). La receta NO cobra ni descuenta stock — es un documento clínico.
8. **"Finalizar y enviar a Cobros"**: exige diagnóstico (y tratamiento salvo vacunas). El cierre es irrevocable: garantiza la factura en Cobros (aunque sea $0), completa la cita automáticamente (`done`) y deja el expediente inmutable. Puede descargarse el PDF de la consulta y de la receta.

**3. El cobro (pantalla Cobros, `/billing`)**
9. Recepción abre el cobro de la consulta (draft). Si hay receta, el panel **"Receta — dispensar"** muestra cada medicamento con lo recetado, lo ya dispensado y el restante; recepción elige presentación y cantidad de lo que el cliente decide llevar — con tope clínico: jamás más de lo recetado. Lo dispensado se suma a la MISMA factura.
10. **Confirmar** el cobro: aquí se descuenta el stock de lo dispensado (los insumos de consulta ya se descontaron al usarse).
11. **Registrar pago**: editor de líneas de pago (efectivo/tarjeta/transferencia, split permitido) que debe sumar exactamente el total; si el efectivo recibido excede, la UI muestra el cambio (no se persiste). El pago queda atado al turno de caja abierto. Reintentos de red no duplican el cobro (idempotencia). El PDF del cobro queda disponible (con marca de agua si es borrador o cancelado).

**4. Venta de mostrador (POS, `/pos` o F11)**
12. Cliente compra alimento/medicina sin consulta: la recepcionista escanea códigos de barras (cada escaneo suma 1) o busca por nombre; cliente genérico por default o cliente real con su mascota. Si un producto exige receta, el carrito pide atestación de receta externa (médico prescriptor). "Cobrar" crea el documento real con IVA calculado por el backend; "Confirmar cobro" ejecuta el pago atómico. Abandonar el pago cancela el borrador automáticamente.

**5. Devoluciones**
13. Un producto salió mal: el ADMIN abre el cobro pagado → **"Devolver"** → selecciona conceptos, cantidades y destino (regresar a inventario o dar de baja), motivo tipificado, y captura el reembolso (debe igualar el crédito). El dinero sale del turno de caja actual; la métrica de ingresos netos se ajusta el día de la devolución; la factura permanece pagada (historia intacta). Si la devolución fue un error, se **revierte** con un contra-asiento — nada se borra jamás.

**6. Cierre del día**
14. La recepcionista registra movimientos manuales del cajón si los hubo (retiro a bóveda, gasto menor) y hace el **Corte de caja**: el sistema calcula el efectivo esperado (fondo + cobros − devoluciones + reversas ± movimientos), ella captura lo contado, y la diferencia queda congelada en un snapshot inmutable. Tarjeta y transferencia se reportan informativamente.
15. Esa noche, el job de analítica congela el snapshot del día por clínica. Al día siguiente, el dueño ve en **Analítica** (`/analytics`) las series históricas (ingresos cobrados/devengados/netos, citas, no-shows, consultas) con el día en curso siempre en vivo, más la bitácora día por día.

**Flujo paralelo del dueño (ADMIN)**: gestiona equipo en `/staff`, servicios y toggles en `/config`, inventario en `/inventory` (alta con wizard, entrada rápida de mercancía con escáner, ajustes), y la migración inicial en `/imports` (subir Excel → revisar mapeo → validar → confirmar).

---

# 6. Funcionalidades diferenciadoras

Ordenadas por potencia competitiva estimada:

1. **Importador de migración con UX de producto.** Auto-mapeo de columnas, dry-run que no miente, tolerancia deliberada a datos sucios (teléfonos faltantes, especies en texto libre), dedup por teléfono/nombre normalizado, preservación del nº de expediente anterior (buscable) y de las columnas extra en la ficha. Ataca directamente el switching cost — la razón nº1 por la que una clínica no cambia de software. La mayoría de competidores resuelve esto con servicios manuales de onboarding; aquí es producto.

2. **Integridad financiera de grado contable.** Ledger de pagos append-only donde `paid` es una proyección matemática; anchors temporales inmutables protegidos por constraints de base de datos (ni el superusuario puede corromperlos); idempotencia de cobros y devoluciones; total exacto sin pagos parciales; devoluciones por nota de crédito con contra-asiento en lugar de edición. Es un argumento de venta directo al dueño: "aquí nadie puede maquillar ni romper los números".

3. **Corte de caja Z congelado y serializado.** Snapshot inmutable versionado; imposible que un pago "se cuele" después del conteo (verificado con tests de concurrencia); movimientos manuales del cajón auditables. El corte de caja es el momento de mayor conflicto laboral en una clínica — tener un Z legalmente defendible es diferenciador emocional y práctico.

4. **Dispensación de receta con tope clínico.** El circuito receta→dispensación→cobro→stock en un solo documento, con la regla "el cliente puede llevar menos, nunca más" aplicada en unidades base entre presentaciones distintas, más atestación legal para venta de Rx con receta externa. Modela correctamente la farmacia veterinaria mexicana real; los genéricos de agenda no tienen nada parecido.

5. **Inventario multi-presentación en unidades base.** Caja de 3 y pieza suelta del mismo producto con stock único correcto, wizard con tour y animación educativa para que lo configure una recepcionista. El fraccionamiento es EL problema de inventario veterinario y suele estar mal resuelto.

6. **Auditoría total.** 13+ modelos append-only (pagos, devoluciones, vitales, vacunas, atestaciones, transiciones de cita/factura, movimientos de caja/stock, aceptaciones legales, cambios de TZ…): la respuesta a "¿quién hizo esto y cuándo?" siempre existe. Vendible como cumplimiento y como control interno anti-merma.

7. **Backups cifrados, inmutables y ensayados.** Cifrado zero-knowledge con llave offline, bucket con Object Lock que ni un VPS comprometido puede borrar, drill de restauración mensual automatizado con verificación. Para una clínica cuyo activo es el expediente de 10 años, "tus datos sobreviven incluso a un ransomware en nuestro servidor" es un claim que casi nadie del segmento puede hacer honestamente.

8. **RBAC dinámico con permisos de negocio.** Quién puede devolver dinero, dispensar controlados, cerrar caja o importar datos es configurable por rol en DB, con la UI reaccionando a capacidades reales (no a nombres de rol).

9. **Analítica honesta.** Snapshots congelados + hoy en vivo con la misma fórmula + procedencia visible por punto + ajustes por devolución en ventana dual. Los números del dashboard son auditables — contraste con dashboards típicos que recalculan historia silenciosamente.

10. **Demo pública auto-regenerada cada 30 minutos** sobre el stack real (tenant genuino, no mocks): permite "pruébalo ahora" sin riesgo ni mantenimiento manual — palanca go-to-market ya construida.

11. **Localización mexicana profunda.** No es traducción: teléfono 10 dígitos, IVA, glosario es-MX cuidado ("Cobro", "Corte de caja", "Atención sin cita"), NOMs citadas en decisiones de retención de datos, LFPDPPP operativizada (gate de aceptación + ARCO manual). "Hecho para México" es defendible.

12. **Capacidades internas que compran velocidad futura**: disciplina de ADRs/contratos congelados/decisiones diferidas pre-alineadas (los upgrades a PSP, ledger unificado, PITR, multi-terminal están diseñados para ser mecánicos), CI con gates de regresión de seguridad, observabilidad con scrubbing de PII. Invisible para el cliente, decisivo para competir a 12-24 meses.

---

# 7. Limitaciones detectadas

Lo que **NO existe** hoy en el producto (verificado contra código y docs; sin propuestas):

**Comunicación con el cliente final**
- Sin integración WhatsApp (ni Business API ni links).
- Sin recordatorios automáticos de citas (SMS/email/WhatsApp).
- Sin recordatorios de vacunas/desparasitación (solo estado derivado visible en la app).
- Sin confirmación de cita por el cliente.
- Sin envío de documentos (receta/cobro) por correo o mensajería — solo descarga de PDF.
- Sin infraestructura de correo saliente en absoluto (ni transaccional ni marketing).
- Sin portal del cliente / autoservicio del dueño de la mascota.
- Sin reserva de citas en línea.
- Sin encuestas/NPS post-visita.

**Fiscal y pagos**
- Sin CFDI / timbrado / integración SAT (el documento de cobro es interno, no factura fiscal).
- Sin pagos en línea ni pasarela (Stripe/Conekta solo contemplados como trigger futuro DD-002).
- Sin terminal bancaria integrada.
- Sin cuentas por cobrar, crédito a clientes, anticipos ni saldo a favor (diferido DD-006; pagos parciales prohibidos por diseño).
- Sin presupuestos/cotizaciones previos al cobro.

**Clínico avanzado**
- Sin adjuntos en el expediente (imágenes, radiografías, PDFs de laboratorio).
- Sin módulo de laboratorio (órdenes, resultados, integración con analizadores).
- Sin hospitalización/internamiento (kardex, tareas por turno).
- Sin anestesia/quirófano (hojas de monitoreo, consentimientos quirúrgicos).
- Sin plantillas de notas clínicas ni frases rápidas.
- Sin odontograma ni esquemas corporales.
- Sin recordatorio/protocolos de vacunación por especie.

**Negocio y crecimiento de la clínica**
- Sin multi-sucursal (una organización = una ubicación operativa).
- Sin planes de salud/membresías/paquetes prepagados.
- Sin programa de lealtad ni descuentos/promociones/cupones.
- Sin comisiones ni reportes de productividad por veterinario.
- Sin peluquería/estética/pensión como módulos con agenda de recursos propia.
- Sin e-commerce ni marketplace.
- Sin reportes exportables (CSV/Excel/PDF de listados o métricas; único export existente: CSV de filas con problemas del importador).

**Producto/plataforma**
- Sin aplicación móvil ni PWA declarada (SPA responsive de escritorio).
- Sin self-signup, sin trial automatizado, sin billing del SaaS (planes/suscripciones/cobro a clínicas).
- Sin panel web de administración del SaaS (provisioning por API/CLI).
- Sin API pública documentada para terceros, sin webhooks salientes, sin integraciones (ni una).
- Sin multi-idioma ni multi-moneda (es-MX / MXN únicamente).
- Sin "olvidé mi contraseña" self-service (depende del ADMIN o del operador del SaaS).
- Sin MFA/2FA.
- Sin endpoints ARCO automatizados (exportación/borrado de datos personales — proceso manual).
- Sin ticket de venta para impresora térmica.
- Importación limitada a clientes+mascotas (sin historial clínico, citas, inventario ni saldos), síncrona y con cap de 2,000 filas.
- Sin jobs asíncronos/colas (todo request-response + cron).
- Sin PITR (RPO de respaldo = 24 horas; diferido DD-011), sin réplica de DB, un solo VPS (sin HA).
- Sin cifrado en reposo del volumen de DB evidenciado (backups sí cifrados).
- Sin soft-delete real (los borrados bloqueados sugieren "Archivar" que aún no existe — deuda registrada).
- Sin branding por clínica en PDFs (logo propio — planeado Fase 2); sin cédula profesional en receta (Fase 2).

---

# 8. Nivel de madurez del producto

**Clasificación: Beta privada (beta cerrada), en transición hacia beta pública.**

Justificación:

**Por qué es más que un MVP.**
- El núcleo transaccional (citas→consulta→cobro→caja→analytics) está completo, endurecido contra concurrencia real (tests con threads y Postgres), auditado y documentado con 59 ADRs y contratos congelados. Un MVP no tiene idempotencia de pagos, orden global de locks, snapshots inmutables ni drills mensuales de restauración.
- Hay infraestructura de producción operando: VPS endurecido, TLS automático, Redis, Sentry con scrubbing de PII, uptime probes, backups offsite inmutables, deploy/rollback con tags, CI con gates bloqueantes.
- Hay evidencia de uso real: un piloto documentado con backlog de feedback priorizado (Don Carlos), una clínica migrada con 1,500 mascotas que motivó la paginación (ADR p44), un tenant demo público con benchmark de reset medido en producción.
- El cumplimiento dejó de ser teórico: gate de aceptación legal implementado, proceso ARCO manual documentado, plan de respuesta a incidentes, auditoría GAP de LFPDPPP con evidencia por archivo.

**Por qué no es "Producción" plena (GA).**
- La adquisición y monetización no existen: sin self-signup, sin billing del SaaS, sin planes. Cada cliente entra por provisioning manual — eso define beta cerrada.
- Los propios documentos internos hablan consistentemente de "beta cerrada"/"pre-beta"/"post-beta" como marco temporal (observabilidad dimensionada "para beta cerrada single-VPS", deuda etiquetada "post-beta").
- Faltan piezas que un cliente pagando esperaría pronto: recordatorios, recuperación de contraseña autoservicio, MFA, exportes, factura fiscal.
- Resiliencia de un solo VPS con RPO 24h: correcto para beta, insuficiente para prometer SLAs.
- Deuda y decisiones diferidas explícitamente contenidas "hasta beta" (dual-exposure de IDs, RLS preparado sin activar, listas sin paginar con trigger definido).

**Por qué no es "Beta pública" todavía.** La demo es pública, pero el alta de clínicas no: no hay registro abierto ni onboarding sin intervención del operador. El día que se abra self-signup + cobro, la categoría cambia.

**Distancia a Enterprise:** larga y no es el objetivo — sin SSO/MFA, sin SLAs, sin multi-región, sin certificaciones (ISO/SOC 2 solo como referencia en el GAP), sin ambiente de staging formal, sin API pública. El diseño apunta a PyME, no a cadenas corporativas.

---

# 9. Cobertura funcional

Estimación razonada por dominio del flujo operativo de una clínica veterinaria pequeña/mediana mexicana:

| Dominio operativo | Cobertura | Razonamiento |
|---|---|---|
| Recepción y agenda | ~85% | Calendario, estados auditados, walk-in, alta rápida, no-show, reprogramación. Falta: recordatorios/confirmaciones al cliente, reserva online, lista de espera. |
| Acto clínico ambulatorio | ~75% | Consulta con autosave, vitales, receta, vacunas, PDF, cierre irrevocable. Falta: adjuntos, plantillas, laboratorio. |
| Clínico avanzado (hospitalización, cirugía como proceso, laboratorio, imagen) | ~10% | Solo el tipo de consulta "surgery"/"emergency" como clasificación; nada del proceso. |
| Farmacia / inventario / POS | ~80% | Multi-presentación en unidades base, barcode, entrada rápida, Rx con atestación, ledger de movimientos. Falta: lotes/caducidades, compras/proveedores, promociones, ticket térmico. |
| Cobro y dinero (no fiscal) | ~90% | Documento de cobro, split exacto, dispensación, devoluciones con contra-asiento, caja Z, idempotencia. Falta: crédito/anticipos (por diseño), cotizaciones. |
| Fiscal (CFDI/SAT) | 0% | No existe. En México es la brecha más sensible frente a competidores locales. |
| Comunicación y retención de clientes | ~0% | Sin recordatorios, WhatsApp, email, portal, lealtad. El estado de vacunas existe pero no notifica. |
| Dirección del negocio (métricas) | ~65% | KPIs diarios, series históricas inmutables, conversión/no-show, ingresos netos. Falta: exportes, productividad por veterinario, comparativas configurables. |
| Administración (equipo, permisos, configuración) | ~85% | RBAC granular dinámico, toggles de flujo, servicios. Falta: multi-sucursal, MFA. |
| Migración/onboarding de datos | ~60% | Clientes+mascotas excelente; falta historial clínico, citas, inventario, saldos. |

**Cobertura agregada del flujo operativo diario (lo que la clínica hace todos los días): ~75–80%.** Una clínica puede operar su día completo —agenda, atención, farmacia, cobro, caja— solo con SaaSlyVet.

**Cobertura del "job to be done" completo de gestionar la clínica (incluyendo retener clientes y cumplir con el SAT): ~50–55%.** Las dos ausencias que más pesan comercialmente son comunicación con clientes (motor de retención y el feature más pedido del segmento) y facturación fiscal (requisito duro para muchas clínicas mexicanas).

Muy completo: dinero, caja, inventario, expediente base, seguridad/auditoría, migración de padrón. Incompleto: todo lo que sale de la clínica hacia el cliente final o hacia la autoridad fiscal.

---

# 10. Fortalezas técnicas

1. **Aislamiento multi-tenant riguroso.** Filtro por organización obligatorio y primero en cada query, validación a nivel de objeto con logging de intentos cruzados, cross-tenant = 404 siempre, UUIDs públicos anti-enumeración, y RLS de PostgreSQL ya diseñado como segunda capa. Es la fortaleza nº1 para vender confianza B2B.

2. **Correctitud financiera estructural.** Los invariantes viven en la base de datos (CHECK constraints, unique parciales), no solo en el código: estados con anclas temporales imposibles de dejar inconsistentes, eventos append-only, mutaciones contables atómicas (F-expressions), único escritor por dominio en services. La clase de bug "el dinero no cuadra" está estructuralmente cerrada.

3. **Concurrencia tratada como problema de primera clase.** Orden global de locks documentado y obligatorio (Caja→Expediente→Factura→Presentación→Item), idempotencia por header en cobros/devoluciones, cierres serializados contra pagos en vuelo, tests de concurrencia con hilos reales contra Postgres. Rarísimo en software de este segmento.

4. **Auditoría y trazabilidad totales.** Todo cambio crítico deja rastro consultable (13+ modelos append-only más logs JSON estructurados por dominio con correlación end-to-end por request-id). Sirve a soporte, cumplimiento y disputa laboral por igual.

5. **Respaldo y recuperación probados.** Pipeline nightly validado + cifrado asimétrico con llave offline + offsite inmutable (Object Lock) + drill mensual automatizado que restaura y verifica integridad + deadman alerting. La mayoría de SaaS pequeños tiene backups; casi ninguno los ensaya mensualmente.

6. **Observabilidad con privacidad.** Sentry en ambos extremos con scrubbing activo de PII/credenciales (invariante documentado y con gate de CI contra fugas de token por consola), releases etiquetados por SHA, comandos de auditoría de integridad wireables a cron.

7. **Arquitectura modular con boundaries explícitos.** Apps de dominio con ownership, reglas de importación entre dominios documentadas y respetadas (p. ej. billing→cash unidireccional sin ciclos; platform periférico; imports aislado), services como única puerta de mutación. Facilita crecer el equipo sin degradar el sistema.

8. **Disciplina de evolución.** 59 ADRs con contexto y consecuencias, contratos congelados (eventos financieros, métricas), registro de decisiones diferidas con triggers de activación y pre-alineamiento (los upgrades futuros son mecánicos), deuda técnica clasificada y contenida. Esto es velocidad futura comprada hoy.

9. **Calidad protegida por CI.** Suites de backend y frontend bloqueantes, gates de regresión creativos (grep-gates anti-patrones de seguridad y consistencia), tests que anclan reglas de dinero y stock.

10. **Escalabilidad razonada, no prematura.** Paginación por estrategia según volumen (cursor para ledgers, opt-in para compatibilidad), índices trigram para búsqueda, caché Redis compartida multi-worker con fallback fail-closed en throttling. Dimensionado honesto para su etapa con el camino de crecimiento documentado.

---

# 11. Debilidades técnicas

Capacidades ausentes o inmaduras que afectan adopción comercial y crecimiento (no bugs):

1. **Cero infraestructura de mensajería saliente.** No hay email ni SMS ni WhatsApp en el sistema — ni siquiera correo transaccional para reset de contraseña. Esto bloquea en cadena: recuperación autoservicio de cuenta, recordatorios (el feature más vendible del segmento), notificaciones, y cualquier comunicación con el cliente final.

2. **Go-to-market no construido en producto.** Sin self-signup, sin trial automatizado, sin billing de suscripciones, sin panel de administración del SaaS. Hoy cada cliente nuevo cuesta trabajo manual del operador; el crecimiento no escala sin construir esta capa.

3. **Punto único de falla.** Un VPS, una base de datos, sin réplica ni PITR (RPO 24h — un día de expedientes y cobros perdibles en el peor caso). Correcto para beta; incompatible con SLAs comerciales y con clínicas grandes evaluando riesgo.

4. **Sin capa de trabajos asíncronos.** Todo es request-response + cron: el importador es síncrono (cap 2,000 filas), no hay colas para futuros envíos masivos, reportes pesados o integraciones. Varias features del roadmap natural chocarán con esta ausencia.

5. **Identidad y acceso incompletos para venta B2B exigente.** Sin MFA (ni para ADMIN_SAAS), sin recuperación self-service, sin SSO. Un solo usuario = una clínica (sin identidad multi-clínica), lo que complica al veterinario que trabaja en dos lugares y a las futuras cadenas.

6. **Modelo mono-sucursal.** La organización es a la vez tenant, ubicación y caja de configuración. Multi-sucursal exigirá decisiones de modelo (ya asomadas en el importador y en DD-004) que serán más caras cuanto más tarde lleguen.

7. **Sin superficie de integración.** Ninguna API pública, webhook o integración de terceros (laboratorios, pasarelas, contabilidad, WhatsApp BSP). En un mercado donde el ecosistema decide, hoy el producto es una isla — bien construida, pero isla.

8. **Salida de datos limitada.** Sin exportes CSV/Excel de listados ni métricas, sin API de extracción; el ARCO de acceso/portabilidad es manual. Esto incomoda a dueños analíticos y es fricción de cumplimiento.

9. **Escala de UI pendiente en listas restantes.** Recetas, productos y citas aún cargan lista completa con filtros client-side (DD-013, con plan mecánico de activación). Contenido para clínicas medianas; problema para las grandes.

10. **Compliance operativo a medio cerrar.** Cifrado en reposo del volumen DB no evidenciado, DPAs con subprocesadores sin firmar, log de lecturas de PII inexistente, ARCO manual. Nada bloquea la beta; varios serán preguntas de checklist en ventas a clínicas cuidadosas.

11. **Frontend sin tipos.** SPA React en JavaScript puro (sin TypeScript); mitigado con tests y gates, pero el costo de refactor crece con el producto.

---

# 12. Valor percibido

**Impresión de una clínica evaluándolo por primera vez: "profesional, serio, hecho para mí — aunque le faltan cosas que otros presumen".**

**Lo que transmite en los primeros 10 minutos.** Login limpio en español, checklist de activación que guía el primer uso, alta de paciente tan rápida como el papel, y una demo pública que siempre está impecable (se regenera sola). La terminología es exactamente la del mostrador mexicano: "Cobro", "Corte de caja", "Atención sin cita", "Número de expediente anterior". Los empty states explican qué hacer. Nada parece traducido ni genérico: parece diseñado por alguien que ha estado detrás del mostrador de una veterinaria en México.

**Lo que transmite en la primera semana.** Confianza operativa: el autosave nunca pierde una nota, el corte de caja cuadra al centavo y explica cada peso (devoluciones, retiros, cambio), nada se puede borrar "por accidente" (y el sistema explica por qué: "este cliente tiene 5 mascotas asociadas"), los PDFs se ven profesionales y un borrador impreso dice BORRADOR. El importador convierte el Excel viejo en una base operable en una tarde, conservando el número de expediente de siempre. Para el dueño: la analítica distingue honesta­mente lo cobrado de lo devengado y descuenta devoluciones.

**Dónde se percibe el hueco.** El evaluador que viene de comparar opciones preguntará rápido: "¿y los recordatorios de vacunas por WhatsApp?", "¿factura (CFDI)?", "¿app para mis clientes?", "¿tickets en mi impresora térmica?". Ahí el producto hoy dice no. También hay asperezas de pulido documentadas por el propio piloto (anglicismos residuales, reloj 24h, textos técnicos como "restock/discard") — menores, pero visibles en una demo.

**Clasificación: profesional (gama media-alta operativa), no premium.** No se percibe básico en ningún momento: la profundidad de caja, inventario y devoluciones supera a la mayoría de opciones económicas del mercado. No alcanza percepción premium porque premium en este segmento se asocia a ecosistema (app del cliente, comunicación omnicanal, integraciones, marca pulida) más que a rigor interno — y el rigor interno de SaaSlyVet, su mayor virtud, es en gran parte invisible en una demo de 20 minutos. **Reto de posicionamiento clave: hacer visible lo invisible** (auditoría, backups inmutables, integridad de caja) como argumento de venta.

---

# 13. Posicionamiento preliminar

**Compite en la categoría de software profesional de gestión veterinaria (practice management) de gama media**, para clínica independiente pequeña/mediana en México/LatAm.

**No compite (hoy) contra:**
- **Software económico/genérico** (agendas horizontales, hojas de cálculo mejoradas, apps de citas simples): SaaSlyVet los supera ampliamente en profundidad — caja, inventario fraccionado, devoluciones, auditoría — y su costo de operación (VPS, backups, soporte asistido) exige precios por encima de ese piso. Perdería compitiendo por precio y no lo necesita.
- **Enterprise / cadenas corporativas y hospitales**: sin multi-sucursal, SSO/MFA, SLAs, laboratorio/imagen, hospitalización ni certificaciones. Ni el producto ni la infraestructura apuntan ahí.

**Contra quién sí pelea:** los verticales veterinarios establecidos de gama media en español (los que una clínica mexicana encuentra al googlear "software veterinaria"). Frente a ellos:
- **Ventajas esgrimibles**: migración de datos como producto (no como servicio cobrado), integridad de dinero/caja demostrable, cumplimiento mexicano real (NOM/LFPDPPP operativizados), inventario fraccionado correcto, demo instantánea siempre fresca, y una base técnica que permite iterar más rápido y con menos regresiones que suites legadas.
- **Desventajas hoy**: los incumbentes de gama media casi siempre traen recordatorios (email/WhatsApp), facturación fiscal o su integración, app/portal del cliente y ecosistema de integraciones — exactamente las cuatro ausencias de SaaSlyVet. En un checklist de features lado a lado, hoy pierde en "alcance"; gana en "profundidad y confianza".

**Posicionamiento natural (preliminar):** *el sistema operativo confiable de la clínica independiente mexicana* — el que no pierde una nota, no descuadra un peso y no rompe tu historial al migrar — con roadmap visible hacia comunicación con clientes y fiscal. Precio coherente: medio del mercado (por clínica/mes), nunca low-cost; el ancla de valor es el costo de un descuadre de caja, de un expediente perdido o de una migración fallida, no el precio del software vecino.

---

# 14. Resumen ejecutivo final

**Principales fortalezas**
1. Núcleo operativo completo y profundo: agenda→consulta→farmacia→cobro→caja→analítica funcionan de punta a punta con calidad excepcional.
2. Integridad financiera y clínica estructural: append-only, anclas inmutables, idempotencia, corte Z congelado — "confianza" como feature.
3. Migración de datos como producto (importador tolerante a la realidad), que ataca el mayor freno de adopción del segmento.
4. Localización y cumplimiento mexicanos genuinos (es-MX, IVA, NOM-007/024/046, LFPDPPP con gate de consentimiento y ARCO manual).
5. Base técnica y disciplina de evolución (multi-tenant estricto, backups inmutables ensayados, observabilidad, 59 ADRs) que compran velocidad y confiabilidad futuras.

**Principales debilidades**
1. Cero comunicación con el cliente final (sin WhatsApp/email/SMS/recordatorios/portal) — la brecha más visible en cualquier comparativa.
2. Sin facturación fiscal (CFDI/SAT) ni pagos en línea — requisito duro para una parte del mercado mexicano.
3. Go-to-market no construido: sin self-signup, sin billing del SaaS, onboarding 100% manual.
4. Resiliencia de beta: un VPS, RPO 24h, sin MFA, sin capa asíncrona.
5. Isla sin integraciones ni API pública; salida de datos (exportes) casi nula.

**Funcionalidades más valiosas para el cliente**: consulta con autosave irrecuperablemente confiable; corte de caja Z que cuadra y se defiende; POS con escáner y cobro a prueba de dobles; inventario fraccionado correcto; dispensación de receta en el mismo ticket; importador del Excel viejo; dashboard con pendientes que no dejan nada en el limbo.

**Funcionalidades más diferenciadoras frente al mercado**: importador con dry-run honesto y preservación del expediente anterior; ledger financiero append-only con devoluciones por contra-asiento; tope clínico de dispensación y atestación de Rx externa; Z inmutable serializado; auditoría total; backups zero-knowledge inmutables con drill mensual; demo pública auto-regenerada; RBAC dinámico por capacidad de negocio.

**Tipo de cliente ideal**: clínica veterinaria independiente mexicana de 1 a ~10 personas, con mostrador de farmacia/tienda, dueño-veterinario involucrado que ha sufrido descuadres de caja, pérdida de expedientes o un software anterior del que no puede sacar sus datos; que valora control y confiabilidad por encima de marketing, y que hoy no depende críticamente de recordatorios automatizados ni de facturar CFDI desde el sistema (o tolera resolverlo fuera mientras llega).

**Grado de preparación para salir al mercado**: **listo para beta de pago con venta asistida y cupo controlado; no listo para lanzamiento abierto.** El producto operativo soporta clínicas reales hoy (ya lo hace) y su calidad interna reduce el riesgo reputacional de la beta. Para abrir el grifo comercial faltan, en orden de impacto: (1) recordatorios/WhatsApp como primera capacidad de comunicación, (2) recuperación de cuenta autoservicio + correo transaccional, (3) billing del SaaS con self-signup o pipeline de venta formalizado, (4) exportes básicos y (5) definición fiscal (integración CFDI o partnership). La estrategia de precios puede diseñarse ya: el valor demostrable está en la profundidad operativa y la confianza, y el costo de los faltantes está acotado y mapeado.

---

*Documento generado a partir del análisis exhaustivo del repositorio (código backend/frontend, 14 documentos de módulo, 59 ADRs, contratos de dominio, runbooks, auditorías de cumplimiento y backlog de piloto). Las afirmaciones "NO existe" fueron verificadas contra el código y los registros de decisiones diferidas (DD) y deuda técnica a fecha 2026-07-06.*
