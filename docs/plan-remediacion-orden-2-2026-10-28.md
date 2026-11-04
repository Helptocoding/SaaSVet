# Orden 2 — Plan de remediación de integridad y conservación

Fecha de acuerdos: **28 de octubre de 2026**, America/Mexico_City.

Estado: **LISTO_PARA_IMPLEMENTACION_LOCAL**. Este documento y el [metaprompt ejecutor](metaprompt-remediacion-orden-2-2026-10-28.md) preparan un encargo nuevo. No se ha implementado código ni aplicado migraciones al redactarlos.

Fuentes: [priorización, categoría 2](plan-remediacion-priorizado-2026-10-28.md), [inventario](pendientes-documentados-2026-10-27.md) y [deuda histórica](deuda/fase2-prioridad-alta.md). Las decisiones del usuario recogidas aquí prevalecen sobre las recetas antiguas.

## 1. Objetivo y alcance

Remediar **A6, D6, D7, A5, A7, A3, A2, D5 y A4**, por entregas pequeñas, conservando documentos, trazabilidad, aislamiento tenant y efectos clínicos/financieros existentes.

El resultado debe permitir archivo y restauración cotidianos, y un procedimiento excepcional de borrado físico claramente separado. No debe convertir el borrado de una entidad operativa en borrado de su historia.

| Decisión | Acuerdo vinculante |
|---|---|
| Implementación | El agente puede modificar código, generar migraciones y ejecutar pruebas **solo contra bases aisladas**. |
| Base habitual local | Contiene demos/pruebas y es recreable, pero **no se modifica ni migra** en este encargo. No confundir la descripción de los datos con autorización para borrarla. |
| VPS | Excluido y aplazado. Sin SSH, reactivación, proveedor, despliegue o activación remota. |
| Alcance | Todo el orden 2 por entregas y evidencia individual, no un refactor masivo. |
| Clientes y mascotas | Uso habitual: archivar y restaurar. Histórico clínico/financiero conservado. |
| Archivo de cliente | Archiva también sus mascotas activas, atómicamente. La restauración del cliente **no restaura mascotas automáticamente**. |
| Actividad abierta | Bloquea archivo de cliente/mascota hasta resolver citas y atención abiertas. No cancelar/completar operaciones automáticamente. |
| Cobros pendientes | No impiden archivo normal; permanecen consultables y liquidables. **Sí bloquean borrado físico excepcional**. |
| Permisos de archivo/restauración | Solo ADMIN de su clínica y ADMIN_SAAS, respetando alcance tenant/plataforma. No VET/ASSISTANT. |
| Organización con historia/dependencias | Conservar desactivada; mantener identidad tenant y referencias. |
| Organización desactivada | Personal sin acceso y sin nuevas operaciones automáticas; datos conservados y posibilidad de reactivación. ADMIN_SAAS conserva acceso al histórico. |
| Borrado físico | Solo API de plataforma, ADMIN_SAAS, confirmación, motivo y auditoría. |
| Objetivos físicos permitidos | Únicamente **clientes, mascotas y organizaciones vacías sin dependencias**. Usuarios, productos y presentaciones conservan sus bloqueos actuales. |
| Documentos y ledger | No eliminar facturas, expedientes con contenido, recetas, movimientos o auditorías como parte de ese procedimiento. |
| Veterinario en históricos cerrados | Reconstruir lo recuperable con datos actuales, marcado como reconstruido. Si no hay fuente, desconocido. No inventar identidad histórica. |
| Git | Conservar cambios ajenos. Entregar código/migraciones/documentación revisables; sin commit, push, PR o merge automático. |

El cierre previo del [diagnóstico del orden 1](diagnosticos/orden-1/2026-10-28T174848Z/CIERRE.md) se conserva. Sus restricciones de inspección pasiva no prohíben las nuevas pruebas aisladas autorizadas aquí; sus remediaciones de secretos/dependencias no se incorporan a este encargo.

