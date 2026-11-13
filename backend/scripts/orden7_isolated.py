"""Comandos restringidos al cluster PostgreSQL desechable y exclusivo del orden 7.

Misma pauta que `orden4_isolated.py`: limpia el entorno, desactiva integraciones y
verifica el destino efectivo antes de ejecutar. Nunca toca la base habitual ni el VPS.
Para `test` antepone MD5 a los hashers: PBKDF2 tarda ~3 s por hash en este equipo y
solo afecta a la velocidad de los fixtures, no al código bajo prueba.
"""
import os
import sys
from pathlib import Path

import psycopg

HOST = '127.0.0.1'
PORT = 49937
USER = 'orden7_runner'
DATABASE = 'orden7_iso_20261112'
TEST_DATABASE = 'test_orden7_iso_20261112'
DIRECTORY = Path.home() / 'AppData/Local/Temp/opencode/orden7_pg18_20261112'


def main():
    keys = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP',
            'TMP', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'LOCALAPPDATA', 'APPDATA')
    minimal = {key: os.environ[key] for key in keys if key in os.environ}
    os.environ.clear()
    os.environ.update(minimal)
    args = sys.argv[1:]
    if not args or args[0] not in {'init-db', 'check', 'test', 'migrate', 'makemigrations'}:
        raise SystemExit('Comando no autorizado.')
    if args[0] == 'makemigrations' and not {'--check', '--dry-run'} <= set(args):
        raise SystemExit('makemigrations requiere --check --dry-run.')
    if args[0] == 'migrate' and any(a.startswith('--fake') for a in args):
        raise SystemExit('Migraciones fake no autorizadas.')
    with psycopg.connect(host=HOST, port=PORT, user=USER, dbname='postgres', autocommit=True) as conn:
        name, directory, listen, port = conn.execute(
            "SELECT current_database(), current_setting('data_directory'), "
            "current_setting('listen_addresses'), current_setting('port')"
        ).fetchone()
        if (name != 'postgres' or Path(directory).resolve() != DIRECTORY.resolve()
                or listen != HOST or port != str(PORT)):
            raise SystemExit('Destino fuera de allowlist orden 7.')
        print('Destino verificado: cluster exclusivo orden 7, loopback', PORT, flush=True)
        if args[0] == 'init-db':
            exists = conn.execute(
                'SELECT 1 FROM pg_database WHERE datname = %s', (DATABASE,)).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE {DATABASE}')
            print('Base', DATABASE, 'lista.', flush=True)
            return
    os.environ.update({
        'DJANGO_SETTINGS_MODULE': 'config.settings',
        'DATABASE_URL': f'postgresql://{USER}@{HOST}:{PORT}/{DATABASE}',
        'PGHOST': HOST, 'PGPORT': str(PORT), 'PGUSER': USER, 'PGDATABASE': DATABASE,
        'PGPASSWORD': '', 'SECRET_KEY': 'orden7-isolated-synthetic-not-for-deploy',
        'ENVIRONMENT': 'dev', 'DEBUG': 'False', 'SENTRY_DSN': '',
        'DISABLE_SENTRY': 'True', 'REDIS_URL': '', 'WHATSAPP_APP_SECRET': '',
        'WHATSAPP_ACCESS_TOKEN': '', 'WHATSAPP_VERIFY_TOKEN': '',
        'AGENT_LLM_BASE_URL': '', 'AGENT_LLM_API_KEY': '',
        'HEALTHCHECK_AGENT_WORKER_URL': '', 'HEALTHCHECK_AGENT_SENDER_URL': '',
        'DISCORD_WEBHOOK_URL': '', 'MEDIA_B2_ENDPOINT_URL': '',
        'MEDIA_B2_ACCESS_KEY_ID': '', 'MEDIA_B2_SECRET_ACCESS_KEY': '',
    })
    import decouple
    decouple.config = decouple.Config(decouple.RepositoryEmpty())
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from django.conf import settings
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.DATABASES['default']['TEST'] = {'NAME': TEST_DATABASE}
    if args[0] == 'test':
        settings.PASSWORD_HASHERS = [
            'django.contrib.auth.hashers.MD5PasswordHasher', *settings.PASSWORD_HASHERS]
    from django.core.management import execute_from_command_line
    execute_from_command_line(['manage.py', *args])


if __name__ == '__main__':
    main()
