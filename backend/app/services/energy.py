"""能耗管理业务规则：状态流转、字段校验、统计口径统一走 energy_logic。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store
from app.services import energy_logic as logic

MODULE = "energy"
REQUIRED_FIELDS = ["记录编号", "统计日期", "用电量"]
# 登记表单还可携带的原始量：处理水量、药剂用量；派生指标（单位电耗、药剂单耗、
# 吨水电耗）由共用口径现算，不接收填报值，避免同一指标出现两个来源。

# 内部状态 -> 页面「记录状态」列的展示文案，表格不再展示内部状态机之外的占位值。
STATUS_DISPLAY = {
    logic.STATUS_PENDING: "待填报",
    logic.STATUS_FILED: "已填报",
    logic.STATUS_REVIEWED: "已复核",
    logic.STATUS_DISPUTED: "有争议",
}


class EnergyService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._decorate(row) for row in rows[start:start + size]], total

    def all_rows(self) -> list[dict[str, Any]]:
        return store.rows(MODULE)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """登记能耗记录。返回 (记录, 问题列表)；问题非空时记录不会落库。

        问题既包含缺字段，也包含统计日期格式错误、用电量非数字，避免原始量被
        静默清空后页面出现「—」却不知原因。
        """
        problems = [f"缺少必填字段：{field}" for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if problems:
            return None, problems
        if logic.parse_stat_date(values.get("统计日期")) is None:
            return None, ["统计日期格式应为 YYYY-MM-DD"]
        power = logic.to_number(values.get(logic.POWER_FIELD))
        if power is None:
            return None, ["用电量应为数字"]
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["记录编号"] = values.get("记录编号")
        entry["统计日期"] = values.get("统计日期")
        entry[logic.POWER_FIELD] = power
        # 原始量：非数字按缺失处理；派生指标（单位电耗等）不落库，读取时按统一口径现算。
        for field in (logic.WATER_FIELD, logic.CHEMICAL_FIELD):
            number = logic.to_number(values.get(field))
            if number is not None:
                entry[field] = number
        entry["status"] = logic.STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._decorate(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"能耗记录 {entry_id} 不存在或已归档"
        updated, message = logic.apply_action(entry, action)
        if updated is None:
            return None, message
        return self._decorate(updated), message

    def stats(self, month: str | None = None) -> dict[str, Any]:
        """本月统计卡片：与列表同源，口径全部来自 energy_logic。"""
        target_month = month or date.today().strftime("%Y-%m")
        return logic.summarize(self.all_rows(), target_month)

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """给原始记录补上派生指标与页面展示字段，不改库里的原始数据。"""
        item = dict(row)
        item["单位电耗"] = logic.unit_power(row)
        item["药剂单耗"] = logic.chemical_consumption(row)
        # 单条记录的吨水电耗与单位电耗同口径（当日电量 / 当日水量）；
        # 期间汇总值由 /stats 按总电量/总水量给出，二者共用同一比值实现。
        item["吨水电耗"] = logic.unit_power(row)
        item["记录状态"] = STATUS_DISPLAY.get(str(row.get("status")), "待填报")
        item["actions"] = logic.available_actions(row.get("status"))
        return item
