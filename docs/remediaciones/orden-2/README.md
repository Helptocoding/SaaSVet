# Orden 2 — integridad y conservación (implementación local)

**Estado: implementación y validación local de los nueve IDs; aplicación futura pendiente.** Revisión base `8886604`; cambios sin commit. Sesión local: 28–29-10-2026. La base habitual local y el VPS **permanecen intactos**. Documentos ajenos no rastreados, incluido el cierre del orden 1, permanecen sin modificar.

## Entregas

- **E0:** [ADR-001](ADR-001-conservacion.md) clasifica padres protegidos, FKs separables y blockers; revalidación contra fuente actual por ausencia de herramientas del grafo en este harness.
- **E1:** PROTECT en InvoiceAuditLog/Prescription/ambos padres de StockMovement/TimezoneAudit y líneas clínicas; snapshots v1 de Owner/Pet en Checkout/Invoice/MedicalRecord/Prescription; backfill reconstruido/unknown; lectores de PDF, detalle e historial antes de separar referencias. Ninguna factura se vuelve target DELETE.
- **E2:** cierre autoritativo en `medical_records/services.py`; snapshot UUID/nombre/especialidad de veterinario capturado al primer cierre, reconstruido de fuente actual con hora real o desconocido. Pruebas de replay, concurrencia y rollback de fallo intermedio.
- **E3:** FKs compuestas tenant de Invoice y Checkout con claves únicas de padres, triggers de admisión y de snapshots inmutables; `Invoice.clean()` y flujo p62 mantenidos. Bypass ORM/SQL y cambio de parent cubiertos.
- **E4:** archivo/restauración de Owner/Pet, alias DELETE cotidiano, bloqueos por actividad abierta, metadata, vista mínima de archivados en Mascotas, estado de Organization y gates JWT/login/refresh/worker/sender. Rutas de plataforma para gestión e historia desactivada.
- **E5:** API física preview/execute con `IsPlatformOperator`, confirmación firmada de 300 s, receipt/auditoría idempotente sin FK al target y blockers para referencias no soportadas. Fixtures positivas: Pet con consulta cerrada/receta/factura pagada y Owner sin mascotas con documento pagado; PDFs, saldo y ledger sobreviven. Organización desactivada verdaderamente vacía es elegible, provisionada no. Guard clínico `pre_delete` impide perder evidencia por instance/queryset/collector.
- **E6:** fresh PostgreSQL final, upgrade sintético, reversión segura de trigger, pruebas dirigidas, gates financieros y frontend pasaron. La regresión ampliada de dominios afectados concluyó en grupos: Billing **71**, clínica/pacientes/recetas **231**, citas/inventario/organizaciones **224** PASS, además de importación y agente dirigidos. Corridas monolíticas anteriores agotaron el timeout sin resumen; no se usan como prueba. Validación local no implica aprobación de despliegue ni estado de datos habituales.

La [matriz de nueve IDs](MATRIZ.md) y [evidencia reproducible](EVIDENCIA.md) separan PASS de alcance no ejecutado. [Aplicación/reversión futura](APLICACION.md) deja explícitos los puntos sin vuelta automática.

## Límites observados

La eliminación física de Pet con Appointment, VaccineRecord, ConsultationAssessment, SurgeryRecord, EmergencyRecord o referencias de agente permanece bloqueada como `unsupported_reference` — no se ofrece pérdida silenciosa. La historia de facturas/expedientes de los sujetos borrados sí se conserva y lee mediante el snapshot; esto no es anonimización. No se ha probado recepción externa ni entrega efectiva de proveedores, y no se activó nada en el VPS.
