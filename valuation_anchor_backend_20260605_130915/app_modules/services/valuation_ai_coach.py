# -*- coding: utf-8 -*-
"""AI coach helpers for stock valuation work papers."""
from __future__ import annotations

import json
from typing import Any, Callable


AI_COACH_SYSTEM_PROMPT = """你是内部投研系统里的股票估值教练，不是荐股机器人。

你的工作方式：
1. 你必须苛刻但有启发性。看到用户给出估值假设时，先判断它是否有事实证据，再追问薄弱环节。
2. 你不能直接替用户拍脑袋给结论。你要把假设拆成：事实依据、推理链、风险、反证条件、需要补的数据。
3. 你必须结合输入中的公司事实、行业、历史数据、方法选择和已有估值工作纸上下文。
4. 如果用户的假设和事实冲突，要明确指出冲突，例如“你给长期增长率 8%，但近三年收入增速中枢只有 4%，反转证据是什么？”
5. 你不能给买卖建议、目标收益承诺或确定性判断。只能输出估值假设质量、追问、反证条件和下一步验证动作。
6. 你要偏向让研究员自己补证据，而不是替他完成所有判断。

输出必须是 JSON 对象，不要 markdown。字段：
{
  "summary": "一句话反馈",
  "challenge_level": "low/medium/high",
  "questions": [
    {"question": "追问", "why": "为什么要问", "related_field": "assumption_key"}
  ],
  "evidence_gaps": [
    {"gap": "缺口", "suggested_source": "建议数据源或验证动作", "related_field": "assumption_key"}
  ],
  "counter_evidence": [
    {"title": "反证条件", "trigger_condition": "触发条件", "severity": "low/medium/high", "linked_assumption_key": "assumption_key"}
  ],
  "suggested_revision": {
    "field": "assumption_key",
    "value": null,
    "reason": "如果需要修正，解释原因；没有则为空"
  }
}
"""


AI_ASSUMPTION_REVIEW_SYSTEM_PROMPT = """你是一个给投资新手使用的股票估值假设审稿人。

你的目标不是给买卖建议，而是把“拍脑袋的估值参数”改造成“可验证的研究假设”。

工作要求：
1. 先看公司事实、数据质量、同行参考、估值方法和用户输入的假设。
2. 用新手能听懂的话解释：哪些假设最危险、为什么危险、应该补什么证据。
3. 对每个核心假设给出状态：pass / needs_evidence / too_optimistic / too_conservative / conflict / missing。
4. 不要输出确定性买卖结论、目标收益、荐股语言。
5. 所有建议都要落到下一步动作，例如查历史分位、找可比公司、核对财报、重算情景。
6. 如果证据不足，宁可降低结论强度，不要帮用户硬编理由。

输出必须是 JSON 对象，不要 markdown。字段：
{
  "summary": "一句话总评",
  "beginner_explanation": "给新手看的解释",
  "overall_score": 0,
  "confidence": "low/medium/high",
  "review_status": "pass/needs_work/high_risk",
  "key_risks": [
    {"title": "风险标题", "why_it_matters": "为什么重要", "severity": "low/medium/high"}
  ],
  "assumption_reviews": [
    {
      "field": "assumption_key",
      "label": "中文名",
      "value": "当前值",
      "status": "pass/needs_evidence/too_optimistic/too_conservative/conflict/missing",
      "plain_take": "一句人话判断",
      "evidence_needed": ["还缺什么证据"],
      "suggested_action": "下一步怎么做",
      "suggested_value": null,
      "reason": "判断依据"
    }
  ],
  "evidence_todos": [
    {"title": "待办", "source": "建议数据源", "linked_field": "assumption_key", "priority": "low/medium/high"}
  ],
  "counter_evidence": [
    {"title": "反证条件", "trigger_condition": "触发条件", "severity": "low/medium/high", "linked_assumption_key": "assumption_key"}
  ],
  "next_actions": ["下一步动作"]
}
"""


