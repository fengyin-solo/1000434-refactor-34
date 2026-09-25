"""能耗管理共用实现。

统计口径（统计日期、单位电耗、药剂单耗、吨水电耗）与状态流转判断（填报、复核、
争议）全部收在这里：服务层、统计接口、本地自检 scripts/selfcheck.py 都调用同一份
代码，避免同一套判断写两遍、示例数据写死口径。

口径说明
--------
- 统计日期：YYYY-MM-DD，只有能解析成日期的记录才进入「本月」统计。
- 单位电耗（单条）= 当日用电量(kWh) / 当日处理水量(t)，保留 3 位小数。
- 药剂单耗（单条）= 当日药剂用量(kg) / 当日处理水量(t)，保留 3 位小数。
- 吨水电耗（期间）= 期间总用电量 / 期间总处理水量，保留 3 位小数；
  处理水量缺失或为 0 时无法计算，返回 None（页面显示「—」）。
- 统计只计入已正式上报的记录（已填报、已复核）；待填报缺数据、有争议数据待核实，
  都不进入本月口径。
"""
from __future__ import annotations

from datetime import date
from typing import Any

# 状态与动作：填报/复核/争议的唯一判断来源，服务层和自检都不许再各写一份。
STATUS_PENDING = "待填报"
STATUS_FILED = "已填报"
STATUS_REVIEWED = "已复核"
STATUS_DISPUTED = "有争议"
STATUSES = [STATUS_PENDING, STATUS_FILED, STATUS_REVIEWED, STATUS_DISPUTED]

ACTION_FILE = "提交填报"
ACTION_REVIEW = "复核确认"
ACTION_DISPUTE = "标记争议"
ACTION_RULES = {
    ACTION_FILE: STATUS_FILED,
    ACTION_REVIEW: STATUS_REVIEWED,
    ACTION_DISPUTE: STATUS_DISPUTED,
}

# 允许的状态迁移：键是当前状态，值是该状态下允许执行的动作。
# 终态复核后只能转争议；争议需重新填报；重复填报、重复复核都在这里被拦下。
TRANSITIONS: dict[str, set[str]] = {
    STATUS_PENDING: {ACTION_FILE},
    STATUS_FILED: {ACTION_REVIEW, ACTION_DISPUTE},
    STATUS_REVIEWED: {ACTION_DISPUTE},
    STATUS_DISPUTED: {ACTION_FILE},
}
# 负向动作：执行后计入异常量；异常一旦标记会保留，后续复核也不清除。
NEGATIVE_ACTIONS = [ACTION_DISPUTE]

# 进入本月统计的状态（正式上报口径）。
COUNTED_STATUSES = {STATUS_FILED, STATUS_REVIEWED}

# 待处理：复核与争议都需要继续跟进，所以这两种状态 pending=True。
PENDING_STATUSES = {STATUS_PENDING, STATUS_FILED, STATUS_DISPUTED}

WATER_FIELD = "处理水量"
POWER_FIELD = "用电量"
CHEMICAL_FIELD = "药剂用量"
DATE_FIELD = "统计日期"


