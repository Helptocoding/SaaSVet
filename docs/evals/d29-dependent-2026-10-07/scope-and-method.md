# D29: consumo de la base aceptada y matriz física final

Autorización humana: consumo de la CONFIRMED_BASE de R1-02 para R1-03/04/05/06,
matriz de los 17 escenarios, regresión D29/aplicación e integridad/cleanup.
Baseline: `825db75df68bf076929fa787e77beefe96803350`. Cero commits.

La fuente autoritativa es `../d29-r102-base-2026-10-07/confirmed-base-receipt.json`.
Se verifican sus hashes y los 200 artefactos sellados antes de toda oferta.
No se invoca Controller.run/search, CALIBRATE, SCREEN, REFINE o CONFIRM.
SCENARIO consume las tasas de la base ya aceptada, durante la ventana de 360 s
prevista por Controller.job para escenarios y hasta 240 s de seguimiento.
No es una búsqueda/confirmación de candidato nuevo. Los clocks, provider y
procesos conservan las fuentes existentes; ningún runtime/config persistente cambia.

R1-03 redistribuye 2:1 los slots del calendario equilibrado de la base,
conservando exactamente los instantes globales de oferta y su ventana.
La ejecución real, las aceptaciones durables, episodios y procesos acreditan la
geometría; el calendario previsto no basta. La población mantiene tres slots de
conversación por organización. R1-05 consume los multiplicadores y duración ya
declarados, con observación física de burst, retorno y obligaciones del drain.

El adaptador de series R1-04 contiene una observación posterior que busca
claim miss. Se rechaza como evidencia causal de forecast/yield: son fronteras
distintas. La carga natural se ejecuta sin fabricar esa secuencia. Ausencia de
testigos causales concurrentes deja la condición completa NOT_ACCREDITED; la
secuencia finita ya aceptada conserva su alcance y no se combina artificialmente
con una corrida separada de carga para producir PASS.

R1-06: la receta de ejecución exige backlog en conversaciones distintas.
Con R_base=1.9607508002652434 y duración 2 min, ceil(R_base*2)=4 por org,
pero la base aceptada fija 3 conversaciones por org. No se cambia esa población,
no se coalescen cuatro inputs para llamarlos cuatro episodios, ni se reduce el
backlog. El intento físico sobre la receta intacta conservará su rechazo previo
a oferta. Resolver esta incompatibilidad requiere otra autorización metodológica.

Cada intento dispone de base PostgreSQL local privada nueva y fuentes archivadas,
provider contenido, salida nueva, receipt y cleanup. Los intentos fallidos no se
eliminan. La matriz distingue frontera finita, condición de carga, prerrequisito,
evidencia física y evidencia sintética. Los adapters físicos antiguos no obtienen
acreditación de carga por adjuntar la referencia de base: cuando no ejecutan esa
carga se conserva ese límite explícito.

La transición FULL_CONTROLLER_ACCREDITED exige todas las variantes requeridas,
fronteras y condiciones físicas, verificadores, regresiones e integridad.
Un solo caso no acreditado conserva FULL_LIVE_MATRIX_NOT_READY.
Sin E, máximo, caracterización nueva, PROFILE, tuning, capacidad comercial,
scheduling productivo, modificación contractual o paso automático posterior.
