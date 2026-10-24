"""Real Chromium: quote rendering, local/remote jump, geometry and touch."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, unquote, urlparse

from playwright.sync_api import expect, sync_playwright

out = Path(__file__).resolve().parent
origin = 'http://127.0.0.1:4178'
receipt = dict(status='RUNNING', synthetic_api=True, requests=[], measurements=[], page_errors=[])
assert not (out / 'browser.json').exists(), 'Never overwrite evidence'


def message(identifier):
    return dict(id=identifier, body=f'Mensaje conservado {identifier} de Luna.', direction='in',
        author_type='client', payload_type='text', status='processed',
        created_at=datetime.fromtimestamp(1784635200 + identifier * 60, timezone.utc).isoformat())


def quote(identifier, **extra):
    return dict(dict(id=identifier, author_type='client', payload_type='text', status='processed',
                     excerpt=f'Mensaje conservado {identifier} de Luna.'), **extra)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height), has_touch=label == 'mobile')
            payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time()) + 3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{payload}.fixture') + ');')
            rows = [message(identifier) for identifier in range(1, 201)]
            rows[29].update(direction='out', author_type='agent', payload_type='image', body='', status='discarded')
            rows[179].update(direction='out', author_type='human_staff', human_author_name='Lucía', client_message_id='confirmed-client-key')
            rows[197].update(direction='out', author_type='human_staff', human_author_name='Lucía', reply_to=quote(180,
                author_type='human_staff', human_author_name='Lucía'))
            rows[198].update(reply_to=quote(30, author_type='agent', payload_type='image', excerpt='', status='discarded'))
            rows[199].update(direction='out', author_type='human_staff', human_author_name='Lucía', reply_to=quote(10))
            operational = [row for row in rows if row['id'] != 30]

            def packet(name, messages, **extra):
                return dict(dict(owner_name=name, contact_public_id=name, channel_account_public_id='main',
                    conversation=dict(public_id='session-' + name, state='human_active', session_window_open=True,
                        session_window_expires_at=datetime.fromtimestamp(time.time() + 86400, timezone.utc).isoformat()),
                    messages=messages, next_before=151), **extra)

            def handle(route):
                parsed = urlparse(route.request.url)
                if not parsed.path.startswith('/api/'):
                    route.continue_() if route.request.url.startswith(origin + '/') else route.abort()
                    return
                path, params = unquote(parsed.path.removeprefix('/api/')), parse_qs(parsed.query)
                if path == 'me/':
                    data = dict(id=1, username='jump-staff', organization=1, role='ASSISTANT',
                        organization_name='Clínica sintética', organization_timezone='America/Tijuana',
                        must_change_password=False, permissions=['agentinbox.view', 'agentinbox.send'])
                elif path == 'inbox/threads/':
                    data = dict(results=[dict(contact_public_id=name, channel_account_public_id='main', owner_name=name,
                        conversation_public_id='session-' + name, state='human_active', session_count=1)
                        for name in ['Ana sintética', 'Beto sintético']], has_more=False, unread_total=0)
                elif path.endswith('/messages/'):
                    name = 'Beto sintético' if 'Beto' in path else 'Ana sintética'
                    receipt['requests'].append(dict(viewport=label, params=params, contact=name))
                    if 'around' in params:
                        identifier = int(params['around'][0])
                        selected = [row for row in operational if row['id'] < identifier][-25:]
                        selected += [dict(rows[identifier - 1], is_hidden=identifier == 30)]
                        selected += [row for row in operational if row['id'] > identifier][:24]
                        data = packet(name, selected, conversation=None, next_before=selected[0]['id'],
                            sync_floor='floor-' + str(selected[0]['id']), has_older=selected[0]['id'] > 1, has_newer=True)
                    elif 'before' in params:
                        selected = [row for row in operational if row['id'] < int(params['before'][0])][-50:]
                        data = packet(name, selected, next_before=selected[0]['id'], sync_floor='floor-' + str(selected[0]['id']))
                    elif 'since' in params:
                        floor = int(params.get('floor', ['floor-151'])[0].removeprefix('floor-'))
                        selected = [row for row in operational if row['id'] >= floor]
                        data = dict(mode='delta', sync_cursor='fixture-current', messages=selected, removals=[],
                            metadata={}, range_ids=[row['id'] for row in selected])
                    else:
                        data = packet(name, operational[-50:], mode='full', sync_cursor='fixture-initial', sync_floor='floor-151')
                elif path == 'inbox/metrics/':
                    data = None
                else:
                    data = dict(results=[])
                route.fulfill(status=200, content_type='application/json', body=json.dumps(data))

            context.route('**/*', handle)
            page = context.new_page()
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
            page.goto(origin + '/inbox')
            page.wait_for_load_state('networkidle')
            page.get_by_role('button', name=re.compile('^Ana sintética')).click()
            draft = page.get_by_role('textbox', name='Respuesta al cliente')
            draft.fill('Borrador que acompaña la lectura histórica.')
            local_quote = page.locator('[data-server-message-id="198"]').get_by_role('button', name='Ir al mensaje original de Lucía')
            local_quote.click() if label == 'desktop' else local_quote.tap()
            original = page.locator('[data-server-message-id="180"]')
            expect(original).to_be_focused()
            expect(original).to_have_class(re.compile('messageHighlight'))
            assert not [item for item in receipt['requests'] if item['viewport'] == label and 'around' in item['params']]
            expect(original).not_to_have_class(re.compile('messageHighlight'), timeout=4000)
            parent = page.locator('[data-server-message-id="200"]')
            parent.scroll_into_view_if_needed()
            expect(page.locator('[data-server-message-id="199"]')).to_contain_text('Mensaje no enviado')
            page.screenshot(path=str(out / f'quotes-{label}.png'), full_page=True)
            old_quote = parent.get_by_role('button', name='Ir al mensaje original de Ana sintética')
            old_quote.click() if label == 'desktop' else old_quote.tap()
            original = page.locator('[data-server-message-id="10"]')
            expect(original).to_be_focused()
            expect(original).to_have_class(re.compile('messageHighlight'))
            page.wait_for_function('''() => {
                const node = document.querySelector('[data-server-message-id="10"]');
                const area = document.querySelector('[aria-label="Mensajes de la conversación"]');
                if (!node || !area) return false;
                const rect = node.getBoundingClientRect(), bounds = area.getBoundingClientRect();
                return rect.top >= bounds.top && rect.bottom <= bounds.bottom;
            }''')
            expect(draft).to_have_value('Borrador que acompaña la lectura histórica.')
            assert page.locator('[data-server-message-id="151"]').count() == 1
            page.screenshot(path=str(out / f'jump-{label}.png'), full_page=True)
            failed_quote = page.locator('[data-server-message-id="199"]').get_by_role('button', name='Ir al mensaje original de Asistente')
            failed_quote.click() if label == 'desktop' else failed_quote.tap()
            discarded = page.locator('[data-server-message-id="30"]')
            expect(discarded).to_be_focused()
            expect(discarded).to_have_class(re.compile('messageHighlight'))
            expect(discarded).to_contain_text('[image]')
            earlier = page.get_by_role('button', name='Cargar anteriores', exact=True)
            earlier.click() if label == 'desktop' else earlier.tap()
            expect(page.locator('[data-server-message-id="101"]')).to_have_count(1)
            before = [item for item in receipt['requests'] if item['viewport'] == label and 'before' in item['params']]
            assert before[0]['params'] == dict(before=['151']), before
            around = [item['params'] for item in receipt['requests'] if item['viewport'] == label and 'around' in item['params']]
            assert around == [dict(around=['10']), dict(around=['30'])], around
            ids = page.locator('[data-server-message-id]').evaluate_all('(nodes) => nodes.map(node => node.dataset.serverMessageId)')
            assert len(ids) == len(set(ids))
            page.get_by_role('button', name=re.compile('^Beto sintético')).click()
            expect(draft).to_have_value('')
            assert page.locator('[class*="messageHighlight"]').count() == 0
            overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not overflow
            receipt['measurements'].append(dict(viewport=label, keyboard_focus=True, touch=label == 'mobile',
                local_without_get=True, remote_ids=[10, 30], target_in_viewport=True, discarded_media=True,
                before_chain_preserved=True, deduplicated=True, draft_preserved=True, switch_cancels=True,
                horizontal_overflow=overflow))
            context.close()
        assert not receipt['page_errors'], receipt['page_errors']
        receipt['status'] = 'PASS'
    finally:
        browser.close()
        (out / 'browser.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False))
