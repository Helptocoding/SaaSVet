"""A single owned DB, complete logs and resource timeline, then cleanup."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from lab_control import HERE, ROOT, lab

OFFLINE = ROOT / 'docs/evals/d29-offline-preparation-2026-10-09'
sys.path.append(str(OFFLINE))
import read_only_diagnostic as diagnostic


def sample(cfg, folder, stage):
    memory, processes, limits = diagnostic.memory_and_processes()
    with lab.connect(cfg) as con:
        activity = con.execute('SELECT pid,datname,usename,application_name,backend_start,state,wait_event_type,wait_event '
                               'FROM pg_stat_activity ORDER BY pid').fetchall()
        configuration = con.execute("SELECT name,setting,unit FROM pg_settings WHERE name IN "
            "('fsync','synchronous_commit','shared_buffers','work_mem','maintenance_work_mem','max_connections') ORDER BY name").fetchall()
    row = dict(at_utc=datetime.now(timezone.utc).isoformat(), monotonic_ns=time.perf_counter_ns(), stage=stage,
               memory=memory, processes=processes, current_job_limits=limits,
               pg_stat_activity=activity, private_configuration=configuration)
    with (folder / 'resources.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, default=str) + '\n')


def run(kind, label):
    task, state = lab.session()
    cfg, copy = state['config'], Path(state['copy'])
    if (HERE / 'STOP.json').exists():
        raise RuntimeError('STOP_LATCHED_REVIEW_REQUIRED')
    folder = HERE / label
    folder.mkdir(exist_ok=False)
    name = 'test_d29_rect_' + hashlib.sha256(label.encode()).hexdigest()[:20]
    with lab.connect(cfg) as con:
        others = con.execute("SELECT datname,pid FROM pg_stat_activity WHERE datname NOT IN ('postgres')").fetchall()
        if others:
            raise RuntimeError('UNEXPECTED_PRIVATE_CLIENTS')
        con.execute(lab.sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(lab.sql.Identifier(name),lab.sql.Identifier(cfg['NAME'])))
    isolated = dict(cfg, NAME=name)
    env = lab.environment(isolated, copy)
    env['PYTHONPATH'] = str(HERE) + os.pathsep + str(copy / 'backend')
    if kind == 'adapter':
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / 'test_native_witnesses.py')]
    elif kind == 'suite':
        env['D29_REGRESSION_LABELS'] = json.dumps(['apps.agent.tests.' + label])
        env['D29_REGRESSION_OUTPUT'] = str(folder / 'suite-result.json')
        command = [sys.executable, '-B', '-X', 'utf8', str(ROOT / 'docs/evals/d29-physical-2026-10-06/orchestration-current/app_regression.py')]
    else:
        case, variant = (('R1-06', 'backlog') if kind == 'R1-06' else
                         ('R2-04', 'postcommit') if kind == 'R2-04' else
                         ('R1-04', 'forecasts') if kind == 'R1-04' else ('R2-09', kind))
        job = lab.make_job(case, variant, label)
        if case == 'R1-06':
            job.update(conversations_per_org=4, ordinary_conversations_per_org=3,
                scenario_population='R1-06_OPTION_B_2X4', fourth_slot='BACKLOG_ONLY',
                reconciliation_policy='R106_PROSPECTIVE_OBLIGATIONS_20261009_V1')
        job['evaluation_source_hashes'] = {p.name:lab.sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.ps1')}
        archive = folder / 'execution-sources'
        archive.mkdir()
        for source in job['evaluation_source_hashes']:
            shutil.copy2(HERE/source, archive/source)
        lab.write(folder/'execution-source-archive.json',job['evaluation_source_hashes'])
        job['job_sha256'] = hashlib.sha256(json.dumps({k:v for k,v in job.items() if k!='job_sha256'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        lab.write(folder / 'job.json', job)
        entry = 'r204_entry_v2.py' if kind == 'R2-04' else 'r104_entry.py' if kind == 'R1-04' else 'scenario_entry.py'
        command = [sys.executable, '-B', '-X', 'utf8', str(HERE / entry), '--job', str(folder / 'job.json'), '--output', str(folder / 'capture')]
    receipt = dict(kind=kind,label=label,database=name,status='PENDING',executed=False)
    pglog = task / 'pg.stderr'
    watermark = pglog.stat().st_size if pglog.exists() else 0
    try:
        sample(cfg, folder, 'before')
        with (folder / 'execution.log').open('x',encoding='utf-8') as log:
            proc = subprocess.Popen(['rtk','proxy',*command],cwd=copy/'backend',env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            receipt.update(executed=True, launcher_pid=proc.pid)
            while proc.poll() is None:
                sample(cfg, folder, 'during')
                if pglog.exists():
                    with pglog.open('rb') as f:
                        f.seek(watermark)
                        text = f.read().decode('utf-8', errors='replace')
                    if 'out of memory' in text.lower():
                        (folder / 'capture' / 'stop').touch() if (folder / 'capture').exists() else None
                        lab.write(HERE / 'STOP.json', dict(cause='OOM',attempt=label))
                        receipt['stop_reason'] = 'OOM'
                        break
                time.sleep(2)
            receipt['exit_code'] = proc.wait(timeout=60)
        sample(cfg, folder, 'after')
        receipt['status'] = 'PENDING' if kind not in ('adapter','suite') else ('ACCREDITED' if proc.returncode == 0 else 'FAILED')
        if kind not in ('adapter', 'suite'):
            with (folder / 'verification.log').open('x',encoding='utf-8') as log:
                verifier = 'verify_special.py' if kind in ('R2-04','R1-04') else 'verify_physical_v2.py'
                verified = subprocess.run(['rtk','proxy',sys.executable,'-B','-X','utf8',str(HERE / verifier),str(folder)],
                    cwd=copy/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            receipt['verification_exit_code'] = verified.returncode
            if (folder / 'physical-verification.json').exists():
                physical = json.loads((folder / 'physical-verification.json').read_text())
                receipt['status'] = physical['status']
                findings = json.dumps(physical)
                if any(code in findings for code in ('JOB_SEAL_CHANGED','JOB_SEAL_INVALID','EVALUATION_OVERLAY_CHANGED','EVALUATION_SOURCE_CHANGED','PARTICIPANT_JOB_CHANGED','SEALED_EXECUTOR_JOB_CHANGED')):
                    lab.write(HERE/'STOP.json',dict(cause='EVIDENCE_INTEGRITY_FAILURE',attempt=label))
            if (folder / 'capture-clock/clock-receipt.json').exists():
                clock = json.loads((folder / 'capture-clock/clock-receipt.json').read_text())
                if not clock.get('gate_passed'):
                    lab.write(HERE / 'STOP.json',dict(cause='CLOCK_OR_CAPTURE_INVALID',attempt=label,clock=clock))
    finally:
        if pglog.exists():
            with pglog.open('rb') as f:
                f.seek(watermark)
                (folder / 'postgres-attempt.log').write_bytes(f.read())
        with lab.connect(cfg) as con:
            clients = con.execute('SELECT pid,backend_start,state FROM pg_stat_activity WHERE datname=%s',[name]).fetchall()
            receipt['clients_after_child'] = clients
            if clients:
                receipt['status'] = 'PENDING'
                receipt['stop_reason'] = 'OWNED_CLIENTS_REMAIN'
                lab.write(HERE / 'STOP.json',dict(cause='OWNED_CLIENTS_REMAIN',attempt=label))
            else:
                con.execute(lab.sql.SQL('DROP DATABASE {}').format(lab.sql.Identifier(name)))
                receipt['database_removed'] = not con.execute('SELECT 1 FROM pg_database WHERE datname=%s',[name]).fetchone()
        lab.write(folder / 'execution-receipt.json', receipt)
    print(json.dumps(receipt,default=str),flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('kind',choices=['adapter','suite','R1-06','uncertain_meta','slow_meta','R2-04','R1-04'])
    p.add_argument('label')
    args = p.parse_args()
    run(args.kind,args.label)
