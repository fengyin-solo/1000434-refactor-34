"""能耗管理接口：维护能耗记录，覆盖提交填报、复核确认、标记争议等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.energy import EnergyService
from app.services import energy_logic as logic

router = APIRouter(prefix="/api/energy", tags=["能耗管理"])

service = EnergyService()

LIST_FIELDS = ["记录编号", "统计日期", "用电量", "单位电耗", "药剂单耗", "吨水电耗", "记录人员", "记录状态"]
STATUSES = logic.STATUSES


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="待填报、已填报、已复核、有争议"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤能耗管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status is not None and status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"状态「{status}」无效，可选：{'、'.join(STATUSES)}",
        )
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def energy_stats(
    month: str | None = Query(default=None, description="统计月份，格式 YYYY-MM，默认本月"),
) -> dict[str, Any]:
    """本月统计卡片：本月用电量、吨水电耗、药剂单耗，空数据时数值为 null 并附说明。"""
    if month is not None and (len(month) != 7 or month[4] != "-"):
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM，例如 2026-09")
    return service.stats(month)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出能耗管理清单：返回全量数据与本月统计口径，派生指标与页面同口径。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "energy", "total": total, "stats": service.stats(), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条能耗记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"能耗记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条能耗记录，缺字段、统计日期格式不对或用电量非数字时说明原因，不静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="能耗记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条能耗记录执行提交填报、复核确认、标记争议；重复填报、重复复核等不允许的
    动作会被拦下，并在 message 里说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
