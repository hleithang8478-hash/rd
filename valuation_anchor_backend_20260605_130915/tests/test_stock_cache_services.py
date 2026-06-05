import sqlite3
import unittest

from app_modules.services.stock_master_cache import (
    search_stock_master,
    upsert_stock_master_cache,
)
from app_modules.services.valuation_fact_cache import (
    cached_or_fetch_valuation_facts,
    field_config_hash,
)


class SharedConnection:
    def __init__(self, raw):
        self.raw = raw

    def cursor(self):
        return self.raw.cursor()

    def execute(self, sql, args=()):
        return self.raw.execute(sql, args)

    def executemany(self, sql, seq_of_args):
        return self.raw.executemany(sql, seq_of_args)

    def commit(self):
        self.raw.commit()

    def close(self):
        pass


class StockCacheServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def connect(self, row_factory=None):
        self.conn.row_factory = row_factory
        return SharedConnection(self.conn)

    def test_stock_master_search_uses_cache_before_fallback(self):
        upsert_stock_master_cache(
            self.connect,
            [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "InnerCode": "1",
                    "CompanyCode": "10",
                    "ThirdIndustryName": "银行",
                }
            ],
        )
        calls = {"count": 0}

        def fail_fetcher():
            calls["count"] += 1
            raise AssertionError("fallback should not run on cache hit")

        result = search_stock_master(self.connect, "000001", fetcher_factory=fail_fetcher)

        self.assertTrue(result["cache_hit"])
        self.assertEqual(result["stocks"][0]["name"], "平安银行")
        self.assertEqual(calls["count"], 0)

    def test_valuation_fact_cache_reuses_successful_fetch(self):
        calls = {"count": 0}

        def fetcher():
            calls["count"] += 1
            return {"success": True, "facts": {"stock_code": "000001", "close_price": 10}, "warnings": ["ok"]}

        cfg_hash = field_config_hash({"stock_table": {"table": "SecuMain"}})
        first = cached_or_fetch_valuation_facts(
            self.connect,
            fetcher,
            stock_code="000001",
            as_of="2026-06-05",
            config_hash=cfg_hash,
        )
        second = cached_or_fetch_valuation_facts(
            self.connect,
            fetcher,
            stock_code="000001",
            as_of="2026-06-05",
            config_hash=cfg_hash,
        )

        self.assertEqual(calls["count"], 1)
        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertEqual(second["facts"]["close_price"], 10)


if __name__ == "__main__":
    unittest.main()
