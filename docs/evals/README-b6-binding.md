# Corpus técnico B6 v1

[Corpus](b6-binding-v1.json), independiente del corpus clínico B5. Son textos
sintéticos: 20 conversaciones y 37 turnos sobre correcciones de mascota, fecha,
servicio y cita, negación sin reemplazo, abandono, preguntas públicas,
compuestos, plurales, homónimos, coincidencias parciales y pronombres inmediatos.

La ejecución crea eventos Message reales y TurnContext B1 en PostgreSQL. Cada
conversación se evalúa secuencialmente con el resolver server-side de producción.
Se comprueban binding, necesidad de aclaración, conservación de datos independientes
e invalidación de dependencias. No se usa LLM real ni se mide comprensión abierta.
Los tests complementarios ejercitan planner/tools, B3, DB y procesos separados.

No usar accuracy global como gate. Exigir por separado:

- bindings correctos / comprobados;
- aclaraciones correctas / comprobadas;
- invalidaciones correctas / comprobadas;
- reutilizaciones stale = 0;
- mezclas de asuntos = 0.

Desde `backend`, con DATABASE_URL apuntando a PostgreSQL aislado y permisos
para crear bases de test, sin credenciales de proveedores externos:

```text
rtk proxy python manage.py test apps.agent.tests.test_b6_binding apps.agent.tests.test_b6_corpus apps.agent.tests.test_b6_processes apps.agent.tests.test_b6_migration --testrunner apps.agent.tests.harness.CriticalB6Runner --keepdb --noinput --verbosity 2
rtk proxy python manage.py test apps.agent.tests.test_b0_containment --testrunner apps.agent.tests.harness.CriticalB0Runner --keepdb --noinput --verbosity 2
rtk proxy python manage.py makemigrations --check --dry-run
rtk proxy python manage.py showmigrations agent
```

El runner B6 rechaza suite vacía/parcial, ausencia de casos críticos, skips,
xfail y éxitos inesperados. Los procesos hijos solo aceptan una base `test_*`.
La suite conjunta y su inventario exacto están en
[evidencia de aceptación](b6-acceptance-results.json). Los resultados del corpus
están en [métricas](b6-binding-v1-results.json); su alcance y límites están en
el [acta B6](../implementacion-b6-agente-whatsapp-2026-09-17md).

El arnés `legacy_write_component` conserva pruebas de los handlers inactivos
B0–B5: además de su sustitución B0 preexistente, aísla la precondición B6 solo
en fixtures sin metadata de binding. No inventa provenance. No sustituye
identidad, delivery ni precondiciones de dominio; un fixture versionado B6
continúa usando el validador real. Los gates B0 y B6 nunca usan ese decorador.
Es una prueba de componentes históricos, no evidencia de autonomía WRITE.