## 2. Hechos actuales que el agente debe revalidar

- `InvoiceAuditLog.invoice` conserva CASCADE; `Prescription.medical_record` es OneToOne CASCADE.
- `StockMovement` tiene CASCADE hacia **presentation y product**. Revisar solo presentación no cierra D7.
- `OrganizationTimezoneAudit.organization` conserva CASCADE.
- `Owner`/`Pet` heredan `is_active` y el manager filtra activos. El bloqueo de `TenantQuerySet.delete()` no sustituye todas las rutas de borrado por instancia/collector.
- El modelo `Organization` inspeccionado **no tiene is_active**. La desactivación no se resuelve cambiando solo un label o suponiendo ese campo existente.
- Hay DELETE de consultas en `MedicalRecordDetailView`: rechaza cerradas, facturadas o con contenido clínico. La nota histórica “no hay endpoint” está obsoleta.
- La vista de cierre escribe `closed_at`, usa receipts, materializa borrador, sincroniza cita y abre Checkout primario. La extracción A3 debe conservar toda esa unidad transaccional.
- `Invoice.clean()` exige Checkout al crear y valida pertenencia de FKs; no crear un servicio paralelo que emita Invoice fuera de p62.
- `IsPlatformOperator` requiere autenticación, `is_superuser`, `is_staff` y `role='ADMIN_SAAS'`. Reutilizar ese predicado, no reducirlo a un string del payload.
- Existen protecciones en admin y guards de genéricos. No retirarlos globalmente para hacer funcionar la excepción.
- El venv del backend y Python global difieren del lock según el expediente corregido. Elegir y registrar runtime de pruebas explícito; no instalar sobre el venv/global ni actualizar locks como reparación lateral.

El grafo puede tener líneas/rangos antiguos: verificar fuente real cuando el snippet no corresponda al símbolo. No tomar un resultado incompleto como ausencia de implementación.

## 3. Invariantes de producto y datos

### Conservación

1. Archivo, restauración y borrado excepcional no eliminan ni recrean documentos financieros/clínicos, pagos, cargos, recetas, movimientos o auditorías.
2. No modifican importes, cantidades consumidas, anchors, estados de cobro, provenance financiera ni identidad tenant.
3. No se reasigna documentación a otro cliente, mascota genérica u organización para esquivar una FK.
4. Si una referencia no tiene una estrategia de conservación implementada y probada, el borrado físico se rechaza con blockers explícitos. No hacer cascade, nulificación indiscriminada o ampliación automática de alcance.
5. Mantener `organization_id` como autoridad tenant en documentos conservados. Desactivar no elimina la organización ni permite acceso cruzado.

### Archivo y restauración

- Archivar cliente evalúa citas y consultas abiertas del cliente y de todas sus mascotas; si hay un bloqueo, no se archiva parcialmente ninguna entidad.
- Usar estados de cita operativos reales para los blockers, incluyendo citas pendientes aunque su fecha haya pasado. No convertir una cita pendiente en no_show/canceled por decisión técnica.
- Una consulta abierta bloquea archivo hasta resolverse; no eliminar borradores automáticamente.
- Los cobros existentes pueden consultarse y seguir su liquidación pese al archivo. No habilitar nuevas citas/consultas/ventas a partir de un sujeto archivado.
- Restaurar mascota exige que exista y esté activo su cliente y la organización. Restaurar cliente no cambia el estado de mascotas archivadas previamente o por el archivo del cliente.
- Genéricos de walk-in no se archivan, eliminan o reasignan por estas operaciones.
- Repetir archive/restore con el mismo estado es idempotente: sin eventos duplicados ni cambios artificiales de fecha/actor.
- Archivo y creación concurrente de actividad deben coordinarse en servidor: revisar una vez `is_active` antes de otra transacción no basta. Mapear y coordinar los writers manuales, importación y agente que pueden crear citas/consultas con el sujeto. Preservar el orden global de locks y probar que no aparece atención nueva después del commit del archivo por una validación obsoleta.

