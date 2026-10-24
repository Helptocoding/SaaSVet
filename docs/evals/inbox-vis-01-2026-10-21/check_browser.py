"""VIS-01: real local frontend, synthetic API only; owns/cleans its Vite tree."""
import base64
import json
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[2]
ORIGIN = 'http://127.0.0.1:4178'
messages = [
    {'id': 1, 'direction': 'in', 'body': 'Hola, tengo una duda.', 'created_at': '2026-10-20T18:00:00Z'},
    {'id': 2, 'direction': 'in', 'body': '¿A qué hora cierran?', 'created_at': '2026-10-20T18:01:00Z'},
    {'id': 3, 'direction': 'out', 'author_type': 'human_staff', 'human_author_name': 'Recepción',
     'human_author_public_id': 'staff-a', 'body': 'Hola Ana, hoy cerramos a las seis.', 'status': 'sent', 'created_at': '2026-10-20T18:02:00Z'},
    {'id': 4, 'direction': 'out', 'author_type': 'human_staff', 'human_author_name': 'Recepción',
     'human_author_public_id': 'staff-a', 'body': 'Podemos ayudarte a reservar una cita.', 'status': 'read', 'created_at': '2026-10-20T18:03:00Z'},
    {'id': 5, 'direction': 'out', 'author_type': 'human_staff', 'human_author_name': 'Recepción',
     'human_author_public_id': 'staff-b', 'body': 'Soy del siguiente turno. Quedo al pendiente.', 'status': 'pending', 'created_at': '2026-10-20T18:04:00Z'},
    {'id': 6, 'direction': 'out', 'author_type': 'agent', 'body': 'Mensaje del asistente de prueba.', 'status': 'uncertain', 'created_at': '2026-10-20T18:05:00Z'},
    {'id': 7, 'direction': 'out', 'author_type': 'system', 'body': 'Aviso de prueba del sistema.', 'status': 'failed', 'created_at': '2026-10-20T18:06:00Z'},
]
requests, errors, measurements = [], [], []
phase = 'initial'


def intercept(route):
    req = route.request
    path = urlparse(req.url).path
    if not path.startswith('/api/'):
        route.continue_() if req.url.startswith(ORIGIN + '/') else route.abort()
        return
    path = path.removeprefix('/api/')
    requests.append({'method': req.method, 'path': path, 'phase': phase, 'at': time.monotonic()})
    if path == 'me/':
        data = {'id': 1, 'username': 'demo', 'organization': 1, 'organization_name': 'Clínica de prueba',
                'organization_timezone': 'America/Mexico_City', 'role': 'ASSISTANT',
                'permissions': ['agentinbox.view', 'agentinbox.send'], 'must_change_password': False}
    elif path == 'inbox/threads/':
        data = [{'contact_public_id': 'contact-ana', 'channel_account_public_id': 'account-demo', 'owner_name': 'Ana',
                 'state': 'active', 'session_count': 1, 'last_message_preview': 'Consulta de prueba', 'last_activity_at': '2026-10-20T18:06:00Z'}]
    elif path == 'inbox/threads/contact-ana/account-demo/messages/':
        data = {'owner_name': 'Ana', 'conversation': {'public_id': 'session-ana', 'state': 'active'},
                'messages': messages, 'next_before': None}
    elif path == 'inbox/metrics/':
        data = None
    else:
        data = {'results': [], 'count': 0, 'unread_count': 0}
    route.fulfill(status=200, content_type='application/json', body=json.dumps(data))


def port_open():
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(('127.0.0.1', 4178)) == 0


assert not port_open(), 'Port 4178 already occupied; do not use or terminate another server.'
with (OUTPUT / 'vite.log').open('w', encoding='utf-8') as log:
    server = subprocess.Popen(['rtk', 'proxy', 'pnpm', '--dir', 'frontend', 'exec', 'vite',
                               '--host', '127.0.0.1', '--port', '4178', '--strictPort'],
                              cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    result = {'status': 'RUNNING', 'synthetic_api': True, 'visibility': 'controlled document.hidden + visibilitychange; real browser timers/network'}
    try:
        deadline = time.monotonic() + 60
        while not port_open():
            assert server.poll() is None, 'Vite exited before listening; see vite.log'
            assert time.monotonic() < deadline, 'Vite startup timed out'
            time.sleep(0.2)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={'width': 1366, 'height': 768})
                context.route('**/*', intercept)
                payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time()) + 3600}).encode()).decode().rstrip('=')
                context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{payload}.local-fixture') + ');')
                context.add_init_script("""
                    let hidden = false;
                    Object.defineProperty(document, 'hidden', {get: () => hidden});
                    window.setTestHidden = value => {
                        hidden = value;
                        document.dispatchEvent(new Event('visibilitychange'));
                    };
                """)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(ORIGIN + '/inbox')
                page.wait_for_load_state('networkidle')
                page.get_by_role('button', name='Ana', exact=False).click()
                expect(page.get_by_role('group', name='2 mensajes de Ana', exact=True)).to_be_visible()
                phase = 'hidden'
                page.evaluate('window.setTestHidden(true)')
                # Real elapsed time exceeds both configured intervals (10/20s).
                hidden_started = time.monotonic()
                page.wait_for_timeout(21_000)
                hidden_polls = [r for r in requests if r['phase'] == 'hidden' and r['path'].startswith('inbox/threads/')]
                assert hidden_polls == [], hidden_polls
                measurements.append({'phase': phase, 'elapsed_s': time.monotonic() - hidden_started, 'poll_requests': 0})
                phase = 'resume'
                resumed = time.monotonic()
                with page.expect_response(lambda response: '/api/inbox/threads/contact-ana/' in response.url):
                    page.evaluate('window.setTestHidden(false)')
                page.wait_for_timeout(300)
                resumed_polls = [r for r in requests if r['phase'] == 'resume' and r['path'].startswith('inbox/threads/')]
                assert len(resumed_polls) == 2, resumed_polls
                assert {r['path'] for r in resumed_polls} == {'inbox/threads/', 'inbox/threads/contact-ana/account-demo/messages/'}
                assert all(r['at'] - resumed < 2 for r in resumed_polls), resumed_polls
                measurements.append({'phase': phase, 'poll_requests': 2, 'max_delay_s': max(r['at'] - resumed for r in resumed_polls)})
                phase = 'visible_interval'
                with page.expect_response(lambda response: '/api/inbox/threads/contact-ana/' in response.url, timeout=12_000):
                    page.wait_for_timeout(10_100)
                visible_polls = [r for r in requests if r['phase'] == phase and r['path'].startswith('inbox/threads/')]
                assert len(visible_polls) == 1, visible_polls
                measurements.append({'phase': phase, 'thread_poll_requests': 1})
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
