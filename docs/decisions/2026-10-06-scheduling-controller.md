# SaaSLyVet — controlador D29 y acreditación finita

Fecha del encargo: 2026-10-06. Baseline: `825db75df68bf076929fa787e77beefe96803350`.

Estado: **CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY**.

El encargo «hazlo» autoriza completar la secuencia del controlador de pruebas, los criterios de evaluación y la preparación de escenarios, y validarlos mediante casos finitos aislados. No autoriza el barrido sostenido, benchmarks, tuning, implementación de scheduling, cambios del runtime ni modificación de E4. El [recibo de esta entrega](../evals/scheduling-controller-2026-10-06/report.md) distingue las validaciones del modelo, del pipeline real y los pendientes de integración. No se reescriben D29-v1 ni recibos anteriores.

## Capacidades implementadas

| Archivo | Responsabilidad |
| --- | --- |
| [controller.py](../../backend/apps/agent/tests/scheduling_characterization/controller.py) | Plan sellado, calibración, avance, refinamiento, confirmaciones y descenso a un candidato inferior; IDs nuevos y parada conservadora. |
| [assessment.py](../../backend/apps/agent/tests/scheduling_characterization/assessment.py) | Conciliación de oferta/cohorte, ventanas y crecimiento por organización/global, pertenencia, admisión durable, N=1 en dispatch y clasificación. |
| [recipes.py](../../backend/apps/agent/tests/scheduling_characterization/recipes.py) | Fronteras y variantes de los 17 escenarios; orden, tenant, clocks y reglas de recuperación natural. |
| [replay.py](../../backend/apps/agent/tests/scheduling_characterization/replay.py) | Historias sintéticas con reloj virtual, separadas de cualquier aceptación de carga real. |
| [execution.py](../../backend/apps/agent/tests/scheduling_characterization/execution.py) | Ejecutor aislado, verificación contra fuentes del baseline, participantes, provider contenido, pacing y prueba finita. |
| [scenario_observations.py](../../backend/apps/agent/tests/scheduling_characterization/scenario_observations.py) | Testigos derivados de journals/DB/provider; ausencia de una frontera deja el caso indeterminado. |
| [test_scheduling_controller.py](../../backend/apps/agent/tests/test_scheduling_controller.py) | 30 pruebas nuevas de fallos del controlador, criterios y recetas. |

Se conservan sin modificar `runner.py`, `evidence.py`, las 25 pruebas anteriores, los contratos y toda la evidencia E4. Ningún módulo nuevo es importado por el runtime.

## Secuencia y reglas

Las calibraciones esperan el claim de cada episodio antes de ofrecer el siguiente de esa organización. La referencia es una observación del fixture, no capacidad máxima. El primer nivel usa 50% de esa referencia, avanza ×1.5 y refina por puntos medios hasta el bracket relativo declarado. Filtro, confirmación y repeticiones conservan 360 s, 900 s y tres como defaults iniciales del ensayo.

Una confirmación incompatible descarta ese conjunto y selecciona un candidato inferior previamente observado. Se necesitan tres repeticiones nuevas: no se reutilizan éxitos anteriores ni se promedian fallos. Si ese descenso amplía el intervalo, el recibo conserva tanto el bracket exploratorio como el candidato confirmado y las tasas rechazadas; no afirma que el nuevo bracket cumple la precisión del refinamiento anterior. Si no aparece un nivel incompatible antes del presupuesto, informa frontera no localizada; no llama capacidad máxima al último nivel.

La oferta se calcula con aritmética racional y ventanas semiabiertas: una suma de redondeos no debe crear un intento espurio justo al cierre. Cada intento debe comenzar en el intervalo de pacing declarado; faltantes, duplicados o intentos no previstos invalidan la conformidad. Todas las aceptaciones durables se concilian con la población completa. Si la oferta pretendía episodios distintos y los mensajes se agrupan, se informa demanda coalescida y no se certifica esa tasa nominal como episodios READY.

Se reportan por separado tasas planificadas, aceptaciones, episodios READY dentro de la oferta y obligaciones que alcanzan READY después de cerrarla. Estas últimas conservan su reloj y seguimiento. No se fuerza READY ni se acortan debounce, leases o backoffs. Los cortes de cola se reconstruyen desde la historia completa, con reloj correlacionado, por organización y globalmente; el resto final de un minuto en confirmaciones de 15 minutos se conserva y no cuenta como ventana completa de dos minutos.

Pendientes, clocks inconsistentes, cohortes incompletas, referencias no acreditadas o falta de testigos impiden éxito. Un exceso demostrado se conserva incluso si coexisten otros problemas. Una violación de invariantes detiene la serie. Los fallos tienen cobertura contractual pendiente y no reciben PASS comercial. La verificación de fuentes preserva los locks, CAS, budgets y guards originales; los testigos nuevos acreditan hechos observados de pertenencia y dispatch, no una demostración universal del código.

## Parámetros adaptativos y procedencia

