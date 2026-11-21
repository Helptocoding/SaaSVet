# ADR p65 — Versión de sesión: revocación inmediata de tokens emitidos

**Fecha**: 2026-11-19
**Estado**: **ACEPTADO** (decisión D12 del usuario, 19-11-2026). Escrito antes del código.
**Plan**: [Equipo: corregir y revertir](../plan-equipo-corregir-revertir-2026-11-19.md), fase F0.
**Supera**: la sección «Comportamiento del access token actual» de
[ADR p20](2026-05-22-p20-credential-lifecycle-self-change.md), para las operaciones listadas aquí.

## Contexto

ADR p20 aceptó que un access token siguiera siendo válido hasta 15 minutos después de un cambio
de credenciales, porque simplejwt solo revoca refresh tokens. La reactivación de personal (A2)
mostró que esa ventana no es inofensiva:

1. Una persona inicia sesión y recibe un access token T.
2. Un ADMIN la desactiva y la reactiva antes de que T venza.
3. La persona entra con la contraseña temporal y la cambia: `password_must_change` vuelve a
   `False`.
4. T vuelve a tener acceso completo hasta su vencimiento.

El mismo hueco existe en el restablecimiento de contraseña (de clínica y de plataforma) y en el
cambio de contraseña propio. El caso más grave es el restablecimiento por compromiso: el token
robado vuelve a servir en cuanto la víctima cambia su contraseña.

## Decisión

### 1. Versión por usuario

`User.session_version`: entero no negativo, `default=0`, `db_default=0`, `editable=False`.
Migración aditiva `users/0013_user_session_version`, sin backfill: todas las filas existentes
quedan en 0.

### 2. Claim `sv`

- Todo token emitido para una persona lleva `sv` con la versión del usuario al emitirlo. El
  nombre del claim y las funciones para estamparlo y leerlo viven en
  `apps/core/authentication.py`.
- Se estampa en el login (`EmailOrUsernameTokenObtainPairSerializer.get_token`) y en
  `change_password`. simplejwt copia el claim del refresh al access y lo conserva al rotar.
- **Un token sin `sv` vale 0.** Los tokens vigentes al desplegar siguen funcionando y los del
  agente (`mint_agent_token`, cuentas de servicio) no cambian.
- Un `sv` presente que no sea entero no negativo se rechaza.

### 3. Validación

- `TenantJWTAuthentication` compara, después de comprobar cuenta y organización activas, la
  versión del token con la del usuario que ya relee. Si difieren: 401 con
  `code='session_revoked'`. No agrega consultas.
- `PublicTokenRefreshView` compara en su comprobación previa, **antes** de rotar: 401
  `session_revoked`, sin rotar ni crear un `OutstandingToken`.
- Se compara por igualdad. La versión solo crece; un token con versión mayor solo podría salir de
  una transacción revertida, cuya respuesta nunca llega al cliente.
- Login, refresh y cierre de sesión ignoran la cabecera `Authorization` (`TokenViewBase` declara
  `authentication_classes = ()`): un token viejo almacenado en el navegador no bloquea el login.
- Se registra `AUTH_SESSION_REVOKED` con `user_id` y ambas versiones; nunca el token.

### 4. Incremento

`bump_session_version(user)` en `apps/users/services.py`: `UPDATE … SET session_version =
session_version + 1` dentro de la transacción del llamador. Lo llaman:

| Operación | Servicio |
|---|---|
| Desactivar | `deactivate_staff` |
| Reactivar | `reactivate_staff` |
| Restablecer (clínica) | `reset_password_for_staff` |
| Restablecer (plataforma) | `platform_reset_password` |
| Cambiar la contraseña propia | `change_password`, antes de emitir el par nuevo |

La revocación de `OutstandingToken` se conserva en todas: es defensa en profundidad.

No incrementan: editar el perfil o el correo, cerrar sesión (es por dispositivo), crear un
usuario, `ensure_agent_users` ni desactivar la organización.

### 5. Monotonía

La versión **solo** la escribe `bump_session_version`:

- `User.save()` sin `update_fields` sobre una fila existente guarda los mismos campos que Django
  guardaría, menos `session_version`. Una instancia leída antes de un incremento (por ejemplo, el
  formulario del admin de Django) no puede bajarla.
- `save(update_fields=[...])` con `session_version` lanza `ValueError`.
- Un gate estático (`apps/users/tests/test_session_version_gate.py`) falla si otro código
  productivo la escribe por asignación, argumento con nombre o cadena literal, y otro gate
  enumera los sitios que emiten tokens.

### 6. Cuentas de servicio

Ninguna vía incrementa su versión: `bump_session_version` las rechaza, y el restablecimiento de
plataforma responde 404 ante ellas en la vista y en el servicio, igual que el de clínica
(ADR p51). El criterio es `is_service_account`, no el rol.

### 7. Frontend

El interceptor HTTP reintenta **una sola vez** una petición rechazada con 401 cuando se envió con
un access token distinto del que hoy está almacenado (se renovó mientras viajaba). Excluye las
URLs de token y nunca llama al refresh. El reintento no duplica efectos: DRF autentica antes de
ejecutar la vista.

## Consecuencias

- Cambiar la contraseña cierra al instante las sesiones de esa persona en otros navegadores y
  dispositivos, y en pestañas sin «Recordarme». Las pestañas del mismo navegador con
  «Recordarme» comparten el token y siguen funcionando.
- Restablecer, desactivar o reactivar expulsa a la persona en su siguiente petición.
- Revertir el código es seguro sin revertir la migración: la columna queda sin uso y el claim se
  ignora.
- **Despliegue:** durante el relevo de instancias, una instancia con el código anterior no
  compara versiones. La revocación por versión solo es efectiva cuando ya no queda ninguna
  instancia antigua recibiendo tráfico (ver [runbook de despliegue](../runbooks/deploy.md)).

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Lista de revocación por `jti` del access token | Estado nuevo y una consulta por petición (p20, camino 1). |
| Espera mínima antes de reactivar (D12, opción B) | Depende de tiempos y no cubre restablecer ni cambiar la contraseña. |
| Comparar `iat` con la fecha del último cambio | `iat` tiene resolución de segundos y depende del reloj; un contador entero no. |
| Reducir la vida del access token | Achica la ventana, no la cierra. |
| Incrementar en `set_password()` | Efecto oculto en un método del modelo, sin atomicidad frente a escrituras concurrentes, y no cubre desactivar ni reactivar. |

## Fuera de alcance (riesgos aceptados)

- Cerrar sesión sigue siendo por dispositivo: el access token vale hasta 15 minutos.
- Los cambios hechos desde el admin de Django, `changepassword` o la shell no invalidan sesiones;
  solo se garantiza que no bajen la versión.
- Desactivar y reactivar una organización completa no invalida sus tokens.
