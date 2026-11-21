# Plan técnico — Equipo: corregir y revertir (A1 + A2)

**Fecha:** 2026-11-19
**Revisión:** 4 (incorpora las decisiones aprobadas y la verificación de cinco puntos de la rev. 3)
**Estado:** IMPLEMENTADO en local (F0–F7), sin commit ni despliegue. Todas las decisiones (D1–D14)
aprobadas. Registro de implementación al final; riesgos abiertos en la Parte III §6.
**Origen:** [Análisis de producto del módulo Equipo](analisis-modulo-equipo-2026-11-19.md),
propuestas A1 y A2.

Todas las rutas de archivo son relativas a la raíz del repositorio.

### Historial de revisiones

- **Rev. 1:** plan inicial.
- **Rev. 2:** corrige la protección del último ADMIN, que no resistía peticiones concurrentes;
  cambia su respuesta a 409; agrega `no-store` a las respuestas con contraseña temporal;
  replantea la demo sin bloquear el alta; da a la reactivación un límite propio; precisa la
  validación de nombres (D4); elimina el `get_or_create` de `UserRole`; reduce el frontend a
  la página existente más un CSS module, y amplía las pruebas.
- **Rev. 3:** agrega la fase F0, versión de sesión (D12, ADR p65); retira el «riesgo residual
  aceptado» de la rev. 2, que era falso; agrega el inventario del último ADMIN, las reglas de
  atomicidad de la reactivación, la identificación de las cuentas semilla de la demo y la tabla
  de ejemplos de nombres; plantea D13 y D14.
- **Rev. 4:**
  - Registra como aprobadas D2, D3, D6–D11, D13 y D14.
  - **Monotonía de la versión de sesión** (II.0): especifica el guardado de `User` campo por
    campo (`save()`, `update_fields`, campos diferidos, inserción, `QuerySet.update()`, `F()` y
    admin de Django) y las reglas exactas del gate estático, que distingue lecturas de
    escrituras.
  - **Interceptor (D14)** (II.0): condiciones exactas del reintento, exclusión de login, refresh
    y cierre de sesión, por qué reintentar un POST no duplica efectos, y pruebas concurrentes.
  - **Atomicidad de la reactivación** (II.3): documenta la restricción de `durable=True`, las
    rutas indirectas verificadas, un gate de un solo llamador y `on_commit(robust=True)`.
  - **Cuentas de servicio** (II.0): tabla de protección en vista y servicio por operación,
    criterio estable (`is_service_account`) y gate sobre sus escritores.
  - **Cobertura de F0** (II.0): inventario de emisión y validación de tokens, incluidos los
    tokens sin `sv` y un gate sobre los sitios que emiten tokens. Verificado que login, refresh
    y cierre de sesión ignoran la cabecera `Authorization`, así que un token viejo almacenado
    no bloquea el login.
  - **Correcciones a la rev. 3:**
    - Cambiar la contraseña **no** cierra las otras pestañas del mismo navegador cuando la
      sesión se recordó: comparten el almacenamiento y toman el token nuevo (I.3, hallazgo 18).
    - El evento de la reactivación necesita `on_commit(robust=True)`: la rev. 3 suponía que
      `logging` absorbía cualquier error, pero el propio callback puede fallar y convertir una
      reactivación ya confirmada en un 500 (I.3, hallazgo 16).
  - Agrega la lista explícita de riesgos que siguen abiertos (Parte III §6).

## Alcance aprobado

0. **Versión de sesión (F0, D12):** invalidación inmediata de los tokens emitidos antes de
   desactivar, reactivar, restablecer (de clínica o de plataforma) o cambiar la contraseña.
1. **Edición del integrante (A1):** nombre, apellido, correo electrónico, especialidad y cédula
   profesional.
2. **Reactivación (A2):** ver integrantes activos e inactivos y reactivar a los desactivados
   mediante credenciales temporales y cambio obligatorio de contraseña, conservando la misma
   identidad, relaciones e historial.
3. **Correcciones incluidas:** `can()` en lugar de rol, ocultar acciones no válidas (sobre todo
   en la cuenta propia), `handleFormError`, textos y validaciones de contraseña alineados con el
   backend, sustituir el icono de eliminar, mejorar la confirmación de desactivación y
   reemplazar estilos inline por CSS module y tokens.

**Fuera de alcance:** cambio de rol, estado de acceso (A3), contraseña generada en el alta
(A4), impacto al desactivar (A5), «atiende pacientes» (B1), cerrar sesión en todos los
dispositivos, invalidar sesiones al desactivar una organización completa y los cambios hechos
desde el admin de Django o la shell.

---

## Parte I. Verificación contra el repositorio

### I.1 Hallazgos del análisis confirmados

| Hallazgo | Evidencia |
|---|---|
| El PATCH solo acepta especialidad y cédula | `backend/apps/users/serializers.py:204` |
| La lista solo devuelve activos; no hay endpoint de reactivación | `backend/apps/users/views.py:88`, `backend/config/urls.py:219-224` |
| El correo es único global, sin distinguir mayúsculas, e incluye inactivos | `backend/apps/users/models.py:76` |
| El texto de desactivar dice «revertir desde la base de datos» y usa icono de basura | `frontend/src/pages/staff.jsx:135`, `:332` |
| La página decide por rol (`isAdmin`); restablecer y desactivar no usan `can()` | `frontend/src/pages/staff.jsx:59`, `:318-333` |
| El alta no usa `handleFormError` | `frontend/src/pages/staff.jsx:113` |
| El placeholder pide 6 caracteres; el backend exige 8, una mayúscula y un número | `frontend/src/pages/staff.jsx:515`, `backend/apps/users/serializers.py:128` |
| Estilos inline y color hex `#fbbf24` | `frontend/src/pages/staff.jsx:294-391`, `:472`, `:519` |
| La fila propia muestra acciones que el backend rechaza | `backend/apps/users/services.py:263`, `:393` |
| Las consultas y recetas cerradas usan el snapshot; las abiertas, los datos vivos | `backend/apps/medical_records/views.py:548`, `backend/apps/prescriptions/views.py:169,196` |

### I.2 Supuestos del diseño comprobados

**Tokens y autenticación:**

| Supuesto | Evidencia |
|---|---|
| Revocar todos los `OutstandingToken` alcanza a los refresh tokens rotados | simplejwt 5.5.1 (versión fija en `backend/requirements.lock:49`) llama a `refresh.outstand()` en cada rotación. |
| El refresh se rechaza mientras el usuario está inactivo | El serializer de refresh de simplejwt aplica `USER_AUTHENTICATION_RULE`, que exige `is_active`. |
| Hoy el JWT solo contiene `user_id` y los claims estándar | `EmailOrUsernameTokenObtainPairSerializer` (`backend/apps/users/serializers.py:17`) no sobrescribe `get_token`. |
| Un claim propio del refresh pasa al access y sobrevive a la rotación | simplejwt 5.5.1: `RefreshToken.access_token` copia todos los claims salvo `no_copy_claims` (`token_type`, `exp`, `jti`, `iat`). `TokenRefreshSerializer.validate` rota el mismo token con `set_jti`, `set_exp`, `set_iat` y `outstand`. |
| La autenticación ya relee al usuario en cada petición | `backend/apps/core/authentication.py:27`. Comparar una versión no agrega consultas. |
| No existe versionado de sesión | Ninguna comparación de versión ni de `iat` en `backend/apps/core/authentication.py` ni en `backend/config/urls.py:151-165`. |
| Solo tres sitios productivos emiten tokens, más la rotación de simplejwt | Login (`get_token` heredado), `change_password` (`backend/apps/users/services.py:160`) y el agente (`backend/apps/agent/executor.py:53`, solo cuentas de servicio). Ningún comando ni otra vista los emite. |
| La API solo autentica con `TenantJWTAuthentication` | `DEFAULT_AUTHENTICATION_CLASSES` (`backend/config/settings.py:313-315`) y ninguna vista sobrescribe `authentication_classes`. Ninguna vista fuera de DRF lee un JWT. |
| Login, refresh y cierre de sesión ignoran la cabecera `Authorization` | Heredan de `TokenViewBase` de simplejwt, que declara `authentication_classes = ()`. Son las únicas vistas DRF con `AllowAny` (`backend/config/urls.py:62`, `:148`, `:174`); salud y webhook son vistas Django sin JWT. |
| El 401 de autenticación ocurre antes de ejecutar la vista | DRF autentica en `APIView.initial()`, antes del handler; `TenantMiddleware` no autentica JWT. |
| El frontend usa axios para el login y `fetch` para refresh, cierre de sesión y `/me` inicial | `frontend/src/auth/login.js:4`; `frontend/src/auth/AuthProvider.jsx:44`, `:72`, `:145`, `:186`. |
| El interceptor de peticiones pone el token almacenado en cada petición | `frontend/src/api/client.js:14-18`. |
| Un refresh periódico fallido ya cierra la sesión | `frontend/src/auth/AuthProvider.jsx:86-95` |
| Las sesiones recordadas comparten el token entre pestañas | `tokenStorage`: `localStorage` con «Recordarme»; `sessionStorage` (por pestaña) sin él. |

**Modelo, transacciones y cuentas de servicio:**

| Supuesto | Evidencia |
|---|---|
| Django admite `db_default`, `atomic(durable=True)` y `on_commit(robust=True)` | Django 6.0.5 (`backend/requirements.lock:33`). `durable` exime los bloques propios de `TestCase` (`_from_testcase`, comprobado en el código instalado). |
| No hay `ATOMIC_REQUESTS` ni middleware, mixin o permiso que abra transacciones | Búsqueda en `backend/config` y `backend/apps/core`. |
| El agente llama a la API por HTTP real | `requests.request` en `backend/apps/agent/executor.py:120`: cada llamada es otra petición con su propia transacción. |
| `agent_eval` llama a la API en proceso, dentro de una transacción que revierte | `backend/apps/agent/management/commands/agent_eval.py:112`. |
| El único receptor de `post_save` de `User` solo mira `created` | `backend/apps/users/signals.py:9`. |
| Los usuarios no se borran | No hay API de borrado y el admin lo impide (`backend/apps/users/admin.py:22`). |
| `is_service_account` solo se escribe al crear la cuenta del agente | `ensure_agent_user` (`backend/apps/users/services.py:528`). No está en los serializers (`serializers.py:62`, `:89`) ni en los fieldsets del admin (`admin.py:11-13`); la migración `0011` no tiene paso de datos. |
| El rol no sirve para identificar cuentas de servicio | El alta solo admite ADMIN, VET y ASSISTANT (`serializers.py:73-74`), pero el admin de Django puede asignar `role='AGENT'` a una persona. |
| Las vistas de Equipo ya excluyen las cuentas de servicio | `backend/apps/users/views.py:91`, `:132`, `:154`, `:261`. |
| Ninguna prueba existente afirma la ventana residual que F0 elimina | Búsqueda en las suites de `users`, `platform`, `core` y `legal`. La única prueba de esa clase es `test_access_token_remains_valid_until_it_expires` (`backend/apps/users/tests/test_token_logout.py:70`), sobre cerrar sesión, que F0 no cambia. Ninguna prueba compara el código `token_not_valid`. |

**Resto del diseño:**

| Supuesto | Evidencia |
|---|---|
| `seed_permissions` actualiza los roles existentes en cada despliegue | `role.permissions.set(...)` en `backend/apps/core/management/commands/seed_permissions.py:154`; se ejecuta en `backend/scripts/release.sh:49`. |
| Si el permiso nuevo no se concede al ADMIN, falla un test | `test_admin_receives_the_approved_matrix` exige que la lista del ADMIN sea igual al catálogo. `test_every_route_requires_a_code_the_admin_holds` y `test_codes_asked_by_services_are_held_by_the_admin` detectan rutas o servicios que pidan un código que el ADMIN no tiene (`backend/apps/core/tests/test_admin_explicit_grants.py`). |
| Con la organización desactivada no hay login ni refresh | `backend/apps/core/authentication.py:41`, `backend/config/urls.py:107`, `:162` |
| El frontend tiene `/me` con `id`, y `refreshUser` actualiza el usuario en estado y almacenamiento | `frontend/src/auth/AuthProvider.jsx:250-262` |
| Existe un patrón de pruebas concurrentes con hilos | `threading.Barrier` en `backend/apps/appointments/tests/test_create_with_patient_identity.py:229` |

### I.3 Hallazgos nuevos que condicionan el diseño

1. **Hay que revocar sesiones al reactivar.** Desactivar desde el admin de Django no revoca
   tokens; solo lo hace `deactivate_staff`. Un refresh token sin revocar volvería a funcionar
   tras reactivar a la persona.
