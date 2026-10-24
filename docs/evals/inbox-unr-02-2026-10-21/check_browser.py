"""Chromium UI with synthetic per-user API; no live business data or WhatsApp."""
import base64
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

OUT = Path(__file__).resolve().parent
ORIGIN = 'http://127.0.0.1:4178'
markers = {'a': 160, 'b': 180}
requests, measurements, errors, held = [], [], [], []
fail_next, hold_next = set(), set()
messages = [dict(id=i, direction='in', status='processed', author_type='client',
                 body=f'Mensaje {i:03}: historial sintético para validar lectura estable.',
                 created_at='2026-10-21T12:00:00Z') for i in range(1, 201)]


def respond(route, data, status=200):
    route.fulfill(status=status, content_type='application/json', body=json.dumps(data))


def intercept(actor, route):
    req = route.request
    parsed = urlparse(req.url)
    if not parsed.path.startswith('/api/'):
        route.continue_() if req.url.startswith(ORIGIN + '/') else route.abort()
        return
    path = parsed.path.removeprefix('/api/')
    query = parse_qs(parsed.query)
    requests.append({'actor': actor, 'method': req.method, 'path': path,
                     'body': req.post_data_json if req.method == 'POST' else None})
    count = 200 - max(markers[actor], 160)
    if path == 'me/':
        data = dict(id=1 if actor == 'a' else 2, username='staff-' + actor, organization=1,
                    organization_name='Clínica sintética', organization_timezone='America/Mexico_City',
                    role='VET', permissions=['agentinbox.view'], must_change_password=False)
    elif path == 'inbox/threads/':
        data = {'results': [dict(contact_public_id='contact-ana', channel_account_public_id='main',
                 owner_name='Ana', state='active', session_count=2, unread_count=count,
                 last_message_preview='Historial de prueba')], 'unread_total': count + 20,
                'has_more': True, 'next_offset': 100}
    elif path.endswith('/messages/'):
        before = int(query.get('before', ['201'])[0])
        page = [m for m in messages if m['id'] < before][-50:]
        current_page = [m for m in page if m['id'] > 160]
        unread_page = [m for m in current_page if m['id'] > markers[actor]]
        data = dict(owner_name='Ana', conversation={'public_id': 'current-ana', 'state': 'active'},
                    messages=page, next_before=page[0]['id'] if len(page) == 50 else None,
                    last_read_message_id=markers[actor], unread_count=count,
                    first_unread_message_id=unread_page[0]['id'] if unread_page else None,
                    latest_visible_inbound_id=current_page[-1]['id'] if current_page else None)
    elif path.endswith('/read/') and req.method == 'POST':
        assert req.post_data_json == {'last_read_message_id': 200}
        if actor in fail_next:
            fail_next.remove(actor)
            respond(route, {'code': 'server_error', 'message': 'Fallo sintético.'}, 503)
            return
        if actor in hold_next:
            hold_next.remove(actor)
            held.append((actor, route))
            return
        markers[actor] = 200
        data = dict(last_read_message_id=200, unread_count=0, unread_total=20)
    elif path == 'inbox/metrics/':
        data = None
    else:
        data = {'results': []}
    respond(route, data)


def attention(page, focus=True, visible=True):
    page.evaluate('''([focus,visible])=>{
        window.__readFocus=focus; window.__readVisible=visible;
        document.dispatchEvent(new Event('visibilitychange'));
        window.dispatchEvent(new Event(focus?'focus':'blur'));
    }''', [focus, visible])


def interceptor(actor):
    # Playwright supplies a second Request argument when the callable accepts it.
    def handle(route):
        intercept(actor, route)
    return handle


def post_count(actor):
    return sum(r['actor'] == actor and r['method'] == 'POST' for r in requests)


def wait_held(page):
    deadline = time.monotonic() + 6
    while not held:
        assert time.monotonic() < deadline, 'Read POST did not arrive'
        page.wait_for_timeout(20)
    return held.pop(0)


