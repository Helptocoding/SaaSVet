# Plan de implementación — hallazgos de pruebas manuales del agente WhatsApp

**Estado**: IMPLEMENTADO — pendiente de verificación automatizada.
**Fecha**: 2026-08-28
**Origen**: auditoría de observaciones en
[`qa/guiones-prueba-manual-agente-bloques-pendientes.md`](qa/guiones-prueba-manual-agente-bloques-pendientes.md).

> Este plan no modifica ni redefine los guiones de prueba manual. Cualquier
> corrección de esos guiones se evaluará en una decisión posterior y separada.

---

## Decisiones de producto confirmadas

### Ficha de mascota por WhatsApp

- El agente **no captura peso ni alergias por WhatsApp**.
- Para la edad, pregunta si el cliente conoce la fecha de nacimiento exacta o
  aproximada. Solo persiste `birth_date` cuando el cliente aporta una fecha que
  el contrato del dominio pueda representar sin inventar precisión.
- Si el cliente no conoce una fecha exacta o aproximada, el agente deja
  `birth_date` vacío; no guarda una edad textual ni calcula una fecha ficticia.
- Raza, sexo y color siguen siendo candidatos de captura no clínica, sujetos al
  contrato existente de `Pet` y a la confirmación tier-2.

### Especialidades y servicios

Una especialidad se ofrece al cliente solo cuando existen **ambas** condiciones
en la organización:

1. un servicio activo que represente esa especialidad; y
2. al menos un miembro activo del staff con la especialidad correspondiente.

La existencia de solo una de las dos fuentes no basta para ofertarla. Esto evita
prometer un servicio sin capacidad humana o presentar una especialidad del staff
que la clínica no ofrece como servicio.

### Datos de catálogo que se pueden comunicar

- El catálogo puede buscar por categoría y descripción, además de nombre.
- Precio y stock se comunican cuando el producto tiene existencia positiva. Si
  está agotado, el agente comunica únicamente que está agotado.
- Productos inactivos nunca se muestran. Los que requieren receta deben
  identificarse como tales, sin sugerir tratamiento ni venta/receta automática.

---

## Fase 0 — especificación de búsqueda de catálogo (bloqueadora)

La implementación sigue esta especificación y no se reduce a un `icontains`
sobre nombre y descripción.

### 0.1 Clasificación de la consulta

El servidor recibirá una intención de búsqueda tipada, no una regla libre del
LLM:

| Clase | Ejemplo | Estrategia |
|---|---|---|
| `category` | “alimentos”, “accesorios” | normalizar a una categoría cerrada (`food`, `accessory`, etc.) y listar productos activos de esa categoría |
| `brand_or_name` | “Royal Canin” | coincidencia textual priorizada sobre nombre y, de forma secundaria, descripción |
| `need_or_attribute` | “croquetas para cachorro” | búsqueda textual sobre nombre + descripción, con orden de relevancia definido |
| `ambiguous` | “comida” con más de una interpretación | pedir una aclaración breve; no elegir categoría arbitrariamente |

La clasificación debe ser validada por el servidor contra un vocabulario cerrado
de categorías y sinónimos. El LLM puede proponer la clase o consulta, pero no
puede saltarse esa validación.

### 0.2 Reglas que debe cerrar la especificación

Antes de codificar, documentar y aprobar:

1. Diccionario de sinónimos por categoría, incluido singular/plural y acentos.
2. Normalización Unicode, minúsculas y diacríticos, sin alterar el texto que se
   muestra al cliente.
3. Campo y peso de cada coincidencia: nombre, fabricante, categoría y
   descripción.
4. Orden estable: coincidencia exacta de nombre, prefijo/nombre, categoría
   explícita, descripción; desempate por nombre y `public_id`.
5. Límite de resultados y copy cuando se supera; el límite evita listas largas
   y exposición innecesaria de catálogo.
6. Exclusión de productos inactivos y tratamiento separado de productos
   agotados y de receta.
7. Semántica de cero coincidencias, consulta ambigua y fallo del catálogo.
8. Contrato de proyección seguro: nunca devolver campos que el agente no puede
   comunicar en la rama correspondiente.

### 0.3 Criterios de terminado

- “alimentos” resuelve `category=food`, no una búsqueda textual indiscriminada.
- “Royal Canin” prioriza el nombre comercial.
- “croquetas para cachorro” puede usar nombre y descripción conforme al ranking
  aprobado.
- Acentos, plural y sinónimos producen el mismo resultado canónico cuando el
  diccionario así lo declare.