2. **La contraseña anterior seguiría funcionando** si se reactiva sin emitir una nueva. La
   contraseña temporal es obligatoria.
3. **El último ADMIN se puede perder con peticiones concurrentes (ya ocurre hoy).** Si una
   clínica tiene dos ADMIN y cada uno desactiva al otro al mismo tiempo, cada transacción
   bloquea solo a su objetivo, cuenta dos ADMIN activos y ambas confirman: la clínica queda sin
   administrador. La regla de no desactivarse a sí mismo no lo impide.
4. **El restablecimiento devuelve la contraseña temporal sin `Cache-Control: no-store`.**
   `StaffResetPasswordView` no usa `NoStoreResponseMixin`, a diferencia del login, el refresh y
   el cambio de contraseña (H-09).
5. **La demo se puede romper hoy.** El reset automático (`_purge(full=False)`) no borra usuarios
   y `_ensure_users` omite a los existentes. Un visitante con la cuenta administradora de la demo
   puede restablecer o desactivar las cuentas compartidas, que quedan rotas hasta una
   intervención manual. Además, cualquier alta en la demo inutiliza ese correo para siempre a
   nivel global.
6. **Existe un precedente de listar y restaurar archivados.** Mascotas y Clientes usan
   `?archived=true` y `POST …/restore/` (`frontend/src/api/pets.js:31-37`). El nombre
   «reactivate» tiene precedente en el ciclo de vida de organizaciones.
7. **Hay nombres reales que se rechazan.** `NAME_REGEX` no admite ü, apóstrofo ni guion
   («Argüelles», «María-José»); `.title()` convierte «de la Cruz» en «De La Cruz»; iOS inserta
   el apóstrofo tipográfico ’ (U+2019); un texto pegado puede venir en Unicode NFD.
8. **Desactivar no elimina el `UserRole`** y `seed_permissions` no toca `UserRole`: la
   reactivación no necesita recrearlo.
9. **Corrección menor al análisis.** En Citas, el detalle de la cita sí muestra el nombre de un
   veterinario inactivo (usa `veterinarian_name` como respaldo); solo el filtro y los colores
   lo omiten.
10. **El script de verificación de errores de formulario no existe.** La documentación menciona
    `scripts/check-handle-errors.sh`, pero no está en el repositorio ni en CI. El uso de
    `handleFormError` debe cubrirse con pruebas.
11. **El access token anterior sí recupera privilegios (bloqueante; corrige la rev. 2).**
    - Secuencia: login → desactivar → reactivar dentro de los 15 min → la persona entra con la
      temporal y la cambia → `password_must_change` vuelve a `False` → el access token del
      primer login vuelve a tener acceso completo hasta que vence.
    - Revocar refresh tokens no lo evita: el access token no pasa por la lista de revocación.
    - El mismo hueco existe hoy en el restablecimiento (de clínica y de plataforma) y en el
      cambio de contraseña. ADR p20 lo aceptó como una ventana de 15 min
      (`backend/config/settings.py:399-405`).
    - El caso más grave es el restablecimiento por compromiso: el token robado vuelve a servir
      en cuanto la víctima cambia su contraseña.
12. **El restablecimiento de plataforma no excluye cuentas de servicio.**
    - La vista filtra solo `is_active=True` y `role != 'ADMIN_SAAS'`
      (`backend/apps/platform/views.py:238-241`) y el servicio solo rechaza `ADMIN_SAAS`.
    - Hoy, restablecer la cuenta del agente lo bloquea por el cambio obligatorio hasta que
      `ensure_agent_users` lo repara.
    - Con F0 el daño sería permanente: los tokens del agente no llevan versión y la reparación
      no puede (ni debe) bajarla. D13 lo corrige.
13. **Un `save()` completo sobre una instancia vieja podría bajar la versión de sesión.** Por
    ejemplo, el formulario de usuario del admin de Django guarda todos los campos. Si entre la
    lectura y el guardado la persona cambió su contraseña, la versión volvería al valor anterior
    y revivirían los tokens que debían morir.
14. **Las peticiones en vuelo del propio usuario recibirían 401 al cambiar su contraseña.** Una
    consulta periódica enviada con el token anterior mientras se procesa el cambio llega después
    del incremento. Hoy el interceptor (`frontend/src/api/client.js:35-38`) cierra la sesión
    ante cualquier 401. D14 lo corrige.
15. **Cerrar sesión es por dispositivo.** `PublicTokenLogoutView` revoca solo el refresh
    recibido (`backend/config/urls.py:167-175`). F0 no lo cambia: incrementar la versión al
    cerrar sesión cerraría todos los dispositivos.
16. **El callback de `on_commit` puede fallar después del commit (corrige la rev. 3).** Un error
    al armar el evento (no al escribirlo) se propagaría desde el commit: la reactivación ya
    quedó confirmada, pero la vista respondería 500 sin la contraseña temporal. Con
    `on_commit(..., robust=True)` Django registra el error y no lo propaga.
17. **Un token viejo almacenado no afecta al login.** El login usa axios y el interceptor le
    agrega el token guardado, pero las vistas de token de simplejwt no autentican la cabecera
    (I.2). El login, el refresh y el cierre de sesión funcionan igual con un token revocado en el
    almacenamiento. Se fija con una prueba.
18. **Las pestañas del mismo navegador no se cierran al cambiar la contraseña propia (corrige la
    rev. 3).** Con «Recordarme» comparten `localStorage`: la siguiente petición de otra pestaña
    lee el token nuevo. Se cierran las sesiones de otros navegadores y dispositivos, y las
    pestañas con sesión no recordada (`sessionStorage`).
19. **F0 cierra además una carrera actual de la rotación.** Si un refresh se rota mientras otra
    transacción revoca los `OutstandingToken`, el token rotado se crea después de la lista que
    se revoca y escapa de ella. Con F0 nace con la versión anterior y no sirve.
20. **Los cambios hechos desde el admin de Django o la shell no invalidan sesiones.** Cambiar
    la contraseña desde el admin o con `changepassword` no revoca refresh tokens ni incrementa la
    versión. Es preexistente y es la vía de operadores; F0 solo garantiza que esas vías no bajen
    la versión. Queda como riesgo abierto.

---

## Parte II. Diseño detallado

### II.0 F0 — Versión de sesión (D12, ADR p65)

**Garantía.** Un access o refresh token emitido antes de desactivar, reactivar, restablecer (de
clínica o de plataforma) o cambiar la contraseña de una persona se rechaza en su siguiente uso,
sin esperar a que venza. No depende del frontend, de la revocación de refresh tokens ni de
tiempos.

#### Modelo

`User.session_version`: entero no negativo, `default=0`, `db_default=0` y `editable=False`.
Migración en II.7.

#### Monotonía

La versión solo cambia mediante `bump_session_version`. Comportamiento por mecanismo:

| Mecanismo | Comportamiento |
|---|---|
| `bump_session_version(user)` | `User.objects.filter(pk=user.pk).update(session_version=F('session_version') + 1)` dentro de la transacción del llamador y, después, `refresh_from_db(fields=['session_version'])`. El `UPDATE` es atómico en la base: dos incrementos concurrentes suman dos. Es la **única** escritura legítima. |
| `save()` sin `update_fields`, fila existente | `User.save()` calcula los campos a escribir igual que Django (los campos concretos cargados, sin la PK ni los diferidos) **menos** `session_version`. Una instancia vieja no puede bajar la versión. |
| `save(update_fields=[...])` sin `session_version` | Sin cambio. Es el caso de todos los servicios actuales (`deactivate_staff`, `change_password`, `reset_password_for_staff`, `update_staff_profile`, `ensure_agent_user`). |
| `save(update_fields=[...])` con `session_version` | `ValueError`: error de programación. Cubre también nombres dinámicos, como el `setattr` de `update_staff_profile`, cuyo serializer además tiene lista blanca. |
| Inserción (alta, `create_user`, `ensure_agent_user`) | Sin cambio: nace en 0. |
| `QuerySet.update()`, `bulk_update`, `bulk_create` | No pasan por `save()`. Solo el gate estático las controla. |
| Asignar `F()` al atributo y luego `save()` | El guardado completo la omite y el gate la detecta como escritura. |
| Formulario del admin de Django | `editable=False` la excluye del formulario y no puede ir en los fieldsets. El guardado completo del admin la omite. |
| Cambio de contraseña desde el admin o `changepassword` | Guardado completo: no baja la versión, pero tampoco la incrementa (I.3, hallazgo 20). |
| `loaddata` | Usa `save_base` y escribe el valor del fixture. Solo en pruebas o por operadores. |

**Efectos secundarios del nuevo `save()`, verificados:**

- Un guardado completo de una fila que ya no existe falla en lugar de reinsertarla. Los usuarios
  no se borran (I.2), así que no hay caso real.
- Los receptores de `post_save` reciben `update_fields` como conjunto en lugar de `None` en los
  guardados completos. El único receptor de `User` solo mira `created` (I.2).

**Gate estático de la versión** (`backend/apps/users/tests/test_session_version_gate.py`):

- **Alcance:** Python productivo en `backend/apps` y `backend/config`, sin `tests/` ni
  `migrations/`. Recorre el AST, no el texto.
- **Escrituras:**
  - un atributo `session_version` como destino de una asignación, asignación aumentada o
    anotada;
  - un argumento con nombre `session_version` en cualquier llamada que no sea de lectura
    (`filter`, `exclude`, `get`, `Q`);
  - cualquier cadena literal que contenga `session_version` (listas de `update_fields`,
    `bulk_update`, `setattr`, `values_list` o SQL).
- **Permitidas:** la declaración del campo y el `save()` de `User` en
  `backend/apps/users/models.py`, y `bump_session_version` en `backend/apps/users/services.py`.
- **Lecturas libres:** leer el atributo (`user.session_version`) no se restringe, como en la
  autenticación y al estampar el claim. Una lectura nueva con cadena literal se clasifica a mano
  en la lista del gate.
- **No lo detecta:** una actualización masiva con claves dinámicas (`update(**campos)`). Hoy no
  existe ninguna (Parte III §6).

#### Claim

- Se llama `sv`. El nombre se define una sola vez en `backend/apps/core/authentication.py`,
  junto con dos funciones: una lo estampa en un token a partir del usuario y otra lo lee. No
  choca con los claims de simplejwt (`token_type`, `exp`, `iat`, `jti`, `user_id`).
- Ausente, vale 0. Así los tokens vigentes al desplegar siguen funcionando y nadie pierde la
  sesión.
- Presente pero no entero no negativo: se rechaza como `session_revoked`. Un token firmado por
  el servidor nunca lo tiene así.

#### Emisión de tokens: cobertura

| Vía | Sitio | `sv` |
|---|---|---|
| Login por username o por correo | `get_token` de `EmailOrUsernameTokenObtainPairSerializer` (lo sobrescribe F0) | Versión del usuario autenticado; el access la hereda. |
| Rotación del refresh | simplejwt (sin cambio) | Se conserva en el refresh rotado y en su access. |
| Cambio de contraseña propio | `change_password`: incrementa, relee y emite | La versión nueva. |
| Agente | `mint_agent_token` (sin cambio) | Sin claim: vale 0 y nunca se incrementa. |
| `agent_eval` y harness de pruebas del agente | Usan `mint_agent_token` | Sin claim, cuenta de servicio. |
| Tokens vigentes al desplegar | — | Sin claim: valen 0 hasta el primer incremento de esa persona. |
| Pruebas que emiten con `RefreshToken.for_user` | Solo pruebas | Sin claim: válidas mientras la versión sea 0. |

- **Carreras:** un login o un refresh que corre a la vez que un incremento emite el token con
  la versión anterior; al confirmarse el incremento, ese token se rechaza. Falla hacia el lado
  seguro.
- **Gate de emisión** (en `test_session_version_gate.py`): enumera los sitios productivos que
  llaman a `for_user(` o a `get_token(`. Hoy son tres, cada uno clasificado: login (estampa),
  `change_password` (estampa) y `mint_agent_token` (cuenta de servicio, sin claim). Un sitio
  nuevo sin clasificar hace fallar la prueba.

#### Validación de tokens: cobertura