Los defaults iniciales siguen el [protocolo D29-v1](2026-10-05-scheduling-characterization-protocol.md): 10 episodios por organización en calibración, tres conversaciones, ocho niveles y 240 s de seguimiento después de la oferta. El controlador añade un máximo operativo de 32 pasos de refinamiento para impedir una secuencia sin límite; es un límite del instrumento, no del servicio. El presupuesto de niveles se aplica a la exploración; refinamiento y confirmaciones tienen sus propios presupuestos, identificados en el plan.

Estos números de prueba son adaptativos entre corridas. Cambiarlos exige otro plan/ID, motivo y evidencia; el hash de parámetros, protocolo y fuentes queda sellado antes de ejecutar. La estrategia de avance prevista puede cambiar la tasa dentro de la serie según los resultados, pero no se cambian retroactivamente sus reglas o cohortes para salvarla. El objetivo de producto de 120 s permanece separado y necesita una decisión explícita para cambiar. E sigue `null`.

Los números 12, 6.4 o 6 presentes en el replay son valores inventados de una historia de pruebas para ejercer decisiones del controlador. No son tasas medidas ni recomendaciones de carga. `SYNTHETIC_REPLAY_NOT_LOAD_ACCEPTANCE` acompaña todas sus observaciones; un recibo sintético nunca puede mezclarse con uno real para completar una serie.

## Preparación real de la matriz

| Escenarios | Preparación | Acreditación obtenida aquí |
| --- | --- | --- |
| R1-01–R1-06 | Oferta/captura y extracción de fronteras implementadas. R1-04 exige observar misses con READY coexistente; R1-05/R1-06 necesitan base confirmada y fixture suficiente. | Secuencia y gates mediante replay; pipeline real finito común. No niveles de carga ejecutados. |
| R2-01, R2-02, R2-09 | Provider contenido con lentitud, bloqueo o incertidumbre y observación de fronteras. | Recetas/gates mediante replay. Las inyecciones reales de estos casos no se ejecutaron. |
| R1-07; R2-03–R2-08; R2-10 | Recetas y verificadores de variantes preparados. | Replay de fronteras y antecedentes de W1/W2/rollback/ACK del instrumento anterior. **Faltan adaptadores específicos de inyección/integración con carga**, no cubiertos por el pipeline normal. |

Una serie real que incluya alguno de esos ocho casos sin adaptador se rechaza en preflight, antes de crear salida o base y antes de emitir carga. No se sustituye una receta de crash, safety o guard por tráfico ordinario. La matriz completa **no está lista para ejecutarse**. La lógica del controlador queda validada; falta esa integración y su acreditación antes de considerar preparado el barrido completo. Esta limitación se conserva explícitamente, sin llamarla una mera autorización pendiente.

## Uso sin carga

Desde `backend`:

```powershell
rtk proxy python -X utf8 -m unittest apps.agent.tests.test_scheduling_characterization apps.agent.tests.test_scheduling_controller -v
rtk proxy python -X utf8 -m apps.agent.tests.scheduling_characterization.controller --help
rtk proxy python -X utf8 -m apps.agent.tests.scheduling_characterization.controller plan --series-id ID_NUEVO --output PLAN_NUEVO.json
rtk proxy python -X utf8 -m apps.agent.tests.scheduling_characterization.controller verify-plan --plan PLAN_NUEVO.json
rtk proxy python -X utf8 -m apps.agent.tests.scheduling_characterization.controller replay --plan PLAN_NUEVO.json --output DIRECTORIO_NUEVO
```

`series` y `job` son caminos de carga y exigen `--execute-load`; no se ejecutaron. Esa opción es una barrera mecánica, no sustituye el encargo humano de caracterización. La configuración DB debe ser explícita, local, `test_*`, durable y transitoria. Cada job usa una base nueva desde un template vacío y una salida nueva; solo se retira una base que ese job haya creado. La copia de fuentes debe ser aislada. `D29_ARCHIVE_REPOSITORY`, si se necesita desde una copia sin `.git`, identifica el repositorio leído para verificar el archivo del baseline; nunca modifica ese repositorio.

La prueba `finite-probe` ofrece exactamente un input por cada una de dos organizaciones y comprueba planners/sender, admisiones y cohorte. No deriva referencias de calibración ni acepta un nivel, aunque reciba un plan con las duraciones nominales del protocolo. El entorno usado para acreditarla se cierra al finalizar; sus credenciales no se conservan.

## Continuación necesaria

Primero integrar y acreditar los ocho adaptadores faltantes, conservando recuperación natural, evidencia de interrupciones, presupuestos y grants cerrados. Después validar cada receta real preparada y sellar el plan prospectivo de caracterización. Las futuras corridas obtendrán aproximaciones para proponer E, cobertura de fallos/recovery y política fuera de E; no abrirán automáticamente diseño de scheduling, WRITE ni release. La aceptación del contrato y su argumento de sostenibilidad siguen siendo decisiones posteriores.