- Un producto inactivo no se muestra al agente.
- Un producto de receta no se presenta como vendible sin receta.
- La información de precio y stock respeta la política de existencia positiva
  definida
  arriba.

---

## Fase 1 — contratos de dominio y herramientas

Depende de la Fase 0 para catálogo.

### 1.1 Alta de mascota

1. Ampliar el contrato de las tools de alta para `pet_birth_date` solamente.
2. Mantener peso y alergias fuera de la tool y del prompt de captura.
3. Añadir una normalización conservadora de fecha aproximada solo si se puede
   representar como fecha y el cliente la confirma; de otro modo omitirla.
4. Conservar el staged payload, la confirmación tier-2, idempotencia, aislamiento
   por organización y verificación de identidad existentes.

### 1.2 Especialidades ofertables

1. Crear una fuente de lectura pública para especialidades ofertables, no una
   consulta genérica de usuarios.
2. Construir su resultado mediante la intersección de servicios activos y staff
   activo con especialidad correspondiente.
3. Definir el mapeo canónico entre nombre de servicio y `User.specialty`; no
   comparar texto libre sin normalización.
4. Exponer al agente solo especialidades que pasen la intersección; no nombres
   de personas salvo una decisión posterior explícita.

### 1.3 Catálogo

1. Implementar el clasificador y proyección aprobados en Fase 0.
2. Mantener la consulta tenant-scoped y activa.
3. Separar en el resultado: disponibilidad, receta, coincidencia/ranking y los
   campos permitidos por la política de comunicación.
4. No introducir carrito, reserva ni venta directa: siguen fuera de alcance.

---

## Fase 2 — handoff y respuestas ambiguas

### 2.1 Handoff de urgencia

- Al escalar una urgencia, persistir un resumen operativo no diagnóstico del
  mensaje entrante actual y enlazarlo al handoff.
- La bandeja debe mostrar primero motivo/prioridad/síntoma actual y conservar el
  transcript como fuente completa.
- No alterar el corto circuito determinista de urgencia ni permitir LLM antes
  de la escalada.

### 2.2 Acknowledgements sin operación pendiente

- Distinguir acknowledgements inocuos (`ok`, `gracias`, emoji) de una
  confirmación afirmativa.
- Sin propuesta vigente, un acknowledgement no puede ejecutar ni proponer una
  cita y no debe emitir el copy de “resumen de cita” inexistente.
- Esta mejora no cambia la semántica de opt-out: la baja corta proactividad; un
  mensaje posterior iniciado por el cliente vuelve a ser atendible.

---

## Pruebas requeridas

1. **Catálogo**: categorías, marcas, descripción, sinónimos, acentos,
   singular/plural, ranking, límites, inactivos, receta, agotados y política de
   precio/stock.
2. **Mascotas**: persiste la fecha de nacimiento cuando se conoce una fecha
   concreta; fecha desconocida queda vacía; peso y alergias nunca se solicitan
   ni persisten; confirmación e identidad no
   se degradan.
3. **Especialidades**: servicio+staff se oferta; cualquiera de las fuentes por
   sí sola no se oferta; aislamiento tenant y staff inactivo.
4. **Urgencia**: crea handoff urgente sin LLM y la bandeja recibe el resumen del
   síntoma vigente, no solo slots de una operación previa.
5. **Acknowledgements/opt-out**: `ok` sin pending no crea ni intenta confirmar
   cita; el opt-out se conserva y un nuevo inbound sigue siendo atendible.

Los guiones manuales existentes no se editan en este plan.

---

## Archivos probables

- **Agent**: `backend/apps/agent/tools.py`, `policy.py`, `planner.py`,
  `matchers.py`, `prompts.py`, `models.py` y serializers/views del inbox.
- **Dominio**: `backend/apps/patients/serializers.py`; servicios/serializers de
  catálogo y servicios activos; posiblemente una proyección de especialidades.
- **Tests**: `backend/apps/agent/tests/` y suites de patients, inventory,
  billing/services e inbox.
- **Documentación**: este plan, `docs/modules/agent.md`,
  `docs/modules/patients.md`, `docs/modules/inventory.md` y la especificación
  funcional si se formaliza el nuevo contrato público de catálogo.
- **No tocar**: `docs/qa/guiones-prueba-manual-agente-bloques-pendientes.md`.

Una migración o ADR solo se considerará si la implementación requiere un nuevo
modelo/proyección persistente para especialidades o para el resumen de handoff.