| Superficie | Mecanismo | F0 |
|---|---|---|
| Endpoints DRF autenticados | `TenantJWTAuthentication`, la única clase configurada | Compara la versión después de comprobar cuenta y organización activas: 401 `session_revoked`. Usa la instancia que ya relee: cero consultas adicionales. `user_inactive` y `organization_inactive` conservan su prioridad. |
| Cabecera `Authorization` en login, refresh o cierre de sesión | `TokenViewBase` no autentica (I.2) | Ninguno: la cabecera se ignora, así que un token viejo almacenado no bloquea el login (I.3, hallazgo 17). |
| Refresh token del cuerpo | Comprobación previa de `PublicTokenRefreshView` | Compara **antes** de rotar: 401 `{code: 'session_revoked', detail}`. No se rota ni se crea un `OutstandingToken`. |
| Cierre de sesión | `TokenBlacklistView` | Sin cambio: revocar un token que ya no sirve es inocuo. |
| Vistas Django fuera de DRF | Webhook (firma HMAC) y salud | No usan JWT. |
| Admin de Django | Sesión de Django, solo superusuarios | Fuera de alcance. |

- Se compara por **igualdad**. La versión solo crece, así que un token con versión mayor solo
  podría salir de una transacción revertida, y esa respuesta nunca llega al cliente.
- Evento `AUTH_SESSION_REVOKED` (INFO) con `user_id`, versión del token y versión actual. Sin
  el token ni datos personales.

#### Incrementos

| Operación | Servicio | Fase |
|---|---|---|
| Desactivar | `deactivate_staff` | F0 |
| Restablecer (clínica) | `reset_password_for_staff` | F0 |
| Restablecer (plataforma) | `platform_reset_password` | F0 |
| Cambiar la contraseña propia | `change_password`, después de guardar la contraseña y antes de emitir el par nuevo | F0 |
| Reactivar | `reactivate_staff`, mediante `_revoke_all_sessions` | F3 |

- Se conserva la revocación de `OutstandingToken` en todas: es defensa en profundidad y mantiene
  el contrato actual del refresh.
- Reactivar incrementa aunque desactivar ya lo haya hecho: cubre a quien fue desactivado fuera
  del servicio (admin de Django), cuyos tokens nunca se invalidaron.
- **No** incrementan: editar el perfil o el correo (D2), cerrar sesión (I.3, hallazgo 15), crear
  un usuario (nace en 0), `ensure_agent_users` y desactivar la organización (fuera de alcance).
- Si el servicio falla después del incremento, la transacción lo revierte junto con todo lo
  demás: la contraseña no cambió y los tokens anteriores siguen siendo válidos, que es lo
  coherente.

#### Cuentas de servicio (D13)

**Criterio:** `is_service_account=True`, no el rol (I.2). Ninguna vía incrementa su versión, y
sus tokens sin claim siguen funcionando.

| Operación | Vista | Servicio |
|---|---|---|
| Lista de Equipo | Excluye (`views.py:91`) | — |
| Editar | Excluye (`views.py:132`) | 404 en `update_staff_profile` |
| Desactivar | Excluye (`views.py:154`) | 404 (`services.py:398`) |
| Restablecer (clínica) | Excluye (`views.py:261`) | 404 (`services.py:271`) |
| Reactivar (F3) | El queryset nuevo excluye | 404 en `_assert_manageable_target` |
| **Restablecer (plataforma)** | **F0 agrega la exclusión** (`platform/views.py:238-241`) | **F0 agrega el 404** en `platform_reset_password` |
| Cambiar la contraseña propia | Es la propia cuenta | La contraseña de una cuenta de servicio es inutilizable: `check_password` falla con 400 antes del incremento. |
| `bump_session_version` | — | Rechaza una cuenta de servicio. Llegar ahí sería un error de programación. |

**Gate:** el mismo test que vigila los escritores de `is_active` y `role` (II.3.1) clasifica
los de `is_service_account`. Hoy solo lo escribe `ensure_agent_user` al crear la cuenta.

#### Frontend (D14)

Un 401 `session_revoked` se trata como cualquier 401. La única excepción es el reintento de D14
en `frontend/src/api/client.js`.

**Condiciones del reintento** (se tienen que cumplir todas):

1. La respuesta es 401.
2. La URL no es de autenticación (`token/`, `token/refresh/`, `token/logout/`). El login
   conserva su excepción actual; refresh y cierre de sesión hoy usan `fetch`, pero se excluyen
   también por URL.
3. La petición no fue ya reintentada (marca propia en la configuración de esa petición).
4. La petición llevaba `Authorization: Bearer <t>`.
5. Hay un access token almacenado y es distinto de `<t>`.
6. No hay un cierre de sesión en curso (`isLoggingOut()`).

**Acción:** marcar la petición y repetirla. El interceptor de peticiones pone el token vigente;
`X-Request-ID`, `X-Idempotency-Key`, cuerpo y señal de cancelación se conservan. En cualquier
otro caso, el comportamiento de hoy: limpiar los tokens y llevar a `/login` (o, en el login,
devolver el error sin redirigir).

**Propiedades:**

- **Sin bucles:** como máximo dos intentos por petición.
- **Sin renovaciones recursivas:** el reintento nunca llama al refresh y no hay estado
  compartido entre peticiones.
- **Concurrencia:** cada petición decide sola. Si varias fallan con el token anterior, cada una
  se reintenta una vez; si el token vigente también falla, todas terminan en el cierre de sesión
  de hoy, que es idempotente.
- **Sin efectos duplicados:** DRF autentica antes de ejecutar la vista y ninguna vista fuera de
  DRF usa JWT (I.2). Un 401 significa que la petición no hizo nada, así que reintentar un POST,
  PATCH o DELETE es seguro.
- **Sin interferencias:** login, refresh y cierre de sesión quedan fuera por la condición 2.
  Tras un cierre de sesión no hay token almacenado ni se reintenta (condiciones 5 y 6).
- **Beneficio adicional:** también cubre la carrera actual en que un access token vence mientras
  viaja y el refresh periódico ya lo renovó.
- El interceptor compara tokens, nunca los escribe en consola (gate `noConsoleTokenLeak`).

#### Consecuencias visibles

- Cambiar la contraseña cierra al instante las sesiones de esa persona en otros navegadores y
  dispositivos, y en pestañas con sesión no recordada. Las pestañas del mismo navegador con
  «Recordarme» siguen funcionando, porque toman el token nuevo (I.3, hallazgo 18).
- Restablecer, desactivar o reactivar expulsa a la persona en su siguiente petición.

#### Despliegue y reversión

- `release.sh` migra antes de arrancar la aplicación.
- Durante el relevo de instancias, una instancia antigua no compara versiones: esos minutos
  tienen la misma ventana que hoy.
- Revertir el código es seguro: la columna queda sin uso y el claim se ignora.

#### ADR p65

`docs/decisions/2026-11-19-p65-version-de-sesion.md`, escrito al inicio de F0, antes del código:

- **Contexto:** la ventana de 15 min aceptada en p20 y el caso de I.3, hallazgo 11.
- **Decisión:** lo descrito en esta sección, incluidas la monotonía, la cobertura de emisión y
  validación y la exclusión de las cuentas de servicio.
- **Alternativas descartadas:**
  - Lista de revocación por `jti` del access token: estado nuevo y una consulta por petición
    (p20, camino 1).
  - Espera mínima antes de reactivar (D12, opción B): depende de tiempos y no cubre restablecer
    ni cambiar la contraseña.
  - Comparar `iat` con la fecha del último cambio: `iat` tiene resolución de segundos y depende
    del reloj; un contador entero no.
  - Reducir la vida del access token: achica la ventana, no la cierra.
- **Fuera de alcance:** cerrar sesión en todos los dispositivos, invalidar sesiones al desactivar
  una organización, y los cambios hechos desde el admin de Django o la shell (salvo la
  monotonía, que sí se garantiza).
- **Addendum a p20:** su sección «Comportamiento del access token actual» queda superada por p65
  para estas operaciones. Cerrar sesión conserva la ventana de 15 min.

### II.1 Contrato de API

| Endpoint | Estado | Permiso | Cambio |
|---|---|---|---|
| Toda petición autenticada | Existe | — | Puede responder 401 `session_revoked` (F0). |
| `POST /api/token/` | Existe | Público | El refresh y el access incluyen `sv` (F0). |
| `POST /api/token/refresh/` | Existe | Público | 401 `session_revoked` antes de rotar si la versión no coincide (F0). |
| `POST /api/users/change-password/` | Existe | Autenticado | Mismo contrato; el par devuelto lleva la versión nueva y las sesiones de otros navegadores y dispositivos dejan de servir (F0). |
| `POST /api/platform/staff/<uuid>/reset-password/` | Existe | Operador de plataforma | Cuenta de servicio: 404 (D13). Incrementa la versión (F0). |
| `GET /api/staff/` | Existe | `staff.list` | Por defecto se comporta igual que hoy (solo activos). Lo consume Citas (`frontend/src/pages/appointments.jsx:1057`). |
| `GET /api/staff/?archived=true` | Parámetro nuevo (D6) | `staff.list` y `staff.reactivate` | Solo inactivos de la clínica, sin `ADMIN_SAAS` ni cuentas de servicio. Sin `staff.reactivate`: 403. |
| `PATCH /api/staff/<uuid>/` | Existe | `staff.update` | Admite también `first_name`, `last_name` y `email`. Rol, username, contraseña e `is_active` siguen respondiendo 400. Cuentas semilla de la demo: 403 `demo_seed_account`. |
| `DELETE /api/staff/<uuid>/` | Existe | `staff.destroy` | Bloqueo concurrente (II.3). Respuestas nuevas: 409 `last_active_admin` y 403 `actor_inactive`. Cuentas semilla de la demo: 403. |
| `POST /api/staff/<uuid>/reset-password/` | Existe | `staff.reset_password` | Mismo contrato. Agrega `Cache-Control: no-store` (D11). Cuentas semilla de la demo: 403. |
| `POST /api/staff/<uuid>/reactivate/` | **Nuevo** | `staff.reactivate` | Cuerpo vacío. Responde 201 con la misma forma que el restablecimiento (`temp_password`, `expires_in_seconds`, `must_change_on_first_login`, `request_id`, `duration_ms`) más el `member` serializado. Con `no-store`. Usuario ya activo: 409 `already_active`. |

`UserSerializer` agrega el campo de solo lectura `demo_protected` (booleano), para que la
interfaz oculte las acciones sobre las cuentas semilla de la demo (D5). Es una adición
compatible y **no autoriza nada**: la regla la aplica el servicio (II.4).

El único endpoint nuevo es el de reactivación. Las respuestas de conflicto siguen el sobre
estándar `{code, message}`, igual que `appointment_changed`.

### II.2 Serializers (`backend/apps/users/serializers.py`)

- **Login (F0):** `EmailOrUsernameTokenObtainPairSerializer.get_token` estampa `sv` (II.0).
- **Validadores comunes.** Se extraen a funciones del módulo para que alta y edición usen
  exactamente las mismas reglas.
- **Nombre y apellido (D4, aprobada):**
  - Se normaliza a Unicode NFC y se recortan los espacios de los extremos. Nada más se
    modifica: sin `.title()` ni colapso de espacios internos.
  - Caracteres permitidos: letras latinas por rangos explícitos (`A-Za-z`, `À-Ö`, `Ø-ö`, `ø-ÿ`,
    `Ā-ž`), espacio, guion, apóstrofo recto ' (U+0027) y apóstrofo tipográfico ’ (U+2019).
  - Se rechazan números, emojis, otros signos y letras de otros alfabetos. Los rangos
    explícitos evitan nombres con caracteres que imitan letras latinas (por ejemplo, una A
    cirílica) sin agregar dependencias.
  - `first_name` es obligatorio también en el backend del alta (hoy solo lo exige el
    frontend).
  - **El backend es la autoridad.** El frontend replica la misma regla solo para avisar antes de
    enviar. No es un proyecto de internacionalización.
- **Correo:**
  - Recorta espacios, convierte a minúsculas y comprueba unicidad global excluyendo al usuario
    que se edita.
  - Si está ocupado: «Este correo no está disponible.», el mismo mensaje genérico del alta (ADR
    p48 T-2), sin revelar en qué clínica existe.
  - **En la organización demo (D5):** alta y edición solo aceptan dominios reservados que no
    pertenecen a nadie: `example.com`, `example.net`, `example.org`, `*.test` y `*.example`
    (RFC 2606 y 6761). Mensaje: «En la demo usa un correo de ejemplo, como
    nombre@example.com.»
- **`UpdateEmployeeSerializer`:**
  - Acepta `first_name`, `last_name`, `email`, `specialty` y `license_number`.
  - `last_name` admite vacío.
  - El mismo correo con distintas mayúsculas se acepta sin guardar ni registrar evento.
  - Las claves desconocidas siguen respondiendo 400 con el texto: «Solo se pueden editar
    nombre, apellido, correo, especialidad y cédula profesional.»
  - Se mantiene la regla de cédula obligatoria para VET.