### Desactivación de organización

- Activar/desactivar organización es operación de plataforma, no un campo editable por su personal en `/organizations/me/`.
- Conservar estados individuales del staff: reactivar la organización no reactiva usuarios que ya estaban desactivados ni cambia permisos.
- Rechazar acceso de personal con tokens previos, login/refresh y rutas de aplicación correspondientes mediante controles del servidor, sin depender solo de UI o expiración del access token.
- Bloquear admisión de nuevas operaciones automáticas de esa organización por los mecanismos pertinentes: worker, tools, jobs y sender. Conservar cola/datos y la política de incertidumbre de envíos; no reintentar efectos remotos ya aceptados ni prometer cancelarlos.
- Reactivar no abre autonomía/flags que antes estaban cerrados ni revive trabajos expirados, revocados o con autoridad inválida. Revalidar condiciones originales antes de reanudar.
- No introducir un nuevo rol/login ni retirar el fallback B3. Adaptar únicamente los gates que exige el estado de organización.

## 4. Estrategia de preservación y snapshots

### Antes de tocar FKs

El agente hará un mapa de referencias entrantes/salientes y de lectores reales para Owner/Pet/Organization y los nueve ítems. Debe incluir ORM, serializers, PDF, historial, filtros/KPIs, Checkout/Invoice, citas, vacunas, recetas, inventario, importaciones y referencias de agente cuando existan.

Clasificar cada relación: conservar padre protegido, permitir separación con snapshot válido, o bloquear operación. Registrar la decisión por campo en un ADR del orden 2 antes de implementar cambios de FK. No se requiere una nueva consulta de producto para decisiones técnicas que respeten este contrato.

### Política de documentos

- **A6:** dado que no se autoriza eliminar Invoice, eliminar el cascade destructivo y proteger documento/auditoría. Guardar referencia estable de factura en la auditoría cuando corresponda. No habilitar borrado de facturas para cumplir la receta antigua de SET_NULL.
- **D6:** receta y expediente con evidencia se conservan. Proteger la relación; el borrado de un sujeto operativo no borra ninguno de esos documentos.
- **D7:** proteger ledger frente a borrado de producto **y** presentación; no desbloquear sus DELETE actuales. Preservar referencias/identificación histórica necesarias para lectura.
- **D5:** conservar auditoría de timezone e identidad de organización. Una organización con esa auditoría ya no cumple “sin historial”; no eliminar el evento para volverla elegible.
- Documentar expresamente cuando la solución sea PROTECT y preservación del padre en lugar del SET_NULL histórico: se cierra la misma pérdida de evidencia conforme al contrato nuevo, con pruebas, no solo cambiando el estado de la deuda.

### Separación de clientes/mascotas de su historia

Para permitir su borrado físico cuando no hay actividad ni cobros pendientes, las relaciones históricas que se separen deben tener referencia y datos de presentación suficientes **antes** de quitar la FK. Se pueden usar snapshots versionados por documento o una referencia histórica de propósito acotado, reutilizando patrones existentes. Elegir una representación mínima en el ADR; no crear un framework de event sourcing.

Requisitos:

- UUID histórico y tenant preservados, diferenciados del recurso vivo. No fabricar un Owner/Pet vivo de sustitución.
- Datos mínimos que los lectores actuales necesitan: identidad mostrada del cliente/mascota y atributos del documento que no pueden depender de una fila viva. No copiar perfiles completos, secretos o datos sin consumidor justificado.
- Nuevos documentos capturan identidad en el evento de dominio pertinente. Un snapshot no se sobrescribe al renombrar, archivar, restaurar o borrar al sujeto.
- Históricos reconstruidos: fuente/procedencia y fecha real de reconstrucción; nunca atribuirlos falsamente al instante de emisión/cierre.
- Serializers/PDF/historial no fallan con una relación separada ni ofrecen enlaces funcionales a una entidad ya eliminada. Exponer identidad histórica sin hacerla seleccionable para nuevos writes.
- A2 debe seguir impidiendo FKs/referencias históricas de otro tenant. Permitir NULL por separación histórica no debe permitir crear nuevas facturas sin las identidades requeridas.
- No modificar relaciones de autoridad/consentimiento del agente a ciegas. Si hay referencias cuya conservación/invalidation no está cubierta, la API física devuelve un bloqueo; no relajar sus constraints para completar un DELETE.

