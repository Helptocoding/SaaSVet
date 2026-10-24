"""Local visual check: real frontend, intercepted synthetic API, no Meta/backend."""
import base64
import json
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

OUTPUT = Path(__file__).resolve().parent
ORIGIN = "http://127.0.0.1:4178"
rows = [
    {"contact_public_id": f"contact-{name.lower()}", "channel_account_public_id": "account-demo",
     "owner_name": name, "state": "active", "session_count": 1,
     "last_message_preview": "Consulta de prueba", "last_activity_at": "2026-10-20T18:00:00Z"}
    for name in ("Ana", "Beto")
]
payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) + 3600}).encode()).decode().rstrip("=")
token = f"e30.{payload}.local-fixture"
requests = []
errors = []
measurements = []


def intercept(route):
    request = route.request
    url = urlparse(request.url)
    if not url.path.startswith("/api/"):
        if request.url.startswith(ORIGIN + "/"):
            route.continue_()
        else:
            route.abort()
        return
    path = url.path.split("/api/", 1)[1]
    requests.append({"method": request.method, "path": path})
    if path == "me/":
        data = {"id": 1, "public_id": "staff-demo", "first_name": "Recepción", "username": "demo",
                "organization": 1, "organization_name": "Clínica de prueba", "organization_timezone": "America/Mexico_City",
                "role": "RECEPTIONIST", "permissions": ["agentinbox.view", "agentinbox.send"],
                "must_change_password": False}
    elif path == "inbox/threads/":
        data = rows
    elif path.startswith("inbox/threads/") and path.endswith("/messages/"):
        contact = path.split("/")[2]
        name = "Ana" if contact == "contact-ana" else "Beto"
        data = {"owner_name": name, "contact_public_id": contact, "channel_account_public_id": "account-demo",
                "conversation": {"public_id": f"session-{name.lower()}", "state": "active"},
                "messages": [{"id": 1, "direction": "in", "payload_type": "text", "status": "processed",
                              "body": "Hola, quisiera confirmar el horario de atención.", "created_at": "2026-10-20T18:00:00Z"}],
                "next_before": None}
    elif path.startswith("inbox/conversations/") and path.endswith("/send/"):
        data = {"id": 2, "direction": "out", "author_type": "human_staff", "human_author_name": "Recepción",
                "payload_type": "text", "status": "pending", "body": request.post_data_json["body"],
                "client_message_id": request.headers.get("x-idempotency-key"), "created_at": "2026-10-20T18:01:00Z"}
    elif path == "inbox/metrics/":
        data = None
    else:
        data = {"results": [], "count": 0, "unread_count": 0}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(data))


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    try:
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        context.route("**/*", intercept)
        context.add_init_script("localStorage.setItem('access_token', " + json.dumps(token) + ");")
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(ORIGIN + "/inbox")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUTPUT / "browser-ready.png"), full_page=True)
        page.get_by_role("button", name="Ana", exact=False).click()
        composer = page.get_by_role("textbox", name="Respuesta al cliente")
        expect(composer).to_be_visible()
        for width, height, label in [(1366, 768, "desktop"), (390, 844, "mobile")]:
            page.set_viewport_size({"width": width, "height": height})
            composer.fill("")
            initial = composer.bounding_box()["height"]
            composer.fill(("Texto de prueba para recepción. " * 100)[:2000])
            expect(composer).to_have_value(("Texto de prueba para recepción. " * 100)[:2000])
            geometry = composer.evaluate("el => ({height: el.getBoundingClientRect().height, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight})")
            assert 40 <= initial <= 42, initial
            assert geometry["height"] == 120, geometry
            assert geometry["scrollHeight"] > geometry["clientHeight"], geometry
            composer.scroll_into_view_if_needed()
            page.screenshot(path=str(OUTPUT / f"composer-{label}-2000.png"), full_page=True)
            assert not page.locator("#inbox-composer-count").count()
            composer.fill("a" * 3700)
            count = page.locator("#inbox-composer-count")
            neutral = count.evaluate("el => getComputedStyle(el).color")
            composer.fill("a" * 3800)
            expect(count).to_have_text("3800/4000")
            warning = count.evaluate("el => getComputedStyle(el).color")
            assert neutral != warning, (neutral, warning)
            composer.scroll_into_view_if_needed()
            page.screenshot(path=str(OUTPUT / f"composer-{label}-3800.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "horizontal overflow"
            page.get_by_role("button", name="Enviar", exact=True).click()
            expect(composer).to_have_value("")
            assert composer.bounding_box()["height"] <= 42
            assert not count.count()
            measurements.append({"viewport": label, "initial_height": initial, "long_text": geometry,
                                 "counter_neutral": neutral, "counter_warning": warning, "send_resets": True})
        assert not errors, errors
        (OUTPUT / "browser.json").write_text(json.dumps({"status": "PASS", "synthetic_api": True,
            "measurements": measurements, "page_errors": errors, "requests": requests}, indent=2), encoding="utf-8")
        print(json.dumps({"status": "PASS", "measurements": measurements}))
    except Exception as error:
        (OUTPUT / "browser-failure.json").write_text(json.dumps({"status": "FAIL", "error": str(error),
            "page_errors": errors, "requests": requests}, indent=2), encoding="utf-8")
        raise
    finally:
        browser.close()
