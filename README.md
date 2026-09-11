# shift-optimizer

赌台逐日班次分配（OR-Tools CP-SAT）。

每张台每天分配【一个班次】，在满足小时需求、不超过 capacity 的前提下：
- 尽量覆盖每小时需求（缺口比过剩罚得重）；
- 按业绩排名把【长班次】、以及同长度里【需求更多的窗口】分给高价值的台（Theo 为主、Patron hands 为辅）；
- 保持同一 pod 内排班整齐——整组同班次最好；拆成 2 个班次时，尽量拆成【这个 pod 大小下最公平】
  的两段（大小不同的 pod 标准不同，见下）；拆成的两个班次如果【首尾正好衔接】（交班顺、无缝隙），
  罚分打折；一个 pod 最多用 2 种班次；
- 轻微贴近人工填写的 `preferred_open_hours`（次要信号）。

## 安装

用 [uv](https://docs.astral.sh/uv/)（推荐）：

```bash
uv sync --extra dev        # 创建 .venv，按 uv.lock 装好 ortools / pandas / numpy / pytest
uv run shift-optimizer     # 在 .venv 里跑；或 uv run pytest / uv run python ...
```

或用 pip：

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -e ".[dev]"                              # 或 pip install -r requirements.txt
```

依赖（见 `pyproject.toml` / `uv.lock`）：`ortools>=9.14`、`pandas>=2`、`numpy>=1.26`、
`openpyxl`。Python ≥ 3.10。

> ⚠️ 在被污染的 conda base 环境里，`ortools 9.15` 曾出现 `WinError 127` 加载失败
> （site-packages 里有旧的 protobuf/abseil DLL 冲突）。**独立的 venv（uv 或 python -m venv）里 9.15 正常。**
> 所以别把这个项目装进 conda base，用 `uv sync` 建的隔离环境。

## 用法

```bash
uv run python scripts/make_templates.py    # 生成 data/config.xlsx 和 data/demand.xlsx 示例

uv run shift-optimizer                      # 用默认路径跑
uv run shift-optimizer --config data/config.xlsx --demand data/demand.xlsx --out out.xlsx
uv run shift-optimizer --perf-weight 0.4 --pref-weight 0   # 完全按业绩、忽略人工偏好
uv run shift-optimizer --window-weight 0                    # 同时长内的窗口只按覆盖挑，不看评分
uv run shift-optimizer --soft-split-discount 0               # 拆分罚分不因"衔接得上"打折，退回基准罚分
uv run shift-optimizer --help
```

（激活了 venv 的话，直接 `shift-optimizer ...` / `python -m shift_optimizer ...` 也行。）

## 时间约定

营业日从 **07:00** 开始。小时下标 `0` = 07:00–08:00，……，下标 `23` = 次日 06:00–07:00。
时钟 = `(7 + 下标) % 24`。“24 小时”班次 = 07:00 → 次日 07:00。

| 代码 | 时长 | 时钟窗口 |
|---|---|---|
| G | 关闭 | — |
| A | 24h | 07:00 → 07:00 (+1d) |
| C | 16h | 12:00 → 04:00 (+1d) |
| E | 16h | 15:00 → 07:00 (+1d) |
| H | 8h | 12:00 → 20:00 |
| L | 8h | 20:00 → 04:00 (+1d) |
| J | 8h | 15:00 → 23:00 |
| N | 8h | 23:00 → 07:00 (+1d) |

班次定义、覆盖表、权重都在 [`src/shift_optimizer/config.py`](src/shift_optimizer/config.py)。

## Excel 输入格式

### 配置 Excel（默认 `data/config.xlsx`，第一个工作表）

master 清单，一般一张台一行（同名多行见下方）。列名不分大小写、空格/大小写自动规整。

| 列 | 必填 | 说明 |
|---|---|---|
| `table` | ✅ | 台名/编号（同名多行需配不重叠的日期区间，见下） |
| `pod` | ✅ | 所属 pod 名，pod 大小不限（不必是 4） |
| `preferred_open_hours` | 可选 | 人工偏好时长，必须是 `24/16/8/0`，可逐行留空。别名 `pref` / `preferred_hours` / `preference` / `open_hours` |
| `theo_per_open_hour` | 可选 | 每营业小时理论赢数 (Theo)，**历史数据**。别名 `theo` / `theo_per_hour`。留空 = 新台无历史 |
| `patron_hands_per_hour` | 可选 | 每小时客人手数，**历史数据**。别名 `hands` / `patron_hands`。留空 = 新台无历史 |
| `available_from` | 可选 | 该台生效日期（含）。别名 `start_date` / `valid_from`。留空 = 一直有效 |
| `available_to` | 可选 | 该台失效日期（含）。别名 `end_date` / `valid_to`。留空 = 一直有效 |

**按天可用**：求解某一天时，只纳入 `available_from ≤ 当天 ≤ available_to` 的台。
完全不写这两列 → 所有台每天都在（且需求 Excel 的 `day` 不必是日期）。

**同名台可以有多行**（换 pod、刷新历史业绩、停用后再启用……）：

- 各行带**不重叠**的日期区间 → 全部保留，每天挑当天生效的那行：

  | table | pod | theo_per_open_hour | available_from | available_to |
  |---|---|---|---|---|
  | BJ-05 | Pit-A | 210 | | 2026-06-30 |
  | BJ-05 | Pit-B | 240 | 2026-07-01 | |

- 没有日期列，或日期区间**重叠** → **不报错**，只保留**最新的一行**（`available_from`
  最大者；都没填则取 Excel 里靠后的那行），并打印一条 `[提示]`。

所以台名最终一定是唯一的。

**评分**：`score = 0.8 × Theo_归一化 + 0.2 × Hands_归一化`（min–max 到 0..1），据此排名。
- 归一化只在**当天有历史的台**之间做；
- **新台**（Theo/Hands 留空）→ 评分取当天有历史台评分的**中位数**（不因此被压到短班次，也不占高价值台的位置）；
- 当天没有任何台有历史 → 评分全 0，退化成"只按覆盖 + 人工偏好"。

**评分决定两层顺序**：
1. **时长类别**（24h > 16h > 8h > 关闭）：覆盖需求 + pod 规则先定出"整体要几张 24h、几张 16h……"，
   score 高的台优先拿到长的那类。
2. **同时长内选哪个窗口**（16h 的 C/E、8h 的 H/L/J/N）：当覆盖约束允许"同时长换哪个窗口结果一样"时，
   把当天**覆盖需求更多**的那个窗口（`window_desirability`，见下方 `schedules` 表）让给 score 更高的台；
   覆盖不是真的无所谓的时候，覆盖仍然优先。设 `--window-weight 0` 关掉这层，退回旧版"同时长内純按覆盖挑"。

### 需求 Excel（默认 `data/demand.xlsx`，第一个工作表）

| 列 | 必填 | 说明 |
|---|---|---|
| `day` | ✅ | 当天标签，唯一。**用了 config 的 available_from/to 时必须是日期**（如 `2026-09-01`） |
| 24 个小时列 | ✅ | 按顺序对应下标 0..23（下标 0 = 07:00）。列名随意，只要正好 24 个 |
| `capacity` | 可选 | 当天"同时开台数"上限（硬约束）。留空 = 不限制 |

每一天独立求解一次，用当天可用的台。

## 输出 Excel（`--out`，默认 `schedule_output.xlsx`）

| 工作表 | 内容 |
|---|---|
| `summary` | 每天一行：status、可用台数、capacity、objective、总缺口、总过剩、实现 Theo、实现 hands |
| `fleet` | master 台清单：pod、偏好、Theo、hands、has_history、available_from/to |
| `schedules` | 长表：`day, table, pod, rank, score, has_history, preferred_open_hours, shift, shift_open_hours, window_desirability, pod_split_soft` |
| `coverage` | 逐日逐小时：`demand, capacity, tables_open, shortage, surplus` |

## Pod 拆分：公平性 + 衔接顺不顺

一个 pod 分成 2 个班次时，两件事各算各的罚分：

**1. 这个大小的 pod 能拆得多公平。** 不再简单地看"少数侧是不是只有 1 张"——按跟
"这个 pod 大小下最公平的两段拆分"还差多远来算（`model.pod_penalty_schedule`）：

| pod 大小 | 最公平的拆法（人数差） | 该拆法的罚分 | 更偏的拆法 |
|---|---|---|---|
| 2 | 1+1（差 0） | `PENALTY_PAIRED_SPLIT` (2) | — |
| 3 | 1+2（差 1，3 张台能做到的最好） | `PENALTY_PAIRED_SPLIT` (2) | — |
| 4 | 2+2（差 0） | `PENALTY_PAIRED_SPLIT` (2) | 1+3（差 2）→ `PENALTY_UNEVEN_SPLIT` (30) |
| 5 | 2+3（差 1） | `PENALTY_PAIRED_SPLIT` (2) | 1+4（差 3）→ `PENALTY_UNEVEN_SPLIT` (30) |
| 6 | 3+3（差 0） | `PENALTY_PAIRED_SPLIT` (2) | 2+4（差 2）→30；1+5（差 4）→ 更狠（58） |

旧版本把"少数侧只有 1 张"一律当成最差情况，这对 2、3 张台的 pod 不公平——它们唯一
能做的拆法（1+1、1+2）本来就是那个大小下最公平的拆法，不该跟 4 张台的 1+3 一样重罚。
现在按"跟最公平差多远"分档，4/5 张台 pod 的结果和以前完全一样，2/3 张台的被修正，
更大的 pod 按同一把尺子合理延伸。

**2. 拆成的两个班次首尾接不接得上。** 如果一个 pod 恰好拆成了两个【共用一个开钟点
或关钟点】的班次——比如 H(12:00-20:00) 接 L(20:00-04:00)，一个收工另一个正好接班，
中间没有缝隙，交班干净——这次拆分的罚分打 `SOFT_SPLIT_DISCOUNT` 折（默认 0.5，即半价）。
两个班次的钟点完全对不上（比如 C 和 J）就不打折，按上面第 1 点算出的基准罚分全额计。
当前班次表算出来的"衔接得上"组合：`A-E`、`A-N`、`C-H`、`C-L`、`E-J`、`E-N`、`H-L`、`J-N`
（源码见 `config.SOFT_SHIFT_PAIRS`；`schedules` 表的 `pod_split_soft` 列会标出当天每个
pod 的拆分有没有命中）。

## 权重与优先级

目标函数（最小化）：

```
2.5·Σ缺口  +  1·Σ过剩  +  Σ pod拆分基准罚分  −  SOFT_SPLIT_DISCOUNT·Σ(衔接得上时可退的部分)
  +  PREF_WEIGHT·Σ偏好偏离  −  PERF_WEIGHT·Σ(score·开机小时)  −  WINDOW_WEIGHT·Σ(score·同时长窗口吸引力)
```

| 常量 | 默认 | 作用 |
|---|---|---|
| `WEIGHT_SHORTAGE` / `WEIGHT_SURPLUS` | 2.5 / 1 | 覆盖需求（最高优先级） |
| `PENALTY_UNEVEN_SPLIT` / `PENALTY_PAIRED_SPLIT` | 30 / 2 | pod 拆分明显偏一边 / 该大小下最公平的拆法 |
| `SOFT_SPLIT_DISCOUNT` | 0.5 | 拆成的两个班次首尾衔接得上时，基准罚分打几折退回 |
| `PERF_WEIGHT` | 0.25 | 业绩排名决定"哪个时长类别"（主信号） |
| `WINDOW_WEIGHT` | 0.05 | 业绩排名决定"同时长选哪个窗口"（比 `PERF_WEIGHT` 更细、更弱） |
| `PREF_WEIGHT` | 0.10 | 人工偏好（弱微调；设 0 忽略） |
| `THEO_SHARE` | 0.80 | score 里 Theo 占比 |

优先级从高到低：覆盖需求 > pod 拆分公平性 > 时长类别排名 (`PERF_WEIGHT`) >
同时长窗口排名 (`WINDOW_WEIGHT`) ≈ 人工偏好 (`PREF_WEIGHT`) ≈ 衔接折扣 (`SOFT_SPLIT_DISCOUNT`)。

`PERF_WEIGHT` / `PREF_WEIGHT` / `WINDOW_WEIGHT` / `SOFT_SPLIT_DISCOUNT` 可用命令行
`--perf-weight` / `--pref-weight` / `--window-weight` / `--soft-split-discount` 覆盖。

## 开发

```bash
uv sync --extra dev
uv run pytest                # 43 个测试；test_model.py 需要 ortools，缺则自动跳过
                              # (test_window.py / test_config.py 是纯函数测试，不需要 ortools)
```

## 目录

```
src/shift_optimizer/
  config.py     班次目录 / 时长类别 / 开关钟点 / SOFT_SHIFT_PAIRS / 权重
  scoring.py    业绩指标 -> 0..1 综合评分 + 排名
  io_excel.py   读配置/需求、写结果、按天组装可用台
                TableInfo / FleetConfig / DayDemand / DayFleet / DayResult / build_day_fleet
  model.py      CP-SAT 建模 + 逐日求解；pod_penalty_schedule, window_desirability
  cli.py        命令行入口
scripts/make_templates.py   生成示例 Excel
data/           示例输入
tests/          pytest（test_window.py / test_config.py 不需要 ortools）
```

模型细节（pod 约束、偏好罚分机制、07:00 约定的来龙去脉）见 git 历史里更早的带详细中文注释的单文件版本。
