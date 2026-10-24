"""Quoted composer in Chromium with synthetic API, keyboard and touch."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

out = Path(__file__).resolve().parent
origin = 'http://127.0.0.1:4178'
receipt = dict(status='RUNNING', synthetic_api=True, sends=[], measurements=[], page_errors=[])
assert not (out / 'browser.json').exists(), 'Never overwrite evidence'


def message(identifier, body, **extra):
    return dict(id=identifier, body=body, direction='in', author_type='client', payload_type='text',
                status='processed', created_at='2026-10-21T12:00:00Z', **extra)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height), has_touch=label == 'mobile')
            payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time()) + 3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{payload}.fixture') + ');')
            pending = []

            def handle(route):
                parsed = urlparse(route.request.url)
                if not parsed.path.startswith('/api/'):
                    route.continue_() if route.request.url.startswith(origin + '/') else route.abort()
                    return
                path = parsed.path.removeprefix('/api/')
                if path == 'me/':
                    data = dict(id=1, username='reply-staff', organization=1, role='ASSISTANT',
                        organization_name='Clínica sintética', organization_timezone='America/Tijuana',
                        must_change_password=False, permissions=['agentinbox.view', 'agentinbox.send'])
                elif path == 'inbox/threads/':
                    data = dict(results=[dict(contact_public_id=name, channel_account_public_id='main',
                        owner_name=name, conversation_public_id='session-' + name, state='human_active', session_count=1)
                        for name in ['Ana sintética', 'Beto sintético']], has_more=False, unread_total=0)
                elif path.endswith('/messages/'):
                    name = 'Beto sintético' if 'Beto' in path else 'Ana sintética'
                    data = dict(owner_name=name, contact_public_id=name, channel_account_public_id='main',
                        conversation=dict(public_id='session-' + name, state='human_active', session_window_open=True,
                            session_window_expires_at=datetime.fromtimestamp(time.time() + 86400, timezone.utc).isoformat()),
                        messages=[message(1, '¿Podemos confirmar la cita de mañana para Luna? Me gustaría conocer los horarios disponibles.'),
                                  dict(message(2, 'Estos son los horarios disponibles.'), direction='out', author_type='agent', status='sent')],
                        next_before=None)
                elif path.endswith('/send/'):
                    body = route.request.post_data_json
                    key = route.request.headers.get('x-idempotency-key')
                    receipt['sends'].append(dict(viewport=label, path=path, body=body, key=key))
                    pending.append((route, body, key))
                    return
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
            expect(draft).to_be_visible()
            draft.fill('Confirmamos la cita de Luna.')
            original = page.locator('[data-message-id="1"]')
            action = original.get_by_role('button', name='Responder al mensaje')
            if label == 'desktop':
                original.hover()
                expect(action).to_have_css('opacity', '1')
                action.press('Space')
            else:
                expect(action).to_have_css('opacity', '1')
                assert action.bounding_box()['height'] >= 44
                action.tap()
            quote = page.get_by_role('status', name='Mensaje citado')
            expect(quote).to_contain_text('Respondiendo a Ana sintética')
            expect(draft).to_be_focused()
            expect(draft).to_have_value('Confirmamos la cita de Luna.')
            if label == 'desktop':
                draft.press('Escape')
            else:
                page.get_by_role('button', name='Cancelar respuesta citada').tap()
            expect(quote).to_have_count(0)
            expect(draft).to_have_value('Confirmamos la cita de Luna.')
            action.click() if label == 'desktop' else action.tap()
            other = page.locator('[data-message-id="2"]').get_by_role('button', name='Responder al mensaje')
            other.click() if label == 'desktop' else other.tap()
            expect(quote).to_have_count(1)
            expect(quote).to_contain_text('Respondiendo a Asistente')
            action.click() if label == 'desktop' else action.tap()
            draft.scroll_into_view_if_needed()
            page.screenshot(path=str(out / f'composer-{label}.png'), full_page=True)
            assert quote.locator('span').evaluate('(node) => getComputedStyle(node).whiteSpace') == 'nowrap'
            if label == 'desktop':
                draft.press('Enter')
            else:
                page.get_by_role('button', name='Enviar', exact=True).tap()
            expect(quote).to_have_count(0)
            expect(draft).to_have_value('')
            page.wait_for_function('document.querySelectorAll("[data-message-id]").length === 3')
            assert len(pending) == 1
            route, body, key = pending.pop()
            assert body == dict(body='Confirmamos la cita de Luna.', reply_to_id=1) and key
            local = page.locator('[data-message-id="' + key + '"]')
            expect(local.get_by_role('button', name='Responder al mensaje')).to_be_disabled()
            sent = dict(message(200, body['body']), direction='out', author_type='human_staff', status='pending',
                        client_message_id=key, human_author_name='Recepción sintética')
            route.fulfill(status=201, content_type='application/json', body=json.dumps(sent))
            expect(local.get_by_role('button', name='Responder al mensaje')).to_be_enabled()
            other.click() if label == 'desktop' else other.tap()
            expect(quote).to_be_visible()
            page.get_by_role('button', name=re.compile('^Beto sintético')).click()
            expect(quote).to_have_count(0)
            expect(draft).to_have_value('')
            overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not overflow
            receipt['measurements'].append(dict(viewport=label, keyboard=label == 'desktop',
                touch=label == 'mobile', cancel_preserves_draft=True, one_active_quote=True,
                request_has_reply_id=True, optimistic_reply_disabled=True, confirmed_reply_enabled=True,
                switch_cancels=True, horizontal_overflow=overflow))
            context.close()
        assert not receipt['page_errors'], receipt['page_errors']
        receipt['status'] = 'PASS'
    finally:
        browser.close()
        (out / 'browser.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False))
