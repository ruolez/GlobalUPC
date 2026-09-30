"""
Pure tests for lost_customers_merge.merge_reregistered (no database, no
network). A same-store re-registration is one person under two accounts: the
new account must be dated from the person's first purchase, whichever account
made it, or an existing customer is reported as newly acquired.

Run from /app inside the backend container:
    python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lost_customers_merge import merge_reregistered  # noqa: E402

OLD_ID = "gid://shopify/Customer/100"
SECOND_OLD_ID = "gid://shopify/Customer/101"
NEW_ID = "gid://shopify/Customer/200"
EARLY = "2024-03-05"
MIDDLE = "2025-01-10"
LATE = "2025-06-20"


def _moved(first, dest=NEW_ID, same_store=True, cid=OLD_ID):
    return {
        "customer_id": cid,
        "first_order_local": first,
        "moved_same_store": same_store,
        "moved_to_customer_id": dest,
    }


def _customer(first, cid=NEW_ID):
    return {"customer_id": cid, "first_order_local": first}


class MergeReregistered(unittest.TestCase):
    def test_new_account_takes_the_old_accounts_earlier_first_order(self):
        new = _customer(LATE)
        count = merge_reregistered([_moved(EARLY)], [new])
        self.assertEqual((count, new), (1, {**_customer(LATE), "merged_first_local": EARLY}))

    def test_new_account_keeps_its_own_first_order_when_it_is_earlier(self):
        new = _customer(EARLY)
        count = merge_reregistered([_moved(LATE)], [new])
        self.assertEqual((count, new), (1, {**_customer(EARLY), "merged_first_local": EARLY}))

    def test_earliest_of_several_old_accounts_wins(self):
        new = _customer(LATE)
        merge_reregistered(
            [_moved(MIDDLE), _moved(EARLY, cid=SECOND_OLD_ID)], [new])
        self.assertEqual(new["merged_first_local"], EARLY)

    def test_cross_store_moves_and_unlinked_rows_are_ignored(self):
        new = _customer(LATE)
        count = merge_reregistered(
            [_moved(EARLY, same_store=False), _moved(EARLY, dest=None)], [new])
        self.assertEqual((count, new), (0, _customer(LATE)))

    def test_old_account_with_unknown_first_order_leaves_new_account_dated_by_itself(self):
        new = _customer(LATE)
        count = merge_reregistered([_moved(None)], [new])
        self.assertEqual((count, new), (1, {**_customer(LATE), "merged_first_local": LATE}))

    def test_destination_outside_the_customer_list_stamps_nothing(self):
        other = _customer(LATE, cid=SECOND_OLD_ID)
        count = merge_reregistered([_moved(EARLY)], [other])
        self.assertEqual((count, other), (0, _customer(LATE, cid=SECOND_OLD_ID)))

    def test_merging_twice_gives_the_same_result(self):
        new = _customer(LATE)
        moved = [_moved(EARLY)]
        merge_reregistered(moved, [new])
        once = dict(new)
        merge_reregistered(moved, [new])
        self.assertEqual(new, once)


if __name__ == "__main__":
    unittest.main()
