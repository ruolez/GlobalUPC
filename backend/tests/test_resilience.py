"""
Pure tests for the stability building blocks: MSSQL connection wrappers,
per-store deadlines, session release, the Shopify mutation retry rule and
the cluster-lock key. No database or network needed.

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

import mssql_helper  # noqa: E402
from database import release_db  # noqa: E402
from cluster_lock import lock_key  # noqa: E402

LOGIN_TIMEOUT = 15
QUERY_TIMEOUT = 42


class FakeConn:
    def __init__(self, autocommit=False):
        self.autocommit = autocommit
        self.timeout = 0
        self.calls = []

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


def _patch_connect(conn):
    seen = {}

    def fake_connect(conn_string, timeout=None, **kwargs):
        seen.update(conn_string=conn_string, timeout=timeout, kwargs=kwargs)
        return conn

    return mock.patch.object(mssql_helper.pyodbc, "connect", fake_connect, create=True), seen


class MssqlOpenTests(unittest.TestCase):
    def test_sets_login_and_query_timeout(self):
        conn = FakeConn()
        patcher, seen = _patch_connect(conn)
        with patcher:
            got = mssql_helper.mssql_open("DSN", timeout=LOGIN_TIMEOUT, query_timeout=QUERY_TIMEOUT)
        self.assertEqual((got.timeout, seen["timeout"]), (QUERY_TIMEOUT, LOGIN_TIMEOUT))

    def test_default_query_timeout_is_module_setting(self):
        conn = FakeConn()
        patcher, _ = _patch_connect(conn)
        with patcher:
            got = mssql_helper.mssql_open("DSN")
        self.assertEqual(got.timeout, mssql_helper.MSSQL_QUERY_TIMEOUT)

    def test_passes_extra_kwargs(self):
        conn = FakeConn()
        patcher, seen = _patch_connect(conn)
        with patcher:
            mssql_helper.mssql_open("DSN", autocommit=False)
        self.assertEqual(seen["kwargs"], {"autocommit": False})


class MssqlConnectTests(unittest.TestCase):
    """Same block semantics as `with pyodbc.connect(...)`, plus close()."""

    def test_success_commits_then_closes(self):
        conn = FakeConn()
        patcher, _ = _patch_connect(conn)
        with patcher:
            with mssql_helper.mssql_connect("DSN") as c:
                c.calls.append("work")
        self.assertEqual(conn.calls, ["work", "commit", "close"])

    def test_exception_rolls_back_closes_and_reraises(self):
        conn = FakeConn()
        patcher, _ = _patch_connect(conn)
        with patcher, self.assertRaises(ValueError):
            with mssql_helper.mssql_connect("DSN"):
                raise ValueError("boom")
        self.assertEqual(conn.calls, ["rollback", "close"])

    def test_autocommit_connection_is_not_committed(self):
        conn = FakeConn(autocommit=True)
        patcher, _ = _patch_connect(conn)
        with patcher:
            with mssql_helper.mssql_connect("DSN"):
                pass
        self.assertEqual(conn.calls, ["close"])

    def test_early_return_still_commits_and_closes(self):
        conn = FakeConn()
        patcher, _ = _patch_connect(conn)

        def use():
            with mssql_helper.mssql_connect("DSN"):
                return "early"

        with patcher:
            result = use()
        self.assertEqual((result, conn.calls), ("early", ["commit", "close"]))


class WithDeadlineTests(unittest.TestCase):
    def test_passes_result_through_when_in_time(self):
        async def fast():
            return (True, None, ["row"])

        got = asyncio.run(mssql_helper.with_deadline(fast(), 1, "S2S"))
        self.assertEqual(got, (True, None, ["row"]))

    def test_timeout_returns_store_error_tuple(self):
        async def slow():
            await asyncio.sleep(5)

        got = asyncio.run(mssql_helper.with_deadline(slow(), 0.05, "S2S"))
        self.assertEqual(got, (False, "S2S: timed out after 0s", None))

    def test_timeout_pads_to_requested_width(self):
        async def slow():
            await asyncio.sleep(5)

        got = asyncio.run(mssql_helper.with_deadline(slow(), 0.05, "TS Shopify", width=4))
        self.assertEqual(got, (False, "TS Shopify: timed out after 0s", None, None))

    def test_helper_exception_is_not_swallowed(self):
        async def broken():
            raise RuntimeError("bug")

        with self.assertRaises(RuntimeError):
            asyncio.run(mssql_helper.with_deadline(broken(), 1, "S2S"))


class ReleaseDbTests(unittest.TestCase):
    def test_commits_without_expiring_and_restores_setting(self):
        session = mock.Mock()
        session.expire_on_commit = True
        seen = {}
        session.commit.side_effect = lambda: seen.setdefault("expire_during_commit", session.expire_on_commit)
        release_db(session)
        self.assertEqual((seen["expire_during_commit"], session.expire_on_commit), (False, True))

    def test_restores_setting_when_commit_fails(self):
        session = mock.Mock()
        session.expire_on_commit = True
        session.commit.side_effect = RuntimeError("db down")
        with self.assertRaises(RuntimeError):
            release_db(session)
        self.assertTrue(session.expire_on_commit)


class LockKeyTests(unittest.TestCase):
    def test_key_is_stable_signed_64_bit(self):
        k = lock_key("order_sync_fix.price_bump")
        self.assertEqual((k, -(2 ** 63) <= k < 2 ** 63), (lock_key("order_sync_fix.price_bump"), True))

    def test_different_names_get_different_keys(self):
        self.assertNotEqual(lock_key("order_sync_fix.price_bump"), lock_key("order_sync_fix.create_product"))


if __name__ == "__main__":
    unittest.main()
