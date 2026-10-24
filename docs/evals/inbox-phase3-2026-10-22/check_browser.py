"""Chromium desktop/touch smoke; every API and media byte is synthetic."""
import base64
from collections import Counter
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import unquote, urlparse
import wave

from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

out = Path(os.environ.get('PHASE3_BROWSER_OUTPUT', Path(__file__).resolve().parent))
origin = 'http://127.0.0.1:4178'
receipt = dict(status='RUNNING', synthetic_api=True, measurements=[], page_errors=[])
assert not (out / 'browser.json').exists()
picture = Image.new('RGB', (640, 360), '#dfeee7')
draw = ImageDraw.Draw(picture)
draw.ellipse((260, 130, 380, 250), fill='#1e6250')
for x, y in [(230, 105), (280, 70), (340, 70), (390, 105)]:
    draw.ellipse((x, y, x+35, y+45), fill='#1e6250')
draw.text((20, 320), 'ARCHIVO SINTETICO - LUNA', fill='#16382f')
png = io.BytesIO()
picture.save(png, format='PNG')
audio = io.BytesIO()
with wave.open(audio, 'wb') as sound:
    sound.setnchannels(1)
    sound.setsampwidth(2)
    sound.setframerate(8000)
    sound.writeframes(b'\x00\x00' * 8000)


def media(identity, status='ready', **extra):
    return dict(dict(public_id=identity, status=status, mime_type='image/png', filename='',
        file_size=2048, expires_at='2099-01-01T00:00:00Z', width=640, height=360), **extra)