### A7: veterinario

- Capturar al cierre el UUID y nombre profesional y, si ya existe y se usa en documentos, especialidad. No agregar cédula/funcionalidades de M01 ni email por defecto.
- El lector de un expediente cerrado usa el snapshot incluso si el usuario cambia de nombre. Mantener la atribución después de una eliminación administrativa futura del usuario sin habilitar esa eliminación en esta entrega.
- Procedencias diferenciadas: capturado al cierre, reconstruido desde fuente actual y desconocido. Registrar fecha real de captura/reconstrucción; no inventar nombre si la FK ya no resuelve.
- Backfill idempotente: solo completa lo que falta y nunca sobrescribe snapshots auténticos. No cambia `closed_at`, `closed_at_source`, `paid_at`, `posted_at`, `voided_at`, importes o stock.

## 5. Contratos de API y autorización

Los nombres de rutas siguientes son el contrato objetivo; ajustar solo lo necesario para encajar con el routing actual y documentar la equivalencia. UUID públicos, validación de payload y errores en español según convenciones existentes.

| Operación | Interfaz y comportamiento |
|---|---|
| Archivo/restauración de cliente/mascota | Acciones POST explícitas en sus recursos. GET con filtro de archivo autorizado permite localizar/restaurar archivados. Por defecto listados/selectores solo activos. |
| DELETE cotidiano existente de Owner/Pet | Convertir en alias compatible de archivo, no borrado físico. Mantener status de éxito compatible, refetch y etiquetas de UI acordes; aplicar el límite ADMIN. |
| ADMIN_SAAS sobre una clínica | Resolver organización objetivo explícitamente bajo namespace/predicado de plataforma; no depender de que el operador tenga organization propia. Reutilizar servicios de dominio. |
| Desactivar/reactivar organización | Acciones POST de plataforma por UUID de organización; motivo/auditoría y estado persistido. No habilitar PATCH de estado arbitrario desde tenant. |
| Borrado físico excepcional | Dos pasos de plataforma: preview y execute. Allowlist cerrada de tipos Owner/Pet/Organization; jamás aceptar nombre de tabla/modelo, queryset, lista de PK o SQL del cliente. |

### Borrado físico excepcional: protocolo obligatorio

