import json
from http.client import RemoteDisconnected
from unittest import TestCase
from unittest.mock import patch

from gold.routing import Groq


class GroqContract(TestCase):
    def adapter_with_response(self, status, payload):
        patcher = patch("gold.routing.HTTPSConnection")
        connection = patcher.start().return_value
        self.addCleanup(patcher.stop)
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = json.dumps(payload).encode()
        return Groq("test-only", "test-model"), connection

    def test_router_uses_json_mode_and_validates_intent(self):
        payload = {"choices": [{"message": {"content": '{"intent":"compare"}'}}]}
        adapter, conn = self.adapter_with_response(200, payload)
        self.assertEqual(adapter.classify("question"), "compare")
        method, path, body, _ = conn.request.call_args.args
        self.assertEqual((method, path), ("POST", "/openai/v1/chat/completions"))
        self.assertEqual(json.loads(body)["response_format"], {"type": "json_object"})
        conn.close.assert_called_once()

    def test_unexpected_labels_malformed_results_and_outage_use_local_router(self):
        for status, data in [(429, {}), (200, {}), (200, {"choices": [{"message": {"content": "invalid"}}]}),
                             (200, {"choices": [{"message": {"content": '{"intent":"book_gold_now"}'}}]})]:
            with self.subTest(status=status, data=data):
                adapter, _ = self.adapter_with_response(status, data)
                self.assertIsNone(adapter.classify("question"))
        adapter, conn = self.adapter_with_response(200, {})
        conn.getresponse.side_effect = RemoteDisconnected()
        self.assertIsNone(adapter.classify("question"))
