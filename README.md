# 污水处理厂工艺管控平台

面向污水处理厂进出水监测、工艺单元、加药曝气、污泥处置与达标排放的一体化工艺管控后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 本地自检（装好依赖后先跑这个）

```bash
make check            # 后端自检 + 前端类型检查/构建
# 或分开跑：
cd backend && .venv/bin/python scripts/selfcheck.py
cd frontend && npm run build
```

后端自检 `backend/scripts/selfcheck.py` 不依赖任何外部服务，覆盖三部分：

1. 依赖自检：fastapi / pydantic / uvicorn 可导入，统计路由已注册；
2. 口径自检：用示例数据验证统计日期、单位电耗、药剂单耗、吨水电耗与本月汇总，
   并确认空数据、处理水量缺失或为 0 时返回 `null` 并附说明（页面显示「—」），
   不会除零报错；
3. 流程自检：登记 → 提交填报 → 复核确认走得通；重复填报、重复复核、越级操作会被
   拦下并给出原因；标记争议计入异常量，且重新填报、再次复核后异常标记保留。

任一项失败脚本以非 0 退出，可直接接 CI。

### 能耗管理统计口径

口径只在 `backend/app/services/energy_logic.py` 维护一份，服务层、
`GET /api/energy/stats` 与自检脚本共用，页面统计卡片与表格数字同源：

- 统计日期：`YYYY-MM-DD`，无法解析的记录不进入按月份的统计；
- 单位电耗（单条）= 用电量(kWh) / 处理水量(t)；
- 药剂单耗（单条）= 药剂用量(kg) / 处理水量(t)，本月卡片取各条均值；
- 吨水电耗（本月）= 本月总用电量 / 本月总处理水量；
- 以上比值保留 3 位小数，处理水量缺失或为 0 时为 `null`（页面显示「—」）；
- 本月口径只统计「已填报、已复核」记录，待填报数据不全、有争议数据待核实，
  均不计入；空月份接口在 `note` 里给出说明。

状态流转同样只有一份判断（`energy_logic.apply_action`）：
待填报 → 已填报 → 已复核；已填报/已复核可标记争议，争议后需重新填报；
重复填报、重复复核、越级执行都会返回可读的拦截原因。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 厂区单元 | `plant` | 工艺单元 | 单元编码、单元名称、处理工艺 |
| 进水监测 | `inflow` | 进水记录 | 监测编号、采样时间、进水流量 |
| 出水监测 | `effluent` | 出水记录 | 监测编号、采样时间、出水流量 |
| 曝气控制 | `aeration` | 曝气记录 | 记录编号、曝气池编号、溶解氧值 |
| 加药管理 | `dosing` | 加药单 | 加药单号、药剂名称、投加浓度 |
| 污泥处置 | `sludge` | 污泥处置单 | 处置单号、污泥来源、含水率 |
| 脱水运行 | `dewater` | 脱水记录 | 记录编号、脱水机编号、进泥量 |
| 泵站运行 | `pump` | 泵站 | 泵站编号、泵组台数、运行泵号 |
| 鼓风机组 | `blower` | 鼓风机组 | 机组编号、机组型号、额定风量 |
| 膜组件 | `membrane` | 膜组 | 膜组编号、膜型号、膜面积 |
| 在线仪表 | `online` | 在线仪表 | 仪表编号、仪表类型、测量范围 |
| 取样检测 | `sample` | 检测单 | 检测单号、取样点位、检测项目 |
| 药剂出入 | `chemical` | 药剂单据 | 单据编号、药剂名称、规格型号 |
| 能耗管理 | `energy` | 能耗记录 | 记录编号、统计日期、用电量 |
| 报警中心 | `alarm` | 报警事件 | 报警编号、报警类型、报警等级 |
| 设备检修 | `maint` | 检修单 | 检修单号、关联设备、检修类型 |
| 受限空间作业 | `permit` | 作业许可单 | 许可编号、作业类型、作业地点 |
| 达标审核 | `audit` | 审核记录 | 审核编号、审核周期、审核范围 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