1. **Preview sin borrado:** actor de plataforma autenticado, tipo/UUID objetivo, UUID de organización cuando corresponda y motivo. Devolver efecto previsto y blockers saneados, sin datos de otro tenant ni contenido clínico.
2. **Confirmación verificable por servidor:** ligada a actor, organización, objetivo, acción, motivo y versión/digest del impacto; caducidad breve documentada y consumo único. Un booleano `confirm=true` o una frase aislada no prueba que se confirmó el preview actual.
3. **Execute:** reautorización, confirmación válida e idempotency key obligatoria. Revalidar bajo transacción el estado, impacto, relaciones y blockers; si algo cambió, 409 y nuevo preview.
4. **Condiciones de elegibilidad:** sujeto archivado, sin citas/atención abiertas, sin cobros pendientes y con conservación demostrable de cada referencia. Cliente con mascotas aún existentes se bloquea: no borrar mascotas en cascada. Genéricos siempre bloqueados.
5. **Organización:** solo si está desactivada y no tiene historial ni dependencias. Settings, usuarios, roles u otras dependencias existentes se informan; no purgarlos automáticamente para hacerla elegible. Puede ser correcto que una organización provisionada no sea elegible.
6. **Atomicidad:** snapshots/referencias, separación permitida de FKs, resultado/auditoría y borrado se confirman juntos. Ante error o relación nueva no prevista, rollback completo.
7. **Concurrencia:** locks en orden documentado y revalidación; dos ejecuciones/replays no duplican efectos ni auditorías. Conservar restricciones DB: una carrera con una nueva dependencia debe terminar en conflicto seguro, no perder el hijo.
8. **Auditoría durable:** actor/UUID, rol de plataforma, organización lógica, tipo/UUID objetivo, motivo acotado, fecha, operación/idempotencia, resultado y resumen del impacto. No secretos, cuerpos clínicos ni snapshots completos en logs. Debe sobrevivir al objetivo; para una organización vacía no crear una FK de auditoría que impida su borrado o se borre con ella.
9. **Reintentos:** mismo key/payload y actor devuelve resultado estable incluso si el objetivo ya no existe; mismo key con otro payload se rechaza. El replay de una operación ya confirmada usa su receipt tras reautorización y no vuelve a ejecutar ni exige un objetivo vivo/nueva confirmación. El primer intento sí exige confirmación vigente. Nunca devolver el receipt de otro actor/tenant. No reutilizar ciegamente `billing.CommandReceipt`: su FK a organización podría impedir borrar una organización vacía.
10. **Fallo de auditoría/confirmación:** no borrar. Permisos insuficientes, confirmación vencida o tenant incorrecto nunca causan mutación.

Esta API no implementa anonimización ni un procedimiento ARCO: conserva documentos según el alcance acordado. No usar “borrado total de datos” como copy.

## 6. Plan por entregas y dependencias

### E0 — Baseline, mapa de conservación y ADR

- Revalidar código, routing, migraciones, constraints y lectores; registrar versiones del entorno elegido.
- Documentar relaciones y decisiones de preservación, contrato de snapshots, archivo, blockers y protocolo API. Inventariar gates de organización en autenticación y operaciones automáticas.
- Acordar técnicamente el orden de locks y alcance de cada transacción. No ampliar a limpieza general de serializers, RBAC o nuevas funciones clínicas.
- Preparar bases PostgreSQL dedicadas con fixtures sintéticos. La base habitual no es el baseline de prueba.

**Cierre:** ADR y matriz de ítems/pruebas concretos; controles de destino de DB verificados antes de cualquier comando Django.

### E1 — Referencias históricas, lectores y preservación (A6/D6/D7/D5, base de A5/A7)

- Añadir campos/estructuras de snapshot y procedencia con migraciones compatibles.
- Implementar lectores y fallbacks nulos antes de habilitar separación física; capturar datos en writers autoritativos, no solo en UI.
- Backfill sintético en upgrade, idempotente y sin reescribir anchors/ledger.
- Cambiar los CASCADE destructivos según el ADR, cubriendo ambos padres de StockMovement y auditorías.

**Cierre:** cambios conservan evidencia por API/ORM soportados y lectura histórica no depende de una entidad viva; nada habilita borrado excepcional todavía.

### E2 — Cierre clínico y snapshot de veterinario (A3/A7)

- Extraer a un servicio autoritativo manteniendo autorización, locks, validación por protocolo, materialización de borrador, consumo/cargos, cita, Checkout primario, late-arrival y receipt/replay existentes.
- La vista queda como adaptación HTTP. No sustituir Checkout por creación legacy de Invoice.
- Capturar snapshot al primer cierre; replay/cierre idempotente no lo recaptura ni cambia fecha/actor.
- Aplicar reconstrucción histórica marcada para lo recuperable y desconocido para el resto.

**Cierre:** paridad observable, rollback integral ante fallo y pruebas de snapshot auténtico/reconstruido/desconocido.

