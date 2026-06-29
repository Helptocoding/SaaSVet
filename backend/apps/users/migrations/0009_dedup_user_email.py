"""
ADR p48 — Fase 1: deduplicación previa al constraint de correo único.

Antes de aplicar el índice único case-insensitive sobre `email`
(`0010_user_email_ci_unique`), esta migración verifica que no existan correos
NO vacíos duplicados de forma case-insensitive. Si los hay, **falla ruidosamente
listándolos** — NO fusiona cuentas automáticamente (no son fusionables con
seguridad; la resolución es manual). A escala beta (pocos usuarios reales) esto
es un puñado de casos a lo sumo. En una DB fresca (CI) no hay usuarios → no-op.
"""
from collections import Counter

from django.db import migrations


def check_no_duplicate_emails(apps, schema_editor):
    User = apps.get_model("users", "User")

    rows = User.objects.exclude(email="").values_list("pk", "email")
    counts = Counter()
    by_lower = {}
    for pk, email in rows:
        key = (email or "").strip().lower()
        if not key:
            continue
        counts[key] += 1
        by_lower.setdefault(key, []).append((pk, email))

    dups = {k: v for k, v in by_lower.items() if counts[k] > 1}
    if dups:
        lines = []
        for key, entries in sorted(dups.items()):
            ids = ", ".join(f"#{pk} <{email}>" for pk, email in entries)
            lines.append(f"  {key}: {ids}")
        raise RuntimeError(
            "ADR p48 — correos duplicados (case-insensitive) detectados. "
            "Resuélvelos manualmente (NO se fusionan cuentas) antes de aplicar "
            "el constraint único de correo:\n" + "\n".join(lines)
        )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_user_password_must_change_and_more"),
    ]

    operations = [
        # Reverse = noop: es una verificación, no muta datos.
        migrations.RunPython(check_no_duplicate_emails, migrations.RunPython.noop),
    ]