- **`CreateEmployeeSerializer`:** adopta los validadores comunes. Cambios de comportamiento:
  los de D4 (nombres) y la regla de dominios reservados en la demo.

**Tabla de ejemplos de nombres (D4).** Es el contrato compartido. Las suites del backend y del
frontend la copian literalmente y se documenta en `docs/modules/organizations.md`. Si cambia, se
cambia en los tres lugares.

| Entrada | Resultado | Se guarda como |
|---|---|---|
| `María José` | Acepta | Igual |
| `Argüelles` | Acepta | Igual |
| `María-José` | Acepta | Igual |
| `O'Brien` (U+0027) | Acepta | Igual |
| `D’Angelo` (U+2019) | Acepta | Igual |
| `de la Cruz` | Acepta | Igual, sin mayúsculas agregadas |
| `Zoë`, `Łukasz` | Acepta | Igual |
| `José` en NFD (e + U+0301) | Acepta | `José` en NFC |
| `  Ana  ` | Acepta | `Ana` |
| `Ana  Luz` (dos espacios) | Acepta | Igual, sin colapsar |
| `Juan2` | Rechaza | — |
| `Ana 😀` | Rechaza | — |
| `Аna` (A cirílica) | Rechaza | — |
| `Ana_Luz` | Rechaza | — |
| `Ma. José` | Rechaza: el punto no está entre los caracteres aprobados en D4 | — |
| Vacío o solo espacios, en el nombre | Rechaza: es obligatorio | — |
| Vacío, en el apellido | Acepta | Vacío |

### II.3 Services (`backend/apps/users/services.py`)

**Agregado en F0:** `bump_session_version(user)` (II.0), llamado desde `change_password`,
`reset_password_for_staff`, `deactivate_staff` y, en `backend/apps/platform/services/`,
`platform_reset_password`.

**Extracciones sin cambio de comportamiento** (F1, para no duplicar lógica):

- `_revoke_all_sessions(user) → int`: revoca todos los `OutstandingToken` e incrementa la
  versión de sesión. Sustituye el bucle hoy repetido en `reset_password_for_staff` y
  `deactivate_staff`, conservando lo que F0 ya hacía en ellos.
- `_issue_temporary_password(user) → str`: genera la contraseña, aplica `set_password`, fija
  `password_must_change=True` y `password_temp_issued_at=now`, y llama a
  `_revoke_all_sessions`.
- `_assert_manageable_target(admin, target)`: solo las comprobaciones comunes que responden 404
  (otra clínica, `ADMIN_SAAS`, cuenta de servicio). **No** unifica las respuestas propias de
  cada operación: actuar sobre uno mismo sigue siendo 403 en el restablecimiento y 400 en la
  desactivación.
- `_assert_not_demo_seed_account(target)`: 403 `demo_seed_account` si el usuario es una de las
  tres cuentas semilla de la organización demo (D5, II.4). La usan editar, restablecer y
  desactivar.

**Bloqueo para operaciones del ciclo de vida.** Se bloquean filas de `User` con
`select_for_update` en **una sola consulta ordenada por `pk`**. PostgreSQL aplica el bloqueo
después del ordenamiento, así que dos transacciones toman los bloqueos en el mismo orden y no
se bloquean cruzadas.

**`deactivate_staff`:**

1. Bloquea el conjunto: actor + objetivo y, si el objetivo es ADMIN, además todos los ADMIN
   activos de la clínica.
2. Con los bloqueos tomados vuelve a comprobar:
   - El actor sigue activo; si no, 403 `actor_inactive`.
   - El objetivo sigue activo.
   - Si el objetivo es ADMIN, queda al menos otro ADMIN activo; si no, 409
     `last_active_admin`.
3. Con lectura confirmada (READ COMMITTED), PostgreSQL vuelve a evaluar el filtro `is_active`
   sobre las filas que otra transacción acaba de confirmar. En el caso de dos ADMIN que se
   desactivan entre sí, la segunda operación encuentra a su propio actor inactivo y se rechaza.
4. Usa `_revoke_all_sessions`. El resto del contrato no cambia.

**`update_staff_profile`:**

- Se ejecuta dentro de una transacción.
- El guardado ocurre en un savepoint. Si falla por el índice único del correo, se captura la
  `IntegrityError` **solo si la restricción es `user_email_ci_unique`** y se devuelve como error
  del campo `email`. Cualquier otra `IntegrityError` se propaga: es la misma regla vigente para
  `slot_taken`.
- El log `STAFF_PROFILE_UPDATED` sigue registrando solo los nombres de los campos, nunca sus
  valores (el correo es dato personal).

**`reactivate_staff` (nuevo):**

1. Bloquea actor y objetivo en orden de `pk`.
2. Aplica `_assert_manageable_target` y exige que el actor sea ADMIN y siga activo con el
   bloqueo tomado, igual que en el restablecimiento. Exige organización activa como defensa en
   profundidad: si no lo está, el ADMIN ya no puede autenticarse.
3. Si el objetivo ya está activo: 409 `already_active`.
4. Fija `is_active=True`.
5. Llama a `_issue_temporary_password`: contraseña temporal de 24 h, revocación de todos los
   refresh tokens (incluidos los rotados) e incremento de la versión de sesión.
6. Programa `STAFF_REACTIVATED` con los mismos campos que `STAFF_DEACTIVATED` y sin la
   contraseña.
7. Devuelve la contraseña temporal una sola vez.

No recrea el `UserRole`: desactivar no lo elimina (I.3, hallazgo 8). Se conservan el PK, el
`public_id`, el rol, la cédula y todas las relaciones (citas, consultas, pagos, auditoría). No
se crea una cuenta nueva.

**Reglas de atomicidad de la reactivación:**

1. **`transaction.atomic(durable=True)`.** `reactivate_staff` tiene que ser la transacción más
   externa (restricción documentada abajo).
2. Todas las escrituras van en esa transacción: `is_active`, contraseña, marcas de cambio
   obligatorio, revocación de `OutstandingToken` e incremento de la versión.
3. El commit ocurre al salir del servicio. La vista arma la respuesta solo con lo que el
   servicio devolvió, así que **la contraseña temporal nunca se envía si el commit falla**: la
   excepción sube y se responde 500 sin credenciales en el cuerpo.
4. `STAFF_REACTIVATED` se emite con `transaction.on_commit(..., robust=True)`: no queda evento
   de una reactivación revertida, y un error del propio callback se registra sin convertir en
   500 una reactivación ya confirmada (I.3, hallazgo 16). Los eventos existentes no se mueven,
   porque sus pruebas leen el log dentro de la transacción.
5. Un error al escribir el log tampoco afecta la respuesta: `logging` captura los errores de sus
   handlers.

**Restricción de `durable=True`** (se documenta en el docstring de `reactivate_staff` y en
`docs/modules/organizations.md`):

- Si se llama con una transacción abierta, lanza `RuntimeError` antes de escribir nada. Es a
  propósito: dentro de otra transacción el commit ocurriría después, cuando la contraseña ya se
  devolvió.
- **Llamador único:** solo `StaffReactivateView`. Un gate estático falla si aparece otro
  llamador productivo.
- **Rutas indirectas verificadas** (I.2):
  - No hay `ATOMIC_REQUESTS` ni middleware, mixin o permiso que abra transacciones.
  - El agente llama a la API por HTTP real: cada llamada tiene su propia transacción.
  - `agent_eval` llama a la API en proceso dentro de una transacción que revierte, pero el rol
    AGENT no tiene `staff.reactivate` y recibe 403 antes de llegar al servicio. Si algún día lo
    tuviera, `durable` fallaría de forma visible en lugar de anidar.
- **Pruebas:** en `TestCase` funciona, porque Django exime sus propios bloques. Dentro de un
  `transaction.atomic()` explícito falla, y una prueba lo verifica. Las pruebas de commit real
  usan `TransactionTestCase`.
- **A futuro:** una reactivación masiva, un comando o una acción de admin tendrán que llamar al
  servicio fuera de cualquier transacción.

| Falla | Resultado |
|---|---|
| Al generar la contraseña, calcular el hash, revocar tokens o incrementar la versión | Rollback completo: la cuenta sigue inactiva, la contraseña anterior intacta, la versión sin cambios, sin contraseña temporal en la respuesta y sin evento. |
| Al confirmar la transacción | La excepción sale del bloque antes de que el servicio devuelva: 500 sin contraseña temporal y estado sin cambios. |
| En el callback del evento, después del commit | Se registra el error; la respuesta 201 sale normalmente. |
| La respuesta se pierde después del commit (incluido un fallo al serializar `member`) | La cuenta quedó activa y el ADMIN no vio la contraseña. Al reintentar recibe 409 `already_active`; la interfaz indica «Ya está activo. Si no recibiste la contraseña temporal, usa Restablecer contraseña» y recarga las listas. Nunca se emite una segunda contraseña en silencio. |

### II.3.1 Invariante del último ADMIN

**Invariante:** una organización nunca puede quedar sin al menos un ADMIN activo como
consecuencia de una operación de gestión de personal.

**ADMIN activo:** un `User` de la clínica con `role='ADMIN'`, `is_active=True` y que no es cuenta
de servicio. Se usa `User.role` porque, si faltara el `UserRole`, los permisos caen al rol
estático y el ADMIN conserva sus capacidades.

**Inventario de operaciones que pueden cambiar el conjunto de ADMIN activos:**

| Operación | Efecto | Evidencia | Protección |
|---|---|---|---|
| `deactivate_staff` | **Disminuye** | `backend/apps/users/services.py:412`, el **único** sitio productivo que escribe `is_active=False` en `User` | Bloqueo ordenado (II.3) |
| Reactivar un ADMIN | Aumenta | Nuevo (F3) | No puede romper el invariante |
| Alta con rol ADMIN | Aumenta | `CreateEmployeeSerializer` | No puede romper el invariante |
| Provisión de una organización | Crea el primer ADMIN | `backend/apps/platform/services/provision_organization.py:118` | No aplica |
| Cambio de rol | **No existe**: ningún código cambia `User.role` después del alta | Búsqueda en el repositorio | No aplica hoy; el gate obliga a protegerlo si aparece |
| `UserRole` | Solo se crea (`get_or_create` / `update_or_create`); nunca se borra salvo en la purga completa de la demo, que borra la organización entera | Búsqueda en el repositorio | No aplica |
| Permisos del rol ADMIN | `seed_permissions` los fija siempre a la lista del ADMIN, que incluye `staff.*` | `seed_permissions.py:154` | No aplica |
| Desactivar la organización (plataforma) | Toda la clínica queda inactiva | ADR orden 2 | Fuera del invariante: no hay clínica operando |
| Admin de Django o shell | Pueden cambiar `is_active` y `role` sin protección | `backend/apps/users/admin.py` | **Excluido a propósito**: vía de emergencia de operadores. Se documenta |
| Borrar un usuario | No hay API y el admin no lo permite | `backend/apps/users/admin.py:22` | No aplica |

**Conclusión:** dentro del producto, `deactivate_staff` es la única vía que disminuye el número
de ADMIN activos, así que la protección es real. Para que lo siga siendo:

1. **Gate estático de escritores** (`backend/apps/users/tests/test_staff_lifecycle_writers_gate.py`;
   precedentes: el inventario de `patients` y el gate de `_promote`): enumera los sitios
   productivos que escriben `is_active=False`, `role` o `is_service_account` sobre `User`, cada
   uno clasificado. Un sitio nuevo sin clasificar hace fallar la prueba. El día que exista el
   cambio de rol, queda obligado a usar el mismo protocolo de bloqueo.
2. **Pruebas concurrentes con aumentos:** desactivar a un ADMIN mientras se crea o se reactiva
   otro. Con cualquier orden de ejecución queda al menos uno. El sistema puede responder 409 de
   más si el aumento aún no se confirmó: es la dirección segura.
3. **Independiente del frontend y del permiso:** la regla vive en el servicio. Lo prueba un rol
   con `staff.destroy` concedido directamente en la base de datos.
4. **Documentado** en `docs/system-reference.md`, con su alcance y la vía de recuperación: si el
   único ADMIN olvida su contraseña, el restablecimiento de plataforma (ADR p45).

### II.4 Vistas, rutas y configuración

- **F0:**
  - `backend/config/urls.py`: la comprobación previa de `PublicTokenRefreshView` compara la
    versión antes de rotar.
  - `backend/apps/platform/views.py`: el queryset del restablecimiento de plataforma excluye las
    cuentas de servicio (D13).
  - `backend/config/settings.py`: el comentario de `SIMPLE_JWT` sobre el access token remite a
    p65.
