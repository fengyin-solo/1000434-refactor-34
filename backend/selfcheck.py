#!/usr/bin/env python3
"""能耗管理本地自检：不依赖测试框架，克隆装好依赖后一条命令验证全部口径。

用法（在 backend/ 目录下）：
    .venv/bin/python selfcheck.py
或：
    make check-backend

覆盖内容：
1. 依赖自检：fastapi / uvicorn / pydantic 是否可导入；
2. 口径自检：统计日期、单位电耗、吨水电耗、药剂单耗、统计卡片的共用计算；
3. 流程自检（直接调服务层）：空数据、填报 -> 复核、重复复核、标记争议计入异常量；
4. 接口自检：临时起一个 uvicorn，走真实 HTTP 验证填报与复核链路。

任何一步失败都会以非 0 退出码结束，方便接进 CI 或 Makefile。
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

failures: list[str] = []
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" —— {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def section(title: str) -> None:
    print(f"\n== {title} ==")


def assert_close(name: str, actual: float, expected: float) -> None:
    check(name, abs(actual - expected) < 1e-9, f"实际 {actual} != 预期 {expected}")


# 1. 依赖自检 ------------------------------------------------------------------
def check_dependencies() -> None:
    section("依赖自检")
    try:
        import fastapi  # noqa: F401
        import pydantic  # noqa: F401
        import uvicorn  # noqa: F401
        check("fastapi / uvicorn / pydantic 均可导入", True)
    except ImportError as exc:
        check(f"fastapi / uvicorn / pydantic 均可导入（{exc}）", False)


# 2. 口径自检 ------------------------------------------------------------------
def check_caliber() -> None:
    section("共用口径自检（统计日期 / 单位电耗 / 吨水电耗 / 药剂单耗 / 卡片）")
    from app.services import energy_caliber as c

    # 统计日期：只认 YYYY-MM-DD
    check("合法统计日期可解析", c.parse_date("2026-09-11") == date(2026, 9, 11))
    check("非法/空缺统计日期返回 None", c.parse_date("2026/9/11") is None and c.parse_date("") is None)
    check("非数值原始量返回 None", c.parse_number("能耗管理样例1") is None)
    check("负数原始量返回 None", c.parse_number(-1) is None)

    # 单位电耗：用电量 / 设计日处理水量 50000
    assert_close("单位电耗 = 用电量/设计水量(50000)", c.unit_power_consumption(18650), round(18650 / 50000, 3))
    # 吨水电耗：用电量 / 实际处理水量
    assert_close("吨水电耗 = 用电量/实际水量", c.ton_water_power_consumption(18650, 50200), round(18650 / 50200, 3))
    check("实际水量为 0 时吨水电耗不可计算", c.ton_water_power_consumption(100, 0) is None)
    # 药剂单耗：药剂用量 / 实际处理水量
    assert_close("药剂单耗 = 药剂用量/实际水量", c.chemical_intensity(102, 50200), round(102 / 50200, 4))

    # 单条记录序列化：派生指标统一现算，不接受写死值
    row = {
        "id": 1, "status": c.STATUS_FILLED, "pending": True, "abnormal": False,
        c.KEY_FIELD: "ENER-TEST", c.DATE_FIELD: "2026-09-09",
        c.POWER_FIELD: 18650, c.WATER_FIELD: 50200, c.CHEM_FIELD: 102,
    }
    item = c.serialize_row(row)
    check("记录状态列由 status 统一映射", item[c.STATUS_FIELD] == c.STATUS_FILLED)
    assert_close("序列化吨水电耗与口径一致", item[c.TON_POWER_FIELD], round(18650 / 50200, 3))


# 3. 服务流程自检 --------------------------------------------------------------
def reset_energy_rows(rows: list) -> None:
    from app.store import store
    store.rows("energy").clear()
    store.rows("energy").extend(rows)


def check_flow() -> None:
    section("流程自检：空数据、填报/复核、重复复核、标记争议计入异常量")
    from app.services import energy_caliber as c
    from app.services.energy import EnergyService
    from app.store import store

    service = EnergyService()

    # 空数据：列表空页、卡片全 0 且带说明
    reset_energy_rows([])
    items, total = service.list_entries()
    check("空数据列表返回空页不报错", items == [] and total == 0)
    stats = service.summary()
    check("空数据卡片全部为 0", [card["value"] for card in stats["cards"]] == [0, 0, 0])
    check("空数据必须给出说明", bool(stats["message"]))

    # 缺失原始量不报错
    entry, missing = service.create_entry({c.KEY_FIELD: "", c.DATE_FIELD: "", c.POWER_FIELD: ""})
    check("缺必填字段被拦下并列出字段", entry is None and set(missing) == set(c.REQUIRED_FIELDS))

    # 空表上操作不存在的记录
    _, message = service.run_action(999, c.ACTION_REVIEW)
    check("不存在记录给出可读错误", "不存在" in message)

    # 完整流程：登记 -> 填报 -> 复核（原有填报流程不变）
    today = date.today()
    day = today.strftime("%Y-%m-%d")
    entry, missing = service.create_entry({
        c.KEY_FIELD: "ENER-FLOW",
        c.DATE_FIELD: day,
        c.POWER_FIELD: 20000,
        c.WATER_FIELD: 50000,
        c.CHEM_FIELD: 100,
    })
    check("登记成功（必填齐全）", entry is not None and not missing)
    entry_id = int(entry["id"])
    check("新登记记录为待填报草稿", entry["status"] == c.STATUS_DRAFT and entry["pending"] is True)

    # 未填报先复核要被拦下并说明
    _, message = service.run_action(entry_id, c.ACTION_REVIEW)
    check("未填报先复核被拦下并说明", "先提交填报" in message)

    entry, message = service.run_action(entry_id, c.ACTION_SUBMIT)
    check("提交填报成功", entry is not None and entry["status"] == c.STATUS_FILLED)
    check("填报后不产生异常量", entry["abnormal"] is False)

    # 重复填报被拦下，状态保持已填报
    _, message = service.run_action(entry_id, c.ACTION_SUBMIT)
    check("重复填报被拦下并说明", "无需重复提交填报" in message)
    check("重复填报不改变状态", store.find("energy", entry_id)["status"] == c.STATUS_FILLED)

    entry, message = service.run_action(entry_id, c.ACTION_REVIEW)
    check("复核确认成功", entry is not None and entry["status"] == c.STATUS_REVIEWED)
    check("复核后不再待处理", entry["pending"] is False and entry["abnormal"] is False)

    # 重复复核：必须拦下来并给说明
    _, message = service.run_action(entry_id, c.ACTION_REVIEW)
    check("重复复核被拦下并说明", "请勿重复复核" in message)
    after = store.find("energy", entry_id)
    check("重复复核不改变状态", after["status"] == c.STATUS_REVIEWED and after["pending"] is False)

    # 标记争议是负向动作：进入争议、计入异常量、重新待处理
    entry, message = service.run_action(entry_id, c.ACTION_DISPUTE)
    check("标记争议成功", entry is not None and entry["status"] == c.STATUS_DISPUTED)
    check("标记争议计入异常量", entry["abnormal"] is True and entry["pending"] is True)

    # 争议后复核：重新定稿，异常量清掉（口径收拢后不能再残留异常标记）
    entry, message = service.run_action(entry_id, c.ACTION_REVIEW)
    check("争议后复核重新定稿", entry is not None and entry["status"] == c.STATUS_REVIEWED)
    check("复核定稿后异常量清零", entry["abnormal"] is False and entry["pending"] is False)

    # 非法动作
    _, message = service.run_action(entry_id, "删除记录")
    check("非法动作被拦下", "可执行范围" in message)

    # 示例数据卡片：当月四条已报记录（草稿不计入）
    from app.seed import _energy_seed_rows
    seed_rows = [dict(row) for row in _energy_seed_rows()]
    reset_energy_rows(seed_rows)
    stats = service.summary()
    reportable = [row for row in seed_rows if row["status"] in c.REPORTABLE_STATUSES]
    total_power = sum(float(row[c.POWER_FIELD]) for row in reportable)
    total_water = sum(float(row[c.WATER_FIELD]) for row in reportable)
    total_chem = sum(float(row[c.CHEM_FIELD]) for row in reportable)
    values = {card["label"]: card["value"] for card in stats["cards"]}
    check("卡片覆盖当月全部已报记录", stats["total"] == len(reportable) == 4)
    assert_close("本月用电量为当月求和", values[c.CARD_POWER], round(total_power, 3))
    assert_close(
        "吨水电耗均值为总量相除（加权口径）",
        values[c.CARD_TON_POWER], round(total_power / total_water, 3),
    )
    assert_close(
        "药剂单耗为总量相除（加权口径）",
        values[c.CARD_CHEM], round(total_chem / total_water, 4),
    )

    # 表格行与卡片同源：导出里的吨水电耗逐日值与卡片使用同一函数
    export_items, export_total = service.list_entries(page=1, size=10000)
    row9 = next(row for row in export_items if row[c.KEY_FIELD] == "ENER-0002")
    assert_close(
        "列表吨水电耗由共用口径现算",
        float(row9[c.TON_POWER_FIELD]), round(18650 / 50200, 3),
    )
    check("导出条数与示例数据一致", export_total == len(seed_rows))

    # 异常量汇总：示例数据里争议记录必须进概览异常量
    abnormal = sum(1 for row in store.rows("energy") if row.get("abnormal"))
    check("标记争议进入异常量汇总", abnormal == 1)


# 4. HTTP 接口自检 -------------------------------------------------------------
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def check_http() -> None:
    section("接口自检：真实 HTTP 验证填报与复核")
    import uvicorn

    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=free_port(), log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{config.port}"

    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            status, body = http_json("GET", f"{base}/api/health")
            if status == 200 and body.get("ok"):
                break
        except OSError:
            time.sleep(0.2)
    else:
        check("健康检查可达", False, "uvicorn 10s 内未就绪")
        server.should_exit = True
        return
    check("健康检查可达", True)

    # 从干净的空模块开始，保证流程断言不受示例数据干扰
    from app.store import store
    store.rows("energy").clear()

    status, body = http_json("GET", f"{base}/api/energy")
    check("空列表 HTTP 返回 200 空页", status == 200 and body["total"] == 0 and body["items"] == [])

    status, body = http_json("GET", f"{base}/api/energy/stats")
    check("空数据 stats 返回 0 且带说明", status == 200 and body["cards"][0]["value"] == 0 and bool(body["message"]))

    today = date.today().strftime("%Y-%m-%d")
    status, body = http_json("POST", f"{base}/api/energy", {"values": {
        "记录编号": "ENER-HTTP",
        "统计日期": today,
        "用电量": 21000,
        "处理水量": 50000,
        "药剂用量": 110,
    }})
    check("HTTP 登记成功", status == 200 and body["ok"] is True)
    entry_id = body["entry"]["id"]

    status, body = http_json("POST", f"{base}/api/energy/{entry_id}/actions", {"values": {"action": "复核确认"}})
    check("HTTP 未填报先复核返回 ok=false 并说明", status == 200 and body["ok"] is False and "先提交填报" in body["message"])

    status, body = http_json("POST", f"{base}/api/energy/{entry_id}/actions", {"values": {"action": "提交填报"}})
    check("HTTP 提交填报成功", status == 200 and body["entry"]["status"] == "已填报")

    status, body = http_json("POST", f"{base}/api/energy/{entry_id}/actions", {"values": {"action": "复核确认"}})
    check("HTTP 复核确认成功", status == 200 and body["entry"]["status"] == "已复核")

    status, body = http_json("POST", f"{base}/api/energy/{entry_id}/actions", {"values": {"action": "复核确认"}})
    check("HTTP 重复复核返回 ok=false 并说明", status == 200 and body["ok"] is False and "请勿重复复核" in body["message"])

    status, body = http_json("POST", f"{base}/api/energy/{entry_id}/actions", {"values": {"action": "标记争议"}})
    check("HTTP 标记争议后 abnormal=true", status == 200 and body["entry"]["abnormal"] is True)

    status, body = http_json("GET", f"{base}/api/energy/stats")
    values = {card["label"]: card["value"] for card in body["cards"]}
    check("HTTP stats 本月用电量为 21000", status == 200 and values["本月用电量"] == 21000)
    check("HTTP stats 吨水电耗为 21000/50000", values["吨水电耗均值"] == round(21000 / 50000, 3))

    status, body = http_json("GET", f"{base}/api/energy/export")
    check("HTTP 导出含按口径派生的吨水电耗", status == 200 and body["items"][0]["吨水电耗"] == round(21000 / 50000, 3))

    server.should_exit = True
    thread.join(timeout=5)


def main() -> int:
    print("能耗管理本地自检")
    check_dependencies()
    if failures:
        print("\n依赖不完整，请先执行：cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt")
        return 1
    check_caliber()
    check_flow()
    check_http()

    print(f"\n共 {checks} 项检查，失败 {len(failures)} 项")
    if failures:
        print("失败项：" + "、".join(failures))
        return 1
    print("全部通过：填报与复核口径、空数据、重复复核、异常量与 HTTP 链路均已验证")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
