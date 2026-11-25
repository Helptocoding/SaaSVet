# ADR p68 — Verificación en dos pasos para ADMIN y especialidad estructurada

**Fecha:** 2026-11-24
**Estado:** ACEPTADO (decisiones del PO del 2026-11-24, Fase 4 «Diferenciación» de
[`auditoria-modulo-equipo-2026-11-23.md`](../auditoria-modulo-equipo-2026-11-23.md), sin las
piezas que dependen de WhatsApp)
**Enmienda a:** ADR p21 y p45 (el restablecimiento de contraseña también quita el MFA), ADR p48
(el login puede pedir un segundo paso), ADR p64 (la especialidad deja de ser texto libre) y el
contrato del agente `get_offered_specialties`.

**Supuesto de partida:** no hay clínicas ni usuarios reales (`CLAUDE.md` § Datos y usuarios
reales). La migración de especialidades descarta lo que no reconoce y no hay periodo de
convivencia con clientes anteriores.

## Decisiones

### A. Verificación en dos pasos (MFA)

1. **Opcional y solo para ADMIN** (PO), fuera de la demo y de las cuentas de servicio. Quien
   lo tiene activo puede verlo y quitarlo aunque deje de ser ADMIN.
2. **TOTP (RFC 6238)**: HMAC-SHA1, 6 dígitos, pasos de 30 s, ±1 paso de tolerancia. Solo
   biblioteca estándar (`apps.users.totp`), con los vectores del RFC en las pruebas. Un código
   no se acepta dos veces (`last_used_step`).
3. **Sin QR** (PO): la clave se teclea en la app; también se entrega el enlace `otpauth://`
   para abrirla desde el celular. Sin dependencias nuevas.
4. **Activación**: contraseña → clave pendiente (30 min) → primer código válido → activo, con
   **10 códigos de respaldo** de un solo uso que se muestran una vez. Desactivar o generar
   códigos nuevos exige contraseña y un código (de la app o de respaldo).
5. **Almacenamiento**: `UserMFA` (uno a uno con `User`). El secreto se guarda cifrado (Fernet,
   clave derivada de `MFA_ENCRYPTION_KEY` o de `SECRET_KEY`); los códigos de respaldo, como
   HMAC-SHA256. Cambiar esa clave invalida los MFA activos (la salida es el punto 7).
6. **Login en dos pasos**: con MFA activo, `POST /api/token/` con la contraseña correcta **no
   emite tokens**: responde `{mfa_required: true, mfa_token}`. El reto está firmado
   (`django.core.signing`), vale 5 minutos, un solo inicio de sesión y cinco códigos, y muere
   si cambia la versión de sesión (ADR p65) o la persona se desactiva. `POST /api/token/mfa/`
   `{mfa_token, code}` emite los tokens (estampados) tras las mismas compuertas del login
   (clínica desactivada, contraseña temporal vencida). Throttle propio `login_mfa` (10/15 min
   por IP) y contador de intentos en la caché fail-closed del login.
7. **Recuperación (PO)**: códigos de respaldo; si también se pierden, otro ADMIN (o soporte de
   plataforma) restablece la contraseña y eso **quita el MFA**. Lo mismo al reactivar. El
   historial lo marca (`mfa_removed`).
8. Historial: `mfa_enabled` y `mfa_disabled` en `StaffAccessEvent`.

### B. Especialidad estructurada

1. **Catálogo cerrado** de 16 especialidades (`apps.users.specialties`), copia en
   `frontend/src/features/staff/specialties.json` verificada por prueba.
2. **Varias por integrante** (PO): `User.specialties` (lista de códigos, en el orden del
   catálogo); sustituye a `User.specialty` (texto libre). Solo quien atiende pacientes las
   captura en Equipo. Lo que se muestra e imprime es `specialty_label` («Cirugía,
   Dermatología»); los documentos cerrados conservan su texto congelado.
3. **Servicios**: `Service.specialty` opcional, del mismo catálogo.
4. El agente cruza servicios activos y clínicos activos **por código** en
   `get_offered_specialties` (antes comparaba textos libres por tokens). Es el único cambio en
   el agente, y es de adaptación al dato; la disponibilidad por especialidad del agente queda
   fuera (depende de WhatsApp).

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| MFA por SMS o correo | No hay proveedor transaccional; SMS es el factor más débil |
| `pyotp` / `django-otp` | Una dependencia para ~40 líneas con vectores del RFC verificables |
| QR con `segno` o `qrcode` | Decisión del PO: sin dependencias nuevas |
| Acción separada «Quitar MFA» | El PO prefirió que el restablecimiento lo quite: una sola vía de recuperación |
| Especialidad con «Otra» de texto libre | Volvería el problema de textos que no coinciden |
| Una especialidad por integrante | Un cirujano que también da consulta general quedaría a medias |

## Consecuencias

- Migraciones aditivas `users.0018` (tabla `users_usermfa`) y `billing.0044`
  (`Service.specialty`); `users.0017` sustituye `specialty` por `specialties` traduciendo el
  texto anterior.
- Nuevos errores: `mfa_code_invalid`, `mfa_challenge_invalid` (401, solo en `token/mfa/`),
  `mfa_not_available` (403), `mfa_already_enabled` / `mfa_not_enabled` (409).
- El frontend no redirige ni reintenta un 401 de `token/mfa/` (`isLoginAttempt`).
- Pendiente fuera de alcance: exigir MFA por clínica, MFA para `ADMIN_SAAS`, QR, y la
  disponibilidad por especialidad del agente.
