"""PERF-03 in real Chromium, synthetic API: deltas, scroll anchor and recovery."""
import base64
from datetime import datetime, timezone
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import expect, sync_playwright

out = Path(__file__).resolve().parent
origin = 'http://127.0.0.1:4178'
receipt = dict(status='RUNNING', synthetic_api=True, measurements=[], requests=[], page_errors=[])


def message(number):
    return dict(id=number, direction='out' if number == 60 else 'in', author_type='human_staff' if number == 60 else 'client',
        human_author_name='Recepción' if number == 60 else None, conversation_public_id='session-ana',
        status='sent' if number == 60 else 'processed', body=f'Historial sintético {number:03}',
        created_at='2026-10-21T12:00:00Z', acceptance_known=True)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height), has_touch=label == 'mobile')
            token_payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time())+3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{token_payload}.fixture') + ');')
            context.add_init_script('''(() => {
                window.__syncHidden=false;
                Object.defineProperty(document, 'hidden', {get:()=>window.__syncHidden});
                Object.defineProperty(document, 'visibilityState', {get:()=>window.__syncHidden?'hidden':'visible'});
            })();''')
            current = dict(public_id='session-ana', state='human_active', contact_phone='5551234567',
                session_window_open=True, session_window_expires_at=datetime.fromtimestamp(time.time()+86400, timezone.utc).isoformat())
            metadata = dict(owner_name='Ana', contact_public_id='ana', channel_account_public_id='main',
                conversation=current, contact_verification='staff_verified')
            rows = [dict(contact_public_id='ana', channel_account_public_id='main', owner_name='Ana',
                conversation_public_id='session-ana', state='human_active', session_count=1)]
            all_messages = [message(number) for number in range(1, 101)]
            phase = dict(changed=False, extended=False, reject_list=False, reject_thread=False)
            sizes = {}

            def handle(route):
                request = route.request
                parsed = urlparse(request.url)
                if not parsed.path.startswith('/api/'):
                    route.continue_() if request.url.startswith(origin+'/') else route.abort()
                    return
                path = parsed.path.removeprefix('/api/')
                params = parse_qs(parsed.query)
                status, mode = 200, None
                if path == 'me/':
                    data = dict(id=1, username='sync-staff', organization=1, role='ASSISTANT',
                        organization_name='Clínica sintética', organization_timezone='America/Tijuana',
                        must_change_password=False, permissions=['agentinbox.view', 'agentinbox.send'])
                elif path == 'inbox/threads/':
                    if params.get('since') and phase['reject_list']:
                        phase['reject_list'] = False
                        status, data = 400, dict(code='invalid_sync_cursor', message='Recuperar lista')
                    elif params.get('since'):
                        data = dict(mode='delta', sync_cursor='l2', upserts=[], removals=[],
                            has_more=False, next_offset=None, unread_total=0)
                        mode = 'list_delta'
                    else:
                        data = dict(mode='full', sync_cursor='l1', results=rows,
                            has_more=False, next_offset=None, unread_total=0)
                        mode = 'list_full'
                elif path.endswith('/messages/'):
                    if params.get('before'):
                        data = dict(messages=all_messages[:50], next_before=None, sync_floor='floor-1')
                        mode = 'history'
                    elif params.get('since') and phase['reject_thread']:
                        phase['reject_thread'] = False
                        status, data = 400, dict(code='invalid_sync_cursor', message='Recuperar transcript')
                    elif params.get('since'):
                        changes = []
                        if phase['changed']:
                            changes = [row for row in all_messages if row['id'] in (60, 101)]
                        data = dict(mode='delta', sync_cursor='m2', messages=changes, removals=[], metadata={})
                        if params.get('floor') == ['floor-1'] and not phase['extended']:
                            phase['extended'] = True
                            data['messages'] = [row for row in all_messages if row['id'] < 51] + changes
                            data['range_ids'] = [row['id'] for row in all_messages]
                        mode = 'thread_delta_changed' if data['messages'] else 'thread_delta_empty'
                    else:
                        subset = all_messages if params.get('floor') else all_messages[-50:]
                        data = dict(metadata, mode='full', sync_cursor='m1', messages=subset,
                            next_before=subset[0]['id'], reset_range=bool(params.get('floor')),
                            sync_floor='floor-1' if params.get('floor') else 'floor-51')
                        mode = 'thread_full'
                elif path == 'inbox/metrics/':
                    data = None
                else:
                    data = dict(results=[])
                body = json.dumps(data)
                if mode:
                    sizes.setdefault(mode, []).append(len(body.encode()))
                receipt['requests'].append(dict(viewport=label, path=path, params=params,
                    status=status, mode=mode, payload_bytes=len(body.encode())))
                route.fulfill(status=status, content_type='application/json', body=body)

            def refresh(page):
                page.evaluate('''() => {
                    window.__syncHidden=true; document.dispatchEvent(new Event('visibilitychange'));
                    window.__syncHidden=false; document.dispatchEvent(new Event('visibilitychange'));
                }''')
                page.wait_for_load_state('networkidle')

            context.route('**/*', handle)
            page = context.new_page()
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
            page.goto(origin+'/inbox')
            page.wait_for_load_state('networkidle')
            page.get_by_role('button', name='Ana', exact=False).click()
            page.wait_for_load_state('networkidle')
            composer = page.get_by_role('textbox', name='Respuesta al cliente')
            composer.fill('Borrador conservado durante delta')
            viewport = page.get_by_role('region', name='Mensajes de la conversación')
            refresh(page)
            expect(page.locator('[data-message-id]')).to_have_count(50)
            assert sizes['thread_delta_empty'][-1] < sizes['thread_full'][0]/10
            viewport.evaluate('area=>{area.scrollTop=0;area.dispatchEvent(new Event("scroll"));}')
            page.wait_for_load_state('networkidle')
            expect(page.locator('[data-message-id]')).to_have_count(100)
            viewport.evaluate('''area => {
                const node=area.querySelector('[data-message-id="020"]') || area.querySelector('[data-message-id="20"]');
                area.scrollTop += node.getBoundingClientRect().top-area.getBoundingClientRect().top-20;
                area.dispatchEvent(new Event('scroll'));
            }''')
            anchor = page.locator('[data-message-id="20"]')
            before = anchor.evaluate('node=>node.getBoundingClientRect().top-node.closest("[role=region]").getBoundingClientRect().top')
            all_messages[:] = [row for row in all_messages if row['id'] != 10]
            next(row for row in all_messages if row['id'] == 60)['status'] = 'read'
            all_messages.append(message(101))
            phase['changed'] = True
            refresh(page)
            expect(page.locator('[data-message-id="10"]')).to_have_count(0)
            expect(page.locator('[data-message-id="101"]')).to_have_count(1)
            expect(page.locator('[data-message-id="60"]').get_by_label('Leído', exact=True)).to_have_count(1)
            after = anchor.evaluate('node=>node.getBoundingClientRect().top-node.closest("[role=region]").getBoundingClientRect().top')
            assert abs(after-before) < 1, (before, after)
            expect(composer).to_have_value('Borrador conservado durante delta')
            expect(page.locator('[data-message-id]')).to_have_count(100)
            page.screenshot(path=str(out/f'delta-{label}.png'), full_page=True)
            phase['reject_list'] = phase['reject_thread'] = True
            refresh(page)
            expect(page.locator('[data-message-id]')).to_have_count(100)
            expect(composer).to_have_value('Borrador conservado durante delta')
            restored = anchor.evaluate('node=>node.getBoundingClientRect().top-node.closest("[role=region]").getBoundingClientRect().top')
            assert abs(restored-after) < 1
            phase['changed'] = False
            refresh(page)
            assert sizes['thread_delta_empty'][-1] < sizes['thread_full'][-1]/10
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(out/f'recovered-{label}.png'), full_page=True)
            requests = [row for row in receipt['requests'] if row['viewport'] == label]
            assert sum(row['status'] == 400 for row in requests) == 2
            assert sum(row['mode'] == 'thread_full' for row in requests) == 2
            assert sum(row['mode'] == 'list_full' for row in requests) == 2
            receipt['measurements'].append(dict(viewport=label, full_payload_bytes=sizes['thread_full'][0],
                empty_delta_bytes=sizes['thread_delta_empty'][0], scroll_anchor_delta_px=after-before,
                recovery_anchor_delta_px=restored-after, loaded_messages=100, changed_tick=True,
                new_message=True, removed_history=True, duplicate_ids=False, explicit_full_recovery=True,
                resumed_delta=True, draft_preserved=True, horizontal_overflow=False))
            context.close()
        assert not receipt['page_errors'], receipt['page_errors']
        receipt['status'] = 'PASS'
    except Exception as error:
        receipt.update(status='FAIL', error=str(error))
        raise
    finally:
        browser.close()
        (out/'browser.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps({key: receipt[key] for key in ('status', 'measurements', 'page_errors')}, ensure_ascii=True))
