"""WA-WIN-01 in Chromium with synthetic API and a controlled browser clock."""
import base64
from datetime import datetime, timezone
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

out = Path(__file__).resolve().parent
origin = 'http://127.0.0.1:4178'
receipt = dict(status='RUNNING', synthetic_api=True, controlled_clock_visibility=True,
               measurements=[], requests=[], page_errors=[])


def iso(milliseconds):
    return datetime.fromtimestamp(milliseconds/1000, timezone.utc).isoformat()


def respond(route, payload):
    route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height), has_touch=label == 'mobile')
            token_payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time())+3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{token_payload}.fixture') + ');')
            context.add_init_script('''(() => {
                const NativeDate = Date;
                window.__clockOffset = 0; window.__windowHidden = false;
                window.Date = class extends NativeDate {
                    constructor(...args) { super(...(args.length ? args : [NativeDate.now()+window.__clockOffset])); }
                    static now() { return NativeDate.now()+window.__clockOffset; }
                };
                Object.defineProperty(document, 'hidden', {get:()=>window.__windowHidden});
                Object.defineProperty(document, 'visibilityState', {get:()=>window.__windowHidden?'hidden':'visible'});
            })();''')
            current = dict(public_id='session-ana', state='human_active', contact_phone='5551234567',
                session_window_open=True, session_window_expires_at=iso(time.time()*1000+432*60000))
            messages = [dict(id=i, direction='in', author_type='client', status='processed',
                body=f'Historial sintético {i:02}', created_at='2026-10-21T12:00:00Z') for i in range(1, 41)]

            def handle(route):
                request = route.request
                path = urlparse(request.url).path
                if not path.startswith('/api/'):
                    route.continue_() if request.url.startswith(origin+'/') else route.abort()
                    return
                path = path.removeprefix('/api/')
                if path == 'me/':
                    data = dict(id=1, username='window-staff', organization=1, organization_name='Clínica sintética',
                        organization_timezone='America/Tijuana', role='ASSISTANT',
                        permissions=['agentinbox.view', 'agentinbox.send'], must_change_password=False)
                elif path == 'inbox/threads/':
                    data = dict(results=[dict(contact_public_id='ana', channel_account_public_id='main',
                        owner_name='Ana', conversation_public_id='session-ana', state='human_active',
                        contact_phone='5551234567', session_count=1, last_message_preview='Consulta sintética')])
                elif path.endswith('/messages/'):
                    data = dict(owner_name='Ana', conversation=current, messages=messages, next_before=None)
                elif path.endswith('/send/'):
                    receipt['requests'].append(dict(viewport=label, path=path, body=request.post_data_json,
                        key=request.headers.get('x-idempotency-key')))
                    data = dict(id=99, direction='out', author_type='human_staff', human_author_name='Recepción',
                        client_message_id=request.headers.get('x-idempotency-key'), body=request.post_data_json['body'],
                        status='pending', created_at=iso(time.time()*1000), conversation_public_id='session-ana')
                    messages.append(data)
                elif path == 'inbox/metrics/':
                    data = None
                else:
                    data = dict(results=[])
                respond(route, data)

            def refresh(page):
                page.evaluate('''() => {
                    window.__windowHidden=true; document.dispatchEvent(new Event('visibilitychange'));
                    window.__windowHidden=false; document.dispatchEvent(new Event('visibilitychange'));
                }''')

            context.route('**/*', handle)
            page = context.new_page()
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
            page.goto(origin+'/inbox')
            page.wait_for_load_state('networkidle')
            page.get_by_role('button', name='Ana', exact=False).click()
            composer = page.get_by_role('textbox', name='Respuesta al cliente')
            notice = page.locator('#inbox-session-window')
            expect(notice).to_contain_text('cierra en 7 h 12 min')
            composer.fill('Borrador conservado al vencer')
            notice.scroll_into_view_if_needed()
            page.screenshot(path=str(out/f'warning-{label}.png'), full_page=True)
            page.evaluate('window.__clockOffset=60000')
            refresh(page)
            expect(notice).to_contain_text('cierra en 7 h 11 min')
            current['session_window_expires_at'] = iso(time.time()*1000+60000+1800)
            refresh(page)
            expect(notice).to_contain_text('cierra en 1 min')
            expect(composer).to_be_disabled(timeout=6000)
            expect(page.get_by_role('button', name='Enviar', exact=True)).to_be_disabled()
            expect(composer).to_have_value('Borrador conservado al vencer')
            expect(notice).to_contain_text('Ventana de WhatsApp cerrada')
            expect(notice.get_by_role('link', name='5551234567')).to_have_attribute('href', 'tel:5551234567')
            assert not any(request['viewport'] == label for request in receipt['requests'])
            page.screenshot(path=str(out/f'closed-{label}.png'), full_page=True)
            current['session_window_expires_at'] = iso(time.time()*1000+60000+24*60*60000)
            refresh(page)
            expect(composer).to_be_enabled()
            expect(composer).to_have_value('Borrador conservado al vencer')
            expect(notice).to_have_count(0)
            page.get_by_role('button', name='Enviar', exact=True).click()
            expect(composer).to_have_value('')
            expect(page.get_by_label('Pendiente de envío', exact=True)).to_be_visible()
            sends = [request for request in receipt['requests'] if request['viewport'] == label]
            assert len(sends) == 1 and sends[0]['body'] == {'body': 'Borrador conservado al vencer'} and sends[0]['key']
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            receipt['measurements'].append(dict(viewport=label, warning_7h12=True, countdown_7h11=True,
                exact_expiry_timer=True, closed_input=True, closed_send=True, draft_preserved=True,
                call_link=True, visibility_refresh=True, renewed_window=True, sent_after_renewal=1,
                sent_while_closed=0, horizontal_overflow=False))
            context.close()
        assert not receipt['page_errors'], receipt['page_errors']
        receipt['status'] = 'PASS'
    except Exception as error:
        receipt.update(status='FAIL', error=str(error))
        raise
    finally:
        browser.close()
        (out/'browser.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt))