- `StaffListView` lee `archived` (D6); el modo inactivos exige `staff.reactivate` mediante
  `user_has_permission`.
- `StaffReactivateView` replica `StaffResetPasswordView`: `make_permission("staff.reactivate")`,
  `NoStoreResponseMixin`, `X-Request-ID` y búsqueda con `resolve_public_id` dentro de la
  clínica, excluyendo cuentas de servicio. No abre transacciones propias y arma la respuesta
  solo con el resultado del servicio.
- `StaffResetPasswordView` agrega `NoStoreResponseMixin` (D11).
- `backend/config/urls.py`: ruta nueva `api/staff/<str:pk>/reactivate/`.
- `backend/config/settings.py`: nueva tasa de throttle `staff_reactivate`, 10 por hora (D7),
  independiente de `staff_password_reset` (5 por hora).

**Demo (D5):**

- **Cuenta semilla** = `organization.is_demo` **y** `username` en la lista de usernames semilla.
  Los dos datos se leen del servidor.
- La lista se mueve a `backend/apps/core/demo_reset.py` (constantes compartidas de la demo, sin
  imports de Django). `backend/apps/core/management/commands/_demo_data.py` la reutiliza, para
  que exista una sola lista.
- **Por qué el username identifica de forma segura:**
  - Es único global (`AbstractUser`) y ninguna API lo modifica: el PATCH lo rechaza y no hay
    otro endpoint que lo toque.
  - Es la clave que el propio seed usa para identificar sus cuentas (`_ensure_users`).
  - Los usernames semilla contienen `@` (por ejemplo, `demo-vet@saaslyvet.com`) y
    `USERNAME_REGEX` no admite `@`: ningún visitante puede crear uno igual por la API.
  - Único hueco: un operador puede renombrar una cuenta desde el admin de Django. Se documenta
    como acción de operador.
- **La autorización no depende del frontend.** `demo_protected` solo sirve para ocultar
  acciones; la regla la aplica `_assert_not_demo_seed_account` dentro de los servicios.

### II.5 Permisos

- **D1 aprobada:** código nuevo `staff.reactivate`. Se agrega en
  `backend/apps/core/permissions_codes.py` al catálogo, a `SENSITIVE_CODES` y a la lista literal
  del ADMIN (ADR p63).
- `test_admin_receives_the_approved_matrix` falla con el código nuevo hasta concederlo al
  ADMIN, por diseño.
- `seed_permissions` lo propaga en el despliegue, antes de que la aplicación arranque.
- VET, ASSISTANT y AGENT no lo reciben.
- La regla del último ADMIN se aplica aunque se conceda `staff.destroy` a otro rol en la base
  de datos.
- F0 no agrega ni cambia permisos.

### II.6 Sesiones, refresh tokens y credenciales temporales

| Operación | Refresh tokens anteriores | Access tokens anteriores | Otros efectos |
|---|---|---|---|
| Editar nombre, especialidad o cédula | Sin cambio | Sin cambio | — |
| Editar correo | Sin cambio (D2) | Sin cambio | El correo anterior deja de servir para iniciar sesión de inmediato; el username sigue funcionando. El JWT no contiene el correo. |
| Desactivar | Revocados | Rechazados: cuenta inactiva y versión nueva | — |
| Reactivar | Revocados, incluidos los rotados y los que dejó vivos una desactivación hecha fuera del servicio | Rechazados por versión, también después de que la persona cambie la contraseña | Contraseña temporal de 24 h, cambio obligatorio (`MustChangePasswordGate`) y respuesta con `no-store`. |
| Restablecer (clínica o plataforma) | Revocados | Rechazados por versión | Igual que hoy en lo demás. |
| Cambiar la contraseña propia | Revocados, salvo el nuevo | Rechazados por versión, salvo el par nuevo | Se cierran las sesiones de otros navegadores y dispositivos y de pestañas no recordadas; las pestañas recordadas del mismo navegador siguen (I.3, hallazgo 18). |
| Cerrar sesión | Revoca el recibido | Siguen válidos hasta vencer (15 min), como hoy | Por dispositivo (I.3, hallazgo 15). |
| Cambio desde el admin de Django o la shell | Sin cambio | Sin cambio | Vía de operador, fuera de alcance (I.3, hallazgo 20). |
| Contraseña temporal vencida | — | — | El login responde 403 `temp_password_expired` (ya existe). El ADMIN vuelve a restablecer; puede hacerlo porque la cuenta está activa. |

**La rev. 2 aceptaba un riesgo residual mal evaluado** (I.3, hallazgo 11): lo consideraba
inofensivo porque el gate de cambio obligatorio bloqueaba el token viejo, pero el gate se
levanta en cuanto la persona cambia la contraseña. F0 lo elimina: el token anterior se rechaza
desde la primera petición posterior a la operación, antes y después del cambio de contraseña.

### II.7 Migraciones

**Una, en F0:** `backend/apps/users/migrations/0013_user_session_version.py`.

- **Cambio de esquema:** agrega la columna `session_version` (entero no negativo, `NOT NULL`,
  default de base de datos 0) a `users_user`. Nada más.
- **Compatibilidad con los datos existentes:**
  - Todas las filas quedan en 0 sin backfill. En PostgreSQL agregar una columna con default
    constante no reescribe la tabla.
  - Los tokens vigentes no tienen claim y valen 0: coinciden y nadie pierde la sesión.
  - `db_default` cubre a una instancia con el código anterior que cree un usuario después de
    migrar.
  - Revertir el código no exige revertir la migración.
- Los permisos los siembra `seed_permissions`, no una migración.
- `demo_protected` es un campo calculado del serializer.
- Sin la migración de fecha y autor de la desactivación (D3).

### II.8 Frontend (alcance reducido)

Todo el trabajo se queda en la página existente. No se crea `features/staff/`, no se fusionan
los formularios de alta y edición, y las validaciones siguen en la página.

| Archivo | Cambio |
|---|---|
| `frontend/src/api/client.js` (F0, D14) | Reintento único con las condiciones de II.0. |
| `frontend/src/pages/staff.jsx` | El modal de edición existente agrega nombre, apellido y correo. El modal de contraseña temporal pasa a ser un componente local, reutilizado por restablecer y reactivar. Segmento Activos/Inactivos. Validaciones de nombre con los mismos rangos del backend. |
| `frontend/src/pages/staff.module.css` (nuevo) | Único archivo nuevo de la página, siguiendo la convención de `pages/inventory.module.css`. Reemplaza los estilos inline con tokens (`--c-warning-*`, `--font-mono`, `--c-text-2/3`). Reutiliza clases globales: `form-hint`, `input-error`, `badge-*`, `btn-*`, `segmented-control`. |
| `frontend/src/api/staff.js` | `reactivateStaff(publicId)` con el mismo manejo de `X-Request-ID` que el restablecimiento; `getStaff({archived: true})`; el parámetro de `deactivateStaff` se renombra a `publicId`. |
| `frontend/src/components/icons.jsx` | Agrega `UserX` y `UserCheck` de `lucide-react` (ya es dependencia). |
| `frontend/src/components/Sidebar.jsx` | La entrada Equipo se muestra con `canAny([...permisos de gestión])` en lugar del rol. Configuración queda fuera de alcance. |

**Permisos en la interfaz:**

| Elemento | Condición |
|---|---|
| «+ Agregar miembro» | `can("staff.create")` |
| Editar | `can("staff.update")` y la fila no es `demo_protected` |
| Restablecer contraseña | `can("staff.reset_password")`, no es la fila propia y no es `demo_protected` |
| Desactivar acceso | `can("staff.destroy")`, no es la fila propia y no es `demo_protected` |
| Segmento Inactivos y Reactivar | `can("staff.reactivate")` |
| Columna de acciones y su esqueleto | Al menos una de las acciones anteriores disponible |

La fila propia se identifica con `member.id === user.id` (`/me` devuelve `id`; se usa solo
para comparar, nunca en URLs) y muestra la etiqueta «Tú». Se elimina el código muerto de
`ADMIN_SAAS`.

**Flujos:**

- **Alta:**
  - Al abrir el modal se limpian los errores (`setFormErrors({})`).
  - Las validaciones del cliente se muestran como errores de campo, igual que las del servidor.
  - En el `catch`, `handleFormError`. Se evita `toast.promise` con manejo de error para no
    duplicar toasts: estado de guardado y `toast.success` al terminar.
  - Textos: placeholder «Mínimo 8 caracteres» y ayuda «Al menos 8 caracteres, una mayúscula y
    un número. Deberá cambiarla en su primer acceso.» No se menciona vencimiento: la contraseña
    del alta no caduca.
  - En la demo (`user.is_demo`), el campo de correo muestra la ayuda de dominio de ejemplo.
- **Edición:**
  - Envía solo los campos modificados; sin cambios, Guardar queda deshabilitado.
  - Si cambia el correo, aparece el aviso: «Es su acceso al sistema. Desde que guardes entrará
    con el correo nuevo; avísale.»
  - Si es la fila propia, llama a `refreshUser()` para que el sidebar muestre el nombre nuevo.
- **Restablecer contraseña:**
  - El modal calcula las horas a partir de `expires_in_seconds`, en lugar de mostrarlas fijas.
  - Errores con `apiError`, en lugar de mapear códigos de estado a mano.
  - Texto de entrega: «Entrégala en persona o por un canal privado.»
- **Desactivar:**
  - Botón «Desactivar» con icono `UserX` y `aria-label="Desactivar acceso de {nombre}"`.
  - Confirmación con `useConfirm` y `dangerMode`:
    - Título: «Desactivar acceso de {nombre}».
    - Cuerpo: «Dejará de poder entrar y se cerrarán sus sesiones. Sus citas, consultas y
      registros se conservan. Revisa en Citas si tiene citas próximas asignadas. Podrás
      reactivarlo desde Inactivos.»
    - Botón: «Desactivar acceso».
  - Errores con `apiError`, incluidos `last_active_admin` y `actor_inactive`.
- **Inactivos y reactivar:**
  - `SegmentedControl` «Activos / Inactivos». Con permiso, las dos listas se cargan en
    paralelo.
  - Misma tabla; en inactivos la única acción es «Reactivar» con icono `UserCheck`.
  - Confirmación: «Reactivar acceso de {nombre}. Conservará su rol ({rol}) y su historial. Se
    generará una contraseña temporal válida por 24 h que deberá cambiar al entrar.»
  - Si es un VET sin cédula, la confirmación agrega: «No tiene cédula profesional registrada: no
    podrá firmar consultas ni recetas hasta que la captures.» (D9).
  - Después se abre el modal de contraseña temporal y se recargan ambas listas.
  - **409 `already_active`** (por ejemplo, tras una respuesta perdida): mensaje «Ya está activo.
    Si no recibiste la contraseña temporal, usa Restablecer contraseña» y recarga de ambas
    listas.
  - Sin inactivos: `EmptyState`.
- **Acciones de fila (D8):** botones con icono y texto corto, sin componente de menú nuevo.

### II.9 Casos límite

