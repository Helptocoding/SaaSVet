# Plan de implementación — seguridad, auditoría run-1

**Fecha**: 2026-10-28
**Origen**: auditoría de seguridad `run-1` sobre el commit `8886604` (`~/security-audit-skill/SaaSVet/run-1/`)
**Estado**: **ejecutado casi por completo** — ver el estado por fase abajo (actualizado 2026-11-04)
**Alcance de ejecución**: **100 % local**. Ninguna tarea de este plan requiere acceso al VPS.

---

## Estado por fase (actualizado 2026-11-04)

El cuerpo del plan se conserva como se escribió; esta tabla dice qué quedó hecho. Donde discrepen, manda la tabla.

| Fase | Estado | Nota |
|---|---|---|
| 1 · Correcciones de código | **Hecha** | Las tres aplicadas. Al corregir `AGENT_TOKEN_ENC_KEY` aparecieron **dos instancias más de la misma clase** (`AGENT_LLM_MAX_RETRIES`, `AGENT_LLM_RETRY_DELAY_SECONDS`), que es por lo que el gate nuevo es de tolerancia cero sin baseline. |
| 2 · Unidad `blocked` de billing | **Hecha, sin hallazgo** | Las preguntas de concurrencia e idempotencia se resolvieron a favor del código en tres capas independientes: lock del agregado, invariante de estado posterior al lock y constraints de BD. Un ítem de exactitud documental registrado como endurecimiento. |
| 3 · Huecos acotados | **Hecha** | Cinco de seis cerrados limpios. Produjo **dos hallazgos confirmados**, ambos ya remediados y con regresión. V-6 quedó parcial y se cerró en la Fase 4. |
| 4 · Unidades diferidas | **Hecha: 8 de 8** (2026-11-04) | Devoluciones, caja, inventario/lotes, parser de importación, CI/dependencias/release y cliente navegador, **sin hallazgo confirmado**; cierre de expediente clínico, auditado dentro de la Fase 8. **Scripts de respaldo: un hallazgo (baja)**, que la lectura inicial no vio y apareció al ejecutarlos; remediado en `1d13389`. Endurecimientos nuevos en §7 (H-12 a H-15). |
| 5 · Tests de regresión | **Hecha** | 7 módulos nuevos. Varios gates son **estáticos y no de comportamiento**, a propósito: los defectos eran omisiones, y una prueba sobre una sola vista no impide que una vista nueva repita el olvido. |
| 6 · Suspendido hasta que haya entorno | **Sigue suspendido** | Y la causa empeoró: el servidor no está en servicio y no se puede reconectar. |
| 7 · Mejoras sin prisa | **Lotes 1 y 2 aplicados** (2026-11-04) | Lote 1 en `1d13389`, lote 2 en `cb0ff9e`, H-4 en `6e2a379`. **H-4 resultó ser una vulnerabilidad real** (media), no endurecimiento; ver §7. H-3 aplicada después. |
| **8 · Re-auditoría del traspaso** | **Hecha y remediada** (enmienda 2026-11-04) | 5 hallazgos confirmados (1 alta, 1 media, 3 baja), los 5 remediados con prueba de regresión en `0afea53`, integrado en `develop` (`7b6ed82`); CI verde en `b1c75ec`. Ver §Enmienda — Fase 8, abajo. Absorbe el cierre de expediente clínico de la Fase 4. |

**El cierre de expediente clínico ya no está bloqueado.** Estaba diferido porque sus archivos caían en el trabajo «orden 2» en vuelo; ese trabajo quedó commiteado en `929b6ae`. Pasa a ejecutarse dentro de la Fase 8, no en la 4.

---

## Enmienda — Fase 8: re-auditoría del traspaso (2026-11-04)

### Por qué existe

Este plan se escribió contra `8886604`. Encima hay ahora dos commits: `9c2a613` (remediaciones de esta auditoría) y `929b6ae` (el trabajo «orden 2/4», 170 archivos y ~8 700 líneas, recibido a medias y commiteado al traspasarse). La obligación de re-auditar ese trabajo estaba registrada en `run-metadata.json` —*«todo archivo de esa lista debe re-auditarse cuando el trabajo concurrente se estabilice»*— pero **no tenía fase**. Esta enmienda se la da. No sustituye ninguna fase anterior.

### Qué cambió en la superficie de ataque

Cinco rutas nuevas, **todas en `apps/platform`**, la capa cross-tenant de mayor privilegio:

| Ruta | Riesgo a comprobar |
|---|---|
| `physical-deletions/preview/` | Qué revela el preview sobre otra organización; quién puede pedirlo |
| `physical-deletions/execute/` | **Irreversible.** Firma, caducidad, un solo uso, impacto revalidado, actor |
| `organizations/<uuid:pk>/history/` | Exposición del historial de estado de un tenant |
| `organizations/<uuid:pk>/<str:action>/` | **Acción despachada desde el path**: ¿lista blanca cerrada? |
| `organizations/<uuid:organization_id>/<str:kind>/<uuid:pk>/<str:action>/` | Acción **y tipo** desde el path, con `organization_id` de la URL: ¿lista blanca, y el objeto pertenece a esa org? |

Más cuatro modelos nuevos (`ImportConflict`, `StockReceptionReceipt`, `OrganizationStateAudit`, `PhysicalDeletionReceipt`), la semántica de **archivado** que sustituye al borrado tenant de Owner/Pet, los guards de borrado de `deletion_guards.py`, y `subject_snapshot` como nuevo lugar donde vive la identidad del tenant.

### Unidades, por orden

