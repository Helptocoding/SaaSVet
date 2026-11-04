"""Run explicitly approved Django commands against the disposable order-2 cluster.

This script is intentionally tied to one local cluster and refuses an inherited
DATABASE_URL. Never use it for production or the regular development database.
"""
import os
import sys
from pathlib import Path

import psycopg


HOST = '127.0.0.1'
PORT = 55483
USER = 'orden2_runner'
DATABASE = 'orden2_iso_20261028'
DIRECTORY = Path.home() / 'AppData/Local/Temp/opencode/orden2_pg18'
ALLOWED = {'check', 'migrate', 'test', 'makemigrations',
           'audit_billing_schema', 'audit_anchor_integrity',
           'audit_payment_ledger_integrity', 'audit_stock_integrity'}


def main():
    # Do not inherit the operator's environment, credentials or project .env.
    # Preserve only Windows process/bootstrap variables required by Python.
    process_keys = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
                    'TEMP', 'TMP', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH',
                    'LOCALAPPDATA', 'APPDATA')
    minimal = {key: os.environ[key] for key in process_keys if key in os.environ}
    os.environ.clear()
    os.environ.update(minimal)
    test_schema = '--isolated-test-db' in sys.argv[1:]
    fresh_schema = '--isolated-fresh-db' in sys.argv[1:]
    final_schema = '--isolated-final-db' in sys.argv[1:]
    if sum((test_schema, fresh_schema, final_schema)) > 1:
        raise SystemExit('Elige solo un destino aislado.')
    if test_schema:
        sys.argv.remove('--isolated-test-db')
    if fresh_schema:
        sys.argv.remove('--isolated-fresh-db')
    if final_schema:
        sys.argv.remove('--isolated-final-db')
    database = ('orden2_iso_20261028_test' if test_schema else
                'orden2_iso_20261028_fresh' if fresh_schema else
                'orden2_iso_20261028_final' if final_schema else DATABASE)
    if len(sys.argv) < 2 or sys.argv[1] not in ALLOWED:
        raise SystemExit('Comando fuera de la allowlist de orden 2.')
    if sys.argv[1] == 'makemigrations' and not {'--check', '--dry-run'} <= set(sys.argv[2:]):
        raise SystemExit('makemigrations solo en modo --check --dry-run.')
    if sys.argv[1] == 'migrate' and any(arg in sys.argv[2:] for arg in ('--fake', '--fake-initial')):
        raise SystemExit('No se permiten migraciones fake.')
    if test_schema and sys.argv[1] != 'migrate':
        raise SystemExit('El destino test solo admite migrate (sin tests anidados).')
    if (fresh_schema or final_schema) and sys.argv[1] not in ('migrate', 'check', 'makemigrations'):
        raise SystemExit('El destino fresh solo admite migraciones y checks.')
    with psycopg.connect(host=HOST, port=PORT, user=USER, dbname=database) as conn:
        name, data_dir, encoding = conn.execute(
            'SELECT current_database(), current_setting(\'data_directory\'), '
            'pg_encoding_to_char(encoding) FROM pg_database WHERE datname=current_database()'
        ).fetchone()
    expected_encoding = 'WIN1252' if test_schema else 'UTF8'
    if (name != database or Path(data_dir).resolve() != DIRECTORY.resolve()
            or encoding != expected_encoding):
        raise SystemExit('Destino de PostgreSQL fuera de la allowlist de pruebas.')
    # The existing .env remains unread by Django's config because every variable
    # it consumes for integration/DB is overridden with a synthetic value.
    os.environ.update({
        'DJANGO_SETTINGS_MODULE': 'config.settings',
        'DATABASE_URL': f'postgresql://{USER}@{HOST}:{PORT}/{database}',
        'PGHOST': HOST, 'PGPORT': str(PORT), 'PGUSER': USER,
        'PGDATABASE': database, 'PGPASSWORD': '',
        'SECRET_KEY': 'orden2-isolated-synthetic-key-not-for-deploy',
        'ENVIRONMENT': 'dev', 'DEBUG': 'False', 'SENTRY_DSN': '',
        'DISABLE_SENTRY': 'True', 'REDIS_URL': '',
        'WHATSAPP_APP_SECRET': '', 'WHATSAPP_ACCESS_TOKEN': '',
        'WHATSAPP_VERIFY_TOKEN': '', 'AGENT_LLM_BASE_URL': '',
        'AGENT_LLM_API_KEY': '', 'HEALTHCHECK_AGENT_WORKER_URL': '',
        'HEALTHCHECK_AGENT_SENDER_URL': '', 'DISCORD_WEBHOOK_URL': '',
        'MEDIA_B2_ENDPOINT_URL': '', 'MEDIA_B2_ACCESS_KEY_ID': '',
        'MEDIA_B2_SECRET_ACCESS_KEY': '',
    })
    import decouple
    decouple.config = decouple.Config(decouple.RepositoryEmpty())
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from django.conf import settings
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.DATABASES['default']['TEST'] = {'NAME': 'orden2_iso_20261028_test'}
    from django.core.management import execute_from_command_line
    print(f'allowlist OK: PostgreSQL {expected_encoding} {HOST}:{PORT}/{database} (isolated cluster)')
    execute_from_command_line(['manage.py', *sys.argv[1:]])


if __name__ == '__main__':
    main()
