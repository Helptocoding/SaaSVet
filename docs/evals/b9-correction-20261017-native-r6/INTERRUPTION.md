# Interrupción de native-r6

Decisión: **PENDING**, por evidencia incompleta del entorno. No se ha acreditado un fallo del producto.

Se conservan los recibos RUNNING originales y el journal de 2483 PASS y dos SKIP históricos. Quedan 728 IDs sin resultado; el caso iniciado sin resultado no cuenta como aprobado. El monitor final de disco/reloj y los verificadores posteriores no se guardaron antes del reinicio. La comprobación actual acredita integridad de 3332 fuentes, 44636 dependencias y 160 archivos del sello, identificada expresamente como posterior al reinicio.

No se asigna exit 0 al proceso antiguo ni se declara que el grupo terminó. Los auxiliares antiguos desaparecieron con la sesión de Windows; su restauración de API no fue observada. El runtime privado se conserva sin reiniciarlo mientras se decide la continuación sin repetir casos PASS.

Fuentes: interruption-20261019.json, STOP.json y diagnostics/resumption-20261019/prefix-validation.json.
