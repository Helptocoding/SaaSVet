# Flujo de trabajo con agentes de IA

Esta guía explica cómo utilizar **Codex CLI**, **Claude Code**, **gstack**, **agtx** y **Open Code Review (OCR)** en VetCare SaaS sin API keys, usando las suscripciones personales de ChatGPT Plus y Claude Pro.

> Alcance: desarrollo local. No autoriza despliegues, cambios de secretos, cambios irreversibles de base de datos ni acceso a datos de producción sin aprobación humana explícita.

---

## 1. Conceptos y responsabilidades

Estos nombres no son sinónimos. Cada herramienta tiene una responsabilidad distinta.

| Componente | Qué es | Responsabilidad recomendada |
|---|---|---|
| Codex CLI | Agente de programación de OpenAI | Implementar, ejecutar pruebas y revisar cambios locales. |
| Claude Code | Agente de programación de Anthropic | Planificar, investigar y revisar cambios. |
| gstack | Conjunto de metodologías y comandos para agentes | Añadir disciplina: producto, arquitectura, QA, seguridad y release. Se usa principalmente desde Claude Code. |
| agtx | Tablero y orquestador de sesiones/worktrees | Separar tareas y coordinar sesiones de agentes; no es quien toma decisiones de producto. |
| Open Code Review (OCR) | Sistema de revisión multiagente | Revisar un diff o PR terminado con varias perspectivas independientes. |
| OpenCode | Otro agente/cliente distinto de OCR | Opcional. No es necesario para el flujo descrito aquí. |

La regla central es:

```text
Un agente implementa; otro agente revisa; una persona aprueba.
```

---

## 2. Autenticación: suscripciones, no API keys

Para trabajo local interactivo no se requieren `OPENAI_API_KEY` ni `ANTHROPIC_API_KEY`.

| Herramienta | Inicio de sesión | Verificación |
|---|---|---|
| Codex CLI | `codex login` y autenticar con la cuenta de ChatGPT Plus | `codex login status` |
| Claude Code | Ejecutar `claude` y elegir la cuenta Claude.ai Pro | `claude doctor` |

Las suscripciones tienen límites de uso. Los subagentes y los flujos multiagente consumen más capacidad que una sesión única, por lo que deben reservarse para tareas que realmente lo justifiquen.

### Windows y WSL

Codex CLI y Claude Code pueden instalarse en Windows. Para `agtx` se recomienda **WSL2**, ya que depende de `tmux` y se comporta como una herramienta de Linux.

Si se usa WSL2, iniciar sesión dentro de WSL aunque ya se haya iniciado sesión en Windows:

```bash
codex login
claude
```

La sesión de Windows y la de WSL pueden guardar credenciales en ubicaciones diferentes.

---

## 3. Cómo se comunican los agentes

Codex CLI y Claude Code **no mantienen una conversación directa y permanente**. La coordinación se realiza a través de artefactos verificables del repositorio:

- Especificaciones y planes Markdown.
- ADRs y documentación de módulos.
- Ramas, commits y `git diff`.
- Resultados de pruebas, build y revisión.
- Archivos de hallazgos o listas de verificación.

El flujo recomendado es:

```text
Claude Code + gstack
  → produce un plan aprobado en docs/plans/
  → Codex CLI lee el plan e implementa en una rama
  → Codex ejecuta pruebas y deja un diff/commit
  → Claude Code + gstack revisa el diff en modo lectura
  → OCR aporta una revisión independiente cuando el riesgo lo amerita
  → una persona revisa y decide integrar
```

No se debe permitir que ambos agentes editen simultáneamente el mismo worktree. Aumenta el riesgo de conflictos, cambios no relacionados y regresiones difíciles de atribuir.

---

## 4. Flujo base para una funcionalidad

### Paso 1: formular y planear

Usar Claude Code con gstack para cuestionar el problema antes de escribir código:

```text
/office-hours
/autoplan
```

El resultado debe ser un plan concreto que incluya:

