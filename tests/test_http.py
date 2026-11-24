"""Exercise the production ASGI app over loopback HTTP, including authentication."""
import unittest

from scripts.verify import walkthrough


class HttpJourney(unittest.TestCase):
    def test_two_users_purchase_recovery_and_three_instalments(self):
        walkthrough(verbose=False)


class HttpSecurity(unittest.IsolatedAsyncioTestCase):
    async def test_body_deadline_returns_a_timeout_before_dispatch(self):
        import asyncio
        from unittest.mock import AsyncMock
        from gold.api import BodyLimit

        downstream = AsyncMock()
        # A controllable receiver signals expiry without making a network request.
        receive = AsyncMock(side_effect=TimeoutError)
        send = AsyncMock()
        await BodyLimit(downstream)({"type": "http", "method": "POST"}, receive, send)
        downstream.assert_not_awaited()
        self.assertEqual(send.await_args_list[0].args[0]["status"], 408)
        # The middleware also installs its own deadline around the receive operation.
        class Receiver:
            async def __call__(self):
                await asyncio.Event().wait()

        send.reset_mock()
        await asyncio.wait_for(BodyLimit(downstream, read_timeout=0)(
            {"type": "http", "method": "POST"}, Receiver(), send), timeout=1)
        self.assertEqual(send.await_args_list[0].args[0]["status"], 408)

    async def test_docs_integrity_matches_its_script_policy(self):
        import base64
        import hashlib
        from html.parser import HTMLParser
        from gold.docs import documentation

        class Assets(HTMLParser):
            def __init__(self):
                super().__init__()
                self.external = []
                self.inline = []

            def handle_starttag(self, tag, attrs):
                fields = dict(attrs)
                if tag == "script" and "src" in fields or tag == "link":
                    self.external.append(fields)

            def handle_data(self, data):
                if "SwaggerUIBundle(" in data or "Redoc.init(" in data:
                    self.inline.append(data)

        for redoc in (True, False):
            page = documentation(redoc)
            assets = Assets()
            assets.feed(page.body.decode())
            policy = page.headers["Content-Security-Policy"]
            self.assertEqual(len(assets.external), 1 if redoc else 2)
            self.assertEqual(len(assets.inline), 1)
            for asset in assets.external:
                self.assertEqual(asset["crossorigin"], "anonymous")
                self.assertRegex(asset["integrity"], r"^sha384-[A-Za-z0-9+/]{64}$")
                if "src" in asset:
                    self.assertIn(asset["integrity"], policy)
            sha = base64.b64encode(hashlib.sha256(assets.inline[0].encode()).digest()).decode()
            self.assertIn("sha256-" + sha, policy)
            self.assertIn("connect-src 'self'", policy)
