"""Native runner validation or one fixed formal campaign."""
import sys
from native_support import EVIDENCE, DATA, PORT, environment, save
import os

os.environ.update(environment())

if __name__ == '__main__':
    if sys.argv[1:] == ['--validate-only']:
        import recorded_suite
        from django.conf import settings
        from django.test.utils import get_runner
        names = ('RecordedB0Runner', 'RecordedB3Runner', 'RecordedB4Runner', 'RecordedB5Runner', 'RecordedFullRunner')
        for name in names:
            assert get_runner(settings, 'recorded_suite.' + name) is getattr(recorded_suite, name)
        assert settings.DATABASES['default']['HOST'] == '127.0.0.1'
        assert str(settings.DATABASES['default']['PORT']) == '35488'
        import psycopg
        from pathlib import Path
        with psycopg.connect(host='127.0.0.1', port=PORT, user='b9e',
                dbname='test_b9i_control', connect_timeout=5) as conn:
            values = conn.execute("SELECT current_setting('data_directory'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')").fetchone()
            assert Path(values[0]).resolve() == DATA.resolve()
            assert values[1:] == ('on', 'on', 'on')
        save('launcher-validation.json', {'state': 'PASS', 'runner_resolution': names,
             'owned_postgresql_live_after_preparation': True, 'durability_settings_verified': values[1:],
             'application_tests_executed': False, 'wsl_invoked': False})
        print('NATIVE_RUNNERS_VALIDATED', flush=True)
    else:
        assert not (EVIDENCE / 'STOP.json').exists()
        from run_campaign import run_all, StopCampaign
        try:
            run_all()
        except StopCampaign:
            raise SystemExit(2)
        except Exception as exc:
            save('controller-incident.json', {'type': type(exc).__name__, 'message': str(exc)})
            if not (EVIDENCE / 'STOP.json').exists():
                save('STOP.json', {'state': 'PENDING', 'phase': 'controller', 'cause': str(exc), 'no_rerun': True})
            raise
