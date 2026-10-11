# R1-02: cierre de caracterización inicial de base

**CONFIRMED_BASE_ESTABLISHED**. Estado global: **CONTROLLER_CORE_VALIDATED / FULL_LIVE_MATRIX_NOT_READY**.

Baseline `825db75df68bf076929fa787e77beefe96803350`. Plan prospectivo: un nivel, 50% de la referencia física mínima, filtro 360 s y confirmaciones 900 s ×3; sin explorar una frontera superior.

| Corrida | Fase | Repetición | Aceptaciones | W_hi máximo (s) | Resultado ejecutor | Verificación física |
| --- | --- | --- | --- | --- | --- | --- |
| r102-initial-base-20261007-0001 | CALIBRATE | — | 20 | 0.6304663 | CALIBRATION_REFERENCE_OBSERVED | OK |
| r102-initial-base-20261007-0002 | SCREEN | — | 24 | 0.9587191 | OBSERVED_COMPATIBLE | OK |
| r102-initial-base-20261007-0003 | CONFIRM | 1 | 60 | 1.1079011 | OBSERVED_COMPATIBLE | OK |
| r102-initial-base-20261007-0004 | CONFIRM | 2 | 60 | 1.0057786 | OBSERVED_COMPATIBLE | OK |
| r102-initial-base-20261007-0005 | CONFIRM | 3 | 60 | 1.0499375 | OBSERVED_COMPATIBLE | OK |

Nivel nominal confirmado: [1.9607508002652434, 1.9607508002652434] inputs/min por organización, bajo la población, pacing, servicio, concurrencia, clocks y ventanas de los receipts. Se conservan por separado tasas nominales y conteos READY realmente observados. Frontera no localizada; no es capacidad máxima, E ni afirmación comercial.

Preparación: un error de literal de ruta de Windows se corrigió antes de ofertas. Verificación: la v1 comparaba claves enteras Python con claves JSON; la v2 compara estructuras serializadas, sin tolerancias ni alterar hechos. Procedencia: el checkout y el archivo Git tienen distribuciones distintas de LF/CRLF en 365 fuentes; su texto es equivalente. La aceptación usa comparación exacta de bytes con el archivo Git del baseline más el overlay congelado, y conserva por separado la integridad de bytes originales del checkout. Se conservan los antecedentes y diagnósticos, incluido el helper de diagnóstico interrumpido y sustituido por un script guardado.

Cleanup privado completo; fuentes protegidas y evidencia anterior intactas; cero commits. No se modificó runtime, D29/B8/B9/E4 ni se ejecutaron dependientes. El campo histórico benchmark_executed se conserva en el resultado original; esta fase solo ejecutó la serie inicial autorizada.

[Receipt completo](confirmed-base-receipt.json), [verificación física](physical-verification.json), [plan sellado](sealed-plan.json), [método y límites](scope-and-method.md).

Siguiente decisión: revisión humana de esta evidencia antes de autorizar consumo de la base en escenarios dependientes. La ejecución termina aquí.
