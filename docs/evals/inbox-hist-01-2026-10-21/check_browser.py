"""HIST-01: real browser geometry with a synthetic 200-message transcript."""
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
requests, errors, measurements, held = [], [], [], []
fail_next = False
messages = [{'id': i, 'direction': 'in',
             'body': f'Mensaje {i:03}: texto sintético del historial disponible.',
             'created_at': '2026-10-21T12:00:00Z'} for i in range(1, 201)]


def respond(route, data, status=200):
    route.fulfill(status=status, content_type='application/json', body=json.dumps(data))


def intercept(route):
    global fail_next
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
        data = {'results': [{'contact_public_id': 'contact-ana', 'channel_account_public_id': 'account-demo',
                            'owner_name': 'Ana', 'state': 'active', 'session_count': 4,
                            'last_message_preview': 'Historial de prueba', 'contact_verification': 'unknown'}],
                'has_more': False, 'next_offset': None}
    elif path.endswith('/messages/'):
        before = int(query.get('before', ['201'])[0])
        rows = [m for m in messages if m['id'] < before][-50:]
        data = {'owner_name': 'Ana', 'conversation': {'public_id': 'session-ana', 'state': 'active'},
                'messages': rows, 'next_before': rows[0]['id'] if len(rows) == 50 else None}
        if 'before' in query:
            if fail_next:
                fail_next = False
                respond(route, {'error': 'Cursor de prueba rechazado.'}, 400)
            else:
                held.append((route, data, before))
            return
    elif path == 'inbox/metrics/':
        data = None
    else:
        data = {'results': [], 'count': 0, 'unread_count': 0}
    respond(route, data)


def wait_older(page):
    deadline = time.monotonic() + 5
    while not held:
        assert time.monotonic() < deadline, 'No previous-page request received'
        page.wait_for_timeout(10)
    assert len(held) == 1, 'Duplicate previous-page request'
    return held.pop(0)


def port_open():
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(('127.0.0.1', 4178)) == 0


assert not port_open(), 'Port occupied; never reuse or stop another server.'
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
            assert time.monotonic() < deadline, 'Vite startup timeout'
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
                    page.goto(ORIGIN + '/inbox')
                    page.wait_for_load_state('networkidle')
                    page.get_by_role('button', name='Ana', exact=False).click()
                    region = page.get_by_role('region', name='Mensajes de la conversación')
                    expect(region).to_be_visible()
                    bubbles = region.locator('[class*="bubble_"]')
                    expect(bubbles).to_have_count(50)
                    region.scroll_into_view_if_needed()
                    prepend_checks = []
                    for expected_count in (100, 150, 200, 200):
                        region.evaluate("el => { el.scrollTop=150; el.dispatchEvent(new Event('scroll',{bubbles:true})); }")
                        route, data, cursor = wait_older(page)
                        expect(page.get_by_role('status', name='Cargando mensajes anteriores')).to_have_count(1)
                        current_first = int(bubbles.first.inner_text().split(':')[0].split()[-1])
                        anchor = bubbles.filter(has_text=f'Mensaje {current_first+3:03}:')
                        before_y = anchor.bounding_box()['y']
                        before = region.evaluate('el => ({height:el.scrollHeight,top:el.scrollTop})')
                        respond(route, data)
                        expect(bubbles).to_have_count(expected_count)
                        expect(page.get_by_role('status', name='Cargando mensajes anteriores')).to_have_count(0)
                        after = region.evaluate('el => ({height:el.scrollHeight,top:el.scrollTop})')
                        delta = after['height'] - before['height']
                        assert abs(after['top'] - before['top'] - delta) <= 2, (before, after)
                        after_y = anchor.bounding_box()['y']
                        assert abs(after_y-before_y) <= 2, (before_y, after_y)
                        prepend_checks.append({'cursor': cursor, 'rows': expected_count,
                                               'height_delta': delta, 'top_delta': after['top']-before['top'],
                                               'anchor_delta': after_y-before_y})
                    region.evaluate('el => { el.scrollTop=0; }')
                    expect(page.get_by_text('Inicio del historial disponible', exact=True)).to_be_in_viewport(ratio=1)
                    expect(page.get_by_role('button', name='Cargar anteriores', exact=True)).to_have_count(0)
                    bodies = [text.splitlines()[0] for text in bubbles.all_text_contents()]
                    for i, text in enumerate(bodies, 1):
                        assert f'Mensaje {i:03}:' in text
                    assert len(bodies) == 200
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(OUTPUT / f'history-{label}.png'))
                    page.reload()
                    page.wait_for_load_state('networkidle')
                    page.get_by_role('button', name='Ana', exact=False).click()
                    expect(bubbles).to_have_count(50)
                    composer = page.get_by_role('textbox', name='Respuesta al cliente')
                    composer.fill('Borrador intacto durante scrollback')
                    fail_next = True
                    region.evaluate("el => { el.scrollTop=150; el.dispatchEvent(new Event('scroll',{bubbles:true})); }")
                    expect(page.get_by_role('alert')).to_contain_text('Cursor de prueba rechazado.')
                    expect(bubbles).to_have_count(50)
                    expect(composer).to_have_value('Borrador intacto durante scrollback')
                    retry = page.get_by_role('button', name='Reintentar anteriores', exact=True)
                    retry.scroll_into_view_if_needed()
                    assert retry.bounding_box()['height'] >= 44
                    page.screenshot(path=str(OUTPUT / f'history-error-{label}.png'))
                    retry.click()
                    route, data, cursor = wait_older(page)
                    assert cursor == 151
                    respond(route, data)
                    expect(bubbles).to_have_count(100)
                    expect(page.get_by_role('alert')).to_have_count(0)
                    expect(composer).to_have_value('Borrador intacto durante scrollback')
                    measurements.append({'viewport': label, 'messages_reachable': 200,
                                         'prepend_checks': prepend_checks, 'no_duplicates': True,
                                         'exhaustion_copy_correct': True, 'error_retry_preserves_draft': True,
                                         'horizontal_overflow': False})
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
