"""Smoke test against the real local cache; skipped when the cache has not been fetched."""

from pathlib import Path
import unittest

from dart_review.cache import ResponseCache
from dart_review.client import DartClient
from dart_review.companies import DEV_COMPANIES

CACHE = Path(__file__).resolve().parents[1] / "cache"
TARGET_ACCOUNTS = {
    "ifrs-full_Revenue", "dart_OperatingIncomeLoss", "ifrs-full_ProfitLoss",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs-full_Assets", "ifrs-full_Liabilities",
}


def no_key():
    raise AssertionError("the smoke test must not need the API key")


@unittest.skipUnless(CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class CacheSmokeTests(unittest.TestCase):
    def test_dev_companies_have_the_target_accounts_offline(self):
        client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)
        for corp_code in DEV_COMPANIES:
            for fs_div in ("CFS", "OFS"):
                with self.subTest(corp_code=corp_code, fs_div=fs_div):
                    response = client.financial_statements(corp_code, 2025, "11011", fs_div)
                    self.assertTrue(response.from_cache)
                    accounts = {row["account_id"] for row in response.json()["list"]}
                    self.assertLessEqual(TARGET_ACCOUNTS, accounts)
        self.assertEqual(client.network_requests, 0)


if __name__ == "__main__":
    unittest.main()
