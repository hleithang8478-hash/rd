# -*- coding: utf-8 -*-
"""Core valuation math services.

This module keeps financial calculation logic separate from Flask routes and
templates.  The first production-grade piece is a DCF engine that can explain
the difference between FCFF and FCFE and expose the WACC derivation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _rate(value: Any, default: float | None = None) -> float | None:
    number = _num(value, default)
    if number is None:
        return default
    return number / 100.0 if abs(number) > 1.5 else number


def _round(value: Any, digits: int = 6) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


@dataclass
class WACCInputs:
    risk_free_rate: float = 0.025
    beta: float = 1.0
    market_risk_premium: float = 0.055
    cost_of_debt_pre_tax: float = 0.04
    tax_rate: float = 0.25
    debt_value: float = 0.0
    equity_value: float = 1.0


@dataclass
class CashFlowYear:
    year: int
    revenue: float = 0.0
    ebit: float = 0.0
    tax_rate: float = 0.25
    depreciation_amortization: float = 0.0
    capital_expenditure: float = 0.0
    change_in_working_capital: float = 0.0
    net_income: float = 0.0
    net_borrowing: float = 0.0


class DCFValuationEngine:
    """DCF math engine with explicit FCFF/FCFE and WACC branches."""

    engine_version = "dcf_engine_v1"

    def cost_of_equity(self, inputs: WACCInputs) -> float:
        return inputs.risk_free_rate + inputs.beta * inputs.market_risk_premium

    def after_tax_cost_of_debt(self, inputs: WACCInputs) -> float:
        return inputs.cost_of_debt_pre_tax * (1.0 - inputs.tax_rate)

    def wacc(self, inputs: WACCInputs) -> dict[str, Any]:
        debt = max(0.0, inputs.debt_value)
        equity = max(0.0, inputs.equity_value)
        capital = debt + equity
        if capital <= 0:
            debt_weight = 0.0
            equity_weight = 1.0
        else:
            debt_weight = debt / capital
            equity_weight = equity / capital
        coe = self.cost_of_equity(inputs)
        cod_after_tax = self.after_tax_cost_of_debt(inputs)
        value = equity_weight * coe + debt_weight * cod_after_tax
        return {
            "cost_of_equity": _round(coe),
            "after_tax_cost_of_debt": _round(cod_after_tax),
            "debt_weight": _round(debt_weight),
            "equity_weight": _round(equity_weight),
            "wacc": _round(value),
            "inputs": {key: _round(val) for key, val in asdict(inputs).items()},
        }

    def fcff(self, row: CashFlowYear) -> float:
        nopat = row.ebit * (1.0 - row.tax_rate)
        return nopat + row.depreciation_amortization - row.capital_expenditure - row.change_in_working_capital

    def fcfe(self, row: CashFlowYear) -> float:
        return (
            row.net_income
            + row.depreciation_amortization
            - row.capital_expenditure
            - row.change_in_working_capital
            + row.net_borrowing
        )

    def present_value(self, cash_flows: list[float], discount_rate: float) -> float:
        return sum(value / ((1.0 + discount_rate) ** idx) for idx, value in enumerate(cash_flows, start=1))

    def terminal_value(self, last_cash_flow: float, discount_rate: float, terminal_growth: float) -> float | None:
        if discount_rate <= terminal_growth:
            return None
        return last_cash_flow * (1.0 + terminal_growth) / (discount_rate - terminal_growth)

    def value_fcff(
        self,
        projection: list[CashFlowYear],
        *,
        wacc_inputs: WACCInputs,
        terminal_growth: float,
        net_debt: float = 0.0,
        shares_outstanding: float | None = None,
    ) -> dict[str, Any]:
        wacc_detail = self.wacc(wacc_inputs)
        discount_rate = float(wacc_detail["wacc"] or 0)
        cash_flows = [self.fcff(row) for row in projection]
        terminal = self.terminal_value(cash_flows[-1], discount_rate, terminal_growth) if cash_flows else None
        pv_cash_flows = self.present_value(cash_flows, discount_rate) if discount_rate > 0 else None
        pv_terminal = terminal / ((1.0 + discount_rate) ** len(cash_flows)) if terminal is not None and discount_rate > 0 else None
        enterprise_value = (pv_cash_flows or 0.0) + (pv_terminal or 0.0) if pv_cash_flows is not None else None
        equity_value = enterprise_value - net_debt if enterprise_value is not None else None
        per_share = equity_value / shares_outstanding if equity_value is not None and shares_outstanding else None
        return {
            "model": "fcff",
            "engine_version": self.engine_version,
            "cash_flows": [_round(value) for value in cash_flows],
            "wacc": wacc_detail,
            "terminal_growth": _round(terminal_growth),
            "terminal_value": _round(terminal),
            "present_value_cash_flows": _round(pv_cash_flows),
            "present_value_terminal": _round(pv_terminal),
            "enterprise_value": _round(enterprise_value),
            "net_debt": _round(net_debt),
            "equity_value": _round(equity_value),
            "per_share_value": _round(per_share),
            "projection": [asdict(row) for row in projection],
        }

    def value_fcfe(
        self,
        projection: list[CashFlowYear],
        *,
        cost_of_equity: float,
        terminal_growth: float,
        shares_outstanding: float | None = None,
    ) -> dict[str, Any]:
        cash_flows = [self.fcfe(row) for row in projection]
        terminal = self.terminal_value(cash_flows[-1], cost_of_equity, terminal_growth) if cash_flows else None
        pv_cash_flows = self.present_value(cash_flows, cost_of_equity) if cost_of_equity > 0 else None
        pv_terminal = terminal / ((1.0 + cost_of_equity) ** len(cash_flows)) if terminal is not None and cost_of_equity > 0 else None
        equity_value = (pv_cash_flows or 0.0) + (pv_terminal or 0.0) if pv_cash_flows is not None else None
        per_share = equity_value / shares_outstanding if equity_value is not None and shares_outstanding else None
        return {
            "model": "fcfe",
            "engine_version": self.engine_version,
            "cash_flows": [_round(value) for value in cash_flows],
            "cost_of_equity": _round(cost_of_equity),
            "terminal_growth": _round(terminal_growth),
            "terminal_value": _round(terminal),
            "present_value_cash_flows": _round(pv_cash_flows),
            "present_value_terminal": _round(pv_terminal),
            "equity_value": _round(equity_value),
            "per_share_value": _round(per_share),
            "projection": [asdict(row) for row in projection],
        }

    def projection_from_driver_assumptions(self, assumptions: dict[str, Any]) -> list[CashFlowYear]:
        years = int(_num(assumptions.get("years"), 5) or 5)
        years = max(1, min(years, 10))
        revenue = _num(assumptions.get("base_revenue"), 0.0) or 0.0
        growth = _rate(assumptions.get("revenue_growth"), 0.05) or 0.05
        ebit_margin = _rate(assumptions.get("ebit_margin"), 0.15) or 0.15
        tax_rate = _rate(assumptions.get("tax_rate"), 0.25) or 0.25
        depreciation_ratio = _rate(assumptions.get("depreciation_ratio"), 0.03) or 0.03
        capex_ratio = _rate(assumptions.get("capex_ratio"), 0.04) or 0.04
        wc_ratio = _rate(assumptions.get("working_capital_ratio"), 0.01) or 0.01
        net_margin = _rate(assumptions.get("net_margin"), ebit_margin * (1.0 - tax_rate)) or ebit_margin * (1.0 - tax_rate)
        net_borrowing_ratio = _rate(assumptions.get("net_borrowing_ratio"), 0.0) or 0.0

        rows: list[CashFlowYear] = []
        prev_revenue = revenue
        for year in range(1, years + 1):
            current_revenue = prev_revenue * (1.0 + growth)
            revenue_delta = current_revenue - prev_revenue
            rows.append(
                CashFlowYear(
                    year=year,
                    revenue=current_revenue,
                    ebit=current_revenue * ebit_margin,
                    tax_rate=tax_rate,
                    depreciation_amortization=current_revenue * depreciation_ratio,
                    capital_expenditure=current_revenue * capex_ratio,
                    change_in_working_capital=revenue_delta * wc_ratio,
                    net_income=current_revenue * net_margin,
                    net_borrowing=current_revenue * net_borrowing_ratio,
                )
            )
            prev_revenue = current_revenue
        return rows


def dcf_detail_from_assumptions(assumptions: dict[str, Any]) -> dict[str, Any]:
    """Calculate detailed DCF output when a route receives DCF driver assumptions."""
    dcf = assumptions.get("dcf_detail") if isinstance(assumptions.get("dcf_detail"), dict) else {}
    if not dcf:
        return {}
    engine = DCFValuationEngine()
    projection = engine.projection_from_driver_assumptions(dcf)
    terminal_growth = _rate(dcf.get("terminal_growth"), 0.02) or 0.02
    model = str(dcf.get("model") or "fcff").lower()
    shares = _num(dcf.get("shares_outstanding"))
    if model == "fcfe":
        cost_of_equity = _rate(dcf.get("cost_of_equity"), 0.09) or 0.09
        return engine.value_fcfe(
            projection,
            cost_of_equity=cost_of_equity,
            terminal_growth=terminal_growth,
            shares_outstanding=shares,
        )
    wacc_inputs = WACCInputs(
        risk_free_rate=_rate(dcf.get("risk_free_rate"), 0.025) or 0.025,
        beta=_num(dcf.get("beta"), 1.0) or 1.0,
        market_risk_premium=_rate(dcf.get("market_risk_premium"), 0.055) or 0.055,
        cost_of_debt_pre_tax=_rate(dcf.get("cost_of_debt_pre_tax"), 0.04) or 0.04,
        tax_rate=_rate(dcf.get("tax_rate"), 0.25) or 0.25,
        debt_value=_num(dcf.get("debt_value"), 0.0) or 0.0,
        equity_value=_num(dcf.get("equity_value"), 1.0) or 1.0,
    )
    return engine.value_fcff(
        projection,
        wacc_inputs=wacc_inputs,
        terminal_growth=terminal_growth,
        net_debt=_num(dcf.get("net_debt"), 0.0) or 0.0,
        shares_outstanding=shares,
    )