def message(identifier, kind, attachment, body=''):
    return dict(id=identifier, body=body, direction='in', author_type='client', payload_type=kind,
        status='processed', media=attachment, created_at='2026-10-22T12:00:00Z')


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    try:
        for width, height, label in [(1366, 768, 'desktop'), (390, 844, 'mobile')]:
            context = browser.new_context(viewport=dict(width=width, height=height), has_touch=label == 'mobile')
            token = base64.urlsafe_b64encode(json.dumps({'exp': int(time.time())+3600}).encode()).decode().rstrip('=')
            context.add_init_script("localStorage.setItem('access_token', " + json.dumps(f'e30.{token}.fixture') + ');')
            counts = Counter()
            authenticated = []
            rows = [
                message(1, 'image', media('photo'), 'Imagen sintética de Luna'),
                message(2, 'audio', media('audio', mime_type='audio/wav', file_size=16000)),
                message(3, 'video', media('video', mime_type='video/mp4', file_size=12*1024*1024)),
                message(4, 'document', media('document', mime_type='application/pdf', filename='estudio.pdf')),
                message(5, 'image', media('pending', 'pending'), 'Caption conservada mientras se recibe'),
                message(6, 'image', media('failed', 'failed')),
                message(7, 'image', media('expired', 'expired')),
                message(8, 'image', media('gone')),
                message(9, 'image', media('retry')),
            ]
            rows[0]['reply_to'] = dict(id=5, author_type='client', payload_type='image',
                excerpt='Caption conservada mientras se recibe', status='processed')

            def handle(route):
                path = unquote(urlparse(route.request.url).path)
                if not path.startswith('/api/'):
                    route.continue_() if route.request.url.startswith(origin + '/') else route.abort()
                    return
                if path.startswith('/api/inbox/media/'):
                    identity = path.rstrip('/').split('/')[-1]
                    counts[identity] += 1
                    authenticated.append(route.request.headers.get('authorization', '').startswith('Bearer '))
                    if identity == 'gone':
                        route.fulfill(status=410, content_type='application/json', body='{"code":"media_expired"}')
                    elif identity == 'retry' and counts[identity] == 1:
                        route.fulfill(status=503, content_type='application/json', body='{"code":"media_unavailable"}')
                    elif identity == 'audio':
                        route.fulfill(status=200, content_type='audio/wav', body=audio.getvalue())
                    elif identity == 'document':
                        route.fulfill(status=200, content_type='application/pdf', body=b'%PDF-1.4\n% synthetic download\n%%EOF')
                    else:
                        route.fulfill(status=200, content_type='image/png', body=png.getvalue())
                    return
                if path == '/api/me/':
                    data = dict(id=1, username='synthetic-staff', organization=1, role='ASSISTANT',
                        organization_name='Clínica sintética', organization_timezone='America/Mexico_City',
                        must_change_password=False, permissions=['agentinbox.view', 'agentinbox.send'])
                elif path == '/api/inbox/threads/':
                    data = dict(results=[dict(contact_public_id='Luna', channel_account_public_id='main',
                        owner_name='Luna sintética', conversation_public_id='session-Luna', state='human_active',
                        last_message_preview='', last_message_type='document', last_message_filename='estudio.pdf')],
                        has_more=False, unread_total=0)
                elif path.endswith('/messages/'):
                    data = dict(owner_name='Luna sintética', contact_public_id='Luna', channel_account_public_id='main',
                        conversation=dict(public_id='session-Luna', state='human_active', session_window_open=True,
                            session_window_expires_at=datetime.fromtimestamp(time.time()+86400, timezone.utc).isoformat()),
                        messages=rows, next_before=None, mode='full', sync_cursor='synthetic', sync_floor='synthetic')
                elif path == '/api/inbox/metrics/':
                    data = None
                else:
                    data = dict(results=[])
                route.fulfill(status=200, content_type='application/json', body=json.dumps(data))

            context.route('**/*', handle)
            page = context.new_page()
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
            page.goto(origin + '/inbox')
            thread = page.get_by_role('button', name=re.compile('^Luna sintética'))
            expect(thread).to_contain_text('estudio.pdf')
            thread.click()
            bubble = lambda identity: page.locator(f'[data-server-message-id="{identity}"]')
            expect(bubble(5)).to_contain_text('Caption conservada mientras se recibe')
            expect(bubble(6)).to_contain_text('Archivo no disponible')
            expect(bubble(7)).to_contain_text('Archivo expirado')
            bubble(8).scroll_into_view_if_needed()
            expect(bubble(8)).to_contain_text('Archivo expirado')
            assert bubble(8).get_by_role('button', name='Reintentar archivo').count() == 0
            bubble(9).scroll_into_view_if_needed()
            retry = bubble(9).get_by_role('button', name='Reintentar archivo')
            retry.click()
            expect(bubble(9).get_by_role('button', name='Ampliar imagen')).to_be_visible()
            page.screenshot(path=str(out / f'media-states-{label}.png'), full_page=True)
            bubble(1).scroll_into_view_if_needed()
            thumbnail = bubble(1).get_by_role('button', name='Ampliar imagen')
            expect(thumbnail).to_be_visible()
            expect(bubble(1)).to_contain_text('Imagen sintética de Luna')
            assert bubble(1).text_content().count('Imagen sintética de Luna') == 1
            thumbnail.click() if label == 'desktop' else thumbnail.tap()
            expect(page.get_by_role('dialog', name='Imagen ampliada')).to_be_visible()
            page.screenshot(path=str(out / f'media-lightbox-{label}.png'), full_page=True)
            page.keyboard.press('Escape')
            expect(page.get_by_role('dialog')).to_have_count(0)
            expect(thumbnail).to_be_focused()
            bubble(2).scroll_into_view_if_needed()
            assert counts['audio'] == counts['video'] == counts['document'] == 0
            bubble(2).get_by_role('button', name=re.compile('Cargar audio')).click()
            expect(bubble(2).locator('audio')).to_have_attribute('controls', '')
            assert bubble(2).locator('audio').get_attribute('autoplay') is None
            bubble(4).scroll_into_view_if_needed()
            with page.expect_download() as event:
                bubble(4).get_by_role('button', name='Descargar documento').click()
            assert event.value.suggested_filename == 'estudio.pdf'
            assert counts['video'] == 0
            assert counts['gone'] == 1 and counts['retry'] == 2
            assert authenticated and all(authenticated)
            overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert not overflow
            receipt['measurements'].append(dict(viewport=label, bearer_on_every_file=True, typed_preview=True,
                caption_and_quote=True, lightbox_escape_focus=True, manual_audio=True, video_not_autoloaded=True,
                document_download=True, pending_failed_expired=True, http410_once=True, explicit_retry=True,
                horizontal_overflow=overflow, file_requests=dict(counts)))
            context.close()
        assert not receipt['page_errors'], receipt['page_errors']
        receipt['status'] = 'PASS'
    finally:
        browser.close()
        (out / 'browser.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False))
