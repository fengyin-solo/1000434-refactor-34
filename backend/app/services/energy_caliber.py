"""能耗管理共用口径：填报字段、派生指标、统计卡片与状态流转判断都收拢在这里。

服务层、路由层、示例数据与本地自检脚本都只准引用这里的实现，避免同一套口径
在不同地方各写一遍后对不上。涉及的口径约定：

- 统计日期：YYYY-MM-DD，按自然月归集「本月」卡片；无法解析的日期不进本月统计。
- 用电量：当日总用电量，单位 kWh，填报时必填。
- 处理水量：当日实际处理水量，单位 吨（m³），用于吨水电耗与药剂单耗。
- 药剂用量：当日药剂总耗量，单位 kg。
- 单位电耗 = 用电量 / 设计日处理水量，kWh/吨，按设计规模归一，缺水量也能算。
- 吨水电耗 = 用电量 / 实际处理水量，kWh/吨，按当日实际水量计算。
- 药剂单耗 = 药剂用量 / 实际处理水量，kg/吨。
- 卡片只统计当月、且已离开待填报状态（已填报/已复核/有争议）的记录；
  吨水电耗均值与药剂单耗都用「当月总量相除」的加权口径，不做逐日简单平均。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

MODULE = "energy"

# ---- 字段口径 ----------------------------------------------------------------
KEY_FIELD = "记录编号"
DATE_FIELD = "统计日期"
POWER_FIELD = "用电量"          # kWh，当日总用电量
WATER_FIELD = "处理水量"        # 吨，当日实际处理水量
CHEM_FIELD = "药剂用量"         # kg，当日药剂总耗量
UNIT_POWER_FIELD = "单位电耗"   # kWh/吨，按设计日处理水量归一
CHEM_INTENSITY_FIELD = "药剂单耗"  # kg/吨，按实际处理水量计算
TON_POWER_FIELD = "吨水电耗"    # kWh/吨，按实际处理水量计算
OPERATOR_FIELD = "记录人员"
STATUS_FIELD = "记录状态"

REQUIRED_FIELDS = [KEY_FIELD, DATE_FIELD, POWER_FIELD]
OPTIONAL_FIELDS = [WATER_FIELD, CHEM_FIELD, OPERATOR_FIELD]
RAW_FIELDS = [
    KEY_FIELD, DATE_FIELD, POWER_FIELD, WATER_FIELD,
    CHEM_FIELD, OPERATOR_FIELD,
]
LIST_FIELDS = [
    KEY_FIELD, DATE_FIELD, POWER_FIELD, WATER_FIELD, UNIT_POWER_FIELD,
    CHEM_FIELD, CHEM_INTENSITY_FIELD, TON_POWER_FIELD,
    OPERATOR_FIELD, STATUS_FIELD,
]

# ---- 状态与动作口径 ----------------------------------------------------------
STATUS_DRAFT = "待填报"
STATUS_FILLED = "已填报"
STATUS_REVIEWED = "已复核"
STATUS_DISPUTED = "有争议"
STATUSES = [STATUS_DRAFT, STATUS_FILLED, STATUS_REVIEWED, STATUS_DISPUTED]

ACTION_SUBMIT = "提交填报"
ACTION_REVIEW = "复核确认"
ACTION_DISPUTE = "标记争议"
ACTION_RULES = {
    ACTION_SUBMIT: STATUS_FILLED,
    ACTION_REVIEW: STATUS_REVIEWED,
    ACTION_DISPUTE: STATUS_DISPUTED,
}
# 负向动作：执行后记录计入异常量；被填报/复核覆盖时异常量要同步清掉。
NEGATIVE_ACTIONS = [ACTION_DISPUTE]

# 仍需跟进的状态：有争议不能因为排在状态序列末尾就被当成已办结。
PENDING_STATUSES = {STATUS_DRAFT, STATUS_FILLED, STATUS_DISPUTED}
# 进入统计卡片的状态：待填报只是草稿，不计入已报数据。
REPORTABLE_STATUSES = {STATUS_FILLED, STATUS_REVIEWED, STATUS_DISPUTED}
# 允许复核的状态：填报后或争议处理后才能复核。
REVIEWABLE_STATUSES = {STATUS_FILLED, STATUS_DISPUTED}

# ---- 数值口径 ----------------------------------------------------------------
DESIGN_WATER_DAILY = 50000.0  # 设计日处理水量，吨/日
POWER_DECIMALS = 3            # 电耗类指标保留 3 位小数
CHEM_DECIMALS = 4             # 药剂单耗量级小，保留 4 位小数

CARD_POWER = "本月用电量"
CARD_TON_POWER = "吨水电耗均值"
CARD_CHEM = "药剂单耗"
EMPTY_STATS_MESSAGE = "本月暂无已填报、已复核或有争议的能耗记录，统计卡片按 0 展示"


# ---- 解析与取整 --------------------------------------------------------------
def parse_date(value: Any) -> date | None:
    """把统计日期解析成 date；只接受 YYYY-MM-DD，非法或缺失返回 None。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_number(value: Any) -> float | None:
    """解析用电量/水量/药剂用量；非数值、空值或负数返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    return number if number >= 0 else None


def quantize(value: float, decimals: int) -> float:
    """四舍五入到指定小数位（ROUND_HALF_UP，避免银行家舍入造成口径偏差）。"""
    quantum = Decimal(1).scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


# ---- 派生指标（单条记录） -----------------------------------------------------
def unit_power_consumption(power: float) -> float:
    """单位电耗 = 用电量 / 设计日处理水量，kWh/吨。"""
    return quantize(power / DESIGN_WATER_DAILY, POWER_DECIMALS)


def ton_water_power_consumption(power: float, water: float) -> float | None:
    """吨水电耗 = 用电量 / 实际处理水量，kWh/吨；水量为 0/缺失时不可计算。"""
    if water <= 0:
        return None
    return quantize(power / water, POWER_DECIMALS)


def chemical_intensity(chem: float, water: float) -> float | None:
    """药剂单耗 = 药剂用量 / 实际处理水量，kg/吨；水量为 0/缺失时不可计算。"""
    if water <= 0:
        return None
    return quantize(chem / water, CHEM_DECIMALS)


def derived_metrics(row: dict[str, Any]) -> dict[str, float | None]:
    """按共用口径补出一条记录的三项派生指标；原始量缺失时对应指标为 None。"""
    power = parse_number(row.get(POWER_FIELD))
    water = parse_number(row.get(WATER_FIELD))
    chem = parse_number(row.get(CHEM_FIELD))
    return {
        UNIT_POWER_FIELD: unit_power_consumption(power) if power is not None else None,
        TON_POWER_FIELD: (
            ton_water_power_consumption(power, water)
            if power is not None and water is not None else None
        ),
        CHEM_INTENSITY_FIELD: (
            chemical_intensity(chem, water)
            if chem is not None and water is not None else None
        ),
    }


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """列表/明细/导出统一出口：补派生指标，并把 status 映射成「记录状态」列。"""
    item = dict(row)
    item.update(derived_metrics(item))
    item[STATUS_FIELD] = item.get("status")
    return item


# ---- 统计卡片口径 -------------------------------------------------------------
def _month_start(today: date) -> date:
    return today.replace(day=1)


def _is_current_month(value: Any, month_start: date, next_month_start: date) -> bool:
    day = parse_date(value)
    return day is not None and month_start <= day < next_month_start


def summarize(rows: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    """汇总当月已报记录，返回页面卡片所需数字。

    口径：本月用电量=Σ用电量；吨水电耗均值=Σ用电量/Σ处理水量；
    药剂单耗=Σ药剂用量/Σ处理水量。待填报草稿、缺原始量的记录不参与对应汇总，
    没有可统计记录时三项都给 0，并在 message 里说明原因。
    """
    today = today or date.today()
    month_start = _month_start(today)
    next_month_start = (month_start + timedelta(days=32)).replace(day=1)

    selected = [
        row for row in rows
        if row.get("status") in REPORTABLE_STATUSES
        and _is_current_month(row.get(DATE_FIELD), month_start, next_month_start)
    ]
    total_power = 0.0
    total_water = 0.0
    total_chem = 0.0
    for row in selected:
        power = parse_number(row.get(POWER_FIELD))
        water = parse_number(row.get(WATER_FIELD))
        chem = parse_number(row.get(CHEM_FIELD))
        if power is not None:
            total_power += power
        if water is not None:
            total_water += water
        if chem is not None:
            total_chem += chem

    if not selected:
        cards = [
            {"label": CARD_POWER, "value": 0},
            {"label": CARD_TON_POWER, "value": 0},
            {"label": CARD_CHEM, "value": 0},
        ]
        return {"cards": cards, "total": 0, "message": EMPTY_STATS_MESSAGE}

    cards = [
        {"label": CARD_POWER, "value": quantize(total_power, POWER_DECIMALS)},
        {
            "label": CARD_TON_POWER,
            "value": ton_water_power_consumption(total_power, total_water) or 0,
        },
        {
            "label": CARD_CHEM,
            "value": chemical_intensity(total_chem, total_water) or 0,
        },
    ]
    return {"cards": cards, "total": len(selected), "message": ""}


# ---- 状态流转判断（填报/复核共用） --------------------------------------------
def decide_action(entry: dict[str, Any], action: str) -> tuple[str | None, str]:
    """判断一条能耗记录能否执行某个动作，返回 (目标状态, 错误说明)。

    目标状态为 None 表示拦下并附一句可读原因；空数据、重复复核这类情况都要在
    这里给出说明，而不是让调用方各自判断。
    """
    if action not in ACTION_RULES:
        return None, f"动作「{action}」不属于能耗管理可执行范围"
    target = ACTION_RULES[action]
    if target not in STATUSES:
        return None, f"目标状态「{target}」不在允许的状态序列里"

    current = entry.get("status")
    if action == ACTION_SUBMIT:
        if current == STATUS_DRAFT:
            return target, ""
        if current == STATUS_DISPUTED:
            return None, "能耗记录存在争议，请先复核确认或补充说明后再处理"
        return None, f"能耗记录已处于「{current}」，无需重复提交填报"

    if action == ACTION_REVIEW:
        if current == STATUS_REVIEWED:
            return None, "能耗记录已复核，请勿重复复核"
        if current == STATUS_DRAFT:
            return None, "能耗记录尚未提交填报，请先提交填报再复核"
        return target, ""

    # 标记争议沿用原流程：任何状态都可以翻案；已复核被翻案后进入争议，
    # pending/abnormal 在 apply_action 里统一重算，再次复核即可重新定稿。
    return target, ""


def apply_action(entry: dict[str, Any], action: str) -> tuple[dict[str, Any] | None, str]:
    """按共用判断执行状态流转，并同步 pending/abnormal 标记。"""
    target, error = decide_action(entry, action)
    if target is None:
        return None, error
    entry["status"] = target
    entry["pending"] = target in PENDING_STATUSES
    entry["abnormal"] = action in NEGATIVE_ACTIONS
    return entry, f"能耗记录已{action}"