1. **8.1 · Borrado físico de plataforma** — preview/execute, `PhysicalDeletionReceipt`, `deletion_guards`. Primero porque es lo único irreversible.
   **Hecha (2026-11-04): un hallazgo confirmado, severidad media, sin remediar todavía.** `_inspect` enumera referencias con `_meta.related_objects`, que excluye las FK con `related_name='+'`; cinco FK del módulo `agent` hacia Owner/Pet son invisibles. Las cuatro SET_NULL se anulan en silencio al borrar, saltándose el chequeo de preservación de identidad y el digest de impacto, y reescriben una `ConversationOperation` B7A inmutable que después ya no valida contra su propio digest. Reproducido con una operación real. Lo demás resiste: doble autorización, confirmación firmada con TTL que liga actor+objetivo+motivo+impacto, un solo uso garantizado por UNIQUE en base, idempotencia bajo advisory lock, impacto re-inspeccionado bajo lock. Nota menor: las cuatro vistas nuevas de platform no tienen throttle, a diferencia de crear organización y resetear contraseña.
2. **8.2 · Transiciones de estado de organización** — las dos rutas `<str:action>`, `OrganizationStateAudit`, efectos de `is_active=False` sobre login y API del tenant.
   **Hecha (2026-11-04): un hallazgo confirmado, severidad ALTA, sin remediar todavía.** El acceso HTTP se corta bien en las tres puertas (login tras validar contraseña, refresh antes de rotar, y cada petición JWT/sesión), y las dos rutas `<str:action>` tienen lista blanca cerrada. Pero el selector de candidatos del worker no excluye organizaciones inactivas antes de su `LIMIT 3`, y ordena por el claim más antiguo: una org desactivada nunca vuelve a ser reclamada y sube al frente. Con **tres** clínicas desactivadas cuyos clientes siguen escribiendo, el agente deja de atender a **todas** las clínicas activas, en silencio y de forma persistente. Reproducido por la ruta real con caso de control (2 inactivas: atiende; 3: cero procesados). El webhook sigue ingiriendo para orgs desactivadas porque solo comprueba la cuenta de canal. El sender tiene la misma forma, no reproducido y acotado.
3. **8.3 · Archivado de pacientes** — `change_archive_state`, que una mascota archivada no reaparezca ni reciba escrituras, aislamiento.
   **Hecha (2026-11-04): un hallazgo confirmado, severidad baja, sin remediar todavía.** El servicio está bien acotado: todo filtrado por organización, orden de locks Organization→Owner→Pet compatible con citas, el dueño de la mascota se revalida con el lock tomado, y se bloquea si hay citas o consultas abiertas. Pero el resolvedor de identidad por teléfono cuenta solo clientes **activos**, así que archivar libera la clave; si mientras tanto se da de alta otro cliente con ese teléfono, **restaurar** al archivado deja dos expedientes activos con el mismo número, porque restaurar no pasa por el lock ni comprueba la clave. INV-C falla en cerrado (devuelve ambiguo, no vincula mal), pero el teléfono deja de funcionar en todas las vías de identidad. Reproducido con los servicios reales. Nota de endurecimiento: la autorización se escribe a mano con `role == 'ADMIN'` en vez de pasar por RBAC; es más estricta, no más laxa, y las acciones `archive`/`restore` solo exigen `IsAuthenticated` y delegan todo en el servicio.
4. **8.4 · Cierre de expediente clínico** (antes unidad 11 de la Fase 4) — `medical_records/services.py`, `subject_snapshot`, `vet_*_at_close`.
   **Hecha (2026-11-04): una regresión funcional confirmada (severidad baja, no es vulnerabilidad) y una hipótesis refutada.** El cierre resiste: recibo idempotente (que revierte entero si el permiso falla, y que rechaza a un actor distinto), fila bloqueada, permiso bajo lock, y anchor + cita + Checkout en una transacción. `subject_snapshot` y los `vet_*_at_close` no son escribibles desde ningún serializer. Hipótesis refutada: que `assign-patient` dejara la identidad de la mascota genérica congelada en el expediente; el trigger `0041` lo hace imposible. Pero ese mismo trigger rechaza la escritura de `assign-patient`, que no actualiza el snapshot: **vincular el paciente real a una atención sin cita da 500 en cuanto hay consulta abierta** (con control: sin consulta, 200). No queda estado incoherente, la transacción revierte. Ningún test cubría esa combinación. Es el único escritor con ese patrón.
5. **8.5 · Unidades rancias** — 12 (platform), 18 y 4 (billing), 20 (rutas hijas): repetir sus comprobaciones contra `929b6ae` y re-anclar los cuatro registros rechazados cuyos archivos cambiaron.
   **Hecha (2026-11-04): los cuatro rechazos se sostienen, re-anclados; un hallazgo nuevo de severidad baja.** Platform: las siete vistas (cuatro nuevas) exigen `IsPlatformOperator` y ningún código RBAC, así que el comodín `*.*` del ADMIN de clínica sigue sin alcanzarlas. Billing: `unit_price` sigue siendo de solo lectura y sale del catálogo; el filtro `?owner=` de cobros ahora también busca en `subject_snapshot`, pero sobre un queryset ya acotado por organización. Rutas hijas: el padre se resuelve con `for_organization`, el hijo se filtra por ese padre y el `service` del body se compara con la organización bajo lock. PDF: todos los campos de usuario, incluidas las identidades congeladas nuevas, pasan por `safe_pdf_text`. Pacientes: `owner_id`, `is_active` y `archived_at` son de solo lectura y la referencia se resuelve por organización. **Hallazgo nuevo:** `reprice` de un cargo clínico no comprueba que la consulta siga abierta. Después del cierre responde 200 con el precio nuevo, pero el Checkout (y la Invoice que salga de él) sigue cobrando el precio viejo, porque la línea se congeló al cerrar y nada la vuelve a materializar. Si algo la rematerializara, saldrían dos líneas para un solo servicio. Reproducido con los servicios reales. Solo lo puede hacer un ADMIN.

