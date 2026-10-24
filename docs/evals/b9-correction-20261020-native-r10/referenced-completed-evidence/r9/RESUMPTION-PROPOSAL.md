# Reanudar sin repetir casos PASS

Estado: propuesta, pendiente de decisión sobre la limitación de evidencia.

Verificación completada:
[`prefix-validation.json`](../b9-correction-20261017-native-r6/diagnostics/resumption-20261019/prefix-validation.json),
SHA-256 `51bed99c98bc8683f2764c841076f6ea47288fe339608fd122c4b405ba9e21db`.
Los 3332 archivos del candidato, las 44636 dependencias y los 160 archivos
del sello coinciden actualmente; no se detectaron diferencias. Este resultado
es posterior al reinicio y no sustituye el monitor histórico ausente.

La instrucción del usuario del 19 de octubre es continuar sin repetir pruebas
que ya pasaron. El candidato sigue siendo el árbol
`68dffd746793700071f577a58528b0f9636930db`; no se propone modificar el producto,
los tests, sus assertions, los locks, las cargas, los tiempos ni los umbrales.

## Evidencia conservada

- Se mantienen los trece bloques PASS completos ya acreditados por procedencia.
- El journal sincronizado de native-r6 contiene 2485 IDs únicos: 2483 PASS y
  los dos SKIP históricos no críticos. No contiene FAIL, ERROR, XFAIL ni XPASS.
- La prueba de reloj corregida pasó dentro de ese journal.
- Quedan 728 IDs sin resultado; incluyen el caso que estaba en ejecución al
  interrumpirse Windows. Ese caso no se considera aprobado.
- Se comprueba también la ausencia de errores posteriores de teardown y de
  errores de clase/módulo. El log acredita que, después del último PASS,
  comenzó el caso siguiente. La última clase quedó parcial: no se afirma que
  sus hooks de cierre antiguos se completaron; el remanente ejecutará los
  hooks originales de su nuevo contexto.
- Se conservarán los recibos RUNNING originales. Se registrará su interrupción
  por separado, sin inventar un exit code, un resultado final ni una corrida
  continua completada.

## Limitación que requiere una decisión expresa

El controlador acumulaba las muestras de disco y diferencia entre reloj de
pared y monotónico en memoria hasta finalizar el bloque. El reinicio impidió
guardar ese monitor y los verificadores posteriores. Se conservan muestras
continuas de RAM y actividad del auxiliar, además de verificadores previos
limpios. La comprobación actual de hashes se registrará como posterior al
reinicio; no demuestra por sí sola el estado histórico de disco/reloj.

El [plan ejecutado](../b9-correction-20261017-native-r6/PLAN.md:115) exige
«verificadores antes/después íntegros y reservas/reloj válidos». Sus condiciones
ordinarias no permiten acreditar todo el grupo general con el journal parcial.

## Continuación propuesta

1. Verificar ahora los 3332 archivos del candidato, las 44636 dependencias y
   los archivos del sello anterior. Cualquier diferencia bloquea su reuso.
2. Conservar los 2483 PASS y los dos SKIP con su origen. Ejecutar únicamente
   los 728 IDs sin resultado con el `RecordedFullRunner` original, en un proceso
   nuevo y una base de pruebas nueva. La unión debe cubrir exactamente los
   3213 IDs, sin omisiones ni duplicados.
3. Mantener el agregado full de 3331 IDs y todos sus verificadores de inventario,
   fallos y skips críticos. Ejecutar las etapas todavía no realizadas: frontend,
   seguridad, auditorías y los cinco perfiles originales con sus migraciones y
   ventanas 30/300/20 segundos.
4. Mantener RAM mínima de 2 GiB, disco mínimo de 1 GiB y reloj máximo de 1 s
   durante las nuevas ejecuciones. Guardar sus muestras de monitor de forma
   incremental y durable para que otra interrupción no borre ese registro.
5. Acreditar el cierre únicamente bajo una enmienda que acepte expresamente
   la falta del monitor histórico de native-r6. El informe señalará esa
   limitación y la aceptación compuesta. No afirmará que se cumplieron las
   condiciones documentales originales del grupo completo.

Sin esa excepción, los PASS se conservan y no se repiten; la aceptación formal
del grupo y la campaña permanecen PENDING por evidencia ambiental incompleta.
Los perfiles siguen sujetos al prerrequisito de gates bloqueantes aceptados.

Activación, despliegue, commits y push siguen fuera del alcance. R1-04 y E/P/UX
mantienen los límites ya aceptados. No se propone ampliar el plan.
