"""Select a validated disposable PostgreSQL clone before Django initializes."""
import json
import os
import re
from urllib.parse import quote, unquote, urlsplit

LOOPBACK_HOSTS = ('localhost', '127.0.0.1')


def validate_test_database(config, *, allowed_prefixes, source_url):
    if not isinstance(config, dict):
        raise RuntimeError('Test database configuration must be an object')
    name = config.get('NAME')
    if (config.get('ENGINE') != 'django.db.backends.postgresql'
            or config.get('HOST') not in LOOPBACK_HOSTS
            or not isinstance(name, str)
            or not re.fullmatch(r'[a-zA-Z0-9_]{1,63}', name)
            or not any(name.startswith(prefix) and len(name) > len(prefix) for prefix in allowed_prefixes)):
        raise RuntimeError('Recognized isolated loopback PostgreSQL required')
    try:
        source = urlsplit(source_url)
        port = int(config.get('PORT') or 5432)
        if (source.scheme not in ('postgres', 'postgresql')
                or source.hostname not in LOOPBACK_HOSTS or not 0 < port < 65536):
            raise ValueError('Invalid source or test endpoint')
        # Both accepted hosts designate loopback. A differently spelled host
        # must not bypass the protection against restoring the source database.
        if port == (source.port or 5432) and name == unquote(source.path.lstrip('/')):
            raise RuntimeError('The ordinary/source database is forbidden')
    except (TypeError, ValueError) as error:
        raise RuntimeError('Valid ordinary/source PostgreSQL URL required') from error
    return config


def configure_test_database_environment(*, allowed_prefixes):
    try:
        config = json.loads(os.environ['B3_TEST_DATABASE'])
    except (KeyError, ValueError) as error:
        raise RuntimeError('Explicit test database configuration required') from error
    validate_test_database(config, allowed_prefixes=allowed_prefixes,
                           source_url=os.environ.get('DATABASE_URL', ''))
    user = quote(str(config.get('USER') or ''), safe='')
    password = quote(str(config.get('PASSWORD') or ''), safe='')
    credentials = f'{user}:{password}@' if user or password else ''
    name = quote(config['NAME'], safe='')
    os.environ['DATABASE_URL'] = (
        f"postgresql://{credentials}{config['HOST']}:{config.get('PORT') or 5432}/{name}"
    )
    return config