**Fase 8 completa y remediada.** Las notas «sin remediar todavía» de arriba describen el estado al auditar; las cinco correcciones y el throttle de platform están en la tabla siguiente.

### Remediaciones de la Fase 8 (2026-11-04, commit `0afea53`)

Cada una con prueba de regresión que **falla sobre el código sin arreglar** y pasa con él.

| Hallazgo | Cambio | Prueba |
|---|---|---|
| 8.2 (alta) | Worker y sender filtran `organization__is_active` **antes** del `LIMIT`; el «ceder a una org menos atendida» ignora las desactivadas; el lote del sender queda ordenado. | `agent/tests/test_inactive_org_starvation.py`. Reprodujo además el bloqueo del **sender**, que en 8.2 había quedado sin reproducir. |
| 8.1 (media) | El inspector recorre todas las relaciones entrantes, también las ocultas; las no soportadas bloquean. | `platform/tests/test_physical_deletion_hidden_refs.py`, con gate estático. |
| Throttle platform | Corrección a la nota de 8.1: no estaban sin límite, solo tenían el global por usuario (500/h). Ahora `platform_physical_deletion` 30/h y `platform_lifecycle` 60/h. | `platform/tests/test_platform_throttles.py` (gate). |
| 8.3 (baja) | Restaurar toma el lock de teléfono antes que las filas (el orden de las altas), revalida bajo lock y responde `409 owner_exists` / `owner_ambiguous`. | `patients/tests/test_restore_phone_identity.py` |
| 8.4 (baja) | **Decisión de producto: excepción del genérico.** Migración `billing.0043` (solo reemplaza la función del trigger) que permite reescribir el snapshot únicamente si el anterior es la mascota genérica de la misma organización y la consulta está abierta (o es la receta de una consulta abierta). `assign-patient` escribe paciente + snapshot en la consulta y en su receta. Addendum en ADR-001. | `appointments/tests/test_assign_patient_open_record.py`, incluidos los límites del trigger. Reversa de la migración verificada. |
| `reprice` (baja) | Bloquea la fila del expediente, exige consulta abierta y rechaza si el ciclo ya está congelado en la cuenta. | `billing/tests/test_reprice_open_record_only.py` |

Verificación conjunta: core (gates de scoping, URL y calendario), prescriptions, appointments, billing, medical_records, platform y patients en verde (729 tests); suites del agente que ejercen los selectores, 265 en verde; `makemigrations --check` sin cambios. **La migración `0043` no se ha aplicado a ningún entorno real.** Al desplegar, aplicarla junto con el código de `assign-patient`: sin ella, ese endpoint sigue dando 500 con consulta abierta.

### Integración en `develop` y CI (2026-11-04)

La rama `codex/e4-capacity-scheduling` (`9c2a613`, `929b6ae`, `0afea53`) se integró en `develop` con el merge `7b6ed82`. En el mismo paso:

- **`bbfe016`** — `SECRET_KEY` falla cerrado: sin clave el proceso no arranca, salvo con `DEBUG=True`, que genera una aleatoria por proceso. Sustituye un default fijo que dos commits locales de `develop` habían introducido y que nunca llegaron al remoto; esos commits se rehicieron sin el `backend/.env` que también incluían.
- **`9129f5f`** — tres pruebas rojas tras el merge: la excepción de URL de reintento quedó duplicada (se conserva la estricta), una prueba borraba una `Pet` sin `authorize_physical_deletion`, y una carrera de citas dependía de la hora del reloj real porque el serializer importa `now` directamente.
- **`b1c75ec`** — el job de backend queda fijado en `ubuntu-24.04`. `ubuntu-latest` pasó a 26.04, cuyo `pg_dump` emite `SET transaction_timeout`, que PostgreSQL 16 (CI y producción) rechaza; el simulacro de restauración de media fallaba sin causa visible. Ahora además afirma que el cliente no es más nuevo que el servidor.

CI de `develop` verde en `b1c75ec` (backend, frontend y gitleaks).

### Lo que ya se tocó durante el traspaso, y no cuenta como auditoría

Al cerrar las pruebas rojas del traspaso se leyó y modificó parte de esta superficie: el guard invertido de `?pet=`, la autorización de purga de la demo, `authorize_physical_deletion`, y dos entradas del baseline de scoping. Eso fue **trabajo de arreglo**, guiado por pruebas que fallaban, no una revisión adversarial. Se registra como evidencia parcial, no como cobertura.

### Mismas limitaciones que el resto

Un solo revisor, sin verificación independiente, sin sandbox. Esta fase añade cobertura; no corrige el método.

**Lo que ninguna fase de este plan arregla:** la corrida sigue siendo de **un solo revisor**, sin verificación independiente y sin ejecución en sandbox. Eso no es cobertura que falte: es una propiedad del método con el que se obtuvo todo lo anterior. Está en `REPORT.md` §9.5.

---

## 0. Encuadre

### 0.1 Qué cubre y qué no

Este plan implementa **solo** lo que la auditoría alcanzó a revisar: las 17 unidades de cobertura con evidencia (6 `covered`, 10 `candidate`, 1 `blocked`). Añade además el trabajo de auditoría pendiente que es **puramente local**, porque la pérdida del entorno de producción no lo bloquea.

**No cubre**, y no debe leerse como si lo hiciera:

- Las tres preguntas de despliegue (U-1): entropía del slug del admin, qué listeners alcanzan el backend, qué hay delante del proxy. Se responden sobre el entorno nuevo cuando exista.
- El ensayo de restauración de backup. Requiere infraestructura.
- Un límite de tasa de borde para `/hooks/*`. Decisión de infraestructura.

