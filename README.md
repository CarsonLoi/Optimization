# shift-optimizer

赌台逐日班次分配（OR-Tools CP-SAT）。

每张台每天分配【一个班次】，在满足小时需求、不超过 capacity 的前提下：
- 尽量覆盖每小时需求（缺口比过剩罚得重）；
- 按业绩排名把【长班次】分给高价值的台（Theo 为主、Patron hands 为辅）；
- 保持同一 pod 内排班整齐（整组同班次最好；2+2 可接受；落单强烈避免；一个 pod 最多 2 种班次）；
- 轻微贴近人工填写的 `preferred_open_hours`（次要信号）。

## 安装

```bash
pip install -e .
# 或： pip install -r requirements.txt
```

> ⚠️ **ortools 版本**：`pip install ortools` 会装 9.15，在部分 Windows 环境
> 加载失败（`WinError 127`），且把 numpy/pandas 升到 2.x/3.x。请用：
> `pip install --no-deps "ortools==9.10.4067"`

依赖：`ortools==9.10.4067`、`pandas<2.2`、`numpy<2`、`openpyxl`。Python ≥ 3.10。

## 用法

```bash
python scripts/make_templates.py          # 生成 data/config.xlsx 和 data/demand.xlsx 示例

shift-optimizer                            # 用默认路径跑
shift-optimizer --config data/config.xlsx --demand data/demand.xlsx --out out.xlsx
shift-optimizer --perf-weight 0.4 --pref-weight 0   # 完全按业绩、忽略人工偏好
python -m shift_optimizer --help
```

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

**一张台一行**（master 清单）。列名不分大小写、空格/大小写自动规整。

| 列 | 必填 | 说明 |
|---|---|---|
| `table` | ✅ | 台名/编号，唯一 |
| `pod` | ✅ | 所属 pod 名，pod 大小不限（不必是 4） |
| `preferred_open_hours` | 可选 | 人工偏好时长，必须是 `24/16/8/0`，可逐行留空。别名 `pref` / `preferred_hours` / `preference` / `open_hours` |
| `theo_per_open_hour` | 可选 | 每营业小时理论赢数 (Theo)，**历史数据**。别名 `theo` / `theo_per_hour`。留空 = 新台无历史 |
| `patron_hands_per_hour` | 可选 | 每小时客人手数，**历史数据**。别名 `hands` / `patron_hands`。留空 = 新台无历史 |
| `available_from` | 可选 | 该台生效日期（含）。别名 `start_date` / `valid_from`。留空 = 一直有效 |
| `available_to` | 可选 | 该台失效日期（含）。别名 `end_date` / `valid_to`。留空 = 一直有效 |

**按天可用**：求解某一天时，只纳入 `available_from ≤ 当天 ≤ available_to` 的台。
完全不写这两列 → 所有台每天都在（且需求 Excel 的 `day` 不必是日期）。

**评分**：`score = 0.8 × Theo_归一化 + 0.2 × Hands_归一化`（min–max 到 0..1），据此排名。
- 归一化只在**当天有历史的台**之间做；
- **新台**（Theo/Hands 留空）→ 评分取当天有历史台评分的**中位数**（不因此被压到短班次，也不占高价值台的位置）；
- 当天没有任何台有历史 → 评分全 0，退化成"只按覆盖 + 人工偏好"。

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
| `schedules` | 长表：`day, table, pod, rank, score, has_history, preferred_open_hours, shift, shift_open_hours` |
| `coverage` | 逐日逐小时：`demand, capacity, tables_open, shortage, surplus` |

## 权重与优先级

目标函数（最小化）：

```
2.5·Σ缺口  +  1·Σ过剩  +  Σ pod拆分罚分  +  PREF_WEIGHT·Σ偏好偏离  −  PERF_WEIGHT·Σ(score·开机小时)
```

| 常量 | 默认 | 作用 |
|---|---|---|
| `WEIGHT_SHORTAGE` / `WEIGHT_SURPLUS` | 2.5 / 1 | 覆盖需求（最高优先级） |
| `PENALTY_UNEVEN_SPLIT` / `PENALTY_PAIRED_SPLIT` | 30 / 2 | pod 落单 / 对半拆 |
| `PERF_WEIGHT` | 0.25 | 业绩排名决定班次长短（主信号） |
| `PREF_WEIGHT` | 0.10 | 人工偏好（弱微调；设 0 忽略） |
| `THEO_SHARE` | 0.80 | score 里 Theo 占比 |

`PERF_WEIGHT` / `PREF_WEIGHT` 可用命令行 `--perf-weight` / `--pref-weight` 覆盖。

## 开发

```bash
pip install -e ".[dev]"
pytest                       # 24 个测试；test_model.py 需要 ortools，缺则自动跳过
```

## 目录

```
src/shift_optimizer/
  config.py     班次目录 / 时长类别 / 权重
  scoring.py    业绩指标 -> 0..1 综合评分 + 排名
  io_excel.py   读配置/需求、写结果、按天组装可用台
                TableInfo / FleetConfig / DayDemand / DayFleet / DayResult / build_day_fleet
  model.py      CP-SAT 建模 + 逐日求解；pod_penalty_schedule
  cli.py        命令行入口
scripts/make_templates.py   生成示例 Excel
data/           示例输入
tests/          pytest
```

模型细节（pod 约束、偏好罚分机制、07:00 约定的来龙去脉）见 git 历史里更早的带详细中文注释的单文件版本。
