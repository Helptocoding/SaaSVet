# VetCare · Priorización Reconciliada + Backlog de Quick Wins

> Este documento **reemplaza** las dos listas que competían entre sí. Un solo backlog, un solo orden.

---

## 1. Priorización reconciliada (los cambios acordados)

Partiendo de mi clasificación, se aplicaron 3 ajustes tras comparar ambos análisis:

| Punto | Antes | Ahora | Motivo |
|---|---|---|---|
| **#5** Empty state / onboarding | 🟡 Considerable | 🔴 **Urgente** | Define la confianza del primer minuto y es barato. |
| **#6** Alta rápida de paciente | 🟡 Considerable | 🔴 **Urgente** | Es la comparación directa contra el papel; si pierde aquí, pierde la adopción. |
| **#23** Cambio no registrado | 🔴 Urgente | 🟡 **Considerable** | No es bug: $500 recibido − $150 cambio = $350 neto = la venta. Solo falta mostrarle el desglose para su tranquilidad. |

### Distribución final

| Categoría | Cantidad |
|---|---|
| 🔴 Urgente | **20** |
| 🟡 Considerable | **27** |
| 🟢 Exagerado | **2** |

> **Por qué tier urgente angosto:** un backlog donde 2 de cada 3 cosas "gritan" no te dice por dónde empezar. 20 urgentes ya es un orden ejecutable; el resto es mejora real, no emergencia.

---

## 2. Backlog de Quick Wins

**Definición:** Urgente o Considerable · Esfuerzo Bajo–Medio · Impacto Alto · resoluble en días. El objetivo de este bloque es **uno solo: que Don Carlos vuelva a confiar esta semana.**

### 🥇 Sprint de confianza — los 9 de esta semana

Estos atacan los puntos que más duelen y se pueden cerrar en días.

| # | Acción | Por qué AHORA | Esfuerzo |
|---|---|---|---|
| **6** | **Alta rápida de paciente** (nombre + dueño + teléfono; el resto opcional/después) | El #1 absoluto. Es donde el papel le está ganando a tu producto. | Medio |
| **14** | **Autosave visible + recuperar borrador** | Perder notas clínicas destruye la confianza de golpe. Innegociable. | Medio |
| **5** | **Empty state guiado** ("Aún no hay datos, empieza por tu primer paciente") | Convierte el "creo que rompí algo" en "ya sé qué hacer". | Bajo |
| **44** | **Email opcional** (teléfono como principal) | Cambio de una línea; desbloquea a la mitad de sus clientes y frena datos basura. | Bajo |
| **15** | **Signos vitales visibles** en la pantalla de consulta | Dato clínico que hoy se omite por estar escondido. | Bajo–Medio |
| **17** | **Notas internas / pendientes** (campo libre tipo post-it) | Recupera la flexibilidad informal por la que "el papel gana". | Medio |
| **33** | **Búsqueda parcial / fuzzy** | Búsqueda exacta = pierde velocidad cada día; obliga a memorizar nombres. | Medio |
| **25** | **Validar caja al iniciar el cobro** (no al final) | Deja de tirar a la basura todo el flujo de cobro. | Bajo–Medio |
| **3** | **Arreglar "Bienvenido de nuevo"** en primer login | Casi gratis; sana la primera impresión. | Bajo |

### 🌎 Barrido de localización y términos — 1 solo lote

Individualmente cada uno es de impacto "medio". **Juntos** matan el patrón que más envenena la confianza: *"esto no fue hecho para mí"*. Casi todo es cambio de texto → un solo sprint corto.

| Incluye | Cambio |
|---|---|
| #1 | Unificar UI a español (la marca puede quedarse) |
| #4 | "Dashboard" → "Inicio" |
| #7 | `internal_code` → opcional / autogenerado, etiqueta en español |
| #8 | Reloj 12h AM/PM (configurable) |
| #24 | "restock/discard" → "Regresar a inventario" / "Dar de baja" |
| #29 | Unidades en español (pieza/mililitro/kilo); valores internos intactos |
| #32 | `min_stock` visible en el alta + etiqueta en español |
| #34 | "Z-close" → "Corte de caja" |
| #40 | Toggles con mejor contraste + etiqueta "Sí/No" |

### 💛 Cariño barato — Considerables de bajo esfuerzo (mismo sprint si sobra tiempo)

| # | Acción | Esfuerzo |
|---|---|---|
| **45** | Campo alias/apodo + notas en la mascota | Bajo |
| **46** | Reubicar "Cerrar sesión" / confirmación | Bajo |
| **30** | Animación del wizard saltable / una sola vez | Bajo |
| **26** | Restaurar acceso rápido al "+ Cobro" | Bajo |

---

## 3. Lo que **NO** es Quick Win (importante, pero a roadmap)

Para que el backlog quede honesto: esto es urgente o valioso, pero **no** se resuelve "en un par de días" porque pide diseño, módulo nuevo o trabajo de performance. No lo metas al sprint de confianza.

| # | Tema | Por qué no es quick win | Destino |
|---|---|---|---|
| **13, 19** | Flujo de consulta (orden de bloques, receta vs. producto) | Necesita rediseño de UX/arquitectura | **Entregable 3** (rediseño de consulta) |
| **21** | Unificar POS y Cobros | Esfuerzo Alto; toca arquitectura | Roadmap (épica) |
| **41** | Performance en horas pico | Necesita perfilado real de queries | Roadmap (técnico) |
| **43** | Cuentas por cobrar | Módulo nuevo | Roadmap (alto valor) |
| **49** | Receta membretada con cédula | Plantilla + tema legal | Roadmap (alto valor) |
| **36** | PDFs white-label de la clínica | Diseño + multi-tenant | Roadmap |
| **28** | Producto simple por defecto | Medio; rediseño del alta | Roadmap cercano |
| **39** | Bug de timezone / cache | Bug de Medio esfuerzo | Cola de bugs |
| **31, 47, 48, 18, 27, 37, 42, 35** | Kardex, estado fallecido, desambiguar búsqueda, lista plana de historial, pago mixto, reporte del día, mensajes de error, corrección de corte | Medio esfuerzo c/u | Roadmap por sprints |
| **50** | "Trabajo para el sistema" | Es la meta-señal, no un ticket | KPI guía de toda la iniciativa |

---

## 4. Lo que sigue (Fase 2, entregables restantes)

- ✅ **Entregable 1 — Backlog de Quick Wins** (este documento)
- ⬜ **Entregable 2 — Onboarding vs. cambios de código** (qué se arregla sin tocar código)
- ⬜ **Entregable 3 — Rediseño del flujo de Consulta Clínica** (#13–#19, manteniendo la integridad relacional)
- ⬜ **Entregable 4 — Plantilla de comunicación para Don Carlos** (es-MX, empática)