Esos tres quedan en §6, suspendidos, para que no se pierdan.

### 0.2 Estado de la auditoría que lo origina

La corrida `run-1` terminó **incompleta** y de **un solo revisor**: los cazadores delegados y los críticos de cobertura fallaron por límite de gasto de la cuenta, y no se ejecutó código del target porque el host no podía imponer el sandbox requerido. Consecuencias que condicionan este plan:

- **8 de 25 unidades no tienen evidencia.** Están en §4 porque son auditables localmente.
- **Ningún hallazgo recibió verificación independiente.** Los traces están en `findings.json` para que re-verificarlos cueste poco.
- Resultado: **1 hallazgo confirmado (severidad baja)**, **3 pendientes de validación** (dependen del despliegue), **7 refutados por el propio código**.

### 0.3 Prerrequisito de coordinación

Hay trabajo paralelo en curso («orden 2»): 21 archivos trackeados modificados y 6 migraciones nuevas sobre billing, inventario, expedientes, organizaciones y recetas. **Ese trabajo se conserva; este plan no lo toca.**

Antes de aplicar cada tarea, comprobar si su archivo está en esa lista:

| Tarea | Archivos | ¿Tocados por «orden 2»? |
|---|---|---|
| F-1 | `config/settings.py`, `channels/crypto.py` | **No** — aplicar directo |
| U-3 | `core/throttling.py`, `config/settings.py` | **No** — aplicar directo |
| U-2 | `infra/Caddyfile` | **No** — aplicar directo |
| U-4 | `billing/checkout_services.py`, `billing/services.py` | Indirecto (`billing/serializers.py`, `billing/models.py` sí) → releer antes |
| V-2 | `prescriptions/views.py`, `billing/views.py` | **No** |
| V-3 | `medical_records/*` | **Sí, intensamente** (`views.py` −227 líneas) → releer antes |
| H-3 | `billing/serializers.py` | **Sí** → releer antes |
| H-4 | `core/pdf_utils.py` + consumidores | Consumidores **sí** → releer antes |

Regla: las tareas marcadas «releer antes» se auditan sobre el árbol actual, no sobre `8886604`. Las demás se pueden aplicar ya.

---

## 1. Fase 1 — Correcciones de código (≈ 3 h en total)

Las tres son de bajo riesgo, archivos no tocados por el trabajo paralelo, y cierran lo que la auditoría encontró.

### F-1 · Hacer alcanzable la separación de clave para secretos en reposo

**Severidad**: baja · **confirmado** · **esfuerzo**: ~1 h
**Unidad de cobertura**: `infra (secrets)` · **fingerprint**: `channels/crypto/agent-token-enc-key-setting-never-defined`

**Problema.** `apps/channels/crypto.py:22` lee la clave dedicada con `getattr(settings, 'AGENT_TOKEN_ENC_KEY', '')`, pero `config/settings.py` **nunca define ese nombre**. En este proyecto la única vía para promover una variable de entorno a settings es `config()` de `decouple`, así que el `getattr` devuelve siempre `''`, la rama es código muerto y la clave Fernet es **siempre** `SHA-256(SECRET_KEY)`. Un operador que ponga la variable en el entorno no obtiene efecto ni advertencia.

**Invariante a imponer.** La clave que cifra secretos en reposo debe poder elegirse de forma independiente de la que firma JWT y sesiones, y la ausencia de esa elección debe ser **visible**, no silenciosa.

**Cambio.** En `backend/config/settings.py`, junto al resto de valores ajustables por el operador:

```python
# Secretos en reposo (channels/crypto.py). Clave Fernet urlsafe-b64 de 32
# bytes, INDEPENDIENTE de SECRET_KEY: rotar la firma de JWT no debe invalidar
# los tokens del proveedor, y una fuga de SECRET_KEY no debe descifrarlos.
# Vacío = se deriva de SECRET_KEY (modo degradado, sin separación de claves).
AGENT_TOKEN_ENC_KEY = config('AGENT_TOKEN_ENC_KEY', default='')
if ENVIRONMENT == 'production' and not AGENT_TOKEN_ENC_KEY:
    import warnings
    warnings.warn(
        'AGENT_TOKEN_ENC_KEY no configurado: los secretos en reposo se cifran '
        'con una clave derivada de SECRET_KEY. Sin separación de claves, una '
        'fuga de SECRET_KEY también los descifra y su rotación los invalida.',
        RuntimeWarning,
    )
```

Y en `.env.prod.example`, la entrada con cómo generarla:

```
# Clave Fernet para secretos en reposo. Independiente de SECRET_KEY.
# Generar: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Vacío = derivada de SECRET_KEY (degradado).
AGENT_TOKEN_ENC_KEY=
```

`apps/channels/crypto.py` **no se modifica**: su lógica ya es correcta, lo que faltaba era el setting.

**Secuencia que importa.** Hacerlo **antes** de generar el `SECRET_KEY` del entorno reconstruido, para que los secretos en reposo nazcan con clave propia. Si se hace después, cambiar la clave invalida el ciphertext existente y hace falta una migración de re-cifrado — o que cada clínica vuelva a introducir su token desde la UI, que es un flujo ya soportado.

**Criterio de aceptación.**
1. Con `AGENT_TOKEN_ENC_KEY` definido, `_fernet()` usa esa clave: cifrar con ella descifra, y un cifrador construido desde `SHA-256(SECRET_KEY)` **no** descifra.
2. Con el setting vacío, cae en la derivación (conserva compatibilidad).
3. Con `ENVIRONMENT='production'` y el setting vacío, el arranque emite el `RuntimeWarning`.

**Nota de documentación.** Añadir el orden correcto de rotación a `docs/security/secret-rotation-plan.md`.

---

