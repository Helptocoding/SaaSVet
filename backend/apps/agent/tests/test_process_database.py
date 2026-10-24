"""Reject unsafe child/restore targets before any database I/O."""
import json
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from .process_database import configure_test_database_environment, validate_test_database


class TestProcessDatabaseSafety(TestCase):
    def config(self, **overrides):
        return dict(ENGINE='django.db.backends.postgresql', HOST='127.0.0.1', PORT='5432',
                    NAME='test_ci_42_1_3', USER='test:user', PASSWORD='p@ss:/?#',
                    OPTIONS={'connect_timeout': 5}, **overrides)

    def test_child_selects_exact_clone_and_encodes_credentials(self):
        config = self.config()
        with patch.dict(os.environ, DATABASE_URL='postgres://test@localhost/source',
                        B3_TEST_DATABASE=json.dumps(config)):
            selected = configure_test_database_environment(allowed_prefixes=('test_b8b_', 'test_ci_'))
            url = urlsplit(os.environ['DATABASE_URL'])
            self.assertEqual(unquote(url.username), config['USER'])
            self.assertEqual(unquote(url.password), config['PASSWORD'])
            self.assertEqual(unquote(url.path.lstrip('/')), config['NAME'])
            self.assertEqual(url.hostname, config['HOST'])
            self.assertEqual(url.port, 5432)
            self.assertEqual(selected, config)

    def test_all_existing_dedicated_names_and_ci_clones_are_accepted(self):
        for suite in ('b8b', 'b8c', 'b8d', 'b8e', 'inbox_policy'):
            for name in (f'test_{suite}_local', 'test_ci_42_1_3'):
                config = self.config()
                config['NAME'] = name
                self.assertIs(validate_test_database(config,
                    allowed_prefixes=(f'test_{suite}_', 'test_ci_'),
                    source_url='postgresql://test@localhost/source'), config)

    def test_unsafe_payloads_never_replace_inherited_source_url(self):
        config = self.config()
        cases = [None, [], {}, {**config, 'NAME': ''}, {**config, 'NAME': 'test_ci_'},
                 {**config, 'NAME': 'source'}, {**config, 'NAME': 'test_other_42'},
                 {**config, 'NAME': 'test_ci_a;DROP DATABASE source'},
                 {**config, 'NAME': 'test_ci_' + 'a'*60},
                 {**config, 'HOST': 'production.example'}, {**config, 'HOST': ''},
                 {**config, 'ENGINE': 'django.db.backends.sqlite3'},
                 {**config, 'PORT': 'not-a-port'}, {**config, 'PORT': 65536}]
        for candidate in cases:
            with self.subTest(candidate=candidate), patch.dict(os.environ,
                    DATABASE_URL='postgres://test@localhost/source', B3_TEST_DATABASE=json.dumps(candidate)):
                with self.assertRaises(RuntimeError):
                    configure_test_database_environment(allowed_prefixes=('test_ci_',))
                self.assertEqual(os.environ['DATABASE_URL'], 'postgres://test@localhost/source')

    def test_source_identity_cannot_be_bypassed_by_loopback_spelling(self):
        with self.assertRaisesRegex(RuntimeError, 'ordinary/source'):
            validate_test_database(self.config(), allowed_prefixes=('test_ci_',),
                source_url='postgres://test@localhost/test_ci_42_1_3')

    def test_missing_payload_or_source_url_fails_closed(self):
        for values in ({}, {'B3_TEST_DATABASE': 'not-json'},
                       {'B3_TEST_DATABASE': json.dumps(self.config())}):
            with self.subTest(values=values), patch.dict(os.environ, values, clear=True):
                with self.assertRaises(RuntimeError):
                    configure_test_database_environment(allowed_prefixes=('test_ci_',))

    def test_restore_rejects_ordinary_target_before_fixtures_or_io(self):
        from apps.channels.tests.test_media_restore_drill import MediaDatabaseRestoreDrill
        from apps.channels.tests import test_media_restore_drill as drill

        unsafe = self.config()
        unsafe['NAME'] = 'ordinary_database'
        case = MediaDatabaseRestoreDrill('test_old_dump_cannot_reactivate_revoked_expired_or_recovered_jobs')
        with patch.object(drill, 'connection', SimpleNamespace(settings_dict=unsafe)) as database, \
                patch.object(case, 'build') as build, patch.object(drill.subprocess, 'run') as child:
            with self.assertRaises(RuntimeError):
                case.test_old_dump_cannot_reactivate_revoked_expired_or_recovered_jobs()
            build.assert_not_called()
            child.assert_not_called()
            self.assertFalse(hasattr(database, 'cursor'))
