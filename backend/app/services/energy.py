"""能耗管理业务规则：状态流转、字段校验、筛选与派生指标都走 energy_caliber 共用口径。"""
from __future__ import annotations

from typing import Any

from app.services import energy_caliber as caliber
from app.store import store


class EnergyService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(caliber.MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(caliber.KEY_FIELD, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [caliber.serialize_row(row) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(caliber.MODULE, entry_id)
        return caliber.serialize_row(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in caliber.REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        rows = store.rows(caliber.MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in caliber.REQUIRED_FIELDS + caliber.OPTIONAL_FIELDS:
            if values.get(field) not in (None, ""):
                entry[field] = values.get(field)
        entry["status"] = caliber.STATUS_DRAFT
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return caliber.serialize_row(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(caliber.MODULE, entry_id)
        if entry is None:
            return None, f"能耗记录 {entry_id} 不存在或已归档"
        updated, message = caliber.apply_action(entry, str(action or "").strip())
        if updated is None:
            return None, message
        return caliber.serialize_row(updated), message

    def summary(self) -> dict[str, Any]:
        """页面统计卡片：与列表同口径，空数据由 caliber 给出说明。"""
        return caliber.summarize(store.rows(caliber.MODULE))