def parse_stat_date(value: Any) -> date | None:
    """把统计日期解析成 date；空值或非 YYYY-MM-DD 一律返回 None，不抛异常。"""
    if value is None:
        return None
    text = str(value).strip()
    if len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def to_number(value: Any) -> float | None:
    """把字符串/数字转成 float；空值或非数字返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def ratio(numerator: float | None, denominator: float | None, digits: int = 3) -> float | None:
    """通用比值口径：分母缺失或为 0 时返回 None，避免除零并在页面显示「—」。"""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(numerator / denominator, digits)


def unit_power(entry: dict[str, Any]) -> float | None:
    """单位电耗 = 用电量 / 处理水量。"""
    return ratio(to_number(entry.get(POWER_FIELD)), to_number(entry.get(WATER_FIELD)))


def chemical_consumption(entry: dict[str, Any]) -> float | None:
    """药剂单耗 = 药剂用量 / 处理水量。"""
    return ratio(to_number(entry.get(CHEMICAL_FIELD)), to_number(entry.get(WATER_FIELD)))


def water_power(entries: list[dict[str, Any]]) -> float | None:
    """期间吨水电耗 = 总用电量 / 总处理水量（与单位电耗共用同一比值口径）。"""
    total_power = sum(value for value in (to_number(row.get(POWER_FIELD)) for row in entries) if value is not None)
    total_water = sum(value for value in (to_number(row.get(WATER_FIELD)) for row in entries) if value is not None)
    return ratio(total_power, total_water)


def counted_entries(entries: list[dict[str, Any]], month: str | None = None) -> list[dict[str, Any]]:
    """挑出进入统计口径的记录：状态已正式上报，且统计日期落在指定月份（YYYY-MM）。

    month 为 None 时只按状态过滤；统计日期无法解析的记录不会进入月份口径。
    """
    result: list[dict[str, Any]] = []
    for row in entries:
        if row.get("status") not in COUNTED_STATUSES:
            continue
        if month is not None:
            stat_date = parse_stat_date(row.get(DATE_FIELD))
            if stat_date is None or stat_date.strftime("%Y-%m") != month:
                continue
        result.append(row)
    return result


def summarize(entries: list[dict[str, Any]], month: str) -> dict[str, Any]:
    """汇总一个月的统计卡片数据；空数据时数值为 None 并给出可读说明。"""
    scoped = counted_entries(entries, month)
    if not scoped:
        return {
            "month": month,
            "month_power": None,
            "water_power": None,
            "chemical_consumption": None,
            "count": 0,
            "note": f"{month} 暂无已填报或已复核的能耗记录，统计口径没有可计入的数据，卡片显示「—」",
        }
    month_power = round(
        sum(value for value in (to_number(row.get(POWER_FIELD)) for row in scoped) if value is not None), 3
    )
    chemical_ratios = [
        value for value in (chemical_consumption(row) for row in scoped) if value is not None
    ]
    avg_chemical = round(sum(chemical_ratios) / len(chemical_ratios), 3) if chemical_ratios else None
    return {
        "month": month,
        "month_power": month_power,
        "water_power": water_power(scoped),
        "chemical_consumption": avg_chemical,
        "count": len(scoped),
        "note": "本月口径只统计已填报、已复核记录；待填报与有争议记录不计入",
    }


def available_actions(status: Any) -> list[str]:
    """返回当前状态下允许执行的动作（保持登记页原有三个动作的展示顺序）。"""
    return [action for action in ACTION_RULES if action in TRANSITIONS.get(str(status), set())]


def apply_action(entry: dict[str, Any], action: str) -> tuple[dict[str, Any] | None, str]:
    """执行填报/复核/争议的唯一状态判断。

    返回 (更新后的记录, 说明)；动作非法、重复填报、重复复核、顺序不对都返回
    (None, 可读原因)，调用方据此提示而不是静默失败。
    """
    if action not in ACTION_RULES:
        return None, f"动作「{action}」不属于能耗管理可执行范围"
    status = str(entry.get("status") or "")
    if status not in STATUSES:
        return None, f"当前状态「{status}」不在允许的状态序列里"
    if action not in TRANSITIONS.get(status, set()):
        if action == ACTION_REVIEW and status == STATUS_REVIEWED:
            return None, "该记录已复核，请勿重复复核"
        if action == ACTION_FILE and status in (STATUS_FILED, STATUS_REVIEWED):
            return None, "该记录已填报，请勿重复填报"
        allowed = "、".join(available_actions(status)) or "无"
        return None, f"当前状态「{status}」不允许执行「{action}」，可执行：{allowed}"
    target = ACTION_RULES[action]
    entry["status"] = target
    entry["pending"] = target in PENDING_STATUSES
    # 异常标记粘性：标记争议后即使重新填报、再次复核，仍计入异常量。
    if action in NEGATIVE_ACTIONS or entry.get("abnormal"):
        entry["abnormal"] = True
    return entry, f"能耗记录已{action}"
