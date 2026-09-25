"""能耗管理接口：维护能耗记录，覆盖提交填报、复核确认、标记争议等动作。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import energy_caliber as caliber
from app.services.energy import EnergyService

router = APIRouter(prefix="/api/energy", tags=["能耗管理"])

service = EnergyService()

LIST_FIELDS = caliber.LIST_FIELDS
STATUSES = caliber.STATUSES


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
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict:
    """统计卡片：本月用电量、吨水电耗均值、药剂单耗，与列表共用同一套口径。"""
    return service.summary()


@router.get("/export")
def export_entries() -> dict:
    """导出能耗管理清单：返回当前过滤条件下的全量数据（含按口径派生的指标列）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": caliber.MODULE, "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条能耗记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"能耗记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条能耗记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="能耗记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条能耗记录执行提交填报、复核确认、标记争议；重复复核等情况拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