### E3 — Invariante tenant en factura (A2)

- Inspeccionar defensas reales de Checkout/Invoice y preservar las que ya funcionan. No eliminar `clean()` por cumplir una receta ni crear otro `create_invoice` paralelo.
- Garantizar pertenencia tenant de las referencias relevantes, incluidas Checkout y referencias históricas introducidas. Evaluar FK compuestas/constraints relacionales o triggers explícitos con migraciones reversibles cuando sea seguro.
- Cubrir create/update y cambios de padres que pudieran invalidar referencias existentes; no limitar la protección a DRF.
- Distinguir existencia de la referencia de su actividad: documentos históricos pueden apuntar a padres archivados del mismo tenant; nuevos writes no pueden usar sujetos archivados por conveniencia.
- El ejemplo antiguo de CHECK con subconsulta no se copia. PostgreSQL no admite CHECK contra datos de otras filas/tablas como garantía de esa relación.

**Cierre:** pruebas directas de DB/ORM bypass demuestran rechazo de referencias cross-tenant y aceptación de estados históricos válidos, sin romper p62.

### E4 — Archivo/restauración y organización (A5)

- Persistir metadata de archivo/actor y usar is_active coherentemente; añadir estado de organización y gates correspondientes.
- Implementar servicios atómicos y permisos ADMIN/ADMIN_SAAS. No cambiar el filtrado global de todos los modelos para mostrar archivados.
- Archivo de cliente con mascotas: todas o ninguna; archivo de mascota individual; restauración explícita con validación del padre activo.
- Mantener consulta y liquidación de cobros previos. Adaptar la selección de relacionados históricos para no ocultarlos por managers de activos.
- UI mínima siguiendo componentes actuales: Archivar/Restaurar, acceso autorizado a archivados y mensajes de blockers. No rediseño visual ni botón de borrado físico cotidiano.
- Desactivar organización bloquea personal/operaciones nuevas; reactivar conserva restricciones previas y no reabre autonomía por defecto.

**Cierre:** permisos, disponibilidad histórica, pagos pendientes, gates de acceso y carreras quedan cubiertos con fixtures aisladas.

### E5 — API física excepcional y cierre de A4

- Habilitar preview/execute solo después de preservación, lectores, DB guards y permisos validados.
- Probar borrado de mascota archivada con historia cerrada y cobros resueltos: no basta mostrar éxito sobre una fila sin referencias.
- Probar cliente archivado con documento financiero pagado y sin mascotas existentes; conservar identidad del documento y trazabilidad.
- Organizaciones con cualquier dependencia se bloquean; probar éxito en una organización realmente vacía y rechazo de provisionadas/con historial.
- A4 se resuelve evitando borrar por cascade un expediente con consumo/evidencia: proteger líneas/ledger y las rutas soportadas de borrado. No restock automático por archivo/borrado del padre.
- Conservar, si corresponde al contrato actual, eliminación de un borrador verdaderamente vacío, sin cargos, movimientos ni evidencia durable. No habilitar borrado de expediente cerrado o con contenido ni un endpoint clínico nuevo.

**Cierre:** conservación demostrada, idempotencia y auditoría durable; referencias no soportadas provocan rechazo explícito en vez de ampliar el cascade.

### E6 — Validación integrada y entrega

- Ejecutar gates de esquema, integridad, regresión clínica/financiera/tenant y frontend afectado únicamente en destinos aislados.
- Documentar por cada ID la solución aplicada, cambio de criterio respecto a deuda antigua, migraciones y pruebas que lo acreditan.
- Entregar diff revisable, limitaciones y procedimiento futuro de despliegue/aplicación local. No aplicar a la base habitual ni al VPS.

## 7. Matriz mínima de pruebas de aceptación