| Caso | Comportamiento |
|---|---|
| Login → desactivar → reactivar dentro de 15 min → cambio de la temporal | El access token del primer login responde 401 `session_revoked` en todo momento (F0). |
| Restablecer por compromiso y luego cambiar la contraseña | El token robado deja de servir desde el restablecimiento, no 15 min después (F0). |
| Otro navegador o dispositivo cuando la persona cambia su contraseña | Su siguiente petición recibe 401 y vuelve a `/login`. |
| Otra pestaña del mismo navegador con «Recordarme» | Sigue funcionando con el token nuevo. |
| Petición en vuelo mientras la persona cambia su propia contraseña | Se reintenta una vez con el token nuevo (D14). |
| Varias peticiones en vuelo con el token anterior | Cada una se reintenta una vez; si el token vigente también es inválido, termina en el cierre de sesión de hoy. |
| Login o refresh a la vez que un incremento | Emiten con la versión anterior; esos tokens se rechazan en cuanto se confirma el incremento. |
| Tokens vigentes al desplegar F0 | Siguen funcionando: sin claim valen 0. |
| Restablecimiento de plataforma sobre la cuenta del agente | 404; su versión no cambia (D13). |
| El agente llama a cambiar la contraseña | 400: su contraseña es inutilizable; la versión no cambia. |
| El admin de Django guarda un usuario mientras este cambia su contraseña | La versión no baja (II.0, monotonía). |
| Cambio de contraseña desde el admin de Django | No invalida sesiones (riesgo abierto, Parte III §6). |
| Desactivar y luego reactivar una organización | Fuera de F0: sus tokens vuelven a servir mientras no venzan, como hoy. Se documenta en p65. |
| Dos ADMIN se desactivan entre sí al mismo tiempo | Solo una operación gana; la otra recibe 403 `actor_inactive`. Siempre queda al menos un ADMIN activo. |
| Tres ADMIN se desactivan en cruz | Siempre queda al menos uno activo. |
| Desactivar a un ADMIN mientras se crea o se reactiva otro | Siempre queda al menos uno activo; un 409 de más es aceptable. |
| El actor es desactivado mientras ejecuta su operación | Se detecta con el bloqueo tomado y la operación se rechaza. |
| Desactivar al último ADMIN activo | 409 `last_active_admin`, aunque el actor tenga `staff.destroy` concedido en la base de datos. |
| Dos ADMIN reactivan a la vez | Solo uno tiene éxito; el otro recibe 409 `already_active`. Nunca se emiten dos contraseñas temporales. |
| La respuesta de la reactivación se pierde | El reintento recibe 409 `already_active` y la interfaz indica usar Restablecer contraseña. |
| Falla el callback del evento de reactivación | Se registra; la respuesta 201 sale normalmente. |
| `reactivate_staff` llamado dentro de una transacción | `RuntimeError` antes de escribir nada (`durable=True`). |
| Reactivar y desactivar a la vez | Ambos servicios bloquean las mismas filas en el mismo orden; las operaciones se ejecutan una después de otra. |
| Reactivar a varios pasantes al inicio de semestre | Límite propio de 10 por hora (D7), sin consumir el cupo de restablecimientos. |
| Correo ya usado por alguien de otra clínica o por un inactivo | 400 genérico en el campo, sin revelar información. |
| Dos ADMIN guardan el mismo correo a la vez | La restricción de base de datos resuelve; quien pierde recibe 400 en el campo, nunca 500. |
| Mismo correo propio con distintas mayúsculas | 200 sin guardar ni registrar evento. |
| Cambiar el correo propio | Permitido. La sesión continúa; el siguiente login usa el correo nuevo. |
| Cambiar el correo de alguien que nunca ha entrado | El ADMIN le comunica el correo nuevo; el username sigue funcionando. |
| Nombre pegado en Unicode NFD o con apóstrofo de iOS (’) | Se normaliza a NFC y se acepta. |
| Editar a un VET antiguo sin cédula | Cualquier PATCH exige la cédula (regla existente). El modal incluye el campo y el error aparece en él. |
| Editar a un inactivo | 404: primero debe reactivarse. |
| Reactivar a un VET | Vuelve a aparecer en la agenda y el agente vuelve a ofrecer sus horarios (`_scheduling_vets`). Comportamiento esperado. |
| Reactivar a un VET sin cédula | Se permite y la interfaz avisa que no podrá firmar (D9). |
| Reactivar a quien era `default_veterinarian` del agente | Vuelve a ser el veterinario fijo del agente sin aviso. Se documenta; no se cambia en este alcance. |
| Reactivar a quien dejó una caja abierta antes de la baja | La retoma tal como estaba. Corresponde a Caja (cierre administrativo); se documenta. |
| Reactivar a un ADMIN | Se permite: restaura el mismo nivel, no hay escalada. |
| Reactivar una cuenta de servicio inactiva | 404: el apagado de emergencia del agente no se puede saltar por la API de Equipo. |
| Organización desactivada | El ADMIN no puede autenticarse y, además, el servicio lo rechaza. |
| Cambiar el nombre | Las consultas y recetas cerradas conservan el snapshot. Las vistas en vivo (citas, auditoría, caja, bandeja) muestran el nombre corregido. La identidad (el PK) no cambia. |
| Pestaña abierta desde antes del despliegue | No muestra «Inactivos» hasta recargar, porque los permisos llegan con `/me`. No requiere acción. |

### II.10 Seguridad y multitenencia

- **Sesiones (F0):** cualquier cambio de credenciales o de acceso hecho por la API invalida de
  inmediato los tokens anteriores, con una comparación sin consultas adicionales. La versión solo
  crece y solo la escribe su función.
- **Aislamiento:** todas las consultas nuevas (lista de inactivos, reactivar, editar) se
  limitan a la organización del usuario y el servicio lo vuelve a comprobar. Las pruebas usan
  dos clínicas.
- **Credenciales:** respuestas con contraseña temporal con `no-store` (reactivar y restablecer,
  D11). La contraseña nunca aparece en logs ni sale de una transacción revertida.
- **Cuentas de servicio:** ninguna vía de Equipo ni de plataforma las restablece, desactiva,
  reactiva ni incrementa su versión; la protección está en la vista y en el servicio (D13).
- **Existencia de correos:** la edición devuelve el mismo mensaje genérico que el alta; no
  amplía lo que ya expone el alta (ADR p48 T-2).
- **Condición para el futuro:** si algún día se agrega recuperación de contraseña por correo,
  que el ADMIN pueda cambiar el correo de otra persona se convierte en una vía de robo de
  cuentas. Debe revisarse antes. Se deja escrito en el addendum de p48.
- **Demo:** cuentas semilla protegidas en el servicio y correos solo de dominios reservados
  (D5, II.4).
- **Datos de ex empleados:** la lista de inactivos solo la ve quien tiene `staff.reactivate`.

### II.11 Documentación por actualizar

- **F0:**
  - ADR p65 nuevo y addendum a p20 (II.0).
  - `docs/system-reference.md`: invariante de la versión de sesión y fila de error
    `session_revoked`.
  - `docs/modules/logs.md`: evento `AUTH_SESSION_REVOKED`.
  - `docs/modules/frontend.md`: reintento del interceptor (D14) y qué sesiones se cierran al
    cambiar la contraseña.
- **F7:**
  - `docs/modules/organizations.md`, sección «Cómo el ADMIN de una clínica gestiona su equipo»:
    campos del PATCH, tabla de ejemplos de nombres, `?archived=true`, reactivación (con la
    restricción de `durable=True`), protección del último ADMIN, nuevas respuestas de conflicto
    y reglas de la demo.
  - `docs/system-module-operations.md` §1: acciones «Editar integrante», «Desactivar» (con la
    regla nueva) y «Reactivar».
  - `docs/system-reference.md`: invariante del último ADMIN con su inventario y alcance, y orden
    de bloqueo de `User` en el ciclo de vida del personal.
  - `docs/modules/logs.md`: evento `STAFF_REACTIVATED`.
  - Addendums de ADR (D10):
    - p21: la reactivación forma parte del ciclo de credenciales; `no-store` en respuestas con
      contraseña temporal.
    - p48: el ADMIN puede editar el correo, se mantiene la unicidad, y la condición sobre
      recuperación por correo.
    - p63: nota sobre `staff.reactivate`.
  - `docs/modules/frontend.md`: en la tabla de rutas, «/staff — Solo ADMIN» pasa a «gestión por
    capacidad».

---

## Parte III. Entregable

### 1. Resumen de la solución

- **Versión de sesión (F0):** cada usuario tiene una versión que viaja en sus tokens. Desactivar,
  reactivar, restablecer (de clínica o de plataforma) y cambiar la contraseña la incrementan, y
  la autenticación y el refresh rechazan cualquier token con otra versión. Cierra el hueco de la
  reactivación y el que ya existía en restablecer y cambiar la contraseña. Sin consultas
  adicionales, sin cerrar sesiones al desplegar, con la versión protegida contra retrocesos y
  con las cuentas de servicio fuera de su alcance.
- **Edición (A1):** el PATCH existente acepta también nombre, apellido y correo, con los mismos
  validadores del alta. Los nombres se guardan tal como se escriben. La carrera por el correo se
  resuelve de forma segura. Los snapshots clínicos no se modifican.
- **Reactivación (A2):** un único endpoint nuevo que reactiva la misma cuenta, emite una
  contraseña temporal, obliga a cambiarla, invalida todas las sesiones anteriores y responde con
  `no-store`. Es atómica: nunca devuelve una contraseña que no se confirmó.
- **Lista:** reutiliza el endpoint actual con `?archived=true`, siguiendo la convención de
  Mascotas y Clientes.
- **Desactivación:** bloqueo concurrente que garantiza al menos un ADMIN activo, verificación
  del actor con el bloqueo tomado y un gate estático sobre las demás vías.
- **Demo:** cuentas semilla protegidas en el servicio y correos de dominios reservados, sin
  bloquear el alta.
- **Frontend:** permisos con `can()`, acciones ocultas en la fila propia y en las cuentas
  protegidas, `handleFormError`, textos de contraseña correctos, icono y confirmación de
  desactivación nuevos, estilos en un CSS module con tokens, y un reintento único en el
  interceptor. Todo dentro de la página existente y `client.js`.
- **Una migración aditiva** (F0).

### 2. Fases en el orden recomendado

| Fase | Contenido | ¿Cambia comportamiento? |
|---|---|---|
| F0 | Versión de sesión: ADR p65, migración, monotonía, claim, validación en autenticación y refresh, incrementos en las cuatro operaciones existentes, gates de versión y de emisión, D13 y D14. | Sí: cambiar la contraseña cierra las sesiones de otros navegadores y dispositivos; restablecer o desactivar expulsa en la siguiente petición |
| F1 | Backend base: extraer `_revoke_all_sessions`, `_issue_temporary_password` y `_assert_manageable_target`; bloqueo concurrente y regla del último ADMIN en la desactivación; gate estático de escritores. | Sí, en la desactivación (409 y 403 nuevos) |
| F2 | Backend A1: serializer de edición, validadores comunes (D4) y manejo de `IntegrityError`. | Sí |
| F3 | Backend A2 y endurecimiento: `?archived=true`, servicio y vista de reactivación con sus reglas de atomicidad y gate de llamador único, ruta, permiso, throttle (D7), `no-store` (D11) y demo (D5). | Sí |
| F4 | Correcciones de frontend sin funcionalidad nueva: `can()`, fila propia, iconos y textos, confirmación, `handleFormError` en el alta, CSS module, modal temporal como componente local, `expires_in_seconds`. | Solo UX |
| F5 | Frontend A1: campos de identidad en el modal de edición, aviso de cambio de correo y `refreshUser`. | Sí |
| F6 | Frontend A2: segmento, tabla de inactivos, flujo de reactivación, aviso de VET sin cédula, manejo de `already_active` y `demo_protected`. | Sí |
| F7 | Documentación y addendums de ADR restantes. | No |

F0 va primero: F1 y F3 usan `bump_session_version`. F4 no depende del backend y puede
ejecutarse en paralelo.

### 3. Archivos afectados por fase

- **F0:**
  - Nuevo: `docs/decisions/2026-11-19-p65-version-de-sesion.md`
  - `docs/decisions/2026-05-22-p20-credential-lifecycle-self-change.md` (addendum)
  - `backend/apps/users/models.py` (campo y `save()`)
  - Nuevo: `backend/apps/users/migrations/0013_user_session_version.py`
  - `backend/apps/core/authentication.py` (nombre del claim, estampar, leer y comparar)
  - `backend/apps/users/serializers.py` (`get_token` del login)
  - `backend/apps/users/services.py` (`bump_session_version` y sus llamadas)
  - `backend/apps/platform/services/platform_reset_password.py` (incremento y 404 a cuentas de
    servicio)
  - `backend/apps/platform/views.py` (queryset sin cuentas de servicio)
  - `backend/config/urls.py` (comprobación previa del refresh)
  - `backend/config/settings.py` (comentario de `SIMPLE_JWT`)
  - Nuevos: `backend/apps/users/tests/test_session_version.py` y
    `backend/apps/users/tests/test_session_version_gate.py`
  - Regresión: `backend/apps/users/tests/test_change_password.py`, `test_reset_password.py`,
    `test_deactivate_revokes_session.py`, `test_token_logout.py`, `test_login_by_email.py`,
    `backend/apps/core/tests/test_auth_no_store.py`,
    `backend/apps/platform/tests/test_platform_reset_password.py`,
    `backend/apps/platform/tests/test_view_integration.py`, `backend/apps/legal/tests/test_legal.py`
    y las suites del agente que emiten tokens (`test_b9a_e2e.py`, `test_operation_execution.py`).
    Verificado: ninguna afirma la ventana residual ni el código `token_not_valid`. Si alguna
    emitiera un token con `RefreshToken.for_user` **después** de un incremento, solo cambia ese
    fixture para estampar la versión; no se quita ni se invierte ninguna aserción.
  - `frontend/src/api/client.js` y nuevo `frontend/src/api/client.test.js` (D14)
  - `docs/system-reference.md`, `docs/modules/logs.md`, `docs/modules/frontend.md`
