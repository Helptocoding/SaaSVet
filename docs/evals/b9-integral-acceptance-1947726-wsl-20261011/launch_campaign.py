"""Corrected bootstrap; validation never runs application tests or a campaign."""
import json
import os
import sys
from prepare_wsl import EVIDENCE,environment,save

os.environ.update(environment())

if __name__=='__main__' and sys.argv[1:]==['--validate-only']:
    import recorded_suite
    from django.conf import settings
    from django.test.utils import get_runner
    names=['RecordedB0Runner','RecordedB3Runner','RecordedB4Runner','RecordedB5Runner','RecordedFullRunner']
    for name in names:
        assert get_runner(settings,'recorded_suite.'+name) is getattr(recorded_suite,name)
    assert settings.SECRET_KEY=='b9i-wsl-disposable-test-only'
    assert settings.DATABASES['default']['HOST']=='127.0.0.1'
    assert str(settings.DATABASES['default']['PORT'])=='35479'
    result={'state':'PASS','django_setup':'PASS','runner_resolution':names,
        'application_tests_executed':False,'formal_campaign_restarted':False,
        'original_controller_preserved':True,'durable_stop_preserved':(EVIDENCE/'STOP.json').exists()}
    save('corrected-launcher-validation.json',result)
    print(json.dumps(result),flush=True)
elif __name__=='__main__':
    from run_campaign import run_all
    if (EVIDENCE/'STOP.json').exists():
        raise RuntimeError('Campaign stopped. Corrected bootstrap does not authorize a new campaign.')
    run_all()