| Grupo | Casos obligatorios y resultado esperado |
|---|---|
| Preservación | A6/D6/D7/D5 no pierden documentos/ledger/auditoría ante intentos de borrado de sus padres; cubrir instancia y queryset/cascade soportados. Productos y presentaciones con movimientos permanecen protegidos. |
| FKs y lectores | Documentos conservados después de borrar sujeto admitido: API, PDF, detalle e historial muestran identidad histórica sin excepción ni reasignación. Cualquier relación desconocida bloquea borrado. |
| Snapshot | Renombre posterior no cambia snapshot auténtico; backfill marcado no modifica anchors; repetición no sobrescribe; fuente ausente queda desconocida. |
| Cierre | Primer cierre/replay/doble cierre y carrera: una materialización, consumo, sincronización y Checkout. Fallo intermedio revierte todo, incluido snapshot/receipt. |
| Tenant | Dos organizaciones: ADMIN no actúa sobre otra; snapshots de otro tenant se rechazan. Bypass bulk/update/SQL controlado en test no crea Invoice cross-tenant. Parent reparenting no corrompe referencias. |
| Archivo | Cliente+mascotas atómico; bloqueo por cita/consulta abierta sin archivo parcial; carrera archivo frente a creación de cita/consulta sin actividad nueva admitida por estado obsoleto; genérico rechazado; restaurar cliente no restaura mascotas; restaurar mascota exige padres activos. |
| Cobros | Archivo no altera deuda, importes, ledger o stock; liquidación válida sigue funcionando. Borrado físico con saldo/obligación pendiente se rechaza, aunque el sujeto esté archivado. |
| Organización | Login/refresh/tokens previos/rutas y admisión automática bloqueados al desactivar; plataforma conserva histórico. Reactivación no activa usuarios/flags/trabajos inválidos. |
| API física | Anónimo/VET/ASSISTANT/ADMIN tenant rechazados; predicado ADMIN_SAAS incompleto rechazado; UUID/tenant/tipo inválidos rechazados; motivo/confirmación obligatorios; vencimiento, actor equivocado y preview stale sin mutación. |
| Idempotencia y carreras | Dos execute simultáneos y replay producen un resultado/auditoría; key con payload distinto da conflicto. Nuevo hijo/actividad entre preview y execute produce rechazo/rollback, no pérdida del hijo. |
| Auditoría | Éxito conserva registro tras borrar objetivo; auditoría fallida impide operación. Snapshot/PII sensible no sale a logs. Organización vacía no pierde su recibo de borrado. |
| A4 | Expediente con productos, consumo o movimiento histórico no se elimina por una ruta soportada, aunque la línea activa ya no exista. No devolución de stock duplicada o por cascade. |
| Migraciones | Base vacía y upgrade con fixtures previas; backfill repetido, referencias históricas, datos desconocidos y validación de constraints. No fabricar sujetos para completar faltantes. |
| Compatibilidad | Listados activos/selectores, errores y UUID siguen contrato; archive/restore en UI autorizada; lectores nulos y cobros existentes sin regresión. |

Usar PostgreSQL real para constraints/carreras. No sustituir esos casos por SQLite o mocks de transacciones. Adaptar los tests históricos de PROTECT solo donde haya un nuevo criterio demostrado; no borrarlos o relajarlos para obtener verde.

## 8. Aislamiento, migraciones y reversión

