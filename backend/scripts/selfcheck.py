#!/usr/bin/env python3
"""能耗管理本地自检：装好依赖后一条命令验证依赖、共用口径、填报与复核流转。

用法（在 backend 目录下）：
    .venv/bin/python scripts/selfcheck.py

检查三部分，任一失败即以非 0 退出，方便接到 make check / CI：
1. 依赖自检：fastapi / pydantic / uvicorn 可导入，应用与 /api/energy/stats 路由就绪；
2. 口径自检：示例数据的统计日期、单位电耗、药剂单耗、吨水电耗与本月汇总符合预期，
   空数据、缺水量/水量为 0 有明确说明而不是除零；
3. 流程自检：登记→提交填报→复核确认可走通，重复填报、重复复核、越级操作被拦下，
   标记争议进入异常量且重新复核后异常标记保留。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" —— {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> int:
    # ---- 1. 依赖自检 ----
    section("依赖自检")
    try:
        import fastapi
        import pydantic
        import uvicorn  # noqa: F401
        check("fastapi / pydantic / uvicorn 均可导入", True)
        print(f"         fastapi {fastapi.__version__} / pydantic {pydantic.__version__}")
    except ImportError as exc:
        check("fastapi / pydantic / uvicorn 均可导入", False, str(exc))
        print("\n依赖自检未通过：请先执行 .venv/bin/pip install -r requirements.txt")
        return 1

    from app.main import app
    def collect_paths(routes: list[object]) -> set[str]:
        # FastAPI 新版 include_router 是惰性嵌套的（_IncludedRouter），需要递归展开。
        paths: set[str] = set()
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                paths.add(path)
            inner = getattr(route, "routes", None)
            if inner is None:
                inner = getattr(getattr(route, "original_router", None), "routes", None)
            if inner:
                paths.update(collect_paths(inner))
        return paths

    route_paths = collect_paths(list(app.routes))
    check("/api/energy/stats 统计路由已注册", "/api/energy/stats" in route_paths)

    from app.services import energy_logic as logic
    from app.services.energy import EnergyService

    service = EnergyService()

    # ---- 2. 口径自检（示例数据） ----
    section("口径自检：示例数据")
    rows = service.all_rows()
    by_code = {str(row["记录编号"]): row for row in rows}

    decorated = {row["记录编号"]: service.get_entry(int(row["id"])) for row in rows}

    e1 = decorated["ENER-0001"]
    check("单位电耗 = 用电量 / 处理水量（21000/9500 → 2.211）", e1["单位电耗"] == 2.211, str(e1["单位电耗"]))
    check("单条吨水电耗与单位电耗同口径", e1["吨水电耗"] == e1["单位电耗"])
    e3 = decorated["ENER-0003"]
    check("药剂单耗 = 药剂用量 / 处理水量（350/5600 → 0.062）", e3["药剂单耗"] == 0.062, str(e3["药剂单耗"]))
    check("记录状态列由内部状态统一映射（已复核）", e3["记录状态"] == "已复核")
    check("可执行动作由状态机统一给出（已复核仅可标记争议）", e3["actions"] == ["标记争议"], str(e3["actions"]))

    september = service.stats("2026-09")
    print(f"         2026-09 汇总: {september}")
    check("本月只统计已填报/已复核（2 条，待填报与争议不计入）", september["count"] == 2, str(september["count"]))
    check("本月用电量 = 24300 + 12800 = 37100", september["month_power"] == 37100.0, str(september["month_power"]))
    check("吨水电耗 = 总电量/总水量 = 37100/16200 → 2.29", september["water_power"] == 2.29, str(september["water_power"]))
    check("药剂单耗均值 → 0.061", september["chemical_consumption"] == 0.061, str(september["chemical_consumption"]))

    august = service.stats("2026-08")
    check("统计日期口径：上月数据只进上月（1 条）", august["count"] == 1, str(august["count"]))
    check("上月吨水电耗 = 22600/10100 → 2.238", august["water_power"] == 2.238, str(august["water_power"]))

    section("口径自检：空数据与除零保护")
    empty = logic.summarize([], "2025-01")
    check("空数据汇总返回 None 而不是报错", (empty["month_power"], empty["water_power"]) == (None, None))
    check("空数据附可读说明", "暂无" in empty["note"], empty["note"])
    check("处理水量缺失时单位电耗为 None", logic.unit_power({"用电量": 100}) is None)
    check("处理水量为 0 时吨水电耗为 None", logic.unit_power({"用电量": 100, "处理水量": 0}) is None)
    check("非数字用电量不参与计算", logic.to_number("能耗管理样例1") is None)
    check("统计日期只认 YYYY-MM-DD", logic.parse_stat_date("2026/09/01") is None)

    # ---- 3. 填报与复核流转自检 ----
    section("流程自检：登记 → 填报 → 复核")
    entry, missing = service.create_entry({
        "记录编号": "ENER-T1",
        "统计日期": "2026-09-10",
        "用电量": "10000",
        "处理水量": "5000",
        "药剂用量": "300",
        "记录人员": "自检脚本",
    })
    check("登记成功且初始为待填报", entry is not None and entry["status"] == "待填报", str(missing))
    assert entry is not None
    new_id = int(entry["id"])
    check("新登记记录派生指标按共用口径现算（10000/5000 → 2.0）", entry["单位电耗"] == 2.0)

    bad_date, date_problems = service.create_entry({"记录编号": "ENER-TX", "统计日期": "2026/09/10", "用电量": 1})
    check("统计日期格式不对时登记被拒", bad_date is None and any("YYYY-MM-DD" in p for p in date_problems), str(date_problems))

    bad_power, power_problems = service.create_entry({"记录编号": "ENER-TY", "统计日期": "2026-09-10", "用电量": "一万度"})
    check("用电量非数字时登记被拒", bad_power is None and any("用电量" in p for p in power_problems), str(power_problems))

    entry, message = service.run_action(new_id, "提交填报")
    check("提交填报：待填报 → 已填报", entry is not None and entry["status"] == "已填报", message)
    entry, message = service.run_action(new_id, "提交填报")
    check("重复填报被拦下并说明原因", entry is None and "重复填报" in message, message)

    entry, message = service.run_action(new_id, "复核确认")
    check("复核确认：已填报 → 已复核、退出待处理", entry is not None and entry["status"] == "已复核" and not entry["pending"], message)
    entry, message = service.run_action(new_id, "复核确认")
    check("重复复核被拦下并说明原因", entry is None and "重复复核" in message, message)

    entry2, _ = service.create_entry({
        "记录编号": "ENER-T2", "统计日期": "2026-09-11", "用电量": 8000, "处理水量": 4000,
    })
    assert entry2 is not None
    entry2_resp, message = service.run_action(int(entry2["id"]), "复核确认")
    check("待填报不能越级复核", entry2_resp is None and "不允许执行" in message, message)
    check("未知动作被拦下", service.run_action(int(entry2["id"]), "随便点")[0] is None)

    section("流程自检：标记争议与异常量")
    # 已复核记录被标记争议：进入有争议、重新待处理、计入异常量。
    entry, message = service.run_action(new_id, "标记争议")
    check("已复核 → 有争议", entry is not None and entry["status"] == "有争议", message)
    check("争议记录重新进入待处理", entry is not None and entry["pending"] is True)
    check("标记争议进入异常量", entry is not None and entry["abnormal"] is True)

    entry, message = service.run_action(new_id, "提交填报")
    check("争议记录可重新填报", entry is not None and entry["status"] == "已填报", message)
    check("重新填报后异常标记保留", entry is not None and entry["abnormal"] is True)
    entry, message = service.run_action(new_id, "复核确认")
    check("争议后可再次复核", entry is not None and entry["status"] == "已复核", message)
    check("再次复核后仍计入异常量（异常粘性）", entry is not None and entry["abnormal"] is True)

    disputed = service.get_entry(4)
    check("示例争议记录 ENER-0004 本身即异常量", disputed is not None and disputed["abnormal"] is True)

    # ---- 汇总 ----
    print("\n" + "=" * 48)
    if failures:
        print(f"自检未通过：{len(failures)} 项失败")
        for name in failures:
            print(f"  - {name}")
        return 1
    print("全部自检通过：依赖、口径、填报与复核流转均符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
