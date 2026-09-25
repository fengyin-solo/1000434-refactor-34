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
│   ├── app/services/energy_caliber.py  能耗管理共用口径（指标/卡片/流转单一来源）
│   ├── app/store.py          内存数据仓库与示例数据
│   └── selfcheck.py          本地自检：依赖、口径、填报复核链路（make check-backend）
├── Makefile                  install / backend / frontend / check
├── .gitignore
└── docker-compose.yml
```

## 本地自检

```bash
make check                 # 后端自检 + 前端构建（vue-tsc 类型检查 + vite build）
make check-backend         # 仅后端：backend/selfcheck.py
make check-frontend        # 仅前端
```

`backend/selfcheck.py` 不依赖测试框架，覆盖：依赖导入、能耗共用口径计算、
空数据、登记 → 提交填报 → 复核确认 → 重复复核 → 标记争议，并临时起 uvicorn
走真实 HTTP 验证整条链路；任意一项失败以非 0 退出。

## 能耗管理口径（`app/services/energy_caliber.py` 单一来源）

服务层、路由、示例数据、自检脚本与页面卡片都引用同一份实现：

| 口径 | 规则 |
| --- | --- |
| 统计日期 | `YYYY-MM-DD`，按自然月归集「本月」卡片，非法/缺失日期不进统计 |
| 用电量 | 当日总用电量（kWh），登记必填 |
| 处理水量 | 当日实际处理水量（吨），吨水电耗与药剂单耗的分母 |
| 单位电耗 | 用电量 ÷ 设计日处理水量 50000 吨（kWh/吨，保留 3 位） |
| 吨水电耗 | 用电量 ÷ 实际处理水量（kWh/吨，保留 3 位）；水量为 0/缺失时显示 `—` |
| 药剂单耗 | 药剂用量 ÷ 实际处理水量（kg/吨，保留 4 位） |
| 本月用电量 | 当月「已填报/已复核/有争议」记录用电量求和（待填报草稿不计入） |
| 吨水电耗均值 | 当月 Σ用电量 ÷ Σ处理水量（加权口径，不做逐日简单平均） |
| 异常量 | 仅「标记争议」为负向动作，计入异常量；重新复核后清零 |

派生指标在接口返回时现算（列表、明细、导出一致），示例数据只放原始量，
不写死任何指标值；示例日期锚定运行当月，保证「本月」卡片随时可验证。

空数据：`GET /api/energy` 返回空页，`/api/energy/stats` 卡片为 0 并在
`message` 中说明，页面统计区下方同步展示该说明。

状态流转（原有填报/复核/争议流程不变，仅补充拦截说明）：

- 待填报 --提交填报--> 已填报；已填报后重复提交提示「无需重复提交填报」。
- 已填报/有争议 --复核确认--> 已复核；对已复核记录再次复核提示「请勿重复复核」。
- 任意状态可标记争议；争议记录重新待处理并计入异常量，复核后恢复定稿。

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
| 能耗管理 | `energy` | 能耗记录 | 记录编号、统计日期、用电量、处理水量、单位电耗、吨水电耗 |
| 报警中心 | `alarm` | 报警事件 | 报警编号、报警类型、报警等级 |
| 设备检修 | `maint` | 检修单 | 检修单号、关联设备、检修类型 |
| 受限空间作业 | `permit` | 作业许可单 | 许可编号、作业类型、作业地点 |
| 达标审核 | `audit` | 审核记录 | 审核编号、审核周期、审核范围 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
