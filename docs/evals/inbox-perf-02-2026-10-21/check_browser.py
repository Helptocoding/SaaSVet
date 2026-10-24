"""PERF-02: local frontend with synthetic API, 250 threads and owned Vite server."""
import base64
import json
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright, expect

OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[2]
ORIGIN = 'http://127.0.0.1:4178'
requests, errors, measurements = [], [], []
fail_more = False
threads = [
    {'contact_public_id': f'contact-{i}', 'channel_account_public_id': 'account-demo',
     'owner_name': f'Cliente {i:03}', 'contact_verification': 'unknown',
     'state': 'active', 'session_count': 1, 'last_message_preview': 'Consulta sintética de paginación',
     'last_activity_at': '2026-10-21T12:00:00Z', 'handoff_priority': 'urgent' if i < 5 else None}
    for i in range(250)
]


def intercept(route):
    global fail_more
    req = route.request
    parsed = urlparse(req.url)
    path = parsed.path
    if not path.startswith('/api/'):
        route.continue_() if req.url.startswith(ORIGIN + '/') else route.abort()
        return
    path = path.removeprefix('/api/')
    query = parse_qs(parsed.query)
    requests.append({'method': req.method, 'path': path, 'query': query})
    if path == 'me/':
        data = {'id': 1, 'username': 'demo', 'organization': 1, 'organization_name': 'Clínica de prueba',
                'organization_timezone': 'America/Mexico_City', 'role': 'ASSISTANT',
                'permissions': ['agentinbox.view', 'agentinbox.send'], 'must_change_password': False}
    elif path == 'inbox/threads/':
        offset = int(query.get('offset', ['0'])[0])
        if fail_more and offset == 100:
            fail_more = False
            route.fulfill(status=503, content_type='application/json',
                          body=json.dumps({'error': 'Conexión de prueba interrumpida'}))
            return
        source = threads
        if query.get('archived') == ['1']:
            source = threads + [dict(threads[-1], contact_public_id='archived', state=None,
                                     owner_name='Cliente archivado', conversation_public_id=None)]
        end = offset + 100
        data = {'results': source[offset:end], 'has_more': end < len(source),
                'next_offset': end if end < len(source) else None}
    elif path.endswith('/messages/'):
        contact = path.split('/')[2]
        name = next((t['owner_name'] for t in threads if t['contact_public_id'] == contact), 'Cliente archivado')
        data = {'owner_name': name, 'conversation': {'public_id': f'session-{contact}', 'state': 'active'},
                'messages': [], 'next_before': None}
    elif path == 'inbox/metrics/':
        data = None
    else:
        data = {'results': [], 'count': 0, 'unread_count': 0}
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data))


def port_open():
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(('127.0.0.1', 4178)) == 0


