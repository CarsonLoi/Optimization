"""
脚本级配置：班次目录、时长类别、目标函数权重。
这部分【不来自 Excel】——改班次定义或调权重就改这里。

时间约定
--------
营业日从 07:00 开始。小时下标 0 = 07:00-08:00，……，下标 23 = 次日 06:00-07:00。
时钟 = (GAMING_DAY_START_HOUR + 下标) % 24。
"""

import numpy as np

# --- 班次目录 -----------------------------------------------------------
SHIFT_CODES = ['G', 'A', 'C', 'E', 'H', 'L', 'J', 'N']
NUM_SHIFTS = len(SHIFT_CODES)

GAMING_DAY_START_HOUR = 7
HOURS_PER_DAY = 24

# SHIFT_COVERS_HOUR[shift, hour] == 1  ->  选了该班次的台在该小时下标是开着的。
# 列 = 小时下标 0..23（下标 0 = 07:00 那一格）。
SHIFT_COVERS_HOUR = np.array([
    [0] * 24,                                                      # G  关闭
    [1] * 24,                                                      # A  24h  07:00 -> 07:00 +1d
    [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],  # C  16h  12:00 -> 04:00 +1d
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],  # E  16h  15:00 -> 07:00 +1d
    [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  # H  8h   12:00 -> 20:00
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],  # L  8h   20:00 -> 04:00 +1d
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0],  # J  8h   15:00 -> 23:00
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1],  # N  8h   23:00 -> 07:00 +1d
])
assert SHIFT_COVERS_HOUR.shape == (NUM_SHIFTS, HOURS_PER_DAY)

# --- 时长类别（从上表每行的开机小时数自动推导，单一数据源）-------------
#   类别编号: 0 = 24h, 1 = 16h, 2 = 8h, 3 = 关闭
_LENGTH_BUCKETS = (24, 16, 8, 0)
CATEGORY_INDEX = {24: 0, 16: 1, 8: 2, 0: 3}


def bucket_hours(open_hours: int) -> int:
    """把任意开机小时数归到最近的 {24,16,8,0} 桶。"""
    return min(_LENGTH_BUCKETS, key=lambda c: abs(c - open_hours))


SHIFT_OPEN_HOURS = [int(row.sum()) for row in SHIFT_COVERS_HOUR]          # 例: [0,24,16,16,8,8,8,8]
SHIFT_CATEGORY   = [CATEGORY_INDEX[bucket_hours(h)] for h in SHIFT_OPEN_HOURS]

# --- 偏好营业时长的偏离罚分（沿用旧模型）------------------------------
# 内层 key = 实际落到的类别编号；净效果 = 惩罚"类别距离"。
PENALTY_BY_PREF_AND_CATEGORY = {
    24: {0: 3, 1: 2, 2: 1, 3: 0},
    16: {0: 2, 1: 3, 2: 2, 3: 1},
    8:  {0: 1, 1: 2, 2: 3, 3: 2},
    0:  {0: 0, 1: 1, 2: 2, 3: 3},
}
VALID_PREF_HOURS = set(PENALTY_BY_PREF_AND_CATEGORY)     # {0, 8, 16, 24}

# --- 目标函数权重 -----------------------------------------------------
# 优先级（从高到低）：满足需求  >  按业绩排名分配长班次  >  贴近人工偏好
WEIGHT_SHORTAGE      = 2.5   # 缺 1 个"台·小时"罚 2.5（先保覆盖）
WEIGHT_SURPLUS       = 1.0   # 多 1 个"台·小时"罚 1
PENALTY_UNEVEN_SPLIT = 30    # pod 里某班次落单（少数侧只有 1 张台）
PENALTY_PAIRED_SPLIT = 2     # pod 里某班次是"对半"拆的一侧
MAX_DISTINCT_SHIFTS_PER_POD = 2

# 业绩奖励项：目标里减去  PERF_WEIGHT * Σ_台 score[台] * (该台开机小时数)
#   score 已归一化到 0..1（见 scoring.py），所以每张台一天的最大奖励 ≈ PERF_WEIGHT * 24。
#   在【覆盖需求 / pod 规则】允许的范围内，这一项把"长班次"尽量分给 score 高的台。
#   PERF_WEIGHT 越大 -> 越倾向把长班次给高业绩的台；过大会开始牺牲覆盖。
PERF_WEIGHT = 0.25
THEO_SHARE  = 0.80          # score = THEO_SHARE*Theo_norm + (1-THEO_SHARE)*Hands_norm

# 人工偏好项：目标里加  PREF_WEIGHT * Σ 偏离罚分。
#   现在业绩排名是决定班次长短的【主】信号，人工偏好只是【弱】微调，所以默认很小。
#   想让 preferred_open_hours 起主导作用 -> 调大 --pref-weight（或调小 --perf-weight）。
#   设 0 可完全忽略 preferred_open_hours。
PREF_WEIGHT = 0.10

DEFAULT_TIME_LIMIT_S = 60   # 每天求解时间上限（模型很小，通常 1 秒内出最优）
