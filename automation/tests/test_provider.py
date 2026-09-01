import unittest
from unittest.mock import patch

from automation.moderation_agent.models import Action
from automation.moderation_agent.provider import (
    LlmDecision,
    OpenAICompatibleProvider,
    ProviderError,
)


class ProviderTests(unittest.TestCase):
    def test_valid_json_decision(self):
        decision = LlmDecision.from_json(
            '{"action":"RETURN_FOR_REVISION","summary":"需要补充来源",'
            '"findings":[{"rule_id":"SOURCE_NEEDED","evidence":"某项结论",'
            '"reason":"缺少可核验来源"}]}'
        )
        self.assertEqual(decision.action, Action.RETURN_FOR_REVISION)
        self.assertEqual(len(decision.findings), 1)

    def test_invalid_json_fails_closed(self):
        with self.assertRaises(ProviderError):
            LlmDecision.from_json("not json")

    def test_remote_endpoint_is_disabled_by_default(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleProvider(
                base_url="https://example.com/v1",
                model="example",
            )

    def test_loopback_endpoint_is_allowed(self):
        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:8000/v1",
            model="local",
        )
        self.assertEqual(provider.model, "local")

    def test_generate_adds_bounded_and_json_options(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"choices":[{"message":{"content":"{}"}}]}'

        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:8000/v1",
            model="local",
        )
        with patch(
            "automation.moderation_agent.provider.urllib.request.urlopen",
            return_value=FakeResponse(),
        ) as mocked_open:
            provider.generate(
                [{"role": "user", "content": "test"}],
                max_tokens=32,
                response_format_json=True,
                extra_body={"thinking": {"type": "disabled"}},
            )

        request = mocked_open.call_args.args[0]
        payload = __import__("json").loads(request.data.decode("utf-8"))
        self.assertEqual(payload["max_tokens"], 32)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "disabled"})

    def test_extra_options_cannot_replace_messages(self):
        provider = OpenAICompatibleProvider(
            base_url="http://127.0.0.1:8000/v1",
            model="local",
        )
        with self.assertRaises(ValueError):
            provider.generate(
                [{"role": "user", "content": "test"}],
                extra_body={"messages": []},
            )


if __name__ == "__main__":
    unittest.main()
