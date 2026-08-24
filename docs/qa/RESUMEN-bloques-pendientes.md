# Resumen: Extensión de bloques de prueba — Agente WhatsApp

## Estado

✅ **Completado**: Documento de diseño de casos de prueba para 7 bloques pendientes.
📁 **Archivo**: `guiones-prueba-manual-agente-bloques-pendientes.md` (18.8 KB)
📅 **Fecha**: 2026-08-20
🔗 **Base**: Especificación funcional (F1, congelada), ADRs p51–p56, módulo agent.md

---

## Qué se extendió

El documento original `guiones-prueba-manual-agente.md` cubría:
- ✅ **Crear cita** (C1–C6): 6 guiones fáciles/medios/complejos
- ✅ **Gestionar cita** (G1–G6): 6 guiones fáciles/medios/complejos

Y dejaba **7 bloques pendientes** sin documentar:

| # | Bloque | Tema | Estado |
|---|--------|------|--------|
| 1 | Registro | Cliente/mascota nuevos | **✅ Diseño completado** |
| 2 | Vacunas | Protocolos e historial | **✅ Diseño completado** |
| 3 | Productos | Inventario y compra | **✅ Diseño completado** |
| 4 | Clínica | Horario, dirección, especialidades | **✅ Diseño completado** |
| 5 | Urgencias | Triaje, límites clínicos | **✅ Diseño completado** |
| 6 | Identidad | Privacidad, anti-spoofing | **✅ Diseño completado** |
| 7 | Conversación | Multi-objetivo, interrupciones | **✅ Diseño completado** |

---

## Estructura de cada bloque

Cada uno de los 7 bloques incluye **3–5 casos de prueba** con:

### Para cada caso:
- **Dificultad**: fácil, media, compleja
- **Requisitos del agente**: mapeo a especificación, modelos, herramientas
- **Preparar**: datos de test necesarios, marcadores
- **Puntos de validación**: checklist de BD/frontend
- **Señales a observar**: UX, tono, redacción que indica éxito
- **Riesgos conocidos**: de ADRs, auditorías previas

---

## Alineación con arquitectura

Cada caso está **explícitamente anclado** a:
- **ADRs** (p51–p56): autoridad del turno, objetivos, reglas duras
- **Especificación funcional** (v1.1, congelada F1): alcance confirmado
- **Módulo `agent.md`**: capacidades por fase (F1/F2/F3)
- **Modelos Django**: `Conversation`, `ConversationGoal`, `VaccineProtocol`, etc.
- **Auditorías**: learnings previos incorporados

---

## Casos de prueba por bloque

### Bloque 1: Registro (D1–D3)
- D1: Agregar mascota en medio de agendar (media)
- D2: Cliente nuevo, identidad desconocida (compleja)
- D3: Datos inconsistentes (edad/peso) (media)

### Bloque 2: Vacunas (V1–V3)
- V1: Consultar siguiente vacuna (fácil)
- V2: Agendar cita de vacuna (media)
- V3: Rechazar cambio de protocolo (compleja)

### Bloque 3: Productos (P1–P3)
- P1: Consultar disponibilidad (fácil)
- P2: Compra con receta requerida (compleja)
- P3: Carrito y orden [F2 candidata]

### Bloque 4: Clínica (I1–I3)
- I1: Consultar horario (fácil)
- I2: Dirección y maps (fácil)
- I3: Especialidades de médicos (media)

### Bloque 5: Urgencias (U1–U3)
- U1: Síntoma grave → escalada inmediata (media)
- U2: Rechazar consejo médico (media)
- U3: Límite de turnos sin llenar slots (compleja)

### Bloque 6: Identidad (ID1–ID3)
- ID1: Suplantación / anti-spoofing (compleja)
- ID2: Solicitud GDPR (media)
- ID3: Opt-out de proactividad (media)

### Bloque 7: Conversación (X1–X3)
- X1: Multi-objetivo entremedias (compleja)
- X2: Pausa y reanudación (compleja)
- X3: Interrupción: humano toma chat (compleja)

**Total**: 22 casos de prueba diseñados.

---

## Roadmap de implementación

### Fase α (Fáciles) — Lecturas puras
V1, I1, I2, P1

**Criterio de entrada**: Endpoints de lectura disponibles.
**Criterio de salida**: 4 casos pasados, sin crear datos.

### Fase β (Medios) — Escritura simple
D1, D3, V2, P2, U1, I3, X2

**Criterio de entrada**: Validadores de slot, `ConversationGoal` persistido.
**Criterio de salida**: 7 casos pasados, datos creados correctamente.

### Fase γ (Complejos) — Escaladas y concurrencia
D2, V3, U2, U3, ID1–3, X1, X3

**Criterio de entrada**: `TurnDecision`, handoff, guards de privacidad.
**Criterio de salida**: 11 casos pasados, comportamiento de ruptura verificado.

---

## Criterios de aceptación

Un guion pasa a "listo para manual" si:

1. ✅ **Mapeado a especificación**: Sección X + ADR pYY citados explícitamente
2. ✅ **Datos preparables**: Procedimiento claro en entorno de test (sin ambigüedad)
3. ✅ **Validable**: Checklist de BD + observable en dashboard (no "según lo que diga")
4. ✅ **Redacción clara**: Alternativas explícitas, no especulación
5. ✅ **Independiente**: No requiere otro guion como precondición

---

## Notas de integridad

- ✅ Todos los marcadores `[MASCOTA_X]`, `[FECHA_Y]` son consistentes con el doc original
- ✅ Reglas duras (G1–G7 de ADR p54) se validan en **todos** los casos
- ✅ Cadena de auditoría (`created_by`, `ToolExecution`, `LLMCall`) es reconstruible
- ✅ Casos F1 prioritarios; F2/F3 marcados explícitamente como candidatos
- ✅ Riesgos conocidos de auditorías previas incorporados como "Señales a observar"

---

## Cómo usar este documento

1. **Para diseño de casos**: copiar la estructura de un bloque, reemplazar detalles específicos.
2. **Para escribir guiones**: tomar "Preparar" + "Mensajes" + "Verificar" y escribir paso a paso.
3. **Para testing**: ejecutar caso, validar "Puntos de validación", observar "Señales a observar".
4. **Para debugging**: si falla, buscar en "Riesgos conocidos" de ese bloque (ADR/auditoría ref).

---

## Siguiente: Convertir a guiones paso a paso

Este documento es un **diseño arquitectónico**, no un manual ejecutable. El siguiente paso es:

Para cada bloque (α, β, γ por fases):
1. Seleccionar 1 caso
2. Preparar datos de test
3. Escribir mensajes literales con alternativas explícitas
4. Validar contra checklist
5. Documentar learnings en "Señales a observar"

Ej. de siguiente documento: `guiones-prueba-manual-agente-bloque-1-registro.md` (Fase α)

