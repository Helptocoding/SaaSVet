"""
PostgreSQL advisory locks for cross-process coordination.

Used to prevent overlapping cron executions and accidental concurrent
nightly job runs on Railway (where deploys can overlap, restarts can
re-trigger jobs, and there's no single-source scheduler guarantee).

API:
  try_advisory_lock(key) → bool
      Acquire a session-level advisory lock. Returns True if acquired,
      False if another session holds it. Lock is released automatically
      when the DB session ends.
  advisory_lock(key) [context manager]
      Try to acquire; raise LockUnavailable if held by another session;
      release on exit.
  advisory_xact_lock(*parts) → int
      Transaction-scoped lock (waits instead of failing). Released by the
      commit/rollback of the enclosing transaction. Used by the owner phone
      deduplication key (INV-C) — see apps/patients/services.py.
  hash_lock_key(*parts) → int
      Stable 63-bit signed bigint hash of arbitrary string parts. PG
      advisory locks accept (int, int) or (bigint). We use bigint form.

PostgreSQL specific. Code that runs on other backends should branch on
connection.vendor.
"""
import contextlib
import hashlib

from django.db import connection


class LockUnavailable(Exception):
    """Raised when advisory_lock() cannot acquire because another session holds it."""


class AdvisoryLockUnsupported(RuntimeError):
    """El backend de base de datos no ofrece locks de aviso.

    NO se degrada a no-op: un lock de deduplicación que no bloquea es un
    fail-open invisible — justo la clase de bug que INV-C existe para cerrar
    (ADR p57, decisión §4.7.3). Mejor romper ruidosamente.
    """


def hash_lock_key(*parts):
    """
    Hash arbitrary parts into a 63-bit signed bigint suitable for
    pg_advisory_lock. Stable across processes and Python versions.
    """
    raw = ':'.join(str(p) for p in parts).encode('utf-8')
    digest = hashlib.blake2b(raw, digest_size=8).digest()
    n = int.from_bytes(digest, 'big', signed=False)
    # Convert to signed 63-bit range to fit PG bigint and avoid sign issues.
    return n & 0x7FFFFFFFFFFFFFFF


def try_advisory_lock(key):
    if connection.vendor != 'postgresql':
        # Other backends: no-op (sqlite/mysql tests won't deadlock anyway).
        return True
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [key])
        return cur.fetchone()[0]


def release_advisory_lock(key):
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", [key])


def advisory_xact_lock(*key_parts):
    """Lock de aviso a nivel de TRANSACCIÓN sobre `hash_lock_key(*key_parts)`.

    Diferencia con `advisory_lock` (sesión): éste se libera **solo** con el
    commit o el rollback de la transacción que lo tomó. No hay que acordarse de
    soltarlo y no sobrevive a un rollback — que es exactamente lo que necesita
    una clave de deduplicación (decisión §4.7.3).

    Espera si otra transacción lo tiene (no es `try_`): el segundo actor debe
    ver el mundo DESPUÉS del primero, no rendirse.

    Los locks de aviso son de **cluster**, no de base: quien construya la clave
    debe incluir lo que haga falta para no colisionar con otra base del mismo
    servidor (ver `patients.services._lock_dedup_key`).

    Dos guardas deliberadas, ambas ruidosas:

      1. **PostgreSQL o nada.** En otro motor lanza `AdvisoryLockUnsupported`
         en vez de devolver `True` como hace `try_advisory_lock`. Un no-op aquí
         convertiría la garantía en decoración.
      2. **Exige transacción abierta.** En autocommit, `pg_advisory_xact_lock`
         toma y suelta el lock dentro de su propia sentencia: el llamador cree
         estar serializado y no lo está. Es el mismo fail-open, con otra cara.

    Devuelve la clave entera (útil para logs y pruebas).
    """
    if connection.vendor != 'postgresql':
        raise AdvisoryLockUnsupported(
            "Los locks de deduplicación exigen PostgreSQL "
            f"(vendor actual: {connection.vendor})."
        )
    if not connection.in_atomic_block:
        raise RuntimeError(
            "advisory_xact_lock() requiere una transacción abierta: en "
            "autocommit el lock se libera en la misma sentencia y no serializa "
            "nada."
        )
    key = hash_lock_key(*key_parts)
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", [key])
    return key


@contextlib.contextmanager
def advisory_lock(key, *, on_busy='raise'):
    """
    Context manager. on_busy='raise' (default) raises LockUnavailable; on_busy='skip'
    yields False instead so caller can short-circuit.
    """
    acquired = try_advisory_lock(key)
    if not acquired:
        if on_busy == 'skip':
            yield False
            return
        raise LockUnavailable(f"Advisory lock {key} held by another session.")
    try:
        yield True
    finally:
        release_advisory_lock(key)
