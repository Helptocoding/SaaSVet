"""Read-only progress monitor; avoids repeated Python launches during disk I/O."""
import json
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent


def main():
    while True:
        passed = sum(len(path.read_text().splitlines())
                     for path in OUT.glob('regression*.results.passed.jsonl'))
        completed = [path.name for path in OUT.glob('regression-resume-?.results.json')]
        failures = sum(sum(line.strip() in ('FAIL','ERROR') or line.startswith(('FAIL:','ERROR:'))
                           for line in path.read_text(encoding='utf-8').splitlines())
                       for path in OUT.glob('regression-resume-?.log'))
        print(json.dumps(dict(historical_passed=passed,completed_shards=completed,
                              recorded_failures=failures)),flush=True)
        if len(completed)==2:
            break
        time.sleep(45)


if __name__=='__main__':
    main()
