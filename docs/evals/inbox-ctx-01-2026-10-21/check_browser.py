"""WA-CTX-01: existing Inbox and pet page, synthetic API, desktop and touch."""
import base64
from datetime import datetime, timezone
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

out = Path(__file__).resolve().parent
origin = 'http://127.0.0.1:4178'
pet_id = '22a832df-45b4-46ee-bf73-3c127134c03a'
receipt = dict(status='RUNNING', synthetic_api=True, measurements=[], page_errors=[])


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height),
                                          has_touch=label == 'mobile')
            token_payload = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time())+3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{token_payload}.fixture') + ');')
            owner = dict(public_id='e6959bca-edbf-4103-b86e-62d85106be35', name='Ana', phone='5551234567')
            pet = dict(public_id=pet_id, name='Luna', species='Perro', owner=owner,
                       breed='Mestiza', sex='female', color='Negro', birth_date='2020-01-01')
            current = dict(public_id='session-ana', state='human_active', contact_phone='5551234567',
                session_window_open=True, session_window_expires_at=datetime.fromtimestamp(time.time()+86400, timezone.utc).isoformat())
            calls = []
            mode = {'context': 'linked'}

            def handle(route):
                request = route.request
                path = urlparse(request.url).path
                if not path.startswith('/api/'):
                    route.continue_() if request.url.startswith(origin+'/') else route.abort()
                    return
                path = path.removeprefix('/api/')
                if path == 'me/':
                    data = dict(id=1, username='context-staff', organization=1, organization_name='Clínica sintética',
                        organization_timezone='America/Tijuana', role='ASSISTANT', must_change_password=False,
                        permissions=['agentinbox.view', 'agentinbox.send', 'patient.retrieve', 'medicalrecord.list', 'appointment.list'])
                elif path == 'inbox/threads/':
                    data = dict(results=[dict(contact_public_id='ana', channel_account_public_id='main',
                        owner_name='Ana', conversation_public_id='session-ana', state='human_active',
                        contact_phone='5551234567', session_count=1, last_message_preview='Consulta sintética')])
                elif path.endswith('/messages/'):
                    data = dict(owner_name='Ana', conversation=current, next_before=None, messages=[
                        dict(id=i, direction='in', author_type='client', status='processed',
                             body=f'Historial sintético {i:02}', created_at='2026-10-21T12:00:00Z') for i in range(1, 21)])
                elif path.endswith('/context/'):
                    calls.append(path)
                    if mode['context'] == 'error':
                        mode['context'] = 'linked'
                        route.fulfill(status=503, content_type='application/json',
                            body=json.dumps(dict(code='temporary_unavailable', message='Contexto temporalmente no disponible')))
                        return
                    data = (dict(owner=None, pets=[], last_appointment=None) if mode['context'] == 'unlinked' else
                        dict(owner=owner, pets=[{key: pet[key] for key in ('public_id', 'name', 'species')}],
                             last_appointment=dict(date='2026-10-20', status='canceled')))
                elif path == f'pets/{pet_id}/':
                    data = pet
                elif path == 'inbox/metrics/':
                    data = None
                else:
                    data = dict(results=[])
                route.fulfill(status=200, content_type='application/json', body=json.dumps(data))

            context.route('**/*', handle)
            page = context.new_page()
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))

            def select_chat():
                page.goto(origin+'/inbox')
                page.get_by_role('button', name='Ana', exact=False).click()
                expect(page.get_by_role('textbox', name='Respuesta al cliente')).to_be_visible()

            select_chat()
            assert not calls, 'Context must be lazy'
            composer = page.get_by_role('textbox', name='Respuesta al cliente')
            composer.fill('Borrador conservado al abrir el contexto')
            # Acceptance counts start with a chat already open: toggle + pet button.
            page.get_by_role('button', name='Ver contexto del cliente', exact=True).click()
            panel = page.get_by_role('region', name='Contexto del cliente', exact=True)
            expect(panel).to_contain_text('Luna')
            expect(panel).to_contain_text('20 de octubre de 2026')
            expect(panel).to_contain_text('Cancelada')
            expect(panel.get_by_role('link', name='5551234567')).to_have_attribute('href', 'tel:5551234567')
            expect(composer).to_have_value('Borrador conservado al abrir el contexto')
            expect(page.locator('[data-message-id="20"]')).to_contain_text('Historial sintético 20')
            expect(page.locator('[data-message-id]')).to_have_count(20)
            assert len(calls) == 1
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(out/f'context-{label}.png'), full_page=True)
            page.get_by_role('button', name='Abrir expediente de Luna', exact=True).click()
            page.wait_for_url(origin+f'/pets/{pet_id}')
            expect(page.get_by_role('heading', name='Luna', exact=True)).to_be_visible()
            expect(page.get_by_text('Ana', exact=True)).to_be_visible()
            page.screenshot(path=str(out/f'expediente-{label}.png'), full_page=True)

            select_chat()
            mode['context'] = 'error'
            page.get_by_role('button', name='Ver contexto del cliente', exact=True).click()
            expect(panel.get_by_role('alert')).to_contain_text('Contexto temporalmente no disponible')
            expect(composer).to_be_enabled()
            page.screenshot(path=str(out/f'error-{label}.png'), full_page=True)
            page.get_by_role('button', name='Reintentar contexto', exact=True).click()
            expect(panel).to_contain_text('Luna')
            page.get_by_role('button', name='Ocultar contexto del cliente', exact=True).click()
            mode['context'] = 'unlinked'
            page.get_by_role('button', name='Ver contexto del cliente', exact=True).click()
            expect(panel).to_contain_text('Este contacto aún no tiene un cliente vinculado.')
            expect(panel.get_by_role('button', name='Abrir expediente', exact=False)).to_have_count(0)
            page.screenshot(path=str(out/f'unlinked-{label}.png'), full_page=True)
            assert len(calls) == 4
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            receipt['measurements'].append(dict(viewport=label, context_requests=4, lazy=True,
                chat_to_correct_pet_clicks=2, pet_route=f'/pets/{pet_id}', pet_heading=True,
                owner_name=True, calendar_date_preserved=True, status_preserved=True, phone_link=True,
                draft_preserved=True, transcript_preserved=True, isolated_error=True, explicit_retry=True,
                unlinked_empty_state=True, horizontal_overflow=False))
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
