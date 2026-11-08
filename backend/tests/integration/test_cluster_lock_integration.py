"""
ClusterLock against a real Postgres (DATABASE_URL). Two ClusterLock objects
with the same name stand in for two worker processes: each has its own
in-process lock, so only the advisory lock can make them wait for each other.

Run inside the backend container (needs the database):
    python -m unittest discover -s tests/integration -v
"""
import asyncio
import sys
import types
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

from cluster_lock import ClusterLock, ClusterLockTimeout  # noqa: E402

SHORT_WAIT_S = 0.5


def _name():
    return f"test.cluster_lock.{uuid.uuid4()}"


class ClusterLockIntegrationTests(unittest.TestCase):
    def test_second_worker_waits_until_first_releases(self):
        name = _name()

        async def scenario():
            a, b = ClusterLock(name), ClusterLock(name, wait_timeout_s=SHORT_WAIT_S)
            async with a:
                with self.assertRaises(ClusterLockTimeout):
                    async with b:
                        pass
            async with b:
                return "acquired after release"

        self.assertEqual(asyncio.run(scenario()), "acquired after release")

    def test_cancelled_waiter_does_not_leave_lock_held(self):
        name = _name()

        async def scenario():
            holder = ClusterLock(name)
            waiter = ClusterLock(name, wait_timeout_s=30)
            await holder.__aenter__()
            task = asyncio.create_task(waiter.__aenter__())
            await asyncio.sleep(0.3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await holder.__aexit__(None, None, None)
            await asyncio.sleep(0.6)  # let the cancelled attempt finish and undo itself
            third = ClusterLock(name, wait_timeout_s=SHORT_WAIT_S)
            async with third:
                return (waiter.locked(), "third acquired")

        self.assertEqual(asyncio.run(scenario()), (False, "third acquired"))


if __name__ == "__main__":
    unittest.main()