- Antes de comandos Django, validar explícitamente host/puerto/nombre de base contra una allowlist de destinos de prueba recién preparados. No confiar solo en prefijo de nombre ni heredar DATABASE_URL de `.env` habitual.
- Fixtures exclusivamente sintéticas. No importar dumps reales, no resetear la base habitual ni detener servidores/procesos ajenos. Bloquear efectos externos de email, Meta, LLM, Sentry y deadman.
- Registrar runtime/versión de PostgreSQL y dependencias usados. Si hace falta preparar un entorno, hacerlo dedicado con las versiones existentes del lock, sin alterar global/venv habitual/locks. Si falta capacidad, informar limitación sin inventar PASS.
- No editar migraciones históricas aplicadas. Migraciones nuevas pequeñas, esquema aditivo antes de backfill y separación de referencias; operaciones de datos acotadas y provenance explícita.
- Si aparecen datos inválidos en una prueba de upgrade, clasificar y preservar. No borrar filas, inventar parents, desactivar constraints o fakear migraciones para pasar.
- Revertir código no recupera una entidad borrada físicamente. Las migraciones que vuelven a exigir FK no nula pueden dejar de ser reversibles después de separaciones reales: documentar y bloquear reversión insegura. Probar reversión donde sea válida; no prometer rollback universal.
- En este encargo no se aplican migraciones ni se ejecuta la API física sobre datos habituales. Operaciones destructivas se demuestran solo con fixtures descartables.

## 9. Gates y entregables

Gates en entornos aislados: `check`, ausencia de drift de migraciones, esquema Billing, anchors, payment ledger, FKs protegidas y tests relevantes. Si cambia frontend: pruebas de componentes/API afectadas, lint de archivos tocados y build. No ocultar errores nuevos ni convertir la deuda de lint global en un refactor lateral. Ejecutar suites más amplias una vez cuando los checks dirigidos pasen; repetir solo por cambios/fallos nuevos. No campañas B9/D29 ni upgrade general de dependencias.

Entregar en un expediente nuevo bajo `docs/remediaciones/orden-2/`:

1. README con revisión/entornos, alcance, decisiones y resultado por entrega.
2. ADR de conservación/API/snapshots y cambios respecto al backlog histórico.
3. Matriz por los nueve IDs: archivos, migraciones, pruebas, resultado y limitación.
4. Evidencia saneada de pruebas/migraciones fresh y upgrade, con comandos/configuración segura reproducibles y sin secretos/datos privados.
5. Guía de aplicación futura y límites de reversión, dejando base habitual/VPS explícitamente sin tocar.

Los campos funcionales y rutas finales deben quedar concretos en la implementación/ADR; no entregar TODOs o stubs que simulen conservación. La eliminación excepcional debe tener al menos los escenarios históricos positivos descritos; una API que solo rechaza todos los casos con historial no cierra ese contrato. Puede bloquear referencias adicionales concretas todavía no soportadas, pero deben quedar enumeradas y sin afirmar cierre más amplio que el probado.

Si un requisito central no puede cumplirse, informar entregas logradas y punto exacto incompleto; no marcar todo el orden 2 cerrado por haber escrito documentación o generado migraciones.

## 10. Referencias de implementación

- `backend/apps/{patients,organizations,medical_records,prescriptions,inventory,billing}/models.py`, serializers/views/admin y lectores/PDF correspondientes.
- `backend/apps/core/{models,authentication,permissions,middleware}.py`, `backend/apps/platform/{permissions,views,urls}.py`.
- `backend/apps/billing/checkout_services.py`, receipts y [contrato p62](decisions/2026-08-30-p62-billing-checkout-lifecycle.md).
- [Readiness de analítica](analytics-readiness-checklist.md), [lockdown anterior](decisions/2026-05-17-p16-pr4b-cascade-and-singleton.md), tests de cascade/tenant, cierre y Checkout existentes.
- [Diagnóstico corregido del entorno local](diagnosticos/orden-1/2026-10-28T174848Z/README.md).
- [PostgreSQL: constraints](https://www.postgresql.org/docs/current/ddl-constraints.html): relaciones entre tablas requieren mecanismos adecuados, no el CHECK histórico con subconsulta.
- [Django 6.0: on_delete](https://docs.djangoproject.com/en/6.0/ref/models/fields/#django.db.models.ForeignKey.on_delete): distinguir comportamiento del ORM de constraints SQL; comprobar ambos en el entorno objetivo, sin asumir que cambiar on_delete equivale por sí solo a una política SQL completa.
