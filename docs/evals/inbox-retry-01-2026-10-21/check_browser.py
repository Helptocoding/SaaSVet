"""Headless Chromium with synthetic API; no Meta traffic or business data."""
import base64
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

OUT = Path(__file__).resolve().parent
ORIGIN = 'http://127.0.0.1:4178'
result = dict(status='RUNNING', synthetic_api=True, measurements=[], requests=[], page_errors=[])


def respond(route, data, status=200):
    route.fulfill(status=status, content_type='application/json', body=json.dumps(data))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height),
                                          has_touch=label == 'mobile')
            payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time())+3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{payload}.fixture') + ');')
            messages = [dict(id=i, conversation_public_id='session-ana', direction='out',
                author_type='human_staff', human_author_public_id='maria', human_author_name='María',
                body=f'Mensaje sintético {i:02}: seguimiento de recepción.', payload_type='text',
                status='read', failure_reason='', created_at='2026-10-21T12:00:00Z') for i in range(1, 61)]
            messages[41].update(body='Respuesta original de María', status='failed',
                                client_message_id='original-key', failure_reason='credentials_missing')
            messages[42].update(body='Respuesta fuera de ventana', status='failed', failure_reason='meta_131047')
            messages[43].update(body='Respuesta incierta sin reintento', status='uncertain',
                                uncertain_at='2026-10-21T12:00:01Z')
            held = []

            def handle(route):
                request = route.request
                path = urlparse(request.url).path
                if not path.startswith('/api/'):
                    route.continue_() if request.url.startswith(ORIGIN + '/') else route.abort()
                    return
                path = path.removeprefix('/api/')
                if '/retry/' in path:
                    result['requests'].append(dict(viewport=label, path=path, body=request.post_data_json,
                                                   key=request.headers.get('x-idempotency-key')))
                    if '/42/' in path:
                        held.append(route)
                    else:
                        respond(route, dict(code='window_closed', message='La ventana está cerrada.', suggestion='call'), 400)
                    return
                if path == 'me/':
                    data = dict(id=1, username='retry-staff', organization=1, organization_name='Clínica sintética',
                        organization_timezone='America/Mexico_City', role='ASSISTANT',
                        permissions=['agentinbox.view', 'agentinbox.send'], must_change_password=False)
                elif path == 'inbox/threads/':
                    data = dict(results=[dict(contact_public_id='ana', channel_account_public_id='main',
                        owner_name='Ana', contact_phone='5551234567', conversation_public_id='session-ana',
                        state='human_active', session_count=1, last_message_preview='Seguimiento')],
                        has_more=False, next_offset=None)
                elif path.endswith('/messages/'):
                    data = dict(owner_name='Ana', contact_phone='5551234567',
                        conversation=dict(public_id='session-ana', state='human_active'),
                        messages=messages, next_before=None)
                elif path == 'inbox/metrics/':
                    data = None
                else:
                    data = dict(results=[])
                respond(route, data)

            context.route('**/*', handle)
            page = context.new_page()
            page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
            page.goto(ORIGIN+'/inbox')
            page.wait_for_load_state('networkidle')
            page.get_by_role('button', name='Ana', exact=False).click()
            main = page.locator('[data-message-id="original-key"]')
            window = page.locator('[data-message-id="43"]')
            uncertain = page.locator('[data-message-id="44"]')
            expect(main.get_by_role('button', name='Reintentar', exact=True)).to_be_attached()
            expect(uncertain.get_by_role('button', name='Reintentar', exact=True)).to_have_count(0)
            expect(window.get_by_role('link', name='5551234567')).to_have_attribute('href', 'tel:5551234567')
            draft = page.get_by_role('textbox')
            draft.fill('Borrador que debe conservarse')
            main.scroll_into_view_if_needed()
            retry = main.get_by_role('button', name='Reintentar', exact=True)
            if label == 'desktop':
                retry.focus()
                retry.press('Enter')
            else:
                retry.tap()
            expect(main.get_by_role('button', name='Reintentando…')).to_be_disabled()
            page.wait_for_timeout(100)
            assert len(held) == 1
            retry_request = result['requests'][-1]
            assert retry_request['body'] == {} and retry_request['key'] == 'original-key'
            page.screenshot(path=str(OUT/f'retrying-{label}.png'), full_page=True)
            before_y = main.bounding_box()['y']
            messages[41].update(status='pending', failure_reason='')
            respond(held.pop(), messages[41])
            expect(main.get_by_label('Pendiente de envío', exact=True)).to_be_visible()
            expect(main.get_by_role('button', name='Reintentar', exact=True)).to_have_count(0)
            expect(draft).to_have_value('Borrador que debe conservarse')
            expect(main).to_contain_text('Respuesta original de María')
            expect(page.locator('[data-message-id]').filter(has_text='Respuesta original de María')).to_have_count(1)
            after_y = main.bounding_box()['y']
            assert abs(after_y-before_y) < 1, (label, before_y, after_y)
            window.get_by_role('button', name='Reintentar', exact=True).click()
            expect(window.get_by_role('button', name='Reintentar', exact=True)).to_be_enabled()
            expect(window.get_by_text('Ventana de WhatsApp cerrada', exact=False)).to_be_visible()
            expect(page.locator('[data-sonner-toast]')).to_have_count(0)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(OUT/f'window-{label}.png'), full_page=True)
            result['measurements'].append(dict(viewport=label, original_key=True, editable_body_sent=False,
                busy_guard=True, original_author=True, duplicates=0, draft_preserved=True,
                uncertain_retry=False, window_call_link=True, anchor_delta=after_y-before_y,
                keyboard=label == 'desktop', touch=label == 'mobile', horizontal_overflow=False))
            context.close()
        assert not result['page_errors'], result['page_errors']
        result['status'] = 'PASS'
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        browser.close()
        (OUT/'browser.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