### U-3 · Declarar el supuesto de proxy dentro de la aplicación

**Estado**: pendiente de validación · **esfuerzo**: ~1 h
**Unidad**: `users (authentication)` · **fingerprint**: `core/throttling/login-key-trusts-unvalidated-forwarded-for`

**Problema.** Las dos clases de throttle de login derivan la identidad del cliente de `X-Forwarded-For` **sin validar la cadena de proxy**:

- `LoginUserRateThrottle.get_cache_key` (`core/throttling.py:105-106`) toma el valor **más a la izquierda**, que es el segmento que un cliente fija libremente si la cabecera se añade en vez de reemplazarse. La clave es `f'{ip}_{username}'` (`:113`): IP distinta = cupo nuevo.
- `LoginRateThrottle` (`:75`) hereda `AnonRateThrottle`; con `NUM_PROXIES` sin configurar, DRF usa **toda** la cabecera como identidad.

Hoy el control se sostiene solo porque `infra/Caddyfile:130,148,173` **reemplaza** la cabecera (`header_up` sin prefijo `+`). El bloque de health (`:90`) no lleva ninguna directiva, lo que demuestra que esa disciplina es **por bloque**, no global: un bloque futuro puede omitirla en silencio.

**Invariante a imponer.** La identidad anti-fuerza-bruta debe derivarse de un valor que el cliente **no** controle, y el número de saltos confiables debe estar declarado en la aplicación, no implícito en el proxy.

**Cambio, dos partes.**

1. Declarar los saltos confiables en `REST_FRAMEWORK` (`backend/config/settings.py`). Con un único proxy delante:

```python
# Caddy es el único salto confiable y reemplaza X-Forwarded-For con la IP real
# del cliente. Declararlo aquí hace que DRF tome el elemento que el proxy
# controla (el de más a la derecha) en vez de toda la cabecera, de modo que un
# cliente que prepende valores no pueda elegir su propio bucket de throttle.
'NUM_PROXIES': 1,
```

Con `NUM_PROXIES = 1`, `AnonRateThrottle.get_ident` devuelve `addrs[-1]` — el elemento de más a la derecha, el que escribe el proxy — y cae a `REMOTE_ADDR` si no hay cabecera.

2. En `LoginUserRateThrottle.get_cache_key` (`core/throttling.py:104-113`), sustituir la lectura manual de `HTTP_X_FORWARDED_FOR` por `self.get_ident(request)`, que ya respeta `NUM_PROXIES`. Conservar el resto del comportamiento: si no hay `username`, la clave sigue siendo solo por IP; el `username` sigue normalizándose con `.strip().lower()`.

> Verificar la firma exacta de `get_ident` contra la versión de DRF instalada (`djangorestframework 3.17.1`) antes de aplicar.

**Criterio de aceptación.**
1. Dos peticiones que solo difieran en el valor de `X-Forwarded-For` mapean al **mismo** bucket, para ambas clases de throttle.
2. Sin cabecera, la clave deriva de `REMOTE_ADDR` y el comportamiento previo se conserva.
3. El bucket por cuenta no se puede partir con identificadores equivalentes: `  Ana `, `ana` y `ANA` mapean a la misma clave.
4. Se conserva el fail-closed: ambas clases siguen usando la cache `throttle_login` con `IGNORE_EXCEPTIONS=False`.

---

### U-2 · Dejar el admin de Django cerrado en el repositorio

**Estado**: pendiente de validación · **esfuerzo**: ~30 min
**Unidad**: `infra (ingress)` · **fingerprint**: `infra/caddy/django-admin-exposed-without-ip-allowlist-or-login-throttle`

**Problema.** El bloque que restringiría el admin por IP de origen existe en `infra/Caddyfile:104-110` pero está **comentado**. El bloque activo (`:171`) proxea el slug del admin desde cualquier origen sin matcher `remote_ip`. Y los throttles del proyecto viven bajo `REST_FRAMEWORK` (`settings.py:286`), así que **por construcción no alcanzan** el formulario de login del admin, que es una vista Django plana: el límite de `5/15min` protege `/api/token/`, no el admin. Una sesión de superusuario rodea `for_organization`, del que depende todo el aislamiento entre clínicas.

**Por qué sigue siendo bloqueante.** `scripts/pre-launch-security-check.sh` §11 ya lo clasifica como **HIGH** y lo exime «para beta con autenticación fuerte + 2FA». **No existe MFA en el código** — no hay WebAuthn, ni TOTP, ni paso de verificación adicional. La condición de la excepción no se cumple.

**Cambio.** En `infra/Caddyfile`: descomentar el bloque `@admin_allowed_ips` / `@admin` existente y poblar los CIDR reales de oficina y VPN. Es un archivo del repositorio que `docker-compose.prod.yml` monta como `./infra/Caddyfile:/etc/caddy/Caddyfile:ro`, así que el cambio viaja solo en el próximo despliegue. Mientras los CIDR definitivos no se conozcan, dejarlos como placeholder **explícitamente marcado**, con un comentario que impida desplegar sin sustituirlo.

**Alternativa si la lista de IPs no es viable operativamente.** Un bloqueo por intentos delante del login de Django (`django-axes` o equivalente). No es intercambiable con lo anterior: la lista de IPs reduce la superficie, el bloqueo por intentos reduce la tasa. Si solo se puede una, la lista de IPs cubre más.

**Criterio de aceptación.**
1. El bloque está activo en `infra/Caddyfile` y no contiene placeholders al desplegar.
2. Test de regresión: recorrer **todos** los `ModelAdmin` registrados y afirmar que ninguno expone un modelo con tenant sin un `get_queryset` restringido por organización. Esto acota el radio de impacto y es independiente del despliegue.
3. El slug configurado no empieza por `admin` (el `handle /admin*` de `:182` lo capturaría y devolvería 404).