1. Problema y alcance explícito.
2. Módulos y archivos probablemente afectados.
3. Contratos de API, datos y UX.
4. Riesgos de seguridad, concurrencia y aislamiento por organización.
5. Estrategia de migración, si hay persistencia de datos.
6. Casos de prueba y criterios de aceptación.

Guardar el resultado en `docs/plans/AAAA-MM-DD-nombre-corto.md`. Un plan no equivale a autorización para implementar: primero debe revisarse y aprobarse.

### Paso 2: implementar

Abrir una rama para una única intención y pedir a Codex CLI que implemente el plan aprobado.

Codex debe:

1. Leer las reglas de `AGENTS.md`/`CLAUDE.md` y la documentación del módulo afectado.
2. Mantener las vistas delgadas y colocar efectos de negocio en services.
3. Añadir o actualizar pruebas de la regla que modifica.
4. Ejecutar las verificaciones relevantes.
5. Mostrar el diff antes de realizar un commit.

### Paso 3: revisar

Usar Claude Code con gstack en modo de lectura:

```text
/review
```

La revisión debe responder, como mínimo:

- ¿Se respetó el aislamiento por `organization`?
- ¿Se reutilizaron servicios y contratos existentes?
- ¿Existe una transición de estado o efecto secundario fuera de un service?
- ¿Las pruebas cubren la regresión y los límites del dominio?
- ¿El cambio arrastra complejidad o cambios no relacionados?

### Paso 4: validar e integrar

Antes de integrar, revisar manualmente el diff y ejecutar CI local o las verificaciones equivalentes. La persona responsable decide si se integra el cambio.

---

## 5. Cuándo usar cada herramienta

| Tipo de trabajo | Herramientas | Regla |
|---|---|---|
| Corrección visual o typo | Codex CLI | Un agente; pruebas/build si aplica. |
| Feature de alcance medio | gstack → Codex → gstack | Plan, implementación, revisión. |
| Cambio de dinero, inventario, RBAC o migración | gstack → un implementador → OCR | Secuencial; no paralelizar escritura. |
| Investigación, documentación o pruebas aisladas | agtx + Codex/Claude | Puede paralelizarse si las salidas no se solapan. |
| PR sensible o cambio grande | OCR | Revisores independientes antes de merge. |
| Despliegue y operación | gstack QA/seguridad + revisión humana | Ningún agente despliega por su cuenta. |

---

## 6. Reglas específicas de VetCare SaaS

Este proyecto no es un repositorio genérico. Los agentes deben respetar los contratos documentados antes de editar.

### Zonas rojas: no paralelizar implementaciones

Usar un único implementador y una revisión independiente cuando el cambio toque:

- `billing`, `cash` o pagos/reembolsos.
- `inventory` o movimientos de stock.
- `medical_records` y el cierre de consulta.
- RBAC, identidad, tenant o endpoints platform.
- Migraciones, constraints, borrados o datos persistentes.
- Agente de WhatsApp, tokens, autorizaciones o acciones de compromiso.

Estas áreas tienen invariantes de concurrencia, aislamiento y auditoría. En particular, deben conservarse las reglas de `organization`, los services transaccionales, el orden de locks y la idempotencia donde corresponda.

### Zonas verdes: candidatas a trabajo paralelo

agtx puede coordinar tareas independientes como:

- Documentación y runbooks ya delimitados.
- Auditoría de enlaces/documentación desactualizada.
- Accesibilidad de un componente aislado.
- Investigación de una deuda técnica sin escribir código.
- Pruebas de un módulo que no comparte archivos ni contratos con otra tarea activa.

### Contexto mínimo obligatorio

Antes de cambiar un módulo, cargar solo el contexto necesario:

- Frontend: `docs/modules/frontend.md` y `frontend/design-system.md` si hay UI.
- Backend de un dominio: `docs/modules/<modulo>.md`.
- Cambio cross-módulo: `docs/system-operational-flow.md` y los contratos pertinentes.
- Cambio arquitectónico: ADRs relevantes en `docs/decisions/`.

No cargar toda la documentación de manera indiscriminada. El contexto irrelevante reduce la precisión del agente.

---