- **F1:**
  - `backend/apps/users/services.py`
  - Regresión sin cambios: `backend/apps/users/tests/test_reset_password.py`,
    `backend/apps/users/tests/test_deactivate_revokes_session.py`,
    `backend/apps/users/tests/test_session_version.py`
  - Nuevos: `backend/apps/users/tests/test_staff_last_admin.py` (secuencial y concurrente) y
    `backend/apps/users/tests/test_staff_lifecycle_writers_gate.py` (gate estático)
- **F2:**
  - `backend/apps/users/serializers.py`
  - `backend/apps/users/services.py`
  - `backend/apps/users/tests/test_staff_license.py` (ajuste del mensaje)
  - Nuevo: `backend/apps/users/tests/test_staff_profile_edit.py` (incluye la tabla de nombres)
- **F3:**
  - `backend/apps/users/views.py`
  - `backend/apps/users/services.py`
  - `backend/apps/users/serializers.py` (`demo_protected` y dominios reservados)
  - `backend/config/urls.py`
  - `backend/config/settings.py` (throttle `staff_reactivate`)
  - `backend/apps/core/permissions_codes.py`
  - `backend/apps/core/tests/test_admin_explicit_grants.py` (se ajusta por diseño con el código
    nuevo)
  - `backend/apps/core/demo_reset.py`
  - `backend/apps/core/management/commands/_demo_data.py`
  - Nuevos: `backend/apps/users/tests/test_staff_reactivate.py` (incluye el gate de llamador
    único), `backend/apps/users/tests/test_staff_list_archived.py`
  - `backend/apps/users/tests/test_demo_restrictions.py`
- **F4:**
  - `frontend/src/pages/staff.jsx`
  - Nuevo: `frontend/src/pages/staff.module.css`
  - `frontend/src/components/icons.jsx`
  - `frontend/src/components/Sidebar.jsx`
  - `frontend/src/pages/staff.test.jsx`
- **F5:**
  - `frontend/src/pages/staff.jsx`
  - `frontend/src/api/staff.js`
  - `frontend/src/pages/staff.test.jsx` (incluye la tabla de nombres)
- **F6:**
  - `frontend/src/pages/staff.jsx`
  - `frontend/src/api/staff.js`
  - `frontend/src/pages/staff.test.jsx`
- **F7:**
  - `docs/modules/organizations.md`
  - `docs/system-module-operations.md`
  - `docs/system-reference.md`
  - `docs/modules/logs.md`
  - `docs/modules/frontend.md`
  - `docs/decisions/2026-05-22-p21-admin-password-reset.md`
  - `docs/decisions/2026-06-28-p48-login-email-identidad-global.md`
  - `docs/decisions/2026-11-04-p63-admin-explicit-grants.md`

### 4. Estrategia de pruebas y criterios de aceptación

Ninguna prueba existente se elimina ni cambia sus aserciones.

**F0 — versión de sesión** (`backend/apps/users/tests/test_session_version.py`):

- **Emisión:**
  - El login por username y por correo devuelve refresh y access con `sv` igual a la versión
    actual.
  - La rotación conserva `sv` en el refresh y el access nuevos.
  - `change_password` devuelve un par con la versión nueva.
- **Compatibilidad:** un token sin `sv` funciona con versión 0 y se rechaza con versión 1 o
  mayor. Un `sv` no entero o negativo se rechaza.
- **Cada vía de incremento** (desactivar, restablecer de clínica, restablecer de plataforma,
  cambiar la contraseña):
  - El access emitido antes responde 401 `session_revoked` en la siguiente petición.
  - El refresh emitido antes responde 401 en `/api/token/refresh/` sin crear un
    `OutstandingToken`.
- **Escenario bloqueante con las operaciones actuales:** login (token T) → restablecer → login
  con la temporal → cambiar la contraseña → T responde 401. El mismo escenario con desactivar y
  reactivar se prueba en F3.
- **`change_password`:** el par devuelto funciona; el access usado en la propia petición y el
  de otra sesión responden 401.
- **Token viejo en la cabecera del login:** un login con credenciales correctas y un
  `Authorization` de versión vieja responde 200 (fija el hallazgo 17).
- **Carreras de emisión:** un token emitido con la versión anterior a un incremento se rechaza
  después del incremento.
- **Concurrencia** (`TransactionTestCase`, `threading.Barrier`): dos incrementos simultáneos
  dejan la versión en inicial + 2.
- **Atomicidad:** un error forzado después del incremento (por ejemplo, en la revocación de
  `OutstandingToken`) deja la versión y la contraseña como estaban, y los tokens anteriores
  siguen funcionando.
- **Monotonía:**
  - Un `save()` completo sobre una instancia leída antes de un incremento no baja la versión y sí
    guarda los demás campos.
  - Un `save()` completo de una instancia con campos diferidos (`.only(...)`) guarda solo los
    cargados, igual que hoy.
  - `save(update_fields=['session_version'])` lanza `ValueError`.
  - Guardar el formulario de usuario del admin de Django sobre una instancia vieja no baja la
    versión.
  - El receptor `assign_rbac_role_on_create` sigue creando el `UserRole` en el alta y no actúa
    en los guardados.
- **Códigos:** un usuario inactivo sigue recibiendo `user_inactive` y una organización inactiva
  `organization_inactive`.
- **Consultas:** una petición autenticada ejecuta el mismo número de consultas que antes
  (`assertNumQueries`).
- **Cuentas de servicio:**
  - El token de `mint_agent_token` sigue autenticando.
  - El restablecimiento de plataforma sobre una cuenta de servicio responde 404 desde la vista,
    y el servicio llamado directamente también lo rechaza; la versión no cambia (D13).
  - Una persona con `role='AGENT'` sin `is_service_account` se trata como persona.
  - El agente que llama a cambiar la contraseña recibe 400 y su versión no cambia.
  - `ensure_agent_users` no toca la versión.
  - `bump_session_version` rechaza una cuenta de servicio.
- **Cerrar sesión** con un refresh de versión vieja: mismo resultado que hoy.
- **Log:** `AUTH_SESSION_REVOKED` sin token ni datos personales.

**F0 — gates** (`backend/apps/users/tests/test_session_version_gate.py`):

- Versión: una escritura de `session_version` fuera de los sitios permitidos (atributo, argumento
  con nombre, cadena literal) hace fallar la prueba; las lecturas del atributo no. La prueba
  incluye casos sintéticos de cada forma para demostrar que el gate las detecta.
- Emisión: los sitios productivos que llaman a `for_user(` o `get_token(` son exactamente los
  tres clasificados.

**F0 — interceptor (D14)** (`frontend/src/api/client.test.js`; adaptador de axios simulado con
una función, sin dependencias nuevas):

- Una petición enviada con el token anterior recibe 401; se reintenta una vez con el token
  vigente y resuelve. El adaptador recibe dos llamadas; la segunda lleva el token nuevo y el
  mismo cuerpo, `X-Request-ID` y `X-Idempotency-Key`.
- Si el reintento también recibe 401: un solo cierre de sesión y dos llamadas en total.
- 401 con el token vigente: sin reintento, cierre de sesión como hoy.
- Login con 401: sin reintento y sin redirección (comportamiento actual).
- `token/refresh/` y `token/logout/`: sin reintento.
- Petición sin `Authorization`, sin token almacenado o con cierre de sesión en curso: sin
  reintento.
- **Concurrencia:**
  - Tres peticiones en vuelo con el token anterior y el token renovado: cada una se reintenta
    exactamente una vez (seis llamadas) y no hay cierre de sesión.
  - Tres peticiones en vuelo y el token vigente también inválido: cada una hace como máximo dos
    llamadas y todas terminan en el cierre de sesión.
- Errores que no son 401 se comportan igual que hoy (500 y 4xx).
- `noConsoleTokenLeak` pasa.

**Último ADMIN** (PostgreSQL, `TransactionTestCase`, hilos con `threading.Barrier`):

- Dos ADMIN se desactivan entre sí al mismo tiempo: exactamente una operación responde 204, la
  otra 403 `actor_inactive`, y queda al menos un ADMIN activo.
- Tres ADMIN se desactivan en cruz: siempre queda al menos uno activo.
- Desactivar a un ADMIN mientras se crea otro ADMIN, y mientras se reactiva otro: con cualquier
  orden queda al menos uno activo.
- Secuencial: un rol con `staff.destroy` concedido en la base de datos no puede desactivar al
  único ADMIN (409 `last_active_admin`).
- Gate estático: un escritor nuevo de `is_active=False`, `role` o `is_service_account` sobre
  `User` sin clasificar hace fallar la prueba.

**Edición:**

- El ADMIN cambia nombre, apellido y correo; el correo se guarda en minúsculas.
- **Nombres:** cada fila de la tabla de II.2 produce el resultado indicado, en el alta y en la
  edición.
- Correo ocupado en la misma clínica, en otra clínica o por un inactivo: 400 con el mismo
  mensaje genérico.
- Mismo correo con distintas mayúsculas sobre uno mismo: 200 sin guardar ni registrar evento.
- Carrera simulada entre la validación y el guardado: una `IntegrityError` de
  `user_email_ci_unique` se convierte en 400 en el campo; una `IntegrityError` de otra
  restricción se propaga.
- Enviar `role`, `username`, `password`, `is_active` o `session_version`: 400 y ningún cambio.
- Otra clínica, cuenta de servicio, `ADMIN_SAAS` o usuario inactivo: 404. VET o ASSISTANT: 403.
- **Integración con login:** entra con el correo nuevo, falla con el anterior y el username
  sigue funcionando.
- **Snapshots:** tras renombrar a un veterinario, una consulta cerrada conserva
  `vet_name_at_close` y su PDF muestra el nombre anterior; una consulta abierta muestra el
  nuevo.
- El log no contiene el valor del correo.

**Reactivación, sesiones y credenciales:**

- Responde 201 con `is_active=True`, `password_must_change=True` y `password_temp_issued_at`
  definido; `public_id`, PK y `UserRole` no cambian.
- La respuesta incluye `Cache-Control: no-store`; también la del restablecimiento (D11).
- **Escenario bloqueante exacto:** login (token T) → desactivar → reactivar dentro de los 15
  min → login con la temporal → cambiar la contraseña → T responde 401 `session_revoked` en cada
  paso posterior a la desactivación.
- Login, luego refresh (rotación), luego `is_active=False` aplicado directo en la base sin el
  servicio, luego reactivar: el refresh original y el rotado fallan, y el access de ese login
  responde 401.
- La contraseña anterior falla.
- La temporal permite entrar, `/me` devuelve `must_change_password=true` y, al cambiarla, la
  marca se limpia.
- Con la temporal vencida (más de 24 h), el login responde 403 `temp_password_expired`.
- **Atomicidad** (`TransactionTestCase`):
  - Con un error forzado en `_revoke_all_sessions`: `is_active=False`, la contraseña anterior
    sigue funcionando, ningún token revocado, versión sin cambios, 500 sin `temp_password` y sin
    evento `STAFF_REACTIVATED`.
  - El evento se emite solo después del commit (`captureOnCommitCallbacks`).
  - Un error forzado en el callback del evento no cambia la respuesta 201 ni el estado.
  - Llamar al servicio dentro de un `transaction.atomic()` explícito lanza `RuntimeError` y no
    escribe nada.
  - Gate: `reactivate_staff` tiene un solo llamador productivo, `StaffReactivateView`.
- Ningún log contiene la contraseña temporal.
- Usuario activo: 409. Otra clínica, cuenta de servicio (incluida una inactiva) o
  `ADMIN_SAAS`: 404. VET o ASSISTANT: 403. El throttle `staff_reactivate` se aplica.
- Las citas y consultas siguen apuntando al mismo usuario.

**Lista y permisos:**

- `GET /api/staff/` sin parámetros devuelve lo mismo que hoy (regresión del consumidor de
  Citas).
- `?archived=true` devuelve solo inactivos de la clínica, sin cuentas de servicio inactivas ni
  usuarios de otra clínica, y responde 403 sin `staff.reactivate`.
- `staff.reactivate` lo tiene solo el ADMIN (ni VET, ni ASSISTANT, ni AGENT).
  `test_admin_receives_the_approved_matrix` se actualiza.
- Al ejecutar `seed_permissions` sobre una clínica existente, su rol ADMIN recibe el permiso.

**Demo (D5):**

