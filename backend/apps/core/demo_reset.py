"""
ADR p49 — constantes compartidas del reset del tenant demo.

Sin lógica ni imports de Django: lo consumen tanto el management command
(`seed_demo_clinic`) como el guard de permisos (`core.permissions.DemoResetGate`)
sin riesgo de import circular.
"""

# Flag en cache (Redis, ADR p41) que marca un reset en curso. Mientras está
# presente, DemoResetGate rechaza las ESCRITURAS de la org demo con 503.
DEMO_RESET_FLAG_KEY = "demo_reset:in_progress"

# TTL del flag = cota superior estimada del reset + margen (ADR p49 §6.1/§9).
# Red de seguridad: si el proceso muere con el flag puesto, expira solo y la
# demo deja de rechazar escrituras. Ajustar con datos reales (§6.3).
DEMO_RESET_FLAG_TTL = 120  # segundos

# Clave bigint estable para pg_try_advisory_xact_lock (una sola demo, ADR p49 §7).
# Si en el futuro hay varias demos, se parametriza entonces (fuera de alcance).
DEMO_RESET_ADVISORY_KEY = 49_00_00_01

# Plan Equipo (D5): usernames de las tres cuentas semilla de la demo. El seed las
# identifica por username (`_ensure_users`), y Equipo las protege: no se editan,
# restablecen ni desactivan por la API. Una sola lista: `_demo_data.DEMO_USERS`
# la reutiliza. Llevan '@', que `USERNAME_REGEX` del alta no admite, así que
# ningún visitante puede crear un username igual. Restricción operativa (R7):
# no renombrarlas ni modificarlas desde el admin de Django.
DEMO_ADMIN_USERNAME = "demo-admin@saaslyvet.com"
DEMO_VET_USERNAME = "demo-vet@saaslyvet.com"
DEMO_RECEPTION_USERNAME = "demo-recepcion@saaslyvet.com"
DEMO_SEED_USERNAMES = frozenset({
    DEMO_ADMIN_USERNAME, DEMO_VET_USERNAME, DEMO_RECEPTION_USERNAME,
})
