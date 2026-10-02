"""Reduce saved PostgreSQL plans to structural metrics; no database access."""
import json
import os
from pathlib import Path

OUT = Path(os.environ.get('SQL_SCALING_OUT', Path(__file__).resolve().parent)).resolve()
FIELDS = ('Node Type', 'Parent Relationship', 'Subplan Name', 'Relation Name',
          'Index Name', 'Actual Rows', 'Actual Loops', 'Actual Startup Time',
          'Actual Total Time', 'Rows Removed by Filter', 'Rows Removed by Index Recheck',
          'Shared Hit Blocks', 'Shared Read Blocks', 'Temp Read Blocks',
          'Temp Written Blocks', 'Sort Method', 'Sort Space Used',
          'Sort Space Type', 'Heap Fetches')


def flatten(node, depth=0):
    row = {'depth': depth, **{key: node[key] for key in FIELDS if key in node}}
    return [row] + [item for child in node.get('Plans', [])
                    for item in flatten(child, depth + 1)]


result = {}
metrics = {}
for path in sorted((OUT / 'explain').glob('*.json')):
    plan = json.loads(path.read_text(encoding='utf-8'))
    nodes = flatten(plan['Plan'])
    result[path.stem] = dict(planning_ms=plan['Planning Time'],
        execution_ms=plan['Execution Time'], nodes=nodes)
    message_nodes = [n for n in nodes if n.get('Relation Name') == 'channels_message']
    forecast = max(message_nodes, key=lambda n: n.get('Actual Loops', 0))
    sorts = [n for n in nodes if n.get('Node Type') == 'Sort']
    metrics[path.stem] = dict(planning_ms=plan['Planning Time'],
        execution_ms=plan['Execution Time'], shared_hit=plan['Plan']['Shared Hit Blocks'],
        shared_read=plan['Plan']['Shared Read Blocks'],
        temp_read=plan['Plan']['Temp Read Blocks'],
        temp_written=plan['Plan']['Temp Written Blocks'],
        forecast_scan={key: forecast.get(key) for key in ('Node Type', 'Index Name',
            'Actual Loops', 'Actual Rows', 'Actual Total Time', 'Rows Removed by Filter',
            'Shared Hit Blocks', 'Shared Read Blocks', 'Heap Fetches')},
        max_sort_kb=max((s.get('Sort Space Used', 0) for s in sorts), default=0),
        sort_methods=sorted(set(s.get('Sort Method', '') for s in sorts)),
        window_loops=[n.get('Actual Loops') for n in nodes if n.get('Node Type') == 'WindowAgg'],
        bitmap_heap_nodes=[n for n in nodes if n.get('Node Type') == 'Bitmap Heap Scan'],
        bitmap_index_nodes=[n for n in nodes if n.get('Node Type') == 'Bitmap Index Scan'])
(OUT / 'plan-nodes.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
(OUT / 'plan-metrics.json').write_text(json.dumps(metrics, indent=2) + '\n', encoding='utf-8')
for name in ('messages-10', 'messages-2000', 'conversations-10',
             'conversations-100', 'conversations-500', 'conversations-1000', 'mixed-354'):
    if name not in result:
        continue
    print(name, metrics[name])
