"""
The shared Shopify GraphQL helper must never re-send a mutation whose outcome
is unknown (timeout, dropped connection, 5xx), while still retrying queries
and requests Shopify certainly rejected (429).

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

import aiohttp  # noqa: E402
import shopify_helper  # noqa: E402
from shopify_helper import ShopifyFetchError, _shopify_graphql  # noqa: E402

QUERY = "query { shop { name } }"
MUTATION = "\n  mutation orderMarkAsPaid($id: ID!) { orderMarkAsPaid(input: {id: $id}) { userErrors { message } } }"
OK_BODY = {"data": {"shop": {"name": "x"}}}


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status = status
        self._body = body or {}
        self.headers = headers or {}

    async def json(self):
        return self._body

    async def text(self):
        return ""


class FakeSession:
    """Plays back one outcome per call: an exception to raise or a response."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, *args, **kwargs):
        session = self

        class _Ctx:
            async def __aenter__(self_inner):
                session.calls += 1
                outcome = session.outcomes.pop(0)
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


def _connector_error():
    return aiohttp.ClientConnectorError(mock.Mock(), OSError(111, "Connection refused"))


def _run(session, query):
    async def no_sleep(_):
        return None

    with mock.patch.object(shopify_helper.asyncio, "sleep", no_sleep):
        return asyncio.run(_shopify_graphql(session, "test-shop.myshopify.com", "token", "2026-01", query))


class MutationRetryTests(unittest.TestCase):
    def test_query_timeout_is_retried(self):
        session = FakeSession([asyncio.TimeoutError(), FakeResponse(200, OK_BODY)])
        data, _ = _run(session, QUERY)
        self.assertEqual((data, session.calls), (OK_BODY["data"], 2))

    def test_mutation_timeout_is_not_resent(self):
        session = FakeSession([asyncio.TimeoutError(), FakeResponse(200, OK_BODY)])
        with self.assertRaises(ShopifyFetchError):
            _run(session, MUTATION)
        self.assertEqual(session.calls, 1)

    def test_mutation_server_error_is_not_resent(self):
        session = FakeSession([FakeResponse(502), FakeResponse(200, OK_BODY)])
        with self.assertRaises(ShopifyFetchError):
            _run(session, MUTATION)
        self.assertEqual(session.calls, 1)

    def test_mutation_rate_limit_is_retried(self):
        session = FakeSession([FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(200, OK_BODY)])
        data, _ = _run(session, MUTATION)
        self.assertEqual((data, session.calls), (OK_BODY["data"], 2))

    def test_mutation_connect_error_is_retried(self):
        session = FakeSession([_connector_error(), FakeResponse(200, OK_BODY)])
        data, _ = _run(session, MUTATION)
        self.assertEqual((data, session.calls), (OK_BODY["data"], 2))

    def test_query_server_error_is_retried(self):
        session = FakeSession([FakeResponse(503), FakeResponse(200, OK_BODY)])
        data, _ = _run(session, QUERY)
        self.assertEqual((data, session.calls), (OK_BODY["data"], 2))


if __name__ == "__main__":
    unittest.main()
