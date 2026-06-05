import sqlite3
import unittest

from app_modules.routes.stock_valuation import (
    DEFAULT_FIELD_CONFIG,
    _clean_assumption_evidence,
    _merge_manual,
    build_industry_peer_stats,
    build_pb_history_stats,
    build_rule_based_valuation_guide,
    calculate_valuation,
    recommend_methods,
)
from app_modules.services.valuation_ai_coach import (
    fallback_ai_coach_response,
    fallback_assumption_review_response,
    normalize_assumption_review_response,
)
from app_modules.services.valuation_engine import CashFlowYear, DCFValuationEngine, WACCInputs
from app_modules.services.valuation_repository import ValuationCaseRepository


class HybridRow:
    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = tuple(values)
        self._map = dict(zip(columns, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __iter__(self):
        return iter(self._values)

    def keys(self):
        return self._columns


class StockValuationTests(unittest.TestCase):
    def test_default_field_config_has_ps_pcf_and_dividend_sources(self):
        valuation_cfg = DEFAULT_FIELD_CONFIG["valuation_table"]
        dividend_cfg = DEFAULT_FIELD_CONFIG["dividend_table"]

        self.assertEqual(valuation_cfg["ps_field"], "PSTTM")
        self.assertEqual(valuation_cfg["pcf_field"], "PCFTTM")
        self.assertEqual(dividend_cfg["table"], "LC_Dividend")
        self.assertEqual(dividend_cfg["inner_code_field"], "InnerCode")

    def test_calculate_relative_methods_from_current_multiples(self):
        facts = {
            "stock_code": "000001",
            "close_price": 10.0,
            "pe_ttm": 10.0,
            "pb": 1.0,
            "revenue_ps": 5.0,
            "dividend_ps": 0.3,
            "roe_ttm": 12.0,
            "third_industry": "银行",
        }
        result = calculate_valuation(
            facts,
            {
                "target_pe": 12,
                "target_pb": 1.2,
                "target_ps": 2,
                "target_dividend_yield": 0.03,
            },
        )
        methods = {item["method"]: item for item in result["methods"]}

        self.assertAlmostEqual(methods["pe"]["fair_price"], 12.0)
        self.assertAlmostEqual(methods["pb"]["fair_price"], 12.0)
        self.assertAlmostEqual(methods["ps"]["fair_price"], 10.0)
        self.assertAlmostEqual(methods["dividend"]["fair_price"], 10.0)
        self.assertGreaterEqual(result["summary"]["available_methods"], 4)

    def test_manual_fields_override_fetched_facts(self):
        facts, overrides = _merge_manual(
            {"stock_code": "000001", "close_price": 10.0, "pe_ttm": 10.0},
            {"close_price": "12.5", "third_industry": "半导体"},
        )

        self.assertEqual(facts["close_price"], 12.5)
        self.assertEqual(facts["third_industry"], "半导体")
        self.assertIn("close_price", overrides)

    def test_industry_peer_stats_builds_high_low_average(self):
        stats = build_industry_peer_stats(
            [
                {"stock_code": "000001", "stock_name": "甲", "pe_ttm": 10, "pb": 1.2, "roe_ttm": 8},
                {"stock_code": "000002", "stock_name": "乙", "pe_ttm": 20, "pb": 1.8, "roe_ttm": 12},
                {"stock_code": "000003", "stock_name": "丙", "pe_ttm": -5, "pb": 2.4, "roe_ttm": -3},
            ],
            industry_level="third",
            industry_name="测试行业",
            as_of="2026-06-03",
        )
        metrics = {item["key"]: item for item in stats["metrics"]}

        self.assertEqual(stats["sample_count"], 3)
        self.assertEqual(metrics["pe_ttm"]["min"], 10)
        self.assertEqual(metrics["pe_ttm"]["max"], 20)
        self.assertEqual(metrics["pe_ttm"]["avg"], 15)
        self.assertEqual(metrics["pe_ttm"]["count"], 2)
        self.assertEqual(metrics["pb"]["avg"], 1.8)
        self.assertEqual(metrics["roe_ttm"]["min"], -3)

    def test_recommendation_prefers_pb_for_financials(self):
        facts = {
            "close_price": 10.0,
            "pb": 1.0,
            "pe_ttm": 8.0,
            "roe_ttm": 0.12,
            "third_industry": "银行",
        }
        valuation = calculate_valuation(facts, {"target_pb": 1.2, "target_pe": 10})
        recommendations = recommend_methods(facts, valuation)

        self.assertEqual(recommendations[0]["method"], "pb")

    def test_rule_based_guide_builds_workflow_before_assumptions(self):
        facts = {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "close_price": 10.0,
            "pb": 1.0,
            "pe_ttm": 8.0,
            "roe_ttm": 12.0,
            "revenue_growth": 5.0,
            "third_industry": "银行",
            "quote_date": "2026-06-03",
            "valuation_date": "2026-06-03",
            "report_date": "2026-03-31",
            "pb_history": build_pb_history_stats(
                [{"valuation_date": f"2025-01-{(idx % 28) + 1:02d}", "pb": 0.8 + idx / 200} for idx in range(200)],
                current_pb=1.0,
            ),
        }
        valuation = calculate_valuation(facts, {"target_pb": 1.2, "target_pe": 10})
        recommendations = recommend_methods(facts, valuation)
        guide = build_rule_based_valuation_guide(facts, valuation, recommendations)

        self.assertEqual(guide["method_decision"]["primary_method"], "pb")
        self.assertIn("target_pb", guide["ui_assumptions"])
        self.assertEqual(guide["anchor_plan"]["anchor_field"], "target_pb")
        self.assertEqual(guide["anchor_plan"]["primary_fields"][0], "target_pb")
        self.assertGreaterEqual(len(guide["anchor_plan"]["factors"]), 4)
        self.assertIn("ROE", guide["anchor_plan"]["factors"][0]["label"])
        self.assertGreaterEqual(len(guide["anchor_plan"]["research_framework"]), 5)
        self.assertIn("周期定位", [item["title"] for item in guide["anchor_plan"]["research_framework"]])
        self.assertIn("PB 高低", guide["anchor_plan"]["pb_diagnostics"][0]["title"])
        self.assertIn("EV/EBITDA", [item["method"] for item in guide["anchor_plan"]["cross_checks"]])
        self.assertIn("target_pcf", guide["anchor_plan"]["secondary_fields"])
        self.assertEqual(guide["anchor_plan"]["process_steps"][0]["key"], "history_percentile")
        self.assertEqual(guide["anchor_plan"]["process_steps"][0]["status"], "done")
        self.assertIn("历史 PB", guide["anchor_plan"]["base_anchor"]["source"])
        self.assertGreaterEqual(len(guide["assumption_steps"]), 3)
        focus_steps = [row["key"] for row in guide["assumption_steps"] if row["key"] != "method"]
        self.assertLess(focus_steps.index("target_pb"), focus_steps.index("target_pe"))
        self.assertEqual([row["name"] for row in guide["scenarios"]], ["保守", "基准", "乐观"])
        self.assertIn("先确认主估值方法", guide["final_checklist"][0])

    def test_pb_history_stats_calculates_real_percentile(self):
        rows = [{"valuation_date": f"2025-01-{idx + 1:02d}", "pb": value} for idx, value in enumerate([1, 2, 3, 4])]
        history = build_pb_history_stats(rows, current_pb=2.5)

        self.assertEqual(history["sample_count"], 4)
        self.assertEqual(history["median"], 2.5)
        self.assertEqual(history["percentile"], 0.5)
        self.assertEqual(history["status"], "thin")

    def test_clean_assumption_evidence_keeps_pb_process_steps(self):
        cleaned = _clean_assumption_evidence({
            "target_pb": "历史分位低",
            "pb_step_cycle": "MDI 价格处于中性偏低",
            "random": "ignore",
        })

        self.assertIn("target_pb", cleaned)
        self.assertIn("pb_step_cycle", cleaned)
        self.assertNotIn("random", cleaned)

    def test_dcf_engine_splits_fcff_fcfe_and_wacc(self):
        engine = DCFValuationEngine()
        row = CashFlowYear(
            year=1,
            revenue=100,
            ebit=20,
            tax_rate=0.25,
            depreciation_amortization=5,
            capital_expenditure=8,
            change_in_working_capital=2,
            net_income=14,
            net_borrowing=3,
        )

        self.assertAlmostEqual(engine.fcff(row), 10.0)
        self.assertAlmostEqual(engine.fcfe(row), 12.0)
        wacc = engine.wacc(WACCInputs(debt_value=40, equity_value=60))
        self.assertAlmostEqual(wacc["debt_weight"], 0.4)
        self.assertAlmostEqual(wacc["equity_weight"], 0.6)

    def test_calculate_valuation_can_attach_detailed_dcf(self):
        result = calculate_valuation(
            {"stock_code": "000001", "close_price": 10.0},
            {
                "dcf_detail": {
                    "model": "fcff",
                    "base_revenue": 100,
                    "revenue_growth": 5,
                    "ebit_margin": 15,
                    "shares_outstanding": 10,
                    "debt_value": 20,
                    "equity_value": 80,
                }
            },
        )

        self.assertEqual(result["dcf_detail"]["model"], "fcff")
        self.assertIn("wacc", result["dcf_detail"])
        self.assertGreater(result["dcf_detail"]["enterprise_value"], 0)

    def test_repository_persists_full_workpaper_parts(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row

        class SharedConnection:
            def __init__(self, raw):
                self.raw = raw

            def cursor(self):
                return self.raw.cursor()

            def commit(self):
                self.raw.commit()

            def close(self):
                pass

        def connect(row_factory=None):
            conn.row_factory = row_factory
            return SharedConnection(conn)

        repo = ValuationCaseRepository(connect)
        case = repo.create_case(
            owner_user_id=1,
            stock_code="000001",
            stock_name="测试银行",
            valuation_date="2026-06-03",
            facts={"close_price": 10},
            warnings=[],
        )
        assumption = repo.upsert_assumption(
            case["id"],
            {"scenario_key": "base", "assumption_key": "target_pb", "value": 1.2, "user_logic": "ROE 稳定"},
        )
        assumption2 = repo.upsert_assumption(
            case["id"],
            {"scenario_key": "base", "assumption_key": "target_pb", "value": 1.1, "user_logic": "折价修正"},
        )
        msg = repo.add_ai_message(
            case["id"],
            {"role": "assistant", "content": "请补 ROE 证据", "payload": {"challenge_level": "medium"}},
        )
        scenario = repo.upsert_scenario(
            case["id"],
            {"scenario_key": "base", "name": "基准", "assumptions": {"target_pb": 1.1}},
        )
        repo.save_scenario_result(case["id"], "base", {"summary": {"blended_fair_price": 11}})
        loaded = repo.get_case(case["id"], owner_user_id=1)

        self.assertEqual(assumption["id"], assumption2["id"])
        self.assertEqual(assumption2["value"], 1.1)
        self.assertEqual(msg["payload"]["challenge_level"], "medium")
        self.assertEqual(scenario["assumptions"]["target_pb"], 1.1)
        self.assertEqual(len(loaded["ai_messages"]), 1)
        self.assertEqual(loaded["latest_results"][0]["result"]["summary"]["blended_fair_price"], 11)

        self.assertTrue(repo.delete_case(case["id"], owner_user_id=1))
        self.assertIsNone(repo.get_case(case["id"], owner_user_id=1))
        cur = conn.cursor()
        for table in (
            "stock_valuation_case_facts",
            "stock_valuation_method_decisions",
            "stock_valuation_assumptions",
            "stock_valuation_scenarios",
            "stock_valuation_scenario_results",
            "stock_valuation_ai_messages",
            "stock_valuation_counter_evidence",
            "stock_valuation_case_events",
        ):
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE case_id=?", (case["id"],))
            self.assertEqual(cur.fetchone()[0], 0, table)

    def test_repository_row_to_dict_handles_mysql_compat_rows(self):
        from app_modules.services import valuation_repository as repo_module

        row = HybridRow(["id", "stock_code", "state_json"], [1, "000001", "{}"])

        self.assertEqual(repo_module._row_to_dict(row)["stock_code"], "000001")
        state = repo_module.default_case_state(stock_code="000001")
        self.assertIn("workflow", state)
        self.assertEqual(state["workflow"]["unlocked_tabs"], ["profile"])

    def test_fallback_ai_coach_builds_questions_and_counter_evidence(self):
        coach = fallback_ai_coach_response(user_message="长期增长 8%", related_field="dcf_growth")

        self.assertEqual(coach["challenge_level"], "medium")
        self.assertGreaterEqual(len(coach["questions"]), 2)
        self.assertEqual(coach["counter_evidence"][0]["linked_assumption_key"], "dcf_growth")

    def test_fallback_assumption_review_flags_weak_assumptions_for_beginners(self):
        review = fallback_assumption_review_response(
            facts={"third_industry": "银行", "pb": 1.0, "roe_ttm": 6.0, "revenue_growth": 3.0},
            method_decision={"primary_method": "pb"},
            assumptions=[],
            ui_assumptions={"target_pb": 2.0, "dcf_growth": 10, "discount_rate": 7},
            user_logic="",
        )

        statuses = {item["field"]: item["status"] for item in review["assumption_reviews"]}
        self.assertEqual(review["review_status"], "high_risk")
        self.assertEqual(statuses["target_pb"], "too_optimistic")
        self.assertIn("bvps", statuses)
        self.assertNotIn("target_ps", statuses)
        self.assertGreaterEqual(len(review["evidence_todos"]), 1)
        self.assertIn("检查每个估值数字", review["beginner_explanation"])
        todo_titles = [item["title"] for item in review["evidence_todos"]]
        self.assertIn("补目标 PB 的历史分位", todo_titles)
        self.assertIn("验证净资产质量", todo_titles)
        self.assertIn("定位行业周期", todo_titles)
        self.assertIn("交叉验证 PB 结论", todo_titles)
        counter_titles = [item["title"] for item in review["counter_evidence"]]
        self.assertIn("周期高点低估值陷阱", counter_titles)
        self.assertIn("净资产折价", counter_titles)

    def test_normalize_assumption_review_keeps_required_frontend_fields(self):
        review = normalize_assumption_review_response(
            {
                "summary": "需要补证据",
                "overall_score": 66,
                "review_status": "needs_work",
                "assumption_reviews": [
                    {
                        "field": "target_pe",
                        "label": "目标 PE",
                        "status": "too_optimistic",
                        "plain_take": "偏乐观",
                    }
                ],
                "evidence_todos": [{"title": "查 PE 分位", "linked_field": "target_pe"}],
            }
        )

        self.assertEqual(review["overall_score"], 66)
        self.assertEqual(review["assumption_reviews"][0]["field"], "target_pe")
        self.assertEqual(review["assumption_reviews"][0]["suggested_action"], "补充证据后再确认该假设。")
        self.assertEqual(review["evidence_todos"][0]["priority"], "medium")


if __name__ == "__main__":
    unittest.main()