---

## 2. Fase 2 — Cerrar la unidad `blocked` de billing (1-2 días)

### U-4 · Concurrencia e idempotencia de comandos de billing

**Esfuerzo**: 1-2 días · **es auditoría, no parche** · **mayor valor del plan**
**Unidad**: `billing (commands)` — estado `blocked`

**Qué ya está establecido** (no repetir el trabajo):

- Ningún importe que resulte autoritativo viene del cliente. `CheckoutItemMutationSerializer` acepta solo `expected_version` y `quantity` (`billing/serializers.py:67-70`). Todo `unit_price` se lee del catálogo: `service.base_price` (`checkout_services.py:518,753`) y `presentation.sale_price` (`:523,733,1163`). El único precio humano, `reprice_clinical_charge` (`:602-607`), tiene permiso propio, rechaza `≤ 0` y escribe un registro append-only.
- La liquidación exacta se exige en ambas vías: `checkout_services.py:1660-1661` contra `checkout.total` y `services.py:196-204` contra `invoice.remaining_balance`.

**Qué falta, y es lo que importa:**

1. **`_claim_receipt`** (`billing/checkout_services.py:96-142`). Solo se leyeron sus mensajes de rechazo. Trazar hasta el modelo y sus constraints: ¿la clave de idempotencia está acotada **por organización**? Comportamiento ante (a) replay con el mismo payload, (b) replay con payload distinto, (c) clave de otro actor, (d) reclamación todavía en vuelo, (e) reuso de la misma clave entre organizaciones.
2. **Orden de locks y cobertura de `select_for_update`** en `post_checkout` y `pay_invoice`, incluido el paso de asignación de stock. ¿Pueden dos peticiones concurrentes pasar ambas una comprobación de «¿ya existe?» e insertar duplicados por ausencia de constraint único o de lock del padre?
3. **`expected_version`**: enumerar qué comandos lo exigen y cuáles aceptan `None`.

**Por qué es prioritario.** Doble cobro ante un cliente real es daño irreversible y de confianza, y es el peor resultado plausible del sistema.

**Criterio de aceptación.** Un calendario de concurrencia determinista que demuestre que dos peticiones de pago simultáneas sobre el mismo checkout producen **exactamente un** `Payment`. Más los dos tests de idempotencia de §5.

---

## 3. Fase 3 — Huecos acotados dentro de lo auditado (≈ 3 días)

Hechos no resueltos **dentro de unidades que sí tienen evidencia**. No son hallazgos; son huecos concretos.

| ID | Qué falta | Dónde | Esfuerzo | Releer antes |
|---|---|---|---|---|
| **V-1** | Paridad validate↔commit del importador: ¿toda regla del preview se aplica en commit? ¿Doble commit o re-commit tras cambiar el mapping? ¿Commit escribe stock sin emitir `StockMovement`? | `imports/services.py`, `imports/services_inventory.py` | 0.5 d | No |
| **V-2** | Rutas hijas con PK entero no trazadas: `prescriptions/<pk>/items/<int:pk>/` y el detalle de `CheckoutItem`. ¿El hijo queda acotado por el padre ya scoped? | `prescriptions/views.py`, `billing/views.py` | 2 h | No |
| **V-3** | Inmutabilidad post-cierre: `assert_can_modify_charges` se observó en **una** vía. Enumerar todo escritor de `MedicalRecordProduct`, `VitalSigns` y `VaccineRecord` | `medical_records/` | 0.5 d | **Sí** |
| **V-4** | Paridad de campos importador↔serializer más allá de los nombres: especie, sexo, fecha de nacimiento, normalización de teléfono, `legacy_id`, `extra_data`, precios, costos, cantidades, factores de conversión, caducidades | `imports/` | 0.5 d | No |
| **V-5** | ¿El preview o el `result` del job devuelven datos de **otra** organización (nombre de un cliente coincidente, un `public_id`, un conteo)? | `imports/services.py` | 2 h | No |
| **V-6** | `notifications`, `legal` y `analytics` quedaron sin revisar dentro de la unidad wildcard | esas tres apps | 1 d | No |

---

## 4. Fase 4 — Las 8 unidades diferidas (auditoría, local)

Es el hueco de cobertura más caro de `run-1`, y **no necesita servidor**: se audita leyendo código. Orden sugerido por lo que está en juego.

| # | Unidad | Por qué importa | Lo peor que hoy no se puede descartar |
|---|---|---|---|
| 1 | **Devoluciones, notas de crédito, reversas, voids** | Ledger append-only de dinero, nunca revisado | Over-refund, reversa aplicada dos veces, devolución sobre factura no pagada |
| 2 | **Caja: turnos y corte Z** | Reconciliación física del efectivo, snapshot declarado inmutable | Mutación post-cierre, pago atado a sesión cerrada o ajena |
| 3 | **Inventario y lotes** | Ledger de stock con FEFO y caducidad | Stock negativo, consumo de lote caducado o descartado, escritura sin `StockMovement` |
| 4 | **Cierre de expediente clínico** | Inmutabilidad post-cierre y trazabilidad de autoría. **Además es código nuevo** por «orden 2» | Mutación de registro cerrado por una vía lateral |
| 5 | **Parser de importación (recursos)** | XLSX es un ZIP | Bomba de descompresión, agotamiento de memoria |
| 6 | **Frontend** | Almacenamiento de tokens, sinks DOM | — |
| 7 | **CI, dependencias, release** | Cadena de suministro | Acción no pinneada, `pip-audit` advisory |
| 8 | **Backup y recuperación** | Único camino de vuelta | Auditable el **código** de los scripts; el **ensayo de restauración** queda suspendido (§6) |

