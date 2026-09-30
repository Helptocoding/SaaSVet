"""Render the requested 60-field acta from completed, immutable receipts."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'docs/evals/w1-mono'


def main():
    result = json.loads((OUT/'acceptance-results.json').read_text(encoding='utf-8'))
    decision = json.loads((OUT/'diagnostic-decision.json').read_text(encoding='utf-8'))
    validation = json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
    diag = [(name, result['diagnostics'][name]) for name in ('diagnostic-base', 'diagnostic-blocked')]
    profile = sorted(OUT.glob('candidate-profile-*.json'))
    def count(run):
        return result['runs'][run]['tests']
    rows = [
        ('Estado del cambio', 'IMPLEMENTED / VERIFIED_SEMANTICS. ' + decision['status']),
        ('Baseline', '`'+result['baseline']+'`'),
        ('SHA enmienda', '`'+result['amendment_commit']+'`'),
        ('SHA runtime/tests', '`'+result['runtime_commit']+'`'),
        ('SHA docs/evidencia', 'Commit que contiene esta acta y los recibos; SHA exacto remitido en la entrega final.'),
        ('HEAD final', 'Commit docs/evidencia de la entrega final. No hay commits de despliegue.'),
        ('Enmienda B3/C4', '[v1 FROZEN](contrato-elegibilidad-preclaim-b3-c4-w1-v1.md), anterior al runtime.'),
        ('Nueva W1', 'Rolling 8 s / cap 25 s hasta primera elegibilidad; después no se reinicia silencio antes del claim.'),
        ('READY', 'Derivado de pendiente ordinario sin asignar y deadline vencido/NULL. Sin autoridad, lease, presupuesto, capacidad o contexto congelado.'),
        ('Fuente de verdad', 'Message.available_at en PostgreSQL, serializado por Conversation.'),
        ('Reloj', 'durable.db_now → statement_timestamp(), después de adquirir Conversation; receipt B7 conserva captura previa.'),
        ('available_at', 'Deadline común de ráfaga. Heredado ya vencido también para B. NULL legado = READY; puede normalizarse a DB now.'),
        ('Antes de READY', 'Cada inbound extiende min(now+8, oldest.created_at+25), limitado inferiormente a now cuando cap vencido.'),
        ('Después de READY', 'Deadline común vencido; A+B elegibles para el mismo claim. No puede retirarse READY.'),
        ('Ingest gana', 'A+B mismo work; orden persistido, lock real y claim inmediato verificados.'),
        ('Claim gana', 'W1 mantiene A; B entra W2 y has_new_input difiere publicación obsoleta.'),
        ('TurnContext', 'Inmutable desde claim; READY permite crecimiento previo y no congela contexto.'),
        ('Membership', 'Exactamente una asignación; no duplication/reassignment/append postclaim; triggers B3 intactos.'),
        ('Anchor', 'Último miembro por (created_at,id), sin cambio B3.'),
        ('Cursor', 'Coordenada del primer miembro; historial estrictamente anterior/exclusivo, sin cursor alternativo.'),
        ('Correcciones', 'Mañana → READY → viernes aparece en contexto completo y B6 termina con viernes.'),
        ('Fragmentos', 'Intención, mascota, fecha y corrección se ordenan por (created_at,id), incluidos empates por ID.'),
        ('Safety', 'Precedencia/fast path B5 preservados; señales no entran al UPDATE ordinario y no esperan capacidad ordinaria cuando B5 lo evita.'),
        ('Takeover', 'Epoch/autoridad invalidados; worker viejo no publica. Gates humanos preservados.'),
        ('B6', 'Binding/revisión/invalidation conservados; corrección preclaim completa y regresión de binding verde.'),
        ('B7', 'Consentimiento causal/digest/receipt conservados; confirmación READY + corrección no autoriza propuesta vieja.'),
        ('B8', 'Corrección postclaim bloquea efecto sin alterar historia de autorización; ningún parámetro nuevo ejecuta bajo digest antiguo.'),
        ('B9B', '30 calls/work, 18000 output tokens reservados/work, máximo 600/call, durable admission, no refund; código intacto.'),
        ('B9C', 'N=1 PROCESSING con lease/epoch válidos por org; Organization → Conversation y SKIP LOCKED conservados. READY no reserva slot.'),
        ('Selector E4', 'KEEP, worker.py idéntico al baseline; E4-SEL-01..07 y E4-PROC-01..02 verdes.'),
        ('Tests W1', 'W1-MONO-01..10 verdes; 33 IDs nuevos únicos contando controles, causales y procesos.'),
        ('8−ε / 8 / 8+ε', 'Reloj controlado, sin sleeps para fronteras. Además reloj app stale bajo espera real de mutex PG.'),
        ('PostgreSQL multiprocess', 'RACE-01..10 y FI-01..10 verdes, procesos OS/conexiones PG independientes.'),
        ('PIDs/locks', f"{len(result['process_pids'])} PIDs OS y {len(result['backend_pids'])} backends en journals MONO; pg_locks y pg_blocking_pids observados, sin mutex Python como autoridad."),
        ('FI-01..10', 'Rollback de ingest antes/después de persist/deadlines, claim crash, lost commit response, death/expiry/reclaim/retry, takeover y safety. IDs combinados trazados en corpus.json.'),
        ('Reextensión observada', 'ELIMINADA: fronteras causales y 7 B del diagnóstico bloqueado comparten deadline vencido/work con A, sin segundo silencio.'),
        ('persisted→eligible', 'Tabla por organización abajo; elegibilidad individual = max(created_at, available_at), NULL = created_at.'),
        ('eligible→claim', 'Tabla por organización abajo, sin nuevo threshold; residual evaluado contra el gate original 10 s.'),
        ('persisted→claim', 'Tabla por organización abajo; recibos conservan p95, máximos, denominadores y faltantes originales.'),
        ('Calls/work', 'Distribución/calls por work y diálogo por org en recibos; READ ordinaria conserva dos llamadas, safety cero. No ahorro supuesto.'),
        ('Deferrals', 'Conteos por organización abajo; continuación postclaim permanece vigente.'),
        ('PROFILE-BETA-1 ejecutado', 'Sí, un rerun temporal de candidato; no B9E integral.' if profile else 'No. ' + decision['reason']),
        ('Resultado exacto PROFILE', 'Recibos candidate-profile-*; no cierre B9E ni reescritura del FAIL histórico.' if profile else 'No hay intento de acceptance ni resultado nuevo de PROFILE; diagnóstico solo.'),
        ('Regresión', '641 IDs históricos del alcance proporcional más 84 B9D/E4; recuperación exacta de 107 pendientes en 3 DBs aisladas, sin alterar assertions.'),
        ('Total IDs', str(result['accepted_unique_total'])+' únicos aceptados: 33 nuevos + 725 de regresión. Inventarios/journals y hashes por fuente conservados.'),
        ('Skips/xfail/pending', '0 / 0 / 0 en el conjunto requerido completado. Intentos de launcher/setup/harness excluidos explícitamente.'),
        ('Checks', 'Django check, makemigrations --check --dry-run, migrate --check y git diff --check verdes.'),
        ('Migraciones', 'Ninguna. Message.available_at y mutex actual bastan.'),
        ('Compatibilidad rollout', 'Workers baseline/nuevo compatibles con deadlines; writers antiguos pueden retirar READY. Garantía exige corte coordinado de todos los writers.'),
        ('Rollback', 'Revertir runtime, conservando Messages/TurnWork/membership/AuthorizationEvidence/effects y presupuesto. No reconstruye silencio histórico de ráfagas promovidas.'),
        ('Observabilidad/privacy', 'Diagnóstico local test-only con tipos de evento cerrados, scalars técnicos; no prompt/response/teléfono/owner/pet/clinical text nuevos para READY.'),
        ('Riesgos residuales', decision['reason']+' Sin fairness fuerte ni extrapolación de proveedor fake a producción.'),
        ('B9', 'IN_PROGRESS; B9A/B9B/B9C/B9D conservan COMPLETED.'),
        ('B9E', 'FAIL; no reapertura formal dentro del encargo.'),
        ('PROFILE histórico', 'FAIL intacto. Ningún recibo histórico sobrescrito.'),
        ('Gates productivos', 'B0 CLOSED; B7B=False; execution flags={}; release grants vacío; PENDING_ACTIVATION_REQUIREMENTS.'),
        ('Clínicas activadas', '0 reales activadas por este encargo; fixtures aislados retirados al cerrar.'),
        ('Deploy', 'No realizado; sin cambios de env productivo/secrets.'),
        ('Commits', 'Enmienda → runtime/tests → esta acta/evidencia, con SHAs exactos en entrega. Cambios preexistentes excluidos.'),
        ('Próximo paso', decision['next_step']+' STOP: no scheduler nuevo, wake-up, E5, P-A/P-B, activación o deploy.'),
    ]
    assert len(rows) == 60
    lines = ['# B3/C4/W1 v1 — acta de implementación y diagnóstico', '',
        '2026-09-30. '+decision['status']+'. B9 IN_PROGRESS; B9E FAIL; producción cerrada.', '',
        '| # | Campo | Resultado |', '|---|---|---|']
    lines += [f'| {i} | {label} | {value} |' for i, (label, value) in enumerate(rows, 1)]
    lines += ['', '## Medición temporal — DIAGNOSTIC_ONLY', '',
        'Mismas condiciones PROFILE-BETA-1 v1: dos planners/sender, N=1, batch/poll 1, tasas 10/10/1 s, '
        'dos LLM de 0.5 s, READ 0.1 s, Meta 0.2 s, warmup 30 s, medición 300 s, drain 20 s. '
        'Cada escenario usa una DB vacía distinta. Instrumentación E4 local en memoria; no altera el selector. '
        'p95 método higher. Org 0/1 sanas, 2 ruidosa. Deltas ordinarios excluyen safety; '
        'el gate sano original incluye su denominador original completo (60, incluyendo safety). '
        'Works/calls/diálogos/deferrals usan TurnWork.context_at dentro de la ventana; '
        'los tiempos usan Message.created_at dentro de la ventana. Son cohortes distintas: '
        'no se debe inferir una correspondencia uno a uno entre sus conteos. '
        'Missing de org ruidosa representa backlog persistido sin claim al observar, no pérdida de inbound; '
        'no se oculta ni se atribuye éxito a ese backlog. Los recibos guardan p50/máximos y distribuciones completas. '
        'Comparar estos dos escenarios no demuestra ahorro de calls ni mejoría causal por sí solo.', '',
        '| Escenario | Org | n ordinarios | persisted→eligible p95 | eligible→claim p95 | persisted→claim p95 | Missing | Joined READY | Works | Calls | Calls/work | Calls/diálogo | Deferrals |',
        '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, receipt in diag:
        for org in receipt['monotonic_diagnostic']['organizations']:
            def v(value): return '—' if value is None else str(round(value, 6))
            lines.append('| '+ ' | '.join(map(str, [name.removeprefix('diagnostic-'), org['organization'],
                org['persisted_to_eligible']['count'], v(org['persisted_to_eligible']['p95_seconds']),
                v(org['eligible_to_claim']['p95_seconds']), v(org['persisted_to_claim']['p95_seconds']),
                org['missing_claim'], org['joined_ready_inbounds'], org['works'], org['calls'],
                v(org['calls_per_work']), v(org['calls_per_dialogue']), org['deferrals']]))+' |')
    for name, receipt in diag:
        lines += ['', f"Gate original {name}: {json.dumps(receipt['healthy_claim'], ensure_ascii=False)}; gates {json.dumps(receipt['gates'])}.", '']
    lines += ['## Evidencia y límites', '',
        '[Recibo consolidado](evals/w1-mono/acceptance-results.json), '
        '[corpus/traceability](evals/w1-mono/corpus.json), '
        '[decisión posterior al diagnóstico](evals/w1-mono/diagnostic-decision.json), '
        '[fuentes protegidas](evals/w1-mono/validation.json), '
        '[fuentes de dominio sin cambios](evals/w1-mono/domain-source-validation.json), '
        '[limpieza local](evals/w1-mono/cleanup.json), '
        '[causalidad bajo condiciones de perfil](evals/w1-mono/ready-profile-causality.json).', '',
        'La regresión original se interrumpió para repartir su cola: 534 IDs ya terminados, '
        '107 recuperados exactamente, incluido el caso en curso repetido; fuentes verificadas contra '
        'los hashes de cada recibo para el árbol agent; los tests de dominio externos a ese árbol '
        'se verifican sin cambios frente a baseline y commit runtime, con SHA normalizado LF. '
        'No se atribuye PASS al run original incompleto. El conjunto final '
        'sí completa todos los 641 IDs. Los incidentes anteriores de reloj mock/discovery/launcher/clone '
        'están excluidos; no fueron intentos PROFILE ni cambios de assertions para acomodar runtime.', '',
        'PIDs OS MONO: `'+ ', '.join(map(str, result['process_pids']))+'`.', '',
        'Backends PG MONO: `'+ ', '.join(map(str, result['backend_pids']))+'`.', '',
        'Los 7 B medidos bajo LLM bloqueado comparten con A el deadline ya vencido y el work; '
        'la lectura final de PostgreSQL verifica scope, members, anchor y cursor sin leer payload. '
        'La causalidad directa registrada incluye stale app time, deadline vencido, fresh DB time '
        'posterior al mutex, dos miembros y segundo silencio=False. Los perfiles son fixtures fake '
        'locales, sin IO real Meta/modelo; aceptación simulated sent no prueba delivered/read.', '',
        'Reproducción: `rtk proxy python -X utf8 docs/evals/w1-mono-run.py --suite targeted '
        '--receipt NUEVO --database test_b8b_w1_mono_targeted --labels targeted-labels.json`. '
        'Requiere clonar bases propias de plantilla migrada vacía en la instancia local descrita; '
        'el runner limita nombres/host y no puede usarse como deploy.', '']
    (ROOT/'docs/implementacion-elegibilidad-monotonica-preclaim-2026-09-30.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