assert not port_open(), 'Port 4178 occupied; do not reuse or stop another server.'
with (OUTPUT / 'vite.log').open('w', encoding='utf-8') as log:
    server = subprocess.Popen(['rtk', 'proxy', 'pnpm', '--dir', 'frontend', 'exec', 'vite',
                               '--host', '127.0.0.1', '--port', '4178', '--strictPort'],
                              cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    result = {'status': 'RUNNING', 'synthetic_api': True}
    try:
        deadline = time.monotonic() + 60
        while not port_open():
            assert server.poll() is None, 'Vite exited; see vite.log'
            assert time.monotonic() < deadline, 'Vite startup timed out'
            time.sleep(0.2)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={'width': 1366, 'height': 768})
                context.route('**/*', intercept)
                payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time()) + 3600}).encode()).decode().rstrip('=')
                context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{payload}.local-fixture') + ');')
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
                    page.set_viewport_size({'width': width, 'height': height})
                    start = len(requests)
                    page.goto(ORIGIN + '/inbox')
                    page.wait_for_load_state('networkidle')
                    expect(page.get_by_text('100 conversaciones cargadas. Hay más conversaciones.', exact=True)).to_be_visible()
                    list_rows = page.locator('[class*="listScroll"]').get_by_role('button')
                    expect(list_rows).to_have_count(100)
                    expect(list_rows.nth(0)).to_contain_text('Urgente')
                    button = page.get_by_role('button', name='Cargar más', exact=True)
                    button.scroll_into_view_if_needed()
                    rect = button.bounding_box()
                    assert rect['height'] >= 44
                    assert button.evaluate('''el => {
                        const r = el.getBoundingClientRect();
                        return [0.1,0.5,0.9].every(x => [0.1,0.5,0.9].every(y =>
                            el.contains(document.elementFromPoint(r.left+x*r.width,r.top+y*r.height))));
                    }'''), 'Pagination button covered by another control'
                    page.screenshot(path=str(OUTPUT / f'pagination-{label}.png'))
                    if label == 'desktop':
                        button.focus()
                        page.keyboard.press('Enter')
                    else:
                        button.click()
                    expect(page.get_by_text('200 conversaciones cargadas. Hay más conversaciones.', exact=True)).to_be_visible()
                    expect(list_rows).to_have_count(200)
                    button.click()
                    expect(page.get_by_text('250 conversaciones cargadas.', exact=True)).to_be_visible()
                    expect(list_rows).to_have_count(250)
                    expect(button).to_have_count(0)
                    names = list_rows.locator('[class*="convName"]').all_text_contents()
                    assert names == [t['owner_name'] for t in threads], names[-5:]
                    list_rows.last.click()
                    expect(page.get_by_text('Cliente 249', exact=True).last).to_be_visible()
                    composer = page.get_by_placeholder('Escribe una respuesta…')
                    expect(composer).to_be_visible()
                    composer.fill('Borrador de prueba conservado')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(OUTPUT / f'all-loaded-{label}.png'))
                    active_gets = [r['query'] for r in requests[start:] if r['path'] == 'inbox/threads/']
                    assert active_gets[:3] == [{}, {'offset': ['100']}, {'offset': ['200']}], active_gets
                    page.get_by_role('button', name='Archivadas', exact=True).click()
                    expect(page.get_by_text('100 conversaciones cargadas. Hay más conversaciones.', exact=True)).to_be_visible()
                    assert [r for r in requests[start:] if r['path'] == 'inbox/threads/'][-1]['query'] == {'archived': ['1']}
                    page.get_by_role('button', name='Activas', exact=True).click()
                    expect(page.get_by_text('100 conversaciones cargadas. Hay más conversaciones.', exact=True)).to_be_visible()
                    fail_more = True
                    page.get_by_role('button', name='Cargar más', exact=True).click()
                    expect(page.get_by_role('alert')).to_contain_text('Conexión de prueba interrumpida')
                    expect(list_rows).to_have_count(100)
                    expect(composer).to_have_value('Borrador de prueba conservado')
                    page.get_by_role('button', name='Reintentar cargar más', exact=True).click()
                    expect(page.get_by_text('200 conversaciones cargadas. Hay más conversaciones.', exact=True)).to_be_visible()
                    expect(page.get_by_role('alert')).to_have_count(0)
                    measurements.append({'viewport': label, 'rows_reachable': 250, 'order_and_uniqueness': True,
                                         'filter_resets_offset': True, 'error_retains_rows_and_draft': True,
                                         'retry_same_offset': True, 'button_height': rect['height'],
                                         'unobscured_hit_area': True, 'horizontal_overflow': False})
                assert not errors, errors
                result['status'] = 'PASS'
            finally:
                browser.close()
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        subprocess.run(['rtk', 'proxy', 'taskkill', '/PID', str(server.pid), '/T', '/F'], capture_output=True)
        server.wait(timeout=10)
        result.update(measurements=measurements, requests=requests, page_errors=errors,
                      temporary_server_listening=port_open())
        (OUTPUT / 'browser.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