---

## 5. Tests de regresión a añadir

El primero vale más que el resto, porque cubre la clase entera y no el caso.

| # | Test | Qué protege | Fase |
|---|---|---|---|
| 1 | **Gate estático: todo nombre leído con `getattr(settings, '<NOMBRE>', ...)` en `apps/` debe estar definido en `config/settings.py`** | Habría detectado F-1 en origen. Cubre toda la clase de «setting leído pero nunca definido» | 1 |
| 2 | Throttle de login: misma clave con y sin `X-Forwarded-For`; bucket por cuenta estable ante variantes de mayúsculas y espacios del `username` | U-3 | 1 |
| 3 | Todo `ModelAdmin` sobre un modelo con tenant tiene `get_queryset` restringido por organización | U-2 | 1 |
| 4 | `_fernet()` usa la clave dedicada cuando el setting está presente; cae en la derivación cuando está vacío | F-1 | 1 |
| 5 | Dos pagos simultáneos sobre el mismo checkout → exactamente un `Payment` | U-4 | 2 |
| 6 | Idempotencia: misma clave con payload distinto → rechazo; clave de otra organización → rechazo | U-4 | 2 |

---

## 6. Suspendido hasta que haya entorno

No se pierden; se retoman cuando exista servidor.

| ID | Qué | Cómo se resuelve |
|---|---|---|
| **U-1** | Las tres preguntas de despliegue: ¿el Caddyfile activo reemplaza `X-Forwarded-For` en todo bloque que proxea al backend y qué listeners lo alcanzan? ¿Entropía del slug del admin, firewall/WAF sobre esa ruta, cuántos superusuarios? ¿Qué hay delante del proxy y qué límite impone a `/hooks/*`, y valores de `GUNICORN_*`? | `scripts/pre-launch-security-check.sh` cubre buena parte: es read-only, no muta estado y está hecho exactamente para esto |
| **NV-3** | Límite de tasa de borde para `/hooks/*`. El trabajo previo a la autenticación ya es mínimo (firma primero, antes de parsear y antes de la base), así que es disponibilidad, no datos | Decisión de infraestructura. La medición acotada es de **coste de una petición**, nunca una prueba de carga |
| — | Ensayo de restauración de backup (`scripts/restore-drill.sh`) | Entorno desechable. Un backup no verificado no es un backup |

---

## 7. Mejoras sin prisa

No bloquean nada. Reducen el coste de los errores futuros.

**Estado (2026-11-04).** Hechas: H-9, H-10, H-13, H-14, H-15 (`1d13389`), H-7, H-12 y H-1 reducida (`cb0ff9e`), H-4 (`6e2a379`) y H-2 (ya estaba en `9c2a613`). H-1 reducida clasifica cada código y hace que `_is_allowed` niegue al comodín los de `WILDCARD_EXCLUDED`; no retira el `*.*` del ADMIN ni resuelve H-1 por completo. H-12 revoca el refresh; el access sigue valiendo hasta expirar (15 min). H-3 hecha: ver el addendum del ADR p14; incluye el cambio deliberado de rechazar actores sin organización en `billing` y `prescriptions`. Diferidas: H-1 completa, H-8 (el token queda en la etapa `builder`, que se descarta: solo persiste en la caché del host que construye, no en la imagen final como decía la tabla). Descartada: H-5 (`_download_url` es el único consumidor y ya es estricto; un guard compartido sería abstracción prematura). H-11 parcial: `CON`, `nul` y `backend/nul` borrados tras revisar su contenido (salida de terminal y un archivo vacío); `_pdf_preview/`, `reports/`, `gemini/` y `svgcomponentes/` se conservan porque pueden ser trabajo del dueño, y Git ya las ignora. `pip-audit` y `pnpm audit` siguen solo avisando, por decisión del dueño: un CVE nuevo no debe detener un merge sin relación.

**La tabla de abajo conserva el texto original, y en dos puntos estaba equivocado.** H-4 dice «hoy nada alcanzable lo explota»: era falso, `assessment.exam` no pasa por `sanitize_text` y permitía SSRF por el PDF, reproducido por la API real. H-13 omitía que los scripts de restauración tenían además un defecto real de códigos de salida, encontrado al ejecutarlos. Ambos están remediados y registrados en `findings.json` y en `REPORT.md` §9.8 y §9.9.