ASSUMPTION_LABELS = {
    "target_pe": "目标 PE",
    "target_pb": "目标 PB",
    "target_ps": "目标 PS",
    "target_pcf": "目标 PCF",
    "target_dividend_yield": "股息率锚",
    "dcf_growth": "DCF 增长率",
    "discount_rate": "折现率",
    "terminal_growth": "终值增长",
    "eps": "EPS",
    "bvps": "每股净资产",
    "cashflow_ps": "每股现金流",
    "dcf_years": "DCF 年数",
}

METHOD_REVIEW_FIELDS = {
    "dcf": ["dcf_growth", "discount_rate", "terminal_growth", "dcf_years", "cashflow_ps"],
    "pe": ["target_pe", "eps", "dcf_growth", "target_pb"],
    "pb": ["target_pb", "bvps", "target_pe", "target_dividend_yield"],
    "ps": ["target_ps", "dcf_growth", "target_pe", "target_pcf"],
    "pcf": ["target_pcf", "cashflow_ps", "target_pe", "dcf_growth"],
    "dividend": ["target_dividend_yield", "target_pb", "target_pe"],
}


_VALID_REVIEW_STATUSES = {
    "pass",
    "needs_evidence",
    "too_optimistic",
    "too_conservative",
    "conflict",
    "missing",
}

_VALID_CASE_STATUSES = {"pass", "needs_work", "high_risk"}
_VALID_LEVELS = {"low", "medium", "high"}