result = {'status': 'RUNNING', 'synthetic_api': True, 'controlled_focus_visibility': True}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            markers.update(a=160, b=180)
            contexts = []
            pages = {}
            for actor in ('a', 'b'):
                context = browser.new_context(viewport={'width': width, 'height': height})
                contexts.append(context)
                payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time()) + 3600}).encode()).decode().rstrip('=')
                context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{payload}.fixture') + ');')
                context.add_init_script('''window.__readFocus=false; window.__readVisible=true;
                    document.hasFocus=()=>window.__readFocus;
                    Object.defineProperty(document,'visibilityState',{get:()=>window.__readVisible?'visible':'hidden'});
                    Object.defineProperty(document,'hidden',{get:()=>!window.__readVisible});''')
                context.route('**/*', interceptor(actor))
                page = context.new_page()
                pages[actor] = page
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(ORIGIN + '/inbox')
                page.wait_for_load_state('networkidle')
                page.get_by_role('button', name='Ana', exact=False).click()
                expect(page.get_by_role('separator', name='Mensajes nuevos')).to_be_attached()
            page, other = pages['a'], pages['b']
            region = page.get_by_role('region', name='Mensajes de la conversación')
            expect(page.get_by_label('40 mensajes sin leer', exact=True)).to_be_visible()
            expect(page.get_by_label('60 mensajes sin leer en conversaciones activas')).to_be_visible()
            expect(page.get_by_role('button', name='Enviar', exact=True)).to_have_count(0)
            start_posts = post_count('a')
            attention(page)
            page.wait_for_timeout(650)
            attention(page, focus=False)
            page.wait_for_timeout(1700)
            assert post_count('a') == start_posts, 'Blur failed to cancel debounce'
            attention(page, focus=True, visible=False)
            page.wait_for_timeout(1700)
            assert post_count('a') == start_posts, 'Hidden tab marked read'
            page.get_by_role('separator', name='Mensajes nuevos').scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / f'unread-{label}.png'), full_page=True)
            fail_next.add('a')
            attention(page)
            deadline = time.monotonic() + 5
            while post_count('a') == start_posts:
                assert time.monotonic() < deadline
                page.wait_for_timeout(20)
            expect(page.get_by_role('separator', name='Mensajes nuevos')).to_be_attached()
            expect(page.locator('[data-sonner-toast]')).to_have_count(0)
            assert markers['a'] == 160
            hold_next.add('a')
            attention(page, focus=False, visible=False)
            attention(page)  # VIS-01 resumes the next poll immediately.
            actor, route = wait_held(page)
            region.scroll_into_view_if_needed()
            region.evaluate('el=>{el.scrollTop=el.scrollHeight-el.clientHeight-120;}')
            anchor = region.evaluate('''el=>{
                const top=el.getBoundingClientRect().top;
                const node=[...el.querySelectorAll('[data-message-id]')].find(n=>n.getBoundingClientRect().bottom>top);
                return {id:node.dataset.messageId,y:node.getBoundingClientRect().top};
            }''')
            markers[actor] = 200
            respond(route, dict(last_read_message_id=200, unread_count=0, unread_total=20))
            expect(page.get_by_role('separator', name='Mensajes nuevos')).to_have_count(0)
            after_y = region.locator(f'[data-message-id="{anchor["id"]}"]').bounding_box()['y']
            assert abs(after_y - anchor['y']) < 1, (label, anchor, after_y)
            expect(page.get_by_label('40 mensajes sin leer', exact=True)).to_have_count(0)
            expect(page.get_by_label('20 mensajes sin leer en conversaciones activas')).to_be_visible()
            expect(other.get_by_label('20 mensajes sin leer', exact=True)).to_be_visible()
            expect(other.get_by_role('separator', name='Mensajes nuevos')).to_be_attached()
            assert markers['b'] == 180, 'Another employee was marked read'
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(OUT / f'read-{label}.png'), full_page=True)
            measurements.append(dict(viewport=label, independent_staff=True, view_only_read=True,
                blur_cancels=True, hidden_does_not_mark=True, silent_failure_retry=True,
                divider_removed_after_ack=True, anchor_delta=after_y-anchor['y'], total_spans_pages=True,
                horizontal_overflow=False))
            for context in contexts:
                context.close()
        assert not errors, errors
        result['status'] = 'PASS'
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        browser.close()
        result.update(measurements=measurements, requests=requests, page_errors=errors)
        (OUT / 'browser.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