- Las tres cuentas semilla responden 403 `demo_seed_account` a editar, restablecer y
  desactivar llamando a la API directamente, sin pasar por la interfaz, y llegan con
  `demo_protected=true`.
- Cada username semilla falla `USERNAME_REGEX`: ninguno se puede crear por la API.
- Un usuario con un username semilla en una organización que no es demo no queda protegido.
- Un correo real en el alta o la edición de la demo: 400. Un correo `@example.com`: aceptado.
- Las cuentas creadas por un visitante se pueden editar, restablecer, desactivar y reactivar.
- La lista de usernames semilla de `demo_reset.py` coincide con la de `_demo_data.py`.

**Multitenant:** cada endpoint se prueba con un ADMIN de la clínica A sobre usuarios de la
clínica B (404) y con listados que mezclan clínicas (sin fugas).

**Frontend (Vitest + RTL):**

- La interfaz decide por `can()` y no por rol: un usuario con rol VET pero con permisos de
  Equipo ve las acciones; un ADMIN sin esos permisos no las ve.
- Solo con `staff.list`: no aparecen «Agregar» ni la columna de acciones.
- Fila propia: aparecen «Tú» y «Editar», pero no «Restablecer» ni «Desactivar». Fila
  `demo_protected`: sin acciones.
- No existe icono de basura; la confirmación recibe el título, texto y botón definidos.
- El formato sin sobre del alta (`{campo: [...]}`) y el sobre `validation_error` del PATCH se
  muestran como errores de campo; el modal permanece abierto.
- **Nombres:** la validación del cliente da, para cada fila de la tabla de II.2, el mismo
  resultado que el backend.
- La edición envía solo los campos modificados; aparece el aviso al cambiar el correo; editar
  la fila propia llama a `refreshUser`.
- El texto de contraseña indica 8 caracteres; ningún texto menciona 6.
- El modal temporal calcula las horas desde `expires_in_seconds`.
- Sin `staff.reactivate` no aparece el segmento Inactivos; reactivar hace el POST, muestra la
  temporal y recarga las listas.
- Reactivar a un VET sin cédula muestra la advertencia de firma (D9).
- Un 409 `already_active` muestra la indicación de restablecer y recarga las listas.
- `getStaff()` sin argumentos no envía parámetros (regresión de Citas).
- La regresión completa de Equipo pasa; `pnpm test`, `pnpm lint` y las pruebas
  `noConsoleTokenLeak` y `lintDisableReason` pasan.

**Cierre:** suites completas de `apps.users`, `apps.core`, `apps.platform` y `apps.legal`, y las
del agente que emiten tokens, en verde sobre PostgreSQL; CI en verde.

### 5. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un defecto en la comparación de versiones deja fuera a todos | Claim ausente = 0; pruebas de compatibilidad y de cada vía de emisión; revertir el código es seguro sin revertir la migración. |
| Una instancia vieja baja la versión y revive tokens | `save()` completo no escribe la versión; `update_fields` con la versión falla; gate estático sobre sus escritores. |
| Un sitio nuevo emite tokens sin versión | Gate de emisión con inventario clasificado. |
| El agente queda inutilizado por un restablecimiento de plataforma | 404 en vista y servicio, y `bump_session_version` rechaza las cuentas de servicio (D13). |
| La persona pierde la sesión justo después de cambiar su contraseña | Reintento único cuando el 401 vino de un token ya renovado (D14). |
| El reintento duplica una escritura | El 401 de autenticación ocurre antes de ejecutar la vista; pruebas con cuerpo y claves de idempotencia. |
| El reintento entra en bucle o interfiere con login, refresh o cierre de sesión | Máximo dos intentos, sin llamadas al refresh, exclusión por URL; pruebas concurrentes. |
| Instancias antiguas durante el relevo del despliegue | Ventana de minutos equivalente a la actual; documentado en p65. |
| La clínica se queda sin ADMIN por desactivaciones concurrentes | Bloqueo ordenado de los ADMIN activos, actor y objetivo; verificación con el bloqueo tomado; pruebas concurrentes. |
| Un escritor nuevo de `is_active`, `role` o `is_service_account` salta las protecciones | Gate estático con inventario clasificado. |
| El refactor de servicios de seguridad introduce regresiones | F0 y F1 aislados; las suites actuales pasan sin quitar ni invertir aserciones. |
| Una sesión antigua revive al reactivar | Versión de sesión, más la revocación de todos los refresh tokens (incluidos los rotados), probadas con un token que quedó vivo. |
| La contraseña anterior vuelve a servir | Siempre se sobrescribe con la temporal. |
| Se entrega una contraseña temporal que no se confirmó | Transacción `durable`, respuesta armada después del commit, gate de llamador único y pruebas con fallas forzadas. |
| El evento convierte en 500 una reactivación confirmada | `on_commit(robust=True)` y prueba con el callback fallando. |
| La contraseña temporal queda en una caché intermedia | `no-store` en reactivar y en restablecer (D11). |
| Reactivación de un empleado despedido sin control | Permiso sensible propio, log `STAFF_REACTIVATED` y credencial temporal visible solo para el ADMIN. |
| El correo nuevo deja a la persona sin poder entrar | Aviso en la interfaz; el username sigue funcionando; el ADMIN puede corregirlo. |
| Capturar una `IntegrityError` ajena al correo | Comparar el nombre de la restricción y propagar las demás. |
| Bloqueos cruzados entre transacciones | Todas bloquean en una sola consulta ordenada por `pk`. |
| Romper Citas por el cambio en la lista | El comportamiento por defecto no cambia y tiene pruebas de regresión en backend y frontend. |
| Los visitantes de la demo rompen las cuentas compartidas o inutilizan correos reales | Cuentas semilla protegidas en el servicio y dominios reservados (D5). |
| Backend y frontend validan nombres distinto | Tabla de ejemplos compartida, copiada en ambas suites. |
| Nombres guardados en minúsculas porque así se capturaron | Consecuencia aceptada de D4 («sin alterar la escritura»); los datos existentes no cambian. |
| Cambiar el correo se vuelve una vía de robo de cuentas si se agrega recuperación por correo | Condición escrita en el addendum de p48. |
| Que la corrección se convierta en un refactor amplio del frontend | Todo dentro de la página existente más un CSS module y `client.js`; sin componentes nuevos. |

### 6. Riesgos que siguen abiertos

Ninguno bloquea la implementación. Todos son preexistentes o consecuencias aceptadas del
alcance, y quedan escritos en p65 o en la documentación de F7.

| # | Riesgo | Por qué sigue abierto | Mitigación actual |
|---|---|---|---|
| R1 | Cambiar la contraseña, desactivar o reactivar desde el admin de Django, `changepassword` o la shell no invalida sesiones ni revoca refresh tokens | Preexistente; es la vía de operadores y quedó fuera de alcance | La versión no puede bajar por esas vías. Los operadores deben usar la API o el restablecimiento de plataforma. |
| R2 | Desactivar y reactivar una organización completa: sus tokens vuelven a servir mientras no venzan, incluidos refresh tokens de hasta 7 días | Preexistente; fuera de alcance | Mientras está inactiva, login, refresh y autenticación la rechazan. |
| R3 | Cerrar sesión deja el access token válido hasta 15 min | Por diseño: cerrar sesión es por dispositivo | Es una salida voluntaria, no un compromiso de credenciales; ante sospecha se usa el cambio de contraseña o el restablecimiento. |
| R4 | Durante el relevo de instancias del despliegue, las instancias antiguas no comparan versiones | Inherente a un despliegue sin corte | Dura minutos y equivale a la ventana actual. |
| R5 | Si la respuesta de la reactivación se pierde (o falla la serialización de `member` después del commit), el ADMIN no ve la contraseña temporal | Una respuesta HTTP no puede garantizar su entrega | 409 `already_active` con la indicación de restablecer; nunca se emite una segunda contraseña en silencio. |
| R6 | Una escritura masiva con claves dinámicas (`update(**campos)`) que incluyera `session_version` no la detecta el gate | Límite de un análisis estático | Hoy no existe ninguna; el `save()` del modelo sí rechaza `session_version` en `update_fields`. |
| R7 | Un operador puede renombrar una cuenta semilla de la demo desde el admin de Django y quitarle la protección | Vía de operador | Documentado como acción de operador. |
| R8 | Una reactivación masiva, un comando o una acción de admin futura no podrán llamar a `reactivate_staff` dentro de una transacción | Consecuencia buscada de `durable=True` | Documentado en el docstring y en `docs/modules/organizations.md`; el gate de llamador único obliga a revisarlo. |
| R9 | Una persona con `role='AGENT'` creada desde el admin, sin `is_service_account`, se trata como persona y su versión sí se incrementa | El criterio estable es `is_service_account`, no el rol | Es el comportamiento correcto para una persona; una prueba lo fija. |

### 7. Decisiones

| # | Decisión | Resolución |
|---|---|---|
| D1 | Permiso para reactivar | **Aprobada:** código nuevo `staff.reactivate` (sensible, solo ADMIN). |
| D2 | ¿Revocar sesiones al cambiar el correo? | **Aprobada: no.** No es un cambio de credencial, el JWT no contiene el correo y no existe recuperación por correo. |
| D3 | Guardar fecha y autor de la desactivación (migración aditiva) | **Aprobada: no en esta iteración.** Los logs bastan y, con D12, la reactivación no depende de ella. |
| D4 | Nombres reales sin alterar su escritura | **Aprobada:** NFC + recorte de extremos; sin `.title()`; letras latinas por rangos explícitos, espacio, guion y apóstrofos ' y ’; `first_name` obligatorio también en el backend del alta; backend como autoridad y tabla de ejemplos compartida. |
| D5 | Demo | **Aprobada:** proteger solo las tres cuentas semilla (organización demo + username) y exigir dominios reservados en el correo. |
| D6 | Nombre del parámetro de inactivos | **Aprobada:** `?archived=true`. |
| D7 | Throttle de reactivación | **Aprobada:** límite propio `staff_reactivate`, 10 por hora. |
| D8 | Acciones de fila | **Aprobada:** botones con icono y texto. |
| D9 | Reactivar a un VET sin cédula | **Aprobada:** se permite y la interfaz advierte que no podrá firmar. |
| D10 | Cómo documentar los cambios de A1 y A2 | **Aprobada:** addendums a p21 y p48, más una nota en p63. La versión de sesión tiene ADR propio (p65). |
| D11 | `no-store` en el restablecimiento existente | **Aprobada:** sí. |
| D12 | Garantía contra tokens emitidos antes de un cambio de credenciales o de acceso | **Aprobada:** opción A, versión de sesión (F0, ADR p65). |
| D13 | Restablecimiento de plataforma sobre cuentas de servicio | **Aprobada:** 404, en la vista y en el servicio, igual que el restablecimiento de clínica (ADR p51). |
| D14 | Peticiones en vuelo al cambiar la contraseña propia | **Aprobada:** reintentar una sola vez cuando el 401 corresponda a un token anterior al almacenado, con las condiciones de II.0. |

---

## Registro de implementación (2026-11-20)

Ajustes respecto del texto anterior, ninguno de contrato:

- `_issue_temporary_password` devuelve `(contraseña, refresh_revocados)`: el restablecimiento
  registra ese conteo en su log.
- El 401 de un refresh ya revocado lo responde simplejwt con `token_not_valid` antes de llegar a la
  versión; `session_revoked` aparece cuando el refresh no está en la lista de revocación (tokens sin
  revocar, ver `CompatibilityTests`). La garantía es la misma: 401 sin rotar.
- En la edición, la validación del cliente sigue avisando con un toast (comportamiento previo, cubierto
  por una prueba existente); los errores del servidor van a su campo con `handleFormError`. En el alta,
  ambos van al campo, como pedía F4.
- `TenantJWTAuthentication` lanza `SessionRevoked` (`default_code='session_revoked'`) para que el
  handler de errores publique ese código.
- Pruebas existentes ajustadas (sin quitar ni debilitar aserciones):
  - `test_staff_email_enforcement.py` y `test_staff_create_must_change.py`: los payloads del alta
    agregan `first_name`, obligatorio por D4.
  - `frontend/src/pages/staff.test.jsx`: el PATCH envía solo lo que cambió (F5), el placeholder dice 8
    caracteres y los errores del alta se ven en su campo (F4).
- Pruebas: backend `apps.users`, `apps.platform`, `apps.legal`, `apps.core` y suites del agente con
  tokens en verde sobre PostgreSQL (con un hasher rápido solo en local); frontend 891/893, con 2 pruebas
  de Inbox que exceden 5 s bajo la carga de la suite completa y pasan aisladas (no usan el código
  modificado).
