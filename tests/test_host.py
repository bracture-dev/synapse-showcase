"""The inherited control channel, runnable with stdlib unittest without the MCP SDK."""

import asyncio
import json
import unittest
from unittest.mock import patch

from synapse_showcase.host import CAPABILITIES, MAX_LINE, MAX_PENDING, StdioHost


class HostPipeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reader = asyncio.StreamReader(limit=MAX_LINE)
        self.requests = asyncio.Queue()

        async def send(line):
            await self.requests.put(json.loads(line))

        self.host = StdioHost(self.reader, send)
        start = asyncio.create_task(self.host.start())
        hello = await self.requests.get()
        self.assertEqual(hello["method"], "hello")
        self.reply(hello, {"version": 1, "capabilities": dict.fromkeys(CAPABILITIES, True)})
        await start

    async def asyncTearDown(self):
        await self.host.close()

    def reply(self, request, result):
        self.reader.feed_data((json.dumps({"id": request["id"], "result": result}) + "\n").encode())

    async def test_correlates_concurrent_replies_and_forwards_notices(self):
        changed = asyncio.Event()
        unsubscribe = self.host.subscribe(changed.set)
        first = asyncio.create_task(self.host.call("appStatus", {"app": "crm"}))
        second = asyncio.create_task(self.host.call("snapshot", {}))
        a, b = await self.requests.get(), await self.requests.get()
        self.reply(b, {"second": True})
        self.reply(a, {"first": True})
        self.assertEqual(await first, {"first": True})
        self.assertEqual(await second, {"second": True})
        self.reader.feed_data(b'{"event":"changed"}\n')
        await asyncio.wait_for(changed.wait(), 1)
        unsubscribe()
        changed.clear()
        self.reader.feed_data(b'{"event":"changed"}\n')
        await asyncio.sleep(0)
        self.assertFalse(changed.is_set())

    async def test_lost_mutation_reply_reports_unknown_outcome_without_retry(self):
        pending = asyncio.create_task(self.host.call("appInstall", {"app": "crm"}))
        await self.requests.get()
        self.reader.feed_eof()
        with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
            await pending
        await asyncio.wait_for(self.host.wait_closed(), 1)
        self.assertTrue(self.requests.empty())
        with self.assertRaisesRegex(RuntimeError, "no action was sent"):
            await self.host.call("appInstall", {})

    async def test_timeout_does_not_repeat_action_or_break_later_status(self):
        with (
            patch("synapse_showcase.host.DEADLINE_MARGIN", 0.02),
            patch.dict("synapse_showcase.host.DEADLINES", {"appLifecycle": 0.0}),
        ):
            action = asyncio.create_task(
                self.host.call("appLifecycle", {"app": "crm", "action": "stop"})
            )
            request = await self.requests.get()
            with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
                await action
        self.reply(request, {"stopped": True})
        status = asyncio.create_task(self.host.call("snapshot", {}))
        self.reply(await self.requests.get(), {"appJob": None})
        self.assertEqual(await status, {"appJob": None})
        self.assertTrue(self.requests.empty())

    async def test_installer_timeout_reply_keeps_the_channel_open(self):
        # The installer answers an expired call with an explicit error and keeps
        # the pipe open; the error reaches the caller and later calls still work.
        action = asyncio.create_task(self.host.call("appStatus", {"app": "crm"}))
        request = await self.requests.get()
        self.reader.feed_data(
            (
                json.dumps({"id": request["id"], "error": "The host operation timed out."}) + "\n"
            ).encode()
        )
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            await action
        status = asyncio.create_task(self.host.call("snapshot", {}))
        self.reply(await self.requests.get(), {"appJob": None})
        self.assertEqual(await status, {"appJob": None})

    def test_every_method_waits_longer_than_the_installer(self):
        from synapse_showcase.host import DEADLINE_MARGIN, DEADLINES, METHODS

        self.assertEqual(METHODS, frozenset(DEADLINES))
        self.assertGreater(DEADLINE_MARGIN, 0)
        self.assertGreaterEqual(DEADLINES["appStatus"], 90)
        self.assertGreaterEqual(DEADLINES["appLifecycle"], 150)

    async def test_unknown_methods_and_busy_channel_send_nothing(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            await self.host.call("operatorSetup", {})
        calls = [asyncio.create_task(self.host.call("snapshot", {})) for _ in range(MAX_PENDING)]
        requests = [await self.requests.get() for _ in calls]
        with self.assertRaisesRegex(RuntimeError, "busy"):
            await self.host.call("appInstall", {})
        self.assertTrue(self.requests.empty())
        for request in requests:
            self.reply(request, {})
        await asyncio.gather(*calls)

    async def test_malformed_response_and_oversized_line_close_channel(self):
        self.reader.feed_data(b'{"id":0,"result":{}}\n')
        await asyncio.wait_for(self.host.wait_closed(), 1)
        reader = asyncio.StreamReader(limit=MAX_LINE)
        host = StdioHost(reader, self.host._send)
        start = asyncio.create_task(host.start())
        await self.requests.get()
        reader.feed_data(b"x" * (MAX_LINE + 1) + b"\n")
        try:
            with self.assertRaisesRegex(RuntimeError, "invalid response"):
                await start
        finally:
            await host.close()

    async def test_handshake_rejects_unsupported_version(self):
        reader = asyncio.StreamReader(limit=MAX_LINE)
        host = StdioHost(reader, self.host._send)
        start = asyncio.create_task(host.start())
        request = await self.requests.get()
        reader.feed_data(
            (
                json.dumps(
                    {
                        "id": request["id"],
                        "result": {
                            "version": 2,
                            "capabilities": dict.fromkeys(CAPABILITIES, True),
                        },
                    }
                )
                + "\n"
            ).encode()
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "Unsupported"):
                await start
        finally:
            await host.close()


if __name__ == "__main__":
    unittest.main()
