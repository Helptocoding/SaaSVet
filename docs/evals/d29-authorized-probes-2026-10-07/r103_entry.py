import argparse
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--job', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_case
import prepared_probe

prepared_probe.r103(load_case, args.job, args.output)
