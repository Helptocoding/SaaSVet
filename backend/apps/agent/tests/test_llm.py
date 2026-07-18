"""
test_llm.py — É-F1 PR-9: adaptador LLM proveedor-agnóstico.

Todo mockeado (spec §9.1: la suite CI jamás toca un proveedor real).
"""
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from apps.agent.llm import (
    LLMError,
    LLMResult,
    OpenAICompatibleClient,
    StubLLMClient,
    estimate_cost,
    get_llm_client,
)

LLM_SETTINGS = dict(
    AGENT_LLM_BASE_URL="https://llm.test/v1",
    AGENT_LLM_API_KEY="key-123",
    AGENT_LLM_MODEL_PLANNER="modelo-capaz",
    AGENT_LLM_MODEL_ROUTER="modelo-barato",
)


def _response(status_code, payload=None):
    response = mock.Mock()
    response.status_code = status_code
    if payload is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = payload
    return response


def _chat_payload(message, finish_reason="stop", model="modelo-capaz"):
    return {
        "model": model,
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 45},
    }


@override_settings(**LLM_SETTINGS)
class OpenAICompatibleClientTests(SimpleTestCase):
    def _complete(self, post_result=None, post_error=None, tools=None):
        client = OpenAICompatibleClient()
        with mock.patch("apps.agent.llm.requests.post") as post:
            if post_error is not None:
                post.side_effect = post_error
            else:
                post.return_value = post_result
            result = client.complete(
                system="eres un asistente",
                messages=[{"role": "user", "content": "hola"}],
                tools=tools,
            )
            return result, post

    def test_text_response_and_request_shape(self):
        result, post = self._complete(
            _response(200, _chat_payload({"content": "¡Hola! ¿En qué te ayudo?"})),
        )
        self.assertEqual(result.kind, "text")
        self.assertEqual(result.text, "¡Hola! ¿En qué te ayudo?")
        self.assertEqual(result.input_tokens, 120)
        self.assertEqual(result.output_tokens, 45)

        url = post.call_args.args[0]
        self.assertEqual(url, "https://llm.test/v1/chat/completions")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer key-123")
        body = kwargs["json"]
        self.assertEqual(body["model"], "modelo-capaz")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertNotIn("tools", body)  # sin tools no se manda el campo

    def test_tool_call_response(self):
        tools = [{"type": "function", "function": {"name": "get_vaccine_status",
                                                   "parameters": {}}}]
        payload = _chat_payload({
            "content": None,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "get_vaccine_status",
                             "arguments": '{"pet_handle": "mascota_1"}'},
            }],
        }, finish_reason="tool_calls")
        result, post = self._complete(_response(200, payload), tools=tools)
        self.assertEqual(result.kind, "tool_call")
        self.assertEqual(result.tool_name, "get_vaccine_status")
        self.assertEqual(result.tool_args, {"pet_handle": "mascota_1"})
        self.assertEqual(post.call_args.kwargs["json"]["tool_choice"], "auto")

    def test_malformed_tool_args_is_non_retryable(self):
        payload = _chat_payload({
            "tool_calls": [{"function": {"name": "x", "arguments": "{no json"}}],
        })
        with self.assertRaises(LLMError) as ctx:
            self._complete(_response(200, payload))
        self.assertFalse(ctx.exception.retryable)

    def test_429_and_5xx_are_retryable(self):
        for status in (429, 503):
            with self.subTest(status=status):
                with self.assertRaises(LLMError) as ctx:
                    self._complete(_response(status))
                self.assertTrue(ctx.exception.retryable)

    def test_4xx_is_not_retryable(self):
        with self.assertRaises(LLMError) as ctx:
            self._complete(_response(401))
        self.assertFalse(ctx.exception.retryable)

    def test_network_error_is_retryable(self):
        with self.assertRaises(LLMError) as ctx:
            self._complete(post_error=requests.ConnectTimeout("t"))
        self.assertTrue(ctx.exception.retryable)

    @override_settings(AGENT_LLM_API_KEY="")
    def test_unconfigured_fails_closed_without_network(self):
        client = OpenAICompatibleClient()
        with mock.patch("apps.agent.llm.requests.post") as post:
            with self.assertRaises(LLMError) as ctx:
                client.complete(system="s", messages=[])
            post.assert_not_called()
        self.assertFalse(ctx.exception.retryable)

    def test_router_falls_back_to_planner_model(self):
        with override_settings(AGENT_LLM_MODEL_ROUTER=""):
            self.assertEqual(get_llm_client("router").model, "modelo-capaz")
        self.assertEqual(get_llm_client("router").model, "modelo-barato")
        self.assertEqual(get_llm_client("planner").model, "modelo-capaz")


class EstimateCostTests(SimpleTestCase):
    @override_settings(AGENT_LLM_COST_PER_MTOK_INPUT=1.0,
                       AGENT_LLM_COST_PER_MTOK_OUTPUT=4.0)
    def test_cost_from_env_pricing(self):
        self.assertAlmostEqual(
            estimate_cost(500_000, 250_000), 0.5 + 1.0,
        )

    def test_zero_without_pricing(self):
        self.assertEqual(estimate_cost(1_000_000, 1_000_000), 0.0)


class StubLLMClientTests(SimpleTestCase):
    def test_scripted_results_and_call_recording(self):
        stub = StubLLMClient(scripted=[
            LLMResult(kind="text", text="hola"),
            LLMError("boom", retryable=True),
        ])
        first = stub.complete(system="s", messages=[{"role": "user", "content": "x"}])
        self.assertEqual(first.text, "hola")
        with self.assertRaises(LLMError):
            stub.complete(system="s", messages=[])
        self.assertEqual(len(stub.calls), 2)