| ID | Mejora | Evidencia | Esfuerzo |
|---|---|---|---|
| **H-1** | Retirar el comodín `*.*` del ADMIN de clínica (corte Fase 4 del RBAC). Hoy cualquier código de permiso nuevo se le concede sin revisión | `core/permissions_codes.py:169` | 1-2 d |
| **H-2** | Unificar las dos definiciones de «operador de plataforma»: `IsPlatformOperator` (3 atributos) vs `IsAdminSaaS` (solo rol), siendo la débil la que protege un endpoint con selector `?org=` cross-tenant | `platform/permissions.py:40-42` vs `dashboard/views.py:41-49` | 2 h |
| **H-3** | Centralizar la validación de FK por tenant. Está reimplementada de tres formas y solo 2 de 5 apps emiten `TENANT_VALIDATION_REJECTED`: en las otras tres, intentar referenciar otro tenant es indistinguible de un error de validación ordinario | `billing/serializers.py:80-81` lo documenta como pendiente | 1 d |
| **H-4** | Escapar marcado de ReportLab en `safe_pdf_text`. Hoy nada alcanzable lo explota, pero la defensa en el renderizador no existe: depende de que el saneador de escritura se haya ejecutado | `core/pdf_utils.py:8-20` | 2 h |
| **H-5** | Extraer un guard SSRF compartido. `core/network.py` sugiere esa defensa y **no la presta** (solo parsea IP entrante); la única lista blanca real vive ad hoc en `media_transfer.py::_download_url` | `core/network.py` | 3 h |
| **H-7** | Mover el invariante `auto_rematch_blocked` del llamador a la mutación. Hoy el llamador único lo cumple sobre un contacto releído; un segundo llamador futuro tendría que redescubrirlo | `identity.py:244` vs `tools.py:2185` | 1 h |
| **H-8** | `SENTRY_AUTH_TOKEN` entra como build arg del frontend, y los build args persisten en el historial de la imagen | `docker-compose.prod.yml` | 1 h |
| **H-9** | Apagar `ALLOW_LEGACY_ID_LOOKUP` (hoy `True` por defecto). No cruza tenant, pero mantiene vivo el lookup por PK entero más de lo necesario | `config/settings.py:346` | 2 h + verificar consumidores |
| **H-10** | Retirar códigos de permiso sin consumidor (`organization.create`, `organization.list`) | `core/permissions_codes.py:112-115` | 15 min |
| **H-11** | Borrar e ignorar basura local no trackeada: `CON`, `nul`, `backend/nul`, `_pdf_preview/`, `reports/`, `gemini/`, `svgcomponentes/` | raíz del repo | 15 min |
| **H-12** | Revocar el refresh en el servidor al cerrar sesión (endpoint de logout que lo ponga en blacklist). Hoy el logout es solo local y un refresh robado antes sigue valiendo hasta 7 días | `frontend/src/auth/authContext.jsx:27`, sin ruta de logout en `config/urls.py` | 2 h |
| **H-13** | `restore-drill.sh`: `compose run --no-deps backend`. Sin el flag, cada simulacro relanza `release` (migrate, collectstatic, seed_permissions) contra la base viva | `scripts/restore-drill.sh:175` | 15 min |
| **H-14** | `umask 077` en los scripts de respaldo, en vez de depender del `chmod 700 ... \|\| true` del directorio | `scripts/pg-backup.sh:138-139`, `scripts/pre-deploy-backup.sh` | 15 min |
| **H-15** | Añadir `media-src 'self' blob:` a la CSP del frontend (funcional: el audio y video del Inbox usan `blob:`). Verificar en navegador | `infra/Caddyfile` | 15 min |

### Deuda estructural de fondo

**Evaluar RLS en PostgreSQL** (existe ya el ADR `docs/decisions/2026-05-26-p23-rls-tenant-isolation.md`). Hoy el aislamiento multi-tenant es 100 % de aplicación: una sola consulta futura sin `for_organization()` es una fuga cross-tenant, y lo único que lo impide de forma sistemática son tres gates de CI. Son buenos — un ratchet AST y dos gates de forma de URL — pero son **la única capa**. No es urgente porque el patrón se cumple de forma consistente; es importante porque el fallo no tiene red de seguridad en base de datos. Decisión de arquitectura, no parche.

---

## 8. Orden de ejecución

```
Fase 1  F-1 ──┐
        U-3 ──┤  ≈3 h, archivos no tocados por «orden 2»
        U-2 ──┘
                └─> Fase 2  U-4  (1-2 d)  ← mayor valor
                              └─> Fase 3  V-1..V-6  (≈3 d)
                                    └─> Fase 4  8 unidades diferidas
                                          └─> Fase 7  H-1..H-11
                                                └─> decisión RLS
```

**Fase 1 y Fase 2 son independientes de las demás** y pueden arrancar en paralelo si hay dos personas.

**Fase 4 es el bloque grande y el que más reduce incertidumbre**: empezar por devoluciones y caja.

---

## 9. Definición de terminado

**Fase 1** — los tres cambios aplicados, los tests 1 a 4 de §5 en verde, `.env.prod.example` actualizado y el orden de rotación documentado en `docs/security/secret-rotation-plan.md`.

**Fase 2** — la unidad `billing (commands)` pasa de `blocked` a `covered` o a `candidate` con hallazgo. Tests 5 y 6 de §5 en verde. Si aparece un defecto, entra en este plan con su propio ID.

**Fase 3** — las 6 unidades con hechos no resueltos quedan sin `unresolved`, o con un hallazgo registrado.

**Fase 4** — las 8 unidades diferidas tienen evidencia y una disposición: `covered`, `candidate` o `blocked` con bloqueador explícito. Ninguna queda `deferred`.

**Puerta de usuarios reales.** Independientemente del avance de este plan, antes de incorporar usuarios reales hacen falta tres cosas que **no** son tareas de código: responder U-1 sobre el entorno nuevo, un ensayo de restauración de backup exitoso, y verificación independiente de los hallazgos de `run-1` (los traces están en `findings.json` para que cueste poco).

---

## 10. Trazabilidad

| Artefacto | Ruta |
|---|---|
| Informe principal | `~/security-audit-skill/SaaSVet/run-1/REPORT.md` |
| Detalle del hallazgo confirmado | `~/security-audit-skill/SaaSVet/run-1/FINDINGS-DETAIL.md` |
| Pendientes de validación | `~/security-audit-skill/SaaSVet/run-1/NEEDS-VALIDATION.md` |
| Registros estructurados (11) | `~/security-audit-skill/SaaSVet/run-1/findings.json` |
| Ledger de cobertura (25 unidades) | `~/security-audit-skill/SaaSVet/run-1/coverage-ledger.json` |
| Superficie de ataque y fronteras | `~/security-audit-skill/SaaSVet/run-1/architecture.md` |
| Estado y limitaciones de la corrida | `~/security-audit-skill/SaaSVet/run-1/run-metadata.json` |

Los 7 registros **rechazados** de `findings.json` existen para que una corrida futura no repita hipótesis sin evidencia nueva. Si alguna reaparece, debe traer evidencia que cambie la traza.
