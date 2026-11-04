# Metaprompt ejecutor — Remediación local del orden 2

Copiar el encargo siguiente al agente que implementará. El [plan detallado](plan-remediacion-orden-2-2026-10-28.md) contiene los acuerdos completos, dependencias y matriz de aceptación.

---

Trabaja en `C:\Users\LAP\Desktop\VeterinariaSaaS`. Implementa el **orden 2: integridad y conservación de datos**, conforme a `docs/plan-remediacion-orden-2-2026-10-28.md`.

Este encargo autoriza código, migraciones y pruebas locales aisladas. No es otro diagnóstico pasivo. Debes cubrir **A6, D6, D7, A5, A7, A3, A2, D5 y A4**, por entregas pequeñas y con evidencia real por ítem. El VPS y la base habitual local quedan fuera de ejecución.

## Acuerdos del usuario: no volver a preguntarlos

1. Puedes modificar código y generar migraciones; **solo aplicarlas y probarlas en bases aisladas**. La base habitual contiene demos recreables, pero no está autorizado modificarla, resetearla ni migrarla.
2. VPS aplazado: sin SSH, proveedor, despliegue, reactivación o activación. No condiciona análisis/código/pruebas locales.
3. Clientes y mascotas se archivan y restauran. Solo ADMIN de la propia clínica y ADMIN_SAAS pueden hacerlo; no VET/ASSISTANT.
4. Archivar cliente archiva también sus mascotas activas, en una transacción. Restaurar cliente no restaura mascotas; se eligen individualmente después y requieren cliente/organización activos.
5. Citas pendientes y atención clínica abiertas bloquean archivo; no cancelarlas/completarlas automáticamente. Cobros pendientes permanecen consultables y liquidables después del archivo.
6. Organización con historia/dependencias se conserva desactivada. Su personal no accede y no se admiten operaciones automáticas nuevas; reactivar no resucita usuarios inactivos, autonomía cerrada o trabajos inválidos. ADMIN_SAAS conserva histórico.
7. Borrado físico excepcional: API exclusiva de plataforma para ADMIN_SAAS, confirmación verificable, motivo, auditoría durable e idempotencia.
8. Targets físicos: solo Owner, Pet y Organization realmente vacía/sin dependencias. No usuarios, productos, presentaciones, facturas, expedientes con contenido, recetas, movimientos ni auditorías.
9. Borrado físico bloqueado por cobros pendientes, citas/atención abiertas, genéricos o una referencia cuya conservación no esté implementada. Cliente con mascotas existentes no se borra en cascada.
10. Historia conservada con identidades/snapshots: no reasignar a genéricos u otra clínica. La operación no es anonimización ni borrado total de datos.
11. Expedientes cerrados sin snapshot de veterinario: reconstruir lo recuperable de datos actuales, marcado como reconstruido y con fecha real; lo irrecuperable es desconocido. No falsificar nombre/fecha histórica.
12. No commit/push/PR/merge automático ni cambios de órdenes ajenos. Mantén los archivos del usuario y el cierre del orden 1.

## Preflight y disciplina del repositorio

- Lee AGENTS.md, referencia RTK, plan detallado, fuentes vigentes y estado Git. No reset/stash/borrado de cambios ajenos.
- Usa codebase-memory-mcp para descubrimiento, trazas y snippets. Si faltan o están desfasados, verifica fuente actual y documenta fallback; un rango viejo no demuestra ausencia.
- RTK en comandos donde haya filtro; `rtk proxy` en el resto. No instalar herramientas en el VPS ni tocarlo.
- Selecciona explícitamente runtime y PostgreSQL de pruebas. El diagnóstico del orden 1 separa Python global y venv con diferencias; no atribuyas el lock al runtime sin comprobar metadatos.
- Si preparas entorno, usa uno dedicado con pins existentes. No upgrades, cambios a locks o instalaciones en global/venv habitual para remediar otra deuda.
- Antes de cualquier comando Django, valida destino completo de DB contra una allowlist de pruebas. No heredar `.env`/DATABASE_URL habituales ni usar la base habitual para introspección/migraciones/tests.
- Fixtures sintéticas; sin dumps reales, secretos del operador o red de proveedores. Deshabilita envíos Meta/LLM/email/Sentry/deadman en pruebas. No detener procesos existentes para liberar puertos sin necesidad/autorización.

## Trabaja por estas entregas, sin detenerte solo en el plan

### E0 — Contrato técnico y baseline

Revalida relaciones y lectores y escribe un ADR concreto. Define por campo qué padre se protege, qué FK puede separarse con snapshot válido y qué bloquea borrado. Incluye clientes/mascotas/organización, auditorías, Invoice/Checkout, citas, recetas, vacunas, movimientos y referencias de agente pertinentes. No amplíes a un rediseño general.

