"""
test_executor.py — É-F1 PR-10: minting, headers, auditoría ToolExecution.
"""
from django.test import TestCase

from apps.agent import executor as executor_module
from apps.agent.executor import ToolExecutor, mint_agent_token
from apps.agent.models import ContactIdentity, Conversation, ToolExecution
from apps.channels.models import ChannelAccount
from apps.core.models import Permission, Role
from apps.core.permissions_codes import PERMISSIONS
from apps.organizations.models import Organization
from apps.users.services import ensure_agent_user


def _seed_agent_role(org):
    role, _ = Role.objects.get_or_create(
        name="AGENT", organization=org, defaults={"is_system_role": True}
    )
    perms = [Permission.objects.get_or_create(code=c)[0] for c in PERMISSIONS["AGENT"]]
    role.permissions.set(perms)


class CapturingTransport:
    """Transport falso: captura la llamada y devuelve lo configurado."""

    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self.data = data if data is not None else []
        self.captured = []

    def __call__(self, method, path, *, headers, params=None, json=None):
        self.captured.append({
            "method": method, "path": path, "headers": headers,
            "params": params, "json": json,
        })
        return self.status_code, self.data


class ToolExecutorTests(TestCase):
    def setUp(self):
        executor_module._token_cache.clear()
        self.org = Organization.objects.create(name="Exec Org", timezone="UTC")
        _seed_agent_role(self.org)
        self.agent_user, _ = ensure_agent_user(self.org)
        channel = ChannelAccount.objects.create(
            organization=self.org, external_account_id="500100500",
        )
        contact = ContactIdentity.objects.create(
            organization=self.org, external_id="5215500110022",
        )
        self.conversation = Conversation.objects.create(
            organization=self.org, channel_account=channel, contact=contact,
        )

    def _executor(self, transport):
        return ToolExecutor(self.conversation, self.agent_user,
                            transport=transport)

    def test_token_is_cached_per_org(self):
        first = mint_agent_token(self.agent_user)
        second = mint_agent_token(self.agent_user)
        self.assertEqual(first, second)

    def test_call_sends_bearer_and_request_id_and_audits(self):
        transport = CapturingTransport(200, [{"x": 1}, {"x": 2}])
        status, data = self._executor(transport).call(
            "GET", "/api/pets/", tool_name="list_my_pets",
            params={"owner": "abc"},
            args_redacted={"q": "safe"},
            result_summarizer=lambda d: {"items": len(d)},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(data), 2)

        captured = transport.captured[0]
        self.assertTrue(
            captured["headers"]["Authorization"].startswith("Bearer ")
        )
        self.assertTrue(captured["headers"]["X-Request-ID"])

        execution = ToolExecution.objects.get(conversation=self.conversation)
        self.assertEqual(execution.tool_name, "list_my_pets")
        self.assertEqual(execution.http_status, 200)
        self.assertEqual(execution.result_summary_redacted, {"items": 2})
        self.assertEqual(execution.args_redacted, {"q": "safe"})
        self.assertEqual(execution.request_id,
                         captured["headers"]["X-Request-ID"])
        # R15: el token JAMÁS aparece en la auditoría.
        self.assertNotIn("Bearer", str(execution.args_redacted))
        self.assertNotIn("Bearer", str(execution.result_summary_redacted))

    def test_http_error_audits_error_code(self):
        transport = CapturingTransport(
            403, {"code": "permission_denied", "message": "no"},
        )
        status, _ = self._executor(transport).call(
            "GET", "/api/medical-records/", tool_name="forbidden_probe",
        )
        self.assertEqual(status, 403)
        execution = ToolExecution.objects.get(tool_name="forbidden_probe")
        self.assertEqual(execution.error_code, "permission_denied")

    def test_record_local_creates_audit_row(self):
        self._executor(CapturingTransport()).record_local(
            tool_name="get_clinic_info",
            args_redacted={"topic": "horario"},
            summary={"facts": 1},
        )
        execution = ToolExecution.objects.get(tool_name="get_clinic_info")
        self.assertIsNone(execution.http_status)
        self.assertTrue(execution.request_id)