def build_ai_coach_messages(
    *,
    case_state: dict[str, Any],
    facts: dict[str, Any],
    method_decision: dict[str, Any],
    assumptions: list[dict[str, Any]],
    user_message: str,
    related_field: str = "",
) -> list[dict[str, str]]:
    payload = {
        "case_state": case_state or {},
        "facts": facts or {},
        "method_decision": method_decision or {},
        "assumptions": assumptions or [],
        "user_message": user_message,
        "related_field": related_field,
        "instructions": [
            "优先挑战 related_field 对应假设；如果为空，则先判断当前工作纸最薄弱假设。",
            "每个追问必须能推动用户补证据、改假设或明确反证条件。",
            "不要输出泛泛而谈的理论课。",
        ],
    }
    return [
        {"role": "system", "content": AI_COACH_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def call_ai_coach(
    call_json: Callable[..., Any],
    *,
    case_state: dict[str, Any],
    facts: dict[str, Any],
    method_decision: dict[str, Any],
    assumptions: list[dict[str, Any]],
    user_message: str,
    related_field: str = "",
) -> dict[str, Any]:
    messages = build_ai_coach_messages(
        case_state=case_state,
        facts=facts,
        method_decision=method_decision,
        assumptions=assumptions,
        user_message=user_message,
        related_field=related_field,
    )
    result = call_json(
        messages,
        temperature=0.16,
        max_tokens=2200,
        timeout=120,
        max_attempts=2,
        max_input_tokens=22000,
        log_prefix="stock_valuation_ai_coach",
    )
    if not isinstance(result, dict):
        raise ValueError("AI Coach 返回不是 JSON 对象")
    return normalize_ai_coach_response(result, related_field=related_field)


def normalize_ai_coach_response(raw: dict[str, Any], *, related_field: str = "") -> dict[str, Any]:
    questions = raw.get("questions") if isinstance(raw.get("questions"), list) else []
    gaps = raw.get("evidence_gaps") if isinstance(raw.get("evidence_gaps"), list) else []
    counter = raw.get("counter_evidence") if isinstance(raw.get("counter_evidence"), list) else []
    revision = raw.get("suggested_revision") if isinstance(raw.get("suggested_revision"), dict) else {}
    return {
        "summary": str(raw.get("summary") or "需要补充该假设的事实依据和反证条件。"),
        "challenge_level": str(raw.get("challenge_level") or "medium"),
        "questions": [
            {
                "question": str(item.get("question") or ""),
                "why": str(item.get("why") or ""),
                "related_field": str(item.get("related_field") or related_field),
            }
            for item in questions[:6]
            if isinstance(item, dict) and item.get("question")
        ],
        "evidence_gaps": [
            {
                "gap": str(item.get("gap") or ""),
                "suggested_source": str(item.get("suggested_source") or ""),
                "related_field": str(item.get("related_field") or related_field),
            }
            for item in gaps[:6]
            if isinstance(item, dict) and item.get("gap")
        ],
        "counter_evidence": [
            {
                "title": str(item.get("title") or ""),
                "trigger_condition": str(item.get("trigger_condition") or ""),
                "severity": str(item.get("severity") or "medium"),
                "linked_assumption_key": str(item.get("linked_assumption_key") or related_field),
            }
            for item in counter[:6]
            if isinstance(item, dict) and item.get("title")
        ],
        "suggested_revision": {
            "field": str(revision.get("field") or related_field),
            "value": revision.get("value"),
            "reason": str(revision.get("reason") or ""),
        },
    }


def _safe_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _level(value: Any, default: str = "medium") -> str:
    text = str(value or "").strip().lower()
    return text if text in _VALID_LEVELS else default


def _case_status(value: Any, default: str = "needs_work") -> str:
    text = str(value or "").strip().lower()
    return text if text in _VALID_CASE_STATUSES else default


def _review_status(value: Any, default: str = "needs_evidence") -> str:
    text = str(value or "").strip().lower()
    return text if text in _VALID_REVIEW_STATUSES else default


def _pct_display(value: Any) -> str:
    number = _safe_number(value)
    if number is None:
        return "-"
    return f"{number:.2f}%"


def _format_value(field: str, value: Any) -> str:
    if value is None or value == "":
        return "-"
    if field in {"dcf_growth", "discount_rate", "terminal_growth", "target_dividend_yield"}:
        return _pct_display(value)
    return str(value)


def _normalize_assumption_review(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    field = str(item.get("field") or item.get("assumption_key") or "").strip()
    if not field:
        return None
    label = str(item.get("label") or ASSUMPTION_LABELS.get(field) or field)
    return {
        "field": field,
        "label": label,
        "value": item.get("value"),
        "status": _review_status(item.get("status")),
        "plain_take": str(item.get("plain_take") or item.get("summary") or "这个假设还需要补证据。"),
        "evidence_needed": [str(x) for x in _as_list(item.get("evidence_needed"))[:5] if str(x or "").strip()],
        "suggested_action": str(item.get("suggested_action") or "补充证据后再确认该假设。"),
        "suggested_value": item.get("suggested_value"),
        "reason": str(item.get("reason") or ""),
    }


def normalize_assumption_review_response(raw: dict[str, Any], *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    base = fallback or {}
    reviews = [
        review
        for review in (_normalize_assumption_review(item) for item in _as_list(raw.get("assumption_reviews")))
        if review
    ]
    if not reviews:
        reviews = list(base.get("assumption_reviews") or [])
    key_risks = []
    for item in _as_list(raw.get("key_risks"))[:6]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        key_risks.append({
            "title": title,
            "why_it_matters": str(item.get("why_it_matters") or item.get("reason") or ""),
            "severity": _level(item.get("severity")),
        })
    evidence_todos = []
    for item in _as_list(raw.get("evidence_todos"))[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        evidence_todos.append({
            "title": title,
            "source": str(item.get("source") or item.get("suggested_source") or ""),
            "linked_field": str(item.get("linked_field") or item.get("related_field") or ""),
            "priority": _level(item.get("priority")),
        })
    counter = []
    for item in _as_list(raw.get("counter_evidence"))[:10]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        counter.append({
            "title": title,
            "trigger_condition": str(item.get("trigger_condition") or ""),
            "severity": _level(item.get("severity")),
            "linked_assumption_key": str(item.get("linked_assumption_key") or item.get("linked_field") or ""),
        })
    next_actions = [str(x) for x in _as_list(raw.get("next_actions"))[:8] if str(x or "").strip()]
    score = _safe_number(raw.get("overall_score"))
    if score is None:
        score = _safe_number(base.get("overall_score")) or 0
    return {
        "summary": str(raw.get("summary") or base.get("summary") or "假设需要补证据后再进入结论。"),
        "beginner_explanation": str(
            raw.get("beginner_explanation")
            or base.get("beginner_explanation")
            or "这一步是在检查估值数字是不是有事实支撑，不是判断股票能不能买。"
        ),
        "overall_score": max(0, min(100, round(score))),
        "confidence": _level(raw.get("confidence") or base.get("confidence"), "low"),
        "review_status": _case_status(raw.get("review_status") or base.get("review_status")),
        "key_risks": key_risks or list(base.get("key_risks") or []),
        "assumption_reviews": reviews,
        "evidence_todos": evidence_todos or list(base.get("evidence_todos") or []),
        "counter_evidence": counter or list(base.get("counter_evidence") or []),
        "next_actions": next_actions or list(base.get("next_actions") or []),
    }


def fallback_assumption_review_response(
    *,
    facts: dict[str, Any],
    method_decision: dict[str, Any],
    assumptions: list[dict[str, Any]],
    ui_assumptions: dict[str, Any] | None = None,
    user_logic: str = "",
) -> dict[str, Any]:
    ui = dict(ui_assumptions or {})
    for item in assumptions or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("assumption_key") or "").strip()
        if key and item.get("value") not in (None, ""):
            ui.setdefault(key, item.get("value"))

    logic_by_key = {
        str(item.get("assumption_key") or ""): str(item.get("user_logic") or "")
        for item in assumptions or []
        if isinstance(item, dict)
    }
    for key, value in ui.items():
        if str(key).startswith("pb_step_") and value not in (None, ""):
            logic_by_key[str(key)] = str(value)
    primary = str((method_decision or {}).get("selected_primary") or (method_decision or {}).get("primary_method") or "")
    industry = str(facts.get("third_industry") or facts.get("second_industry") or facts.get("first_industry") or "当前行业")
    growth_fact = _safe_number(facts.get("revenue_growth"))
    roe_fact = _safe_number(facts.get("roe_ttm"))
    current_pe = _safe_number(facts.get("pe_ttm"))
    current_pb = _safe_number(facts.get("pb"))
    current_ps = _safe_number(facts.get("ps_ttm"))
    current_pcf = _safe_number(facts.get("pcf_ttm"))
    price = _safe_number(facts.get("close_price"))
    peer_stats = facts.get("industry_peer_stats") if isinstance(facts.get("industry_peer_stats"), dict) else {}
    peer_metrics = {
        str(item.get("key")): item
        for item in peer_stats.get("metrics", [])
        if isinstance(item, dict) and item.get("key")
    }

    def review(field: str, value: Any, *, benchmark: float | None = None, fact_label: str = "", extra_reason: str = "") -> dict[str, Any]:
        number = _safe_number(value)
        label = ASSUMPTION_LABELS.get(field, field)
        has_logic = bool((logic_by_key.get(field) or user_logic or "").strip())
        status = "needs_evidence"
        plain = f"{label} 还需要证据支撑。"
        reason_parts = []
        if number is None:
            status = "missing"
            plain = f"{label} 还没有填，先不要让它进入结论。"
            reason_parts.append("缺少当前假设值")
        elif not has_logic:
            status = "needs_evidence"
            reason_parts.append("还没有写清楚这个数字从哪里来")
        else:
            status = "pass"
            plain = f"{label} 已有初步解释，但仍建议用历史和同行数据核对。"
        if benchmark and number is not None and benchmark > 0:
            ratio = number / benchmark
            if ratio >= 1.35:
                status = "too_optimistic"
                plain = f"{label} 明显高于当前参考，容易把估值抬得太乐观。"
                reason_parts.append(f"当前参考约 {benchmark:.2f}，你的假设约 {number:.2f}")
            elif ratio <= 0.65:
                status = "too_conservative"
                plain = f"{label} 明显低于当前参考，可能过于保守。"
                reason_parts.append(f"当前参考约 {benchmark:.2f}，你的假设约 {number:.2f}")
        if extra_reason:
            reason_parts.append(extra_reason)
        source_hint = f"查 {industry} 可比公司、历史分位和最近财报"
        if fact_label:
            source_hint = f"核对 {fact_label}，再查 {industry} 可比公司和历史分位"
        return {
            "field": field,
            "label": label,
            "value": _format_value(field, value),
            "status": status,
            "plain_take": plain,
            "evidence_needed": [
                "这个数字对应的历史区间或分位",
                "同行业可比公司的中位数/平均数",
                "最近财报中能支撑这个假设的事实",
            ],
            "suggested_action": source_hint,
            "suggested_value": None,
            "reason": "；".join(reason_parts) or "规则审稿未发现硬冲突，但证据仍需补齐。",
        }

    reviews: list[dict[str, Any]] = []
    target_fields = list(METHOD_REVIEW_FIELDS.get(primary) or ["target_pe", "target_pb", "dcf_growth"])
    anchor_plan = {}
    if isinstance((method_decision or {}).get("anchor_plan"), dict):
        anchor_plan = (method_decision or {}).get("anchor_plan") or {}
    for key in anchor_plan.get("primary_fields") or []:
        if key in ASSUMPTION_LABELS and key not in target_fields:
            target_fields.insert(0, key)
    for key in anchor_plan.get("secondary_fields") or []:
        if key in ASSUMPTION_LABELS and key not in target_fields:
            target_fields.append(key)
    for field in target_fields:
        value = ui.get(field)
        if value in (None, ""):
            if field == "eps" and price and current_pe and current_pe > 0:
                value = price / current_pe
            elif field == "bvps" and price and current_pb and current_pb > 0:
                value = price / current_pb
            elif field == "cashflow_ps" and price and current_pcf and current_pcf > 0:
                value = price / current_pcf
        benchmark = {
            "target_pe": current_pe,
            "target_pb": current_pb,
            "target_ps": current_ps,
            "target_pcf": current_pcf,
        }.get(field)
        extra = ""
        if field in {"eps", "bvps", "cashflow_ps"}:
            derived_label = {
                "eps": "PE",
                "bvps": "PB",
                "cashflow_ps": "PCF",
            }[field]
            extra = f"{ASSUMPTION_LABELS[field]} 是 {derived_label} 估值的底层口径，需确认不是由错误行情或估值倍数倒推。"
        if field == "dcf_growth":
            number = _safe_number(value)
            if number is not None and growth_fact is not None and number > max(8.0, growth_fact + 5.0):
                extra = f"收入增速参考约 {_format_value(field, growth_fact)}，DCF 增长率不宜无证据长期外推"
        if field == "target_pb" and roe_fact is not None and roe_fact < 8:
            extra = f"ROE 参考约 {roe_fact:.2f}%，低 ROE 公司给高 PB 要特别证明资产回报能改善"
        if field == "discount_rate":
            number = _safe_number(value)
            if number is not None and number < 8:
                extra = "折现率低于 8%，对成长和终值非常敏感，必须说明低风险来源"
        peer = peer_metrics.get({
            "target_pe": "pe_ttm",
            "target_pb": "pb",
            "target_ps": "ps_ttm",
            "target_pcf": "pcf_ttm",
        }.get(field, ""))
        if not benchmark and isinstance(peer, dict):
            benchmark = _safe_number(peer.get("avg"))
        item = review(field, value, benchmark=benchmark, fact_label=field, extra_reason=extra)
        if field == "dcf_growth" and extra:
            item["status"] = "too_optimistic"
            item["plain_take"] = "DCF 增长率高于当前基本面参考，不能直接长期外推。"
        if field == "discount_rate" and extra:
            item["status"] = "too_optimistic"
            item["plain_take"] = "折现率偏低，会让 DCF 结果显得过于乐观。"
        if field == "target_pb" and extra and item["status"] == "pass":
            item["status"] = "needs_evidence"
            item["plain_take"] = "ROE 偏弱时，PB 假设需要额外证明资产回报能改善。"
        if primary == "pb" and field in {"target_pe", "target_dividend_yield"} and item["status"] == "pass":
            item["plain_take"] = f"{item['label']} 可作为 PB 主锚的辅助验证，不应替代目标 PB。"
            item["reason"] = (item["reason"] + "；" if item["reason"] else "") + "当前主方法为 PB，此字段仅用于交叉验证"
        reviews.append(item)

    pb_research_todos: list[dict[str, str]] = []
    pb_counter: list[dict[str, str]] = []
    if primary == "pb":
        target_pb_value = _safe_number(ui.get("target_pb"))
        pb_logic = (logic_by_key.get("target_pb") or user_logic or "").strip()
        if target_pb_value is not None and current_pb and current_pb > 0:
            if "分位" not in pb_logic and "历史" not in pb_logic:
                pb_research_todos.append({
                    "title": "补目标 PB 的历史分位",
                    "source": "公司 5-10 年每日 PB 排序分位，再用同行 PB 中位/均值校验",
                    "linked_field": "target_pb",
                    "priority": "high",
                })
        else:
            pb_research_todos.append({
                "title": "先补当前 PB 和目标 PB 基准",
                "source": "行情估值表、同行估值表、历史 PB 分位",
                "linked_field": "target_pb",
                "priority": "high",
            })
        pb_research_todos.extend([
            item for item in [
                {
                    "title": "验证净资产质量",
                    "source": "拆固定资产、在建工程、存货、应收、商誉/无形资产、减值准备，并核对 ROE/ROIC 与杜邦分解",
                    "linked_field": "bvps",
                    "priority": "high",
                } if not logic_by_key.get("pb_step_asset_quality") else None,
                {
                    "title": "定位行业周期",
                    "source": "核心产品价格/价差、开工率、库存、下游需求、新增供给和正常化利润",
                    "linked_field": "target_pb",
                    "priority": "high",
                } if not logic_by_key.get("pb_step_cycle") else None,
                {
                    "title": "交叉验证 PB 结论",
                    "source": "EV/EBITDA、DCF、PE/PEG 或产能重置成本，至少两种方法侧面印证",
                    "linked_field": "target_pb",
                    "priority": "medium",
                } if not logic_by_key.get("pb_step_cross_check") else None,
            ] if item
        ])
        if not logic_by_key.get("pb_step_quality"):
            pb_research_todos.append({
                "title": "补质地结论",
                "source": "经营现金流/净利润、负债结构、ROIC、毛利稳定性、研发或成本曲线",
                "linked_field": "target_pb",
                "priority": "high",
            })
        if not logic_by_key.get("pb_step_target_pb") and not logic_by_key.get("target_pb"):
            pb_research_todos.append({
                "title": "写目标 PB 推导",
                "source": "历史 PB 分位、同行 PB、质地/周期/资产质量调整和失效条件",
                "linked_field": "target_pb",
                "priority": "high",
            })
        if roe_fact is None:
            pb_research_todos.append({
                "title": "补 ROE/ROIC 证据",
                "source": "最近财报、3-5 年 ROE/ROIC 中枢、杜邦分解",
                "linked_field": "target_pb",
                "priority": "high",
            })
        elif roe_fact < 8:
            pb_counter.append({
                "title": "低 ROE 推翻高 PB",
                "trigger_condition": "ROE/ROIC 连续两个报告期无法改善，或改善主要来自杠杆而非经营效率",
                "severity": "high",
                "linked_assumption_key": "target_pb",
            })
        if growth_fact is not None and growth_fact > 15 and roe_fact is not None and roe_fact < 10:
            pb_counter.append({
                "title": "增长不能转化为资产回报",
                "trigger_condition": "收入增长继续高于行业，但 ROE/ROIC 没有改善，说明扩张可能稀释回报",
                "severity": "medium",
                "linked_assumption_key": "target_pb",
            })
        pb_counter.extend([
            {
                "title": "周期高点低估值陷阱",
                "trigger_condition": "核心产品价格/价差或开工率从高位回落后，正常化 ROE 明显低于当前 ROE",
                "severity": "high",
                "linked_assumption_key": "target_pb",
            },
            {
                "title": "净资产折价",
                "trigger_condition": "出现大额固定资产/存货/应收/商誉减值，或在建工程转固后回报率低于资本成本",
                "severity": "high",
                "linked_assumption_key": "bvps",
            },
        ])

    weak_reviews = [item for item in reviews if item["status"] != "pass"]
    high_risk = [item for item in reviews if item["status"] in {"too_optimistic", "conflict", "missing"}]
    score = max(20, 88 - len(weak_reviews) * 9 - len(high_risk) * 6)
    review_status = "pass" if score >= 78 and not high_risk else "high_risk" if score < 52 or len(high_risk) >= 2 else "needs_work"
    if primary == "pb":
        summary = "PB 主锚已聚焦目标 PB 和每股净资产；请优先补 ROE、资产质量和同行位置证据。"
        if review_status != "pass":
            summary = "PB 主锚还没站稳，先补 ROE、资产质量和同行位置证据。"
    else:
        summary = "假设基本可进入情景测算。" if review_status == "pass" else "假设还没站稳，先补证据再下结论。"
    key_risks = []
    if high_risk:
        for item in high_risk[:3]:
            key_risks.append({
                "title": f"{item['label']} 风险",
                "why_it_matters": item["plain_take"],
                "severity": "high" if item["status"] in {"too_optimistic", "conflict"} else "medium",
            })
    if not key_risks:
        key_risks.append({
            "title": "证据链完整度",
            "why_it_matters": "估值不是把参数填进去就结束，关键是每个参数都能被复盘。",
            "severity": "medium",
        })
    evidence_todos = [
        {
            "title": f"补 {item['label']} 的证据",
            "source": "历史分位、同行可比、最近财报或研报摘录",
            "linked_field": item["field"],
            "priority": "high" if item["status"] in {"too_optimistic", "conflict", "missing"} else "medium",
        }
        for item in weak_reviews[:8]
    ]
    existing_todos = {(item["title"], item["linked_field"]) for item in evidence_todos}
    for item in pb_research_todos:
        key = (item["title"], item["linked_field"])
        if key not in existing_todos:
            evidence_todos.append(item)
            existing_todos.add(key)
    counter = [
        {
            "title": f"{item['label']} 失效",
            "trigger_condition": f"后续事实连续两个报告期无法支撑：{item['plain_take']}",
            "severity": "high" if item["status"] in {"too_optimistic", "conflict"} else "medium",
            "linked_assumption_key": item["field"],
        }
        for item in weak_reviews[:6]
    ]
    existing_counter = {(item["title"], item["linked_assumption_key"]) for item in counter}
    for item in pb_counter:
        key = (item["title"], item["linked_assumption_key"])
        if key not in existing_counter:
            counter.append(item)
            existing_counter.add(key)
    return {
        "summary": summary,
        "beginner_explanation": "你现在要做的不是判断股票涨跌，而是检查每个估值数字有没有来源。没有来源的数字，会让后面的安全边际看起来很精确，但其实不可复盘。",
        "overall_score": score,
        "confidence": "high" if score >= 78 else "medium" if score >= 58 else "low",
        "review_status": review_status,
        "key_risks": key_risks,
        "assumption_reviews": reviews,
        "evidence_todos": evidence_todos,
        "counter_evidence": counter,
        "next_actions": [
            "先补高优先级证据待办。",
            "PB 主锚要先回答质地、周期、净资产质量和历史分位，再进入情景测算。",
            "把过于乐观或缺失的假设改成悲观/基准/乐观三档。",
            "保存假设后再跑三情景，不要直接跳到结论。",
        ],
    }


def build_assumption_review_messages(
    *,
    case_state: dict[str, Any],
    facts: dict[str, Any],
    method_decision: dict[str, Any],
    assumptions: list[dict[str, Any]],
    ui_assumptions: dict[str, Any],
    user_logic: str = "",
) -> list[dict[str, str]]:
    payload = {
        "case_state": case_state or {},
        "facts": facts or {},
        "method_decision": method_decision or {},
        "saved_assumptions": assumptions or [],
        "current_ui_assumptions": ui_assumptions or {},
        "user_logic": user_logic or "",
        "assumption_labels": ASSUMPTION_LABELS,
        "instructions": [
            "给新手可执行的审稿结论，避免术语堆砌。",
            "每个关键估值参数都要判断是否有证据、是否和事实冲突、是否过度乐观。",
            "如果主方法是 PB，必须检查目标 PB 的自身 5-10 年历史分位、同行样本同质性、净资产稳定性、净资产质量、ROE/ROIC 和杜邦分解。",
            "如果主方法是 PB 且公司有周期/重资产特征，必须追问核心产品价格/价差、开工率、库存、供需、正常化利润，避免景气高点低估值陷阱。",
            "如果主方法是 PB，PE/PEG、EV/EBITDA、DCF、PCF、产能重置成本只能作为辅助验证或反证，不能替代 target_pb 和 bvps。",
            "质地较好的结论不能只依赖低估值和高 ROE/成长，还要补经营现金流/净利润、应收周转、毛利/净利稳定性、资产负债率、有息负债、利息保障倍数、资本开支/折旧、ROIC、研发投入、市场份额或成本曲线。",
            "证据待办必须具体到可以立刻去查的数据或资料。",
            "反证条件必须能被后续财报、同行数据或价格/估值数据验证。",
        ],
    }
    return [
        {"role": "system", "content": AI_ASSUMPTION_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def call_assumption_review(
    call_json: Callable[..., Any],
    *,
    case_state: dict[str, Any],
    facts: dict[str, Any],
    method_decision: dict[str, Any],
    assumptions: list[dict[str, Any]],
    ui_assumptions: dict[str, Any],
    user_logic: str = "",
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    messages = build_assumption_review_messages(
        case_state=case_state,
        facts=facts,
        method_decision=method_decision,
        assumptions=assumptions,
        ui_assumptions=ui_assumptions,
        user_logic=user_logic,
    )
    result = call_json(
        messages,
        temperature=0.14,
        max_tokens=3600,
        timeout=150,
        max_attempts=2,
        max_input_tokens=26000,
        log_prefix="stock_valuation_assumption_review",
    )
    if not isinstance(result, dict):
        raise ValueError("AI 假设审稿返回不是 JSON 对象")
    return normalize_assumption_review_response(result, fallback=fallback)


def fallback_ai_coach_response(*, user_message: str, related_field: str = "") -> dict[str, Any]:
    field = related_field or "当前假设"
    return {
        "summary": f"请先为 {field} 补充事实依据、推理链和反证条件。",
        "challenge_level": "medium",
        "questions": [
            {
                "question": f"{field} 的证据来自历史数据、可比公司、行业变化还是主观判断？",
                "why": "估值假设必须有可追踪证据，否则无法复盘。",
                "related_field": related_field,
            },
            {
                "question": "如果这个假设错了，哪个指标最先暴露问题？",
                "why": "反证条件决定估值结论是否可执行。",
                "related_field": related_field,
            },
        ],
        "evidence_gaps": [
            {
                "gap": "缺少该假设的历史区间、行业中枢或可比公司依据。",
                "suggested_source": "补历史财务趋势、估值分位或可比公司表。",
                "related_field": related_field,
            }
        ],
        "counter_evidence": [
            {
                "title": f"{field} 失效",
                "trigger_condition": "实际财务趋势连续两个报告期低于该假设对应的基础指标。",
                "severity": "medium",
                "linked_assumption_key": related_field,
            }
        ],
        "suggested_revision": {"field": related_field, "value": None, "reason": ""},
    }