## 7. Uso de agtx

agtx se introduce después de que el flujo manual funcione bien. Su función es aislar sesiones, no eliminar la revisión humana.

```text
Tablero agtx
├── Tarea A: Codex implementa una mejora de accesibilidad
├── Tarea B: Claude investiga un plan de paginación
└── Tarea C: Codex actualiza un runbook
```

Cada tarea vive en su propio worktree y rama. Antes de comenzar una tarea, debe tener:

1. Objetivo y límites claros.
2. Documentación/ADRs de referencia.
3. Archivos o módulos permitidos.
4. Criterios de aceptación y pruebas esperadas.
5. Una instrucción explícita de no modificar otras tareas o worktrees.

Empezar con **dos workers como máximo**. Aumentar el número solo después de verificar que los cambios llegan limpios, con pruebas y sin conflictos frecuentes.

El modo de orquestación automática de agtx es experimental. Al inicio debe usarse solo como tablero y lanzador manual de sesiones.

---

## 8. Uso de Open Code Review (OCR)

OCR es una puerta de calidad para cambios de riesgo medio o alto. No sustituye las pruebas ni la revisión humana.

Equipo mínimo sugerido para este repositorio:

| Revisor | Enfoque |
|---|---|
| Arquitectura Django | Services, serializers, vistas, contratos y migraciones. |
| Seguridad multi-tenant | `organization`, permisos, IDs públicos, validación de FKs y exposición de datos. |
| Concurrencia y pruebas | Transacciones, locks, idempotencia, regresiones y cobertura relevante. |

Para cambios de frontend, sustituir el revisor de concurrencia por uno de UX/accesibilidad cuando el riesgo de negocio sea bajo.

Los hallazgos de OCR son hipótesis que deben verificarse en el código y pruebas; no deben aplicarse ciegamente.

---

## 9. Ejemplos prácticos

### Caso A: paginación y filtros de recetas

1. gstack define filtros, contrato API, estados de UI y compatibilidad con el frontend.
2. Se aprueba el plan.
3. Codex implementa backend y frontend en una sola rama porque comparten contrato.
4. Claude/gstack revisa consistencia, tenant y experiencia de error/estado vacío.
5. OCR revisa el diff si el cambio es grande.

### Caso B: cambio en reembolsos o caja

1. gstack revisa producto, ingeniería y seguridad.
2. Se consulta el contrato financiero y ADRs relevantes.
3. Un único agente implementa, con tests de concurrencia y de invariantes contables.
4. OCR revisa específicamente locks, idempotencia, eventos y aislamiento tenant.
5. Revisión humana obligatoria antes de merge.

### Caso C: documentación de despliegue

1. agtx crea una tarea independiente para Codex.
2. Codex contrasta runbooks con Docker/CI/configuración actual.
3. Claude revisa claridad operativa y pasos de rollback.
4. Se integra tras revisión humana.

---

## 10. Límites y prácticas de seguridad

- No pegar tokens, cookies, archivos `auth.json`, contraseñas ni variables `.env` en chats, planes o commits.
- No conectar agentes a producción para explorar datos de clientes.
- Usar una base de datos local/sanitizada para QA.
- No ejecutar despliegues, borrados, rotación de secretos o migraciones destructivas desde automatización sin confirmación humana.
- Revisar siempre `git diff` y el estado de Git antes de commit o merge.
- Mantener un único origen de verdad para decisiones: ADRs, contratos y documentación de módulos del repositorio.

---

## 11. Adopción gradual recomendada

1. Usar Codex CLI para cambios pequeños y Claude Code/gstack como revisor.
2. Aplicar el flujo de plan → implementación → revisión en una feature de riesgo medio.
3. Instalar agtx y utilizarlo manualmente con dos tareas verdes en paralelo.
4. Añadir OCR como gate para cambios críticos o PRs grandes.
5. Evaluar el orquestador experimental de agtx únicamente después de varios sprints sin conflictos ni regresiones atribuibles a coordinación.

El objetivo no es maximizar el número de agentes; es producir cambios trazables, revisables y seguros.
