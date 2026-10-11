# R1-02: plan prospectivo limitado a obtener la base inicial

Fecha: 2026-10-07. Baseline: `825db75df68bf076929fa787e77beefe96803350`.
Autorización: encargo humano de esta fase, exclusivamente caracterización inicial
de R1-02 para obtener CONFIRMED_BASE; sin buscar máximo, E ni ejecutar dependientes.
Estado global conservado: `CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY`.

## Inspección y ruta vigente

Se inspeccionaron D29-v1 §1–§8, su manifiesto, la receta R1-02, Controller.search,
LiveBackend, execute_job, reconstrucción de episodios y gates de aceptación.
§5 permite terminar el presupuesto de exploración sin localizar frontera y aun
confirmar el mayor nivel compatible observado. §7 declara adaptativo el presupuesto
operativo de niveles mediante otro plan/ID, motivo y evidencia. Parameters acepta
un presupuesto positivo de uno; el controlador existente no necesita cambios.

El plan sellado usa **max_levels=1**, con motivo respaldado por el límite explícito
del usuario. Los demás parámetros permanecen en sus defaults. No se cambian
contratos, fuentes del controlador ni el significado de CONFIRMED_BASE. Este
presupuesto cierra la exploración en el primer nivel: no ofrece niveles superiores,
no genera un bracket, no refina y conserva `located_frontier=false` si confirma.

1. CALIBRATE: dos organizaciones, diez episodios ordinarios por organización,
   tres conversaciones rotadas por organización; oferta siguiente condicionada
   al claim real de la anterior. Captura antes de toda oferta. READY natural.
2. R_ref por organización = 60 × episodios servidos / intervalo desde primer
   READY hasta último claim exterior confirmado. No es tasa sostenible ni máximo.
3. SCREEN: un solo nivel equilibrado, 0.5 × min(R_ref) por organización durante
   360 s. Tasas numéricas se derivan exclusivamente de la medición física.
4. Si es OBSERVED_COMPATIBLE: CONFIRM 900 s × tres repeticiones independientes,
   cada una con nueva base, salida y run_id. Seguimiento posterior hasta 240 s,
   sin nuevas ofertas y conservando pendientes. Ningún éxito parcial se reutiliza.
5. Solo tres confirmaciones compatibles permiten establecer la base. Luego parar;
   R1-03/04/05/06 conservan sus condiciones pendientes y no consumen el artefacto.

## Condiciones y criterio

Dos planners concurrentes, un sender separado, batch=1, pausa=1 s. Fixture público
READ contenido: dos llamadas LLM × 500 ms, HTTP de dominio 100 ms y Meta 200 ms;
latencias reales observadas en wire. N1, debounce, deadlines, leases, budgets,
backoffs, CAS, guards y configuración de producción permanecen en el baseline.
PostgreSQL local privado durable con fsync/synchronous_commit activos y clones
test_* nuevos. Fuentes archivadas y provider sin destinos externos reales.

Cada nivel necesita población completa, todas las ofertas conciliadas con
aceptaciones durables y episodios realmente READY, pacing conforme, claims
exteriores committed, continuidad y clocks correlacionados; W_hi ≤120 s para cada
episodio, sin pendientes censurados/indeterminados ni violaciones. Colas READY
sin nuevo claim se evalúan por organización y globalmente en ventanas de 120 s;
la confirmación retiene además el resto de 60 s. No debe existir patrón de tres
incrementos completos consecutivos ni cola final superior que deje tendencia
indeterminada. Historiales, no snapshots aislados, acreditan estas condiciones.

Exceso demostrado o crecimiento rechazan el nivel. Indeterminación, desviación
de oferta/preparación o violación de invariantes detienen la serie. Con un único
candidato no existe candidato inferior previamente acreditado para descenso:
si falla no se inventa uno; se conserva la falta de base y se solicita la decisión
prospectiva que corresponda después de analizar evidencia y causa.

Rollback: terminar los participantes, retirar exclusivamente cada clone creado,
verificar su cleanup, eliminar el template privado, detener PostgreSQL privado y
retirar el directorio temporal y sus credenciales tras verificar su ruta absoluta.
La evidencia se conserva sin sobrescribir corridas; hashes antes/después prueban
baseline, fuentes previas y ambos conjuntos históricos de receipts intactos.

## Separación metodológica

Medición alimenta referencia; SCREEN caracteriza un nivel; CONFIRM lo confirma;
CONFIRMED_BASE conserva el nivel y su procedencia. Ninguno calcula E, capacidad
máxima, capacidad comercial, cobertura universal, sostenibilidad formal o cierre
de la matriz. Replay puede verificar herramientas y jamás sustituye confirmación.
El campo histórico `benchmark_executed` del resultado del controlador significa
`not backend.synthetic`; se conservará literalmente. El alcance real es esta
única serie inicial autorizada, sin benchmark comparativo ni búsqueda de máximo.