No necesitas nueva aprobación para elegir detalles técnicos que cumplan estos acuerdos. Si surge una contradicción de producto irreconciliable, explica la alternativa concreta y pregunta solo eso; continúa lo independiente.

### E1 — Conservación y lectores

- A6: Invoice no es target físico. Quita el cascade destructivo que elimina su auditoría y conserva referencias estables; no habilites Invoice DELETE para seguir una receta vieja.
- D6: conserva receta y expediente con evidencia. Protege la relación; borrar un sujeto operativo no elimina documentos.
- D7: cubre CASCADE de StockMovement hacia **product y presentation**. Ambos deben preservar ledger y mantener bloqueos de borrado actuales.
- D5: conserva auditoría de timezone/identidad de organización; su existencia bloquea que se considere una organización vacía.
- Introduce snapshots/referencias históricas y sus lectores antes de separar FKs para borrar Owner/Pet. Captura datos mínimos con consumidor justificado, UUID/tenant/procedencia/fecha; no perfiles completos.
- Adapta serializers, PDFs, detalle, filtros/historial y cobros a sujetos históricos sin fila viva. No ofrezcas links/selecciones de escritura para identidades eliminadas.
- Backfill idempotente y honesto; no cambiar anchors, cantidades, importes o stock.

Documenta cuándo una solución PROTECT satisface la conservación elegida aunque el backlog antiguo propusiera SET_NULL. No cierres un ID cambiando solo documentación.

### E2 — A3/A7: cierre autoritativo y snapshot de veterinario

Extrae el cierre a servicio preservando autorización, atomicidad, locks, receipt/replay, validaciones por protocolo, borrador/materialización, consumo/cargos, cita, Checkout primario y late-arrival. La vista queda como adaptación HTTP. No introducir emisión legacy de Invoice.

Captura snapshot al primer cierre; replay/cierre repetido no lo recaptura. Lectores cerrados usan snapshot aunque cambie el usuario. Históricos: reconstruido desde fuente actual o desconocido, diferenciados del capturado al cierre. No agregar la cédula M01 o email sin necesidad del contrato actual.

### E3 — A2: invariante tenant real

Inspecciona defensas actuales de Checkout/Invoice antes de cambiarlas. No crees otro create_invoice paralelo ni elimines clean() solo por una checklist vieja.

Implementa garantía relacional adecuada en DB y servicio para FKs/referencias históricas, incluyendo Checkout cuando aplique. Cubre inserts/updates/bypasses y cambios de padres que invalidarían la pertenencia. No copies el CHECK con subconsulta de la deuda antigua: no es una garantía soportada entre tablas en PostgreSQL.

Una referencia archivada del mismo tenant puede ser válida en historia; un sujeto archivado no debe habilitar nuevos writes. La nulificación histórica no autoriza nuevas facturas sin identidades requeridas.

### E4 — A5: archivo/restauración y estado de organización

Implementa estado/metadata de archivo, permisos, servicios atómicos y UI mínima con componentes existentes. Convierte DELETE cotidiano de clientes/mascotas en alias de archivo compatible; borrado físico solo en plataforma.

No cambies globalmente managers para mostrar inactivos. Las lecturas de historia deben incluir relacionados archivados **manteniendo scope tenant**. Los cobros previos siguen operando; nuevas citas/consultas/ventas no usan sujetos archivados.

Organization no tiene is_active en la fuente inspeccionada: añade su estado y gates coherentes; no basta mostrar un botón. Estado organizativo solo modificable por plataforma. Cubrir login/refresh/tokens previos, rutas y admisión de operaciones automáticas sin cambiar flags/autonomía o reintentar efectos inciertos. Al reactivar, conservar estados individuales y revalidar trabajo pendiente.

### E5 — API física y A4

Reutiliza `IsPlatformOperator` completo: autenticación + is_superuser + is_staff + role ADMIN_SAAS. No aceptes autoridad/actor desde el payload ni nombres de tabla/modelo arbitrarios.

Protocolo preview→confirmación→execute:

