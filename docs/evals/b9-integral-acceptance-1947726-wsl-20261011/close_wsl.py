"""Close the stopped campaign, preserving evidence before retiring owned resources."""
import json
from pathlib import Path
import re
import shutil
import socket
import time
from prepare_wsl import EVIDENCE,REPO,OLD,WORK,TREE,PYTHON,PG,DATA,PORT,SHA,save,sha256,resources,integrity,run,command
from stage_wsl import host_resources

def main():
    stop=json.loads((EVIDENCE/'STOP.json').read_text())
    assert stop['state']=='PENDING' and stop['phase']=='controller'
    assert not list((EVIDENCE/'blocks').glob('*.command.json'))
    assert json.loads((EVIDENCE/'corrected-launcher-validation.json').read_text())['state']=='PASS'
    integrity('final-before-cleanup')
    save('controller-source-at-stop.json',{'path':'run_campaign.py',
        'sha256':sha256((EVIDENCE/'run_campaign.py').read_bytes()),
        'source_preserved':True,'corrected_entrypoint':'launch_campaign.py',
        'correction_validated_without_tests':True,'campaign_restarted':False})
    host=host_resources();guest=resources()
    save('preflight.json',{'state':'PENDING','candidate_sha':SHA,
        'cause':stop['cause'],'environment_preparation':'PASS','frontend_frozen_install':'PASS',
        'python_locked_dependencies':'PASS','postgresql_private_durable':'PASS',
        'directed_ids_resolved':87,'full_ids_discovered':3331,
        'evaluation_seal':'NOT_CREATED; bootstrap failed before sealing',
        'formal_runs':0,'application_tests_executed':0,'profile_variants_executed':0,
        'corrected_bootstrap_validation':'PASS_NO_TESTS_NO_RESTART',
        'resources_observed_at_closure':{'host':host,'guest':guest},
        'future_budget':{'single_suite_bytes':3*1024**3,'reserve_bytes':2*1024**3,
            'backing_disk_reserve_bytes':1024**3},'host_clock_configuration_changed':False})
    import psycopg
    from psycopg import sql
    with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname='postgres',autocommit=True) as conn:
        names=[row[0] for row in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate AND datname<>'postgres' ORDER BY datname")]
        assert names==['test_b9i_control'],names
        active=conn.execute("SELECT datname,pid,state,wait_event_type FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() ORDER BY pid").fetchall()
        prepared=conn.execute('SELECT gid,database,owner FROM pg_prepared_xacts').fetchall()
        locks=conn.execute("SELECT database,locktype,mode,granted,pid FROM pg_locks WHERE pid<>pg_backend_pid() ORDER BY pid,locktype,mode").fetchall()
        # Persist raw SQL observations before any drop/stop/remove.
        save('cleanup-sql-before.json',{'databases':names,'active_connections':active,
            'prepared_transactions':prepared,'locks_other_than_observer':locks})
        assert not active and not prepared
        for name in names:
            with psycopg.connect(host='127.0.0.1',port=PORT,user='b9e',dbname=name) as database:
                tables=database.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
                save('cleanup-tables-'+name+'.json',{'tables':tables})
                assert not tables
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        save('cleanup-sql-after-drop.json',{'databases':[r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname")]})
    command('pg-stop',[PG/'pg_ctl','-D',DATA,'-m','fast','-w','stop'])
    shutil.copy2(WORK/'postgresql.log',EVIDENCE/'postgresql-final.log')
    with socket.socket() as sock:
        closed=sock.connect_ex(('127.0.0.1',PORT))!=0
    assert closed and not (DATA/'postmaster.pid').exists()
    resolved=WORK.resolve()
    assert resolved==Path('/home/lap/b9i-wsl-1947726-20261011')
    assert json.loads((EVIDENCE/'assembly.json').read_text())['workspace']==str(resolved)
    shutil.rmtree(resolved)
    assert not resolved.exists()
    save('cleanup.json',{'state':'PASS','databases_dropped':names,'private_postgresql_stopped':True,
        'port':PORT,'port_closed':closed,'owned_workspace_removed':str(resolved),
        'foreign_processes_terminated':False,'windows_diagnostic_results_preserved':True,
        'old_windows_python_environment_preserved':True,'raw_sql_saved_before_cleanup':True})
    before=json.loads((EVIDENCE/'checkout-before.json').read_text())
    prior_mismatch=[name for name,h in before['prior_campaign_files'].items()
        if not (OLD/name).is_file() or sha256((OLD/name).read_bytes())!=h]
    unrelated={name:{'exists':(REPO/name).exists(),
        'sha256':sha256((REPO/name).read_bytes()) if (REPO/name).exists() else None}
        for name in before['unrelated']}
    save('preservation-of-prior-work.json',{'prior_campaign_files_checked':len(before['prior_campaign_files']),
        'prior_campaign_mismatches':prior_mismatch,'unrelated_current':unrelated,
        'unrelated_unchanged':unrelated==before['unrelated']})
    assert not prior_mismatch and unrelated==before['unrelated']
    required=['directed','django-check','migration-drift','migrate','billing-schema','b0','b3','b4','b5','full',
        'frontend-build','frontend-test','frontend-lint','frontend-smoke:urls','security','pip-audit','pnpm-audit',
        *['profile-'+s for s in ('base','blocked_llm','meta_slow','duplicate','saturation')]]
    save('block-status.json',{'campaign':'PREFLIGHT_BLOCKED','blocks':{name:'NOT_EXECUTED' for name in required}})
    decision=json.loads((OLD/'candidate-decision.json').read_text())
    decision.update(schema='b9i-wsl-candidate-decision-v1',cause=stop['cause'],
        cause_evidence=['STOP.json','controller-incident.json','controller-source-at-stop.json'],
        environment='Ubuntu-24.04 / WSL2',frontend_dependency_install='PASS',
        corrected_bootstrap_validation='PASS_NO_TESTS_NO_RESTART')
    decision['R01_R15']['R06']='PENDING_NOT_EXECUTED; frozen frontend install PASS, CI checks NOT_EXECUTED'
    decision['new_campaign']='Requires a new execution decision; corrected launcher is validated without restarting this stopped campaign'
    save('candidate-decision.json',decision)
    (EVIDENCE/'README.md').write_text('''# B9E — campaña WSL2 de 1947726, 11-10-2026

Decisión: **PENDING / PREFLIGHT_BLOCKED**. [Reporte](REPORT.md).

Se preparó el candidato exacto en Linux y pasó la instalación congelada del frontend.
El controlador falló antes del sellado al importar Django sin cargar SECRET_KEY.
El controlador usado se conserva intacto. `launch_campaign.py` corrige el arranque;
solo se ejecutó con `--validate-only`, sin tests ni reinicio de campaña.

La instancia privada, su base vacía y la carpeta temporal se retiraron. Se conserva
la campaña Windows previa byte por byte. Todos los bloques de aplicación y PROFILE
permanecen NOT_EXECUTED. El plan conserva una sola ejecución formal por bloque.

Los helpers de ejecución posteriores al preflight no llegaron a ejecutarse y no
se presentan como validados de extremo a extremo. Los logs originales se conservan
en el paquete, con inventario de hashes y recuperación comprobada. Sin commit/push.
''',encoding='utf-8')
    report=f'''# B9E — resultado de la campaña WSL2 de 1947726

Fecha: 2026-10-11. Decisión técnica integral: **PENDING**.
Candidato: `{SHA}`. Campaña: `b9-integral-acceptance-1947726-wsl-20261011`.

## Resultado y causa

La alternativa Linux permitió completar `pnpm install --frozen-lockfile` con Node
20.20.2 y pnpm 9.15.9, sin EPERM ni cambios al lockfile. Se verificaron los 3.332
blobs Git del candidato, se instalaron las dependencias bloqueadas con Python
3.13.2 y se preparó PostgreSQL 16.15 privado y durable en el puerto {PORT}.

El controlador preparado por el agente omitió cargar su entorno de prueba antes
de importar Django al validar el adapter. Falló con
`UndefinedValueError: SECRET_KEY not found. Declare it as envvar or define a default value.`
Es un error del lanzador evaluativo, no evidencia de un defecto del producto.
Ocurrió antes de crear el sello, completar el preflight o iniciar el bloque 1.
`STOP.json` se conserva; no se borró la parada ni se reintentó la campaña.

`run_campaign.py` conserva los bytes usados. La corrección está separada en
`launch_campaign.py`: carga el entorno aislado antes del import. Su validación
de configuración y resolución de cinco runners pasó sin ejecutar tests. El
camino completo de ejecución sigue sin validación de extremo a extremo.

## Preparación acreditada

- Exportación Git exacta con LF, SHA-1 de blobs y SHA-256 por archivo: 3.332/3.332.
- Discovery sin ejecución: 87 IDs dirigidos y 3.331 de suite completa; B0=17,
  B3=42, B4=68 y B5=37. Cero IDs ausentes, errores de import o duplicados.
- Python 3.13.2; instalación del lock y `pip check` satisfactorios.
- Node 20.20.2/pnpm 9.15.9; instalación congelada satisfactoria en Linux en 19,63 s.
- PostgreSQL 16.15: fsync, synchronous_commit y full_page_writes en `on`.
  Solo se creó `test_b9i_control`, sin tablas de aplicación ni fixtures clínicos.
- PROFILE: las tres fuentes base son idénticas a 0831046. Se conservaron los
  cinco escenarios, 30/300/20 s, los gates de SATURATION y las dos llamadas LLM READ.
- Gitleaks 8.18.4 y clon independiente con historial completo preparados;
  **scan no ejecutado**. Auditorías advisory preparadas, **no ejecutadas**.

La consulta inicial a `Packages.xz` devolvió 404. Durante la preparación se
comprobó el índice oficial y se usó el `Packages.gz` publicado, conservando el
incidente y su resolución. No se cambió una dependencia, lock, fixture o gate
del candidato para resolverlo. La adaptación de recibos está en archivos separados.

## Ejecuciones y recursos

**Cero tests de aplicación, cero bloques formales y cero variantes PROFILE.**
Build, Vitest, smoke, checks Django/migraciones/Billing, corpus, regresiones,
seguridad y auditorías están NOT_EXECUTED; instalar dependencias no los sustituye.
No se ejecutaron escenarios físicos D29/R1-04 ni llamadas reales de proveedores.

El presupuesto conserva 3 GiB por suite, 2 GiB de reserva física y 1 GiB de
reserva en el disco Windows que respalda WSL. El espacio virtual ext4 no se
confundió con el espacio real disponible del host. Al cierre se observaron
{host['physical_available']/1024**3:.2f} GiB libres de RAM en Windows y
{guest['disk_available']/1024**3:.2f} GiB libres en el disco de respaldo. El fallo
del bootstrap impidió llegar al gate formal de recursos. Estos datos no acreditan
un preflight completo ni autorizan iniciar suites sin verificar otra vez el margen.

## Conservación y cierre

Integridad final: 3.332 archivos intactos. Se guardaron las observaciones SQL
antes de eliminar la única base propia; no había conexiones ajenas ni transacciones
preparadas. PostgreSQL se detuvo, el puerto quedó cerrado y se retiró la carpeta
propia `{WORK}`. Se conservaron los entornos Windows reutilizados y procesos ajenos.

Los {len(before['prior_campaign_files'])} archivos comprobados de la campaña Windows previa permanecen byte por byte
sin cambios. También se conservaron las dos eliminaciones ajenas y `skills-lock.json`.
Se entrega inventario propio, paquete y recuperación comprobada; la selección Git
es explícita. No se crearon commits ni se hizo push, despliegue o activación.

R01–R15/I01–I14: ver `candidate-decision.json`; los requisitos pendientes no se
consideran cubiertos por la preparación. R1-04 mantiene PENDING con limitación
aceptada; activación conserva PENDING_ACTIVATION_REQUIREMENTS; E/P/UX siguen separados.

Una nueva ejecución requiere una decisión nueva conforme al límite del plan,
empleando el bootstrap corregido, un expediente nuevo y preflight íntegro. Esta
campaña detenida no se sobrescribe ni se presenta como una campaña aprobada.
'''
    (EVIDENCE/'REPORT.md').write_text(report,encoding='utf-8')
    acta=REPO/'docs/evals/b9-consolidation-2026-10-11/ACTA.md'
    marker='## Ejecución posterior en WSL2 — 1947726 — 11-10-2026'
    assert marker not in acta.read_text()
    with acta.open('a',encoding='utf-8') as stream:
        stream.write('\n\n'+marker+'\n\nLa nueva campaña autorizada para WSL2 terminó **PENDING / PREFLIGHT_BLOCKED**. '
            'La instalación congelada del frontend pasó en Linux. El bootstrap evaluativo omitió cargar SECRET_KEY '
            'antes del import de Django y falló antes del sellado y de todo test. La corrección separada se validó '
            'sin reiniciar. Cero bloques formales y cero PROFILE; recursos propios retirados y evidencia Windows '
            'preservada. No se atribuye un fallo al producto. Se mantienen R1-04 PENDING aceptado, '
            'PENDING_ACTIVATION_REQUIREMENTS y alcances E/P/UX separados. '
            '[Reporte y evidencia](../'+EVIDENCE.name+'/REPORT.md).\n')
    print('CLOSED_PENDING; private workspace removed; evidence written',flush=True)

if __name__=='__main__':
    main()
