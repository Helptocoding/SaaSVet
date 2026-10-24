"""Search in real Chromium; API fixtures, keyboard/touch and local latency."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

out = Path(__file__).resolve().parent
origin = 'http://127.0.0.1:4178'
receipt = dict(status='RUNNING', synthetic_api=True, requests=[], measurements=[], page_errors=[])

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height), has_touch=label == 'mobile')
            payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time())+3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', "+json.dumps(f'e30.{payload}.fixture')+');')
            rows = [dict(contact_public_id=contact, channel_account_public_id='main', owner_name=owner,
                contact_display_name=name, contact_phone=phone, conversation_public_id='session-'+contact,
                state='human_active', session_count=1, has_unanswered=True, handoff_priority='urgent')
                for contact, owner, name, phone in [('ana', 'Marta Luna', 'Ana Ramírez', '525512345678'),
                    ('cora', None, 'Cora Pérez', '525598765432')]]

            def handle(route):
                parsed = urlparse(route.request.url)
                if not parsed.path.startswith('/api/'):
                    route.continue_() if route.request.url.startswith(origin+'/') else route.abort()
                    return
                path, params = parsed.path.removeprefix('/api/'), parse_qs(parsed.query)
                if path == 'me/':
                    data = dict(id=1, username='search-staff', organization=1, role='ASSISTANT',
                        organization_name='Clínica sintética', organization_timezone='America/Tijuana',
                        must_change_password=False, permissions=['agentinbox.view', 'agentinbox.send'])
                elif path == 'inbox/threads/':
                    query = params.get('q', [''])[0].strip().casefold()
                    digits = re.sub(r'\D', '', query)
                    selected = rows if len(query) < 2 else [row for row in rows if any(
                        query in (row[field] or '').casefold() for field in ('owner_name', 'contact_display_name', 'contact_phone'))
                        or len(digits) >= 2 and digits in row['contact_phone']]
                    data = dict(mode='full', sync_cursor='synthetic-search', results=selected,
                        unread_total=7, has_more=False, next_offset=None)
                    receipt['requests'].append(dict(viewport=label, params=params, contacts=[row['contact_public_id'] for row in selected]))
                elif path.endswith('/messages/'):
                    data = dict(owner_name='Marta Luna', contact_public_id='ana', channel_account_public_id='main',
                        contact_verification='staff_verified', conversation=dict(public_id='session-ana', state='human_active',
                            session_window_open=True, session_window_expires_at=datetime.fromtimestamp(time.time()+86400, timezone.utc).isoformat()),
                        messages=[], next_before=None)
                elif path == 'inbox/metrics/':
                    data = None
                else:
                    data = dict(results=[])
                route.fulfill(status=200, content_type='application/json', body=json.dumps(data))

            context.route('**/*', handle)
            page = context.new_page()
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
            page.goto(origin+'/inbox')
            page.wait_for_load_state('networkidle')
            expect(page.get_by_role('button', name=re.compile('^Marta Luna'))).to_be_visible()
            page.get_by_role('button', name=re.compile('^Marta Luna')).click()
            draft = page.get_by_role('textbox', name='Respuesta al cliente')
            draft.fill('Conservar borrador de Marta')
            search = page.get_by_role('searchbox', name='Buscar conversaciones')
            if label == 'desktop':
                page.keyboard.press('Control+k')
                expect(search).to_be_focused()
                page.keyboard.press('Meta+k')
                expect(search).to_be_focused()
            else:
                search.tap()

            def query_response(response):
                return urlparse(response.url).path == '/api/inbox/threads/'

            started = time.monotonic()
            with page.expect_response(query_response):
                search.fill('Luna')
            expect(page.get_by_role('button', name=re.compile('^Cora'))).to_have_count(0)
            elapsed = (time.monotonic()-started)*1000
            assert elapsed < 1000, elapsed
            assert receipt['requests'][-1]['params'] == dict(q=['Luna'])
            for name in ('Urgentes', 'Míos'):
                button = page.get_by_role('button', name=name, exact=True)
                with page.expect_response(query_response):
                    button.press('Space') if label == 'desktop' else button.tap()
            assert receipt['requests'][-1]['params'] == dict(q=['Luna'], urgent=['1'], claimed=['me'])
            with page.expect_response(query_response):
                search.fill('(55) 1234')
            expect(page.get_by_role('button', name=re.compile('^Marta Luna'))).to_be_visible()
            expect(draft).to_have_value('Conservar borrador de Marta')
            search.scroll_into_view_if_needed()
            page.screenshot(path=str(out/f'search-{label}.png'), full_page=True)
            with page.expect_response(query_response):
                search.press('Escape') if label == 'desktop' else page.get_by_role('button', name='Limpiar búsqueda').tap()
            expect(search).to_have_value('')
            expect(search).to_be_focused()
            assert receipt['requests'][-1]['params'] == dict(urgent=['1'], claimed=['me'])
            with page.expect_response(query_response):
                search.fill('sin-resultados')
            expect(page.get_by_text('Sin coincidencias', exact=True)).to_be_visible()
            expect(page.get_by_text(re.compile('Prueba otro nombre o teléfono'))).to_be_visible()
            expect(draft).to_have_value('Conservar borrador de Marta')
            overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not overflow
            receipt['measurements'].append(dict(viewport=label, search_ms=elapsed,
                shortcuts=label == 'desktop', touch=label == 'mobile', draft_preserved=True,
                clear_preserves_segments=True, empty_suggestion=True, horizontal_overflow=overflow))
            context.close()
        assert not receipt['page_errors'], receipt['page_errors']
        receipt['status'] = 'PASS'
    finally:
        browser.close()
        (out/'browser.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False))
