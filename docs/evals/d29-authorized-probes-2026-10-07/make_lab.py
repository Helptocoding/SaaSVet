from pathlib import Path

source = Path(r'C:\Users\LAP\Desktop\VeterinariaSaaS\docs\evals\d29-dependent-2026-10-07\orchestration\lab.py').read_text(encoding='utf-8')
source = source.replace("OUT = ROOT / 'docs/evals/d29-dependent-2026-10-07'", "OUT = ROOT / 'docs/evals/d29-authorized-probes-2026-10-07'")
source = source.replace("PREFIX = 'vet-d29-dependent-20261007-'", "PREFIX = 'vet-d29-authorized-20261007-'")
Path(__file__).with_name('authorized_lab.py').write_text(source, encoding='utf-8')