- Preview sin borrar, tipo allowlist/UUID/org explícitos/motivo y efecto/blockers saneados.
- Confirmación emitida/verificada por servidor, ligada a actor/org/objetivo/acción/motivo/impacto, con caducidad breve y consumo único. No solo confirm=true.
- Execute con idempotency key; reautoriza/revalida bajo transacción. Preview vencido o impacto cambiado produce conflicto sin mutación.
- Snapshot, separación de relaciones permitidas, borrado y auditoría durable confirman juntos; error revierte todo.
- Dos ejecuciones/replay no duplican efecto ni auditoría; mismo key con payload diferente se rechaza. El replay confirmado devuelve receipt solo al actor/tenant autorizados, aunque el target ya no exista, sin reejecutar ni pedir una confirmación nueva; el primer intento exige confirmación vigente.
- Organización vacía: ninguna dependencia se elimina a escondidas. Settings, roles y usuarios existentes son blockers. El recibo debe sobrevivir sin crear una FK que impida borrar el propio target o desaparezca con él.
- No reutilices ciegamente billing.CommandReceipt para organizaciones: hereda FK tenant PROTECT.
- Si un vínculo de autoridad/consentimiento o documento no tiene preservación probada, bloquear con código/motivo; no relajar constraints para hacer pasar el borrado.

A4: impedir cascade destructivo de expediente con consumo/evidencia en rutas soportadas, instancia/queryset/collector donde corresponda. No restock por archivo o por borrar padre; no exponer un DELETE clínico nuevo. El endpoint actual existe con guards: conserva eliminación de un borrador realmente vacío solo si no pierde evidencia durable, cargos o movimientos históricos.

### E6 — Regresión y entrega completa

Implementa y ejecuta la matriz de aceptación del plan. Como mínimo:

- Conservación A6/D6/D7/D5; snapshots auténticos/reconstruidos/desconocidos y renombre posterior.
- Cierre idempotente/concurrente y fallo intermedio: sin cobros/consumo/Checkout duplicados y rollback íntegro.
- Dos tenants, permisos ADMIN/ADMIN_SAAS, genéricos protegidos, bypass ORM/DB de A2 rechazado.
- Archivo cliente+mascotas todo/nada, actividad abierta bloquea, restauración selectiva y padres activos.
- Cobros pendientes liquidables tras archivo y bloqueantes de borrado físico.
- Organización inactiva niega personal y operaciones nuevas; reactivación no abre usuarios/autonomía inválidos.
- API física: permisos, motivo/confirmación, vencimiento/actor/tenant, stale preview, reintentos y carreras con nuevo hijo; fallo de auditoría revierte.
- **Éxitos históricos reales con fixtures:** mascota archivada con consulta cerrada/receta y factura pagada; cliente archivado con documento pagado y sin mascotas existentes. Documentos, saldos, ledger y lectura sobreviven. Una API que rechaza todos los casos con historia no acredita ese contrato.
- Organización realmente vacía eliminable y con historia/dependencias rechazada; productos/usuarios/presentaciones no habilitados como targets.
- Migración desde cero y upgrade con datos sintéticos previos, backfill repetido y reversión cuando sea segura.

Usa PostgreSQL real para constraints/carreras. No SQLite, mocks de transacción, tests borrados, expectedFailure o skips ocultando el invariante. No fabricar padres o borrar datos para validar constraints. No aplicar migraciones a la base habitual.

Gates aislados: check, drift de migraciones, esquema Billing, anchors, ledger, FKs y suites afectadas. Si cambias frontend, tests pertinentes, lint de archivos tocados y build; respeta diseño existente, sin rediseño ni refactor de lint/auth ajeno. Amplía regresión una vez tras pasar lo dirigido. No campañas B9/D29 ni nuevos escaneos de seguridad.

## Migraciones, reversión y finalización

No editar migraciones históricas. Separar esquema compatible, lectores/backfill y habilitación de separación física. Un rollback de código no recupera una fila físicamente borrada; no prometer reversión de nullabilidad/FKs si ya existen referencias separadas. Probar reversión segura y documentar los puntos sin vuelta automática.

Crea expediente nuevo bajo `docs/remediaciones/orden-2/` con README, ADR, matriz de los nueve IDs, evidencia saneada de pruebas/migraciones y guía futura de aplicación/reversión. Registra revisión/runtime/DB de cada validación; nada de dumps, PII, claves, logs crudos o datos del operador en Git.

Entrega cambios completos y revisables, sin placeholders/stubs. No termines solo con propuesta, modelo o migraciones sin validar. Si un requisito central no se puede lograr, identifica entrega exacta incompleta y conserva lo logrado; no marques el orden 2 cerrado por documentación ni por un bloqueo que impida todos los casos positivos acordados.

Resume al final qué cambió, qué pruebas pasaron, qué limitaciones quedan y que **base habitual y VPS permanecen intactos**. No hagas commit/push/PR/merge ni despliegue por iniciativa propia.

---

Fuentes normativas de este encargo: decisiones del usuario y plan detallado. Los documentos antiguos son contexto, no permiso para alterar estas decisiones. Para detalles de constraints/on_delete, consultar la documentación oficial enlazada en el plan y verificar el comportamiento en PostgreSQL aislado.
