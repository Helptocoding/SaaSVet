"""Real Chromium, synthetic API: segment requests, keyboard/touch, draft and layout."""
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
            rows = [dict(contact_public_id=name.lower(), channel_account_public_id='main', owner_name=name,
                conversation_public_id='session-'+name.lower(), state='human_active', session_count=1,
                has_unanswered=inbound, handoff_priority='urgent' if urgent else None,
                claimed_by_name='Recepción' if mine else 'Colega')
                for name, inbound, urgent, mine in [('Ana', True, True, True), ('Beto', False, False, True), ('Cora', True, True, False)]]

            def handle(route):
                parsed = urlparse(route.request.url)
                if not parsed.path.startswith('/api/'):
                    route.continue_() if route.request.url.startswith(origin+'/') else route.abort()
                    return
                path, params = parsed.path.removeprefix('/api/'), parse_qs(parsed.query)
                if path == 'me/':
                    data = dict(id=1, username='filter-staff', organization=1, role='ASSISTANT',
                        organization_name='Clínica sintética', organization_timezone='America/Tijuana',
                        must_change_password=False, permissions=['agentinbox.view', 'agentinbox.send'])
                elif path == 'inbox/threads/':
                    selected = rows
                    if params.get('unanswered') == ['1']:
                        selected = [row for row in selected if row['has_unanswered']]
                    if params.get('unanswered') == ['0']:
                        selected = [row for row in selected if not row['has_unanswered']]
                    if params.get('urgent') == ['1']:
                        selected = [row for row in selected if row['handoff_priority'] == 'urgent']
                    if params.get('claimed') == ['me']:
                        selected = [row for row in selected if row['claimed_by_name'] == 'Recepción']
                    data = dict(mode='full', sync_cursor='synthetic-filter-cursor', results=selected,
                        has_more=False, next_offset=None, unread_total=7)
                    receipt['requests'].append(dict(viewport=label, params=params, contacts=[row['owner_name'] for row in selected]))
                elif path.endswith('/messages/'):
                    data = dict(owner_name='Ana', contact_public_id='ana', channel_account_public_id='main',
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
            expect(page.get_by_role('button', name=re.compile('^Ana'))).to_be_visible()
            page.get_by_role('button', name=re.compile('^Ana')).click()
            draft = page.get_by_role('textbox')
            draft.fill('Conservar este borrador')

            def segment(name):
                button = page.get_by_role('button', name=name, exact=True)
                with page.expect_response(lambda response: urlparse(response.url).path == '/api/inbox/threads/'):
                    if label == 'desktop':
                        button.focus()
                        button.press('Space')
                    else:
                        button.tap()
                expect(button).to_have_attribute('aria-pressed', 'true')

            segment('Sin atender')
            expect(page.get_by_role('button', name=re.compile('^Beto'))).to_have_count(0)
            segment('Urgentes')
            segment('Míos')
            expect(page.get_by_role('button', name=re.compile('^Cora'))).to_have_count(0)
            expect(page.get_by_role('button', name=re.compile('^Ana'))).to_be_visible()
            assert receipt['requests'][-1]['params'] == dict(unanswered=['1'], urgent=['1'], claimed=['me'])
            expect(draft).to_have_value('Conservar este borrador')
            segment('Archivadas')
            assert receipt['requests'][-1]['params'] == dict(archived=['1'], unanswered=['1'], urgent=['1'], claimed=['me'])
            page.get_by_role('group', name='Filtros de conversaciones').scroll_into_view_if_needed()
            page.screenshot(path=str(out/f'filters-{label}.png'), full_page=True)
            segment('Esperando cliente')
            expect(page.get_by_role('button', name='Sin atender', exact=True)).to_have_attribute('aria-pressed', 'false')
            expect(page.get_by_text('Sin coincidencias', exact=True)).to_be_visible()
            expect(draft).to_have_value('Conservar este borrador')
            sizes = page.get_by_role('group', name='Filtros de conversaciones').get_by_role('button').evaluate_all(
                '(buttons) => buttons.map(button => ({label:button.textContent.trim(),height:button.getBoundingClientRect().height}))')
            assert all(button['height'] >= 44 for button in sizes)
            overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not overflow
            receipt['measurements'].append(dict(viewport=label, keyboard=label == 'desktop', touch=label == 'mobile',
                draft_preserved=True, empty_segment=True, horizontal_overflow=overflow, chip_sizes=sizes))
            context.close()
        assert not receipt['page_errors'], receipt['page_errors']
        receipt['status'] = 'PASS'
    finally:
        browser.close()
        (out/'browser.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False))
