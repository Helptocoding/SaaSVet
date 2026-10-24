"""Disposable CI test namespace. Production settings remain unchanged."""
import os
import re

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

_run = os.environ.get('CI_TEST_RUN_ID') or os.environ.get('GITHUB_RUN_ID', 'local')
_attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
if not re.fullmatch(r'[a-zA-Z0-9_]{1,32}', _run) or not re.fullmatch(r'[0-9]{1,8}', _attempt):
    raise ImproperlyConfigured('Invalid disposable CI test namespace')
_database = DATABASES['default']  # noqa: F405
if (_database['ENGINE'] != 'django.db.backends.postgresql'
        or _database.get('HOST') not in ('localhost', '127.0.0.1')):
    raise ImproperlyConfigured('CI requires loopback PostgreSQL')
_database.setdefault('TEST', {})['NAME'] = f'test_ci_{_run}_{_attempt}'
