# Continuación del orden 4 desde el avance parcial

Preparado el **31-10-2026**. Copiar el bloque siguiente al agente ejecutor. No implica despacho automático a otro chat ni ejecución de la implementación.

---

Retoma la implementación local del orden 4 en `C:/Users/LAP/Desktop/VeterinariaSaaS` desde el estado actual. La entrega anterior fue parcial: B7 tiene cambio y pruebas de helper, mientras I01/I02/I03/I05 siguen pendientes e I07 no tiene diagnóstico reproducible. No repitas solo la planificación ni recrees el expediente como sustituto de los cambios.

Lee completos:

- `docs/plan-remediacion-orden-4-2026-10-30.md`: contrato normativo de decisiones, entregas, pruebas y límites.
- `docs/metaprompt-remediacion-orden-4-2026-10-30.md`: instrucciones originales de ejecución.
- `docs/remediaciones/orden-4/REVISION-2026-10-31.md`, README, MATRIZ y EVIDENCIA: avance comprobado y límites.

## Autorización vigente

Implementar código local y preparar migraciones; aplicar y validar solo en bases aisladas con datos sintéticos. **No tocar la base habitual, clusters existentes ni VPS**, aunque contengan demos. Sin SSH, pagos, reactivación, regularización real, commit/push/PR, despliegue o trabajo de otros órdenes. I04/I06 siguen aplazados. I07 requiere aprobación futura por producto y no autoriza emitir aperturas ahora.

Conserva cambios previos del checkout y la implementación de B7. No restablezcas archivos ni copies versiones antiguas del grafo sobre cambios locales. Respeta AGENTS/RTK, usa MCP para descubrimiento si está disponible y documenta fallback a fuentes actuales si no lo está. La indisponibilidad del grafo no bloquea por sí sola la implementación.

## Resolver el entorno sin usar destinos ajenos

En la revisión del 31-10 se localizaron:

```text
C:/Program Files/PostgreSQL/18/bin/postgres.exe
C:/Program Files/PostgreSQL/18/bin/pg_ctl.exe
C:/Program Files/PostgreSQL/18/bin/initdb.exe
```

`postgres.exe --version` devolvió 18.3. Verifica de nuevo y usa rutas absolutas; no necesitas modificar PATH global ni instalar PostgreSQL solo porque no aparezca en PATH. Esto no acredita que un cluster de prueba ya esté disponible.

Prepara un cluster **nuevo y exclusivo del orden 4**, en un directorio descartable propio, no existente, con puerto libre y escucha solo en loopback. Verifica los paths absolutos y separación de la base habitual y del runner/cluster de orden 2 antes de inicializar o iniciar. No uses el servicio PostgreSQL habitual ni adaptes la allowlist de orden 2 para apuntar a un destino diferente. Puedes reutilizar patrones de aislamiento tras leerlos, conservando sus límites y creando configuración/allowlist propias.

Configura host/puerto/base/usuario de prueba explícitos y verifica destino efectivo antes de cualquier migración/test. No heredes credenciales/conexiones de `.env` ni muestres valores de secretos. Usa datos sintéticos. Solo detén procesos propios identificados por tu directorio y puerto; cualquier limpieza futura verifica previamente que la ruta está dentro del área descartable creada para esta tarea. No borres ni muevas directorios de PostgreSQL ajenos. Si lanzas un helper en Windows, hazlo oculto salvo necesidad interactiva explícita.

Si el entorno rechaza arranque, permisos o una prueba, registra el comando saneado y el error exacto; intenta alternativas locales autorizadas que mantengan el aislamiento. No conectes la base habitual ni eleves privilegios sin el mecanismo de autorización correspondiente. Continúa mientras tanto con implementación, migraciones preparadas y pruebas independientes. Un bloqueo de ejecución de DB no es automáticamente un bloqueo de todo el código.

## Trabajo restante

1. **B7:** conserva el helper y los tests existentes (35/35 repetidos en revisión). Completa comprobación visual local del orden mostrado y sus controles o evidencia de integración pertinente. Registra el resultado. Los cinco errores de lint reportados como previos deben quedar separados de regresiones; no amplíes el trabajo a una limpieza global.
2. **I02:** normalización común de `Presentation.quantity`/`conversion_factor`, rechazo de contradicciones y transición de precisión 2/4 decimales. Preparar schema nuevo y backfill idempotente solo del alias desde factor válido, sin cambiar factor, saldos, lotes, ledger o snapshots. Probar fresh/upgrade en PostgreSQL aislado. No editar/repetir 0018 ni redondear el factor para adaptarlo al alias.
3. **I01:** conservar captura manual y crear stock inicial con el writer autoritativo una sola vez, desde saldo cero, en la transacción de creación; actor, conversión, rollback y paridad con importación. Preservar recepción por lotes y no inventar atomicidad entre peticiones. Actualizar el gate que actualmente fija la deuda del alta manual sin debilitarlo.
4. **I03:** muestra máxima 100, totales exactos y detalle completo paginado/versionado (default 50, máximo 100), estable por ejecución, sin recalcular contra catálogo cambiante. Persistencia acotada, tenant/RBAC, cursores, transición de reportes legacy y UI de preview/resultado. No cambiar decisiones de importación ni dividir el commit en lotes por paginar la lectura.
5. **I05:** propagar el código `demo_account_restricted` en 403 de importación, manteniendo bloqueo y otros contratos. No basta ocultar botones ni alterar el handler global indiscriminadamente.
6. **I07:** implementar diagnóstico reproducible y probarlo con fixtures sintéticos, sin escrituras de dominio. Clasificar baseline, cobertura insuficiente, legacy, lotes y ambigüedades. Propuesta por producto con saldo/unidad/watermark, efectos y aprobación futura pendiente. Una entrada inicial no es automáticamente el adjustment que busca el auditor; no insertar ajustes para conseguir PASS.

Preserva las correcciones existentes de commit concurrente, validate/mapping coordinados y lectura perezosa con caps, además de conservación/organización desactivada del orden 2. El plan original sigue definiendo todos los criterios de aceptación.

## Evidencia y cierre

Ejecuta pruebas dirigidas significativas por entrega. Para locks/concurrencia y migraciones usa PostgreSQL aislado real; mocks/SQLite no acreditan esas propiedades. Repite checks/build solo cuando los cambios o dudas lo justifiquen. No hagas campañas B9/D29, escaneos o instalaciones ajenas para completar este encargo.

Actualiza los seis documentos del expediente a medida que implementas. Cada estado debe enlazar código, prueba/comando, resultado y límites reales. No conviertas «documentado», «test escrito» o «migración preparada» en «verificado». No afirmes cierre de la base habitual o producción por una prueba aislada.

El alcance local se completa cuando I01/I02/B7/I03/I05 están implementados y suficientemente verificados, I07 tiene diagnóstico reproducible/propuesta preparada y I04/I06 permanecen aplazados. La regularización real sigue pendiente de aprobación por producto.

Continúa autónomamente con el trabajo ya autorizado hasta completar ese alcance o identificar un bloqueo concreto e inevitable. Si una parte queda bloqueada, completa lo independiente y especifica qué falta y qué evidencia o intervención mínima permite continuar. No uses un nuevo resumen de pendientes como sustituto de implementación ni pidas de nuevo decisiones ya respondidas.

---

Contrato: [plan del orden 4](plan-remediacion-orden-4-2026-10-30.md). Contraste del avance: [revisión](remediaciones/orden-4/REVISION-2026-10-31.md).
