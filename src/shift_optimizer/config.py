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

# --- 每个班次的开/关钟点（用来判断两个班次是不是"衔接得上"）------------
#   (start_clock, end_clock)，取值 0..23；G(全天关闭) 没有钟点，记 None。
#   A(24h) 的开=关=07:00（转一圈回到原点）。
def _shift_boundaries(shift: int) -> tuple[int, int] | None:
    ones = [h for h in range(HOURS_PER_DAY) if SHIFT_COVERS_HOUR[shift, h]]
    if not ones:
        return None
    start_clock = (GAMING_DAY_START_HOUR + ones[0]) % 24
    end_clock = (GAMING_DAY_START_HOUR + ones[-1] + 1) % 24
    return (start_clock, end_clock)


SHIFT_BOUNDARIES = [_shift_boundaries(s) for s in range(NUM_SHIFTS)]


def _shares_a_boundary(s1: int, s2: int) -> bool:
    """
    两个班次的"开钟点/关钟点"集合是否有交集——包含两种"衔接得上"的情形:
      * 同时开始 或 同时结束（比如 C 和 H 都是 12:00 开始）；
      * 一个的收尾正好是另一个的开始，首尾相接、没有缝隙（比如 H 20:00 收尾，
        L 正好 20:00 接上；两者若各拆给一半台，交班干净利落）。
    """
    b1, b2 = SHIFT_BOUNDARIES[s1], SHIFT_BOUNDARIES[s2]
    if b1 is None or b2 is None:                 # 一个关闭(G)，没有钟点可比，一律算"接不上"
        return False
    return bool({b1[0], b1[1]} & {b2[0], b2[1]})


# 组内共用开钟点或关钟点的班次对（同长度或不同长度都算，只看钟点）。
# 用当前班次表算出来正好是：
#   A-E（同 07:00 收尾）、A-N（同 07:00 收尾）、C-H（同 12:00 开始）、C-L（同 04:00 收尾）、
#   E-J（同 15:00 开始）、E-N（同 07:00 收尾）、H-L（12:00-20:00 接 20:00-04:00，正好衔接）、
#   J-N（15:00-23:00 接 23:00-07:00，正好衔接）
SOFT_SHIFT_PAIRS = [(s1, s2) for s1 in range(NUM_SHIFTS) for s2 in range(s1 + 1, NUM_SHIFTS)
                    if _shares_a_boundary(s1, s2)]

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
PENALTY_UNEVEN_SPLIT = 30    # pod 拆分明显偏向一边时的基准罚分（见 model.pod_penalty_schedule）
PENALTY_PAIRED_SPLIT = 2     # pod 拆成该 pod 大小下"最公平"那种两段拆分时的基准罚分
MAX_DISTINCT_SHIFTS_PER_POD = 2

# 一个 pod 拆成 2 个班次时，如果这 2 个班次【共用一个开钟点或关钟点】——
# 例如 H(12:00-20:00) 接 L(20:00-04:00)，交接顺、不留缝隙、不需要额外协调——
# 就把该 pod 当次拆分的罚分打个折；两个班次开关钟点【完全对不上】则不打折，按基准罚分。
# 折扣是比例，不是新的绝对值：0.5 = 打对折，0 = 不打折（等于关掉这条规则）。
SOFT_SPLIT_DISCOUNT = 0.5

# 业绩奖励项：目标里减去  PERF_WEIGHT * Σ_台 score[台] * (该台开机小时数)
#   score 已归一化到 0..1（见 scoring.py），所以每张台一天的最大奖励 ≈ PERF_WEIGHT * 24。
#   在【覆盖需求 / pod 规则】允许的范围内，这一项把"长班次"尽量分给 score 高的台。
#   PERF_WEIGHT 越大 -> 越倾向把长班次给高业绩的台；过大会开始牺牲覆盖。
PERF_WEIGHT = 0.25
THEO_SHARE  = 0.80          # score = THEO_SHARE*Theo_norm + (1-THEO_SHARE)*Hands_norm

# 同长度内的"窗口"奖励：目标里减去  WINDOW_WEIGHT * Σ_台 score[台] * desirability[该台选的班次]
#   desirability 只在【同一时长类别内】比较、且当天现算（见 model.py 的 _window_desirability）：
#   16h 里比 C 和 E 各覆盖了多少当天需求、8h 里比 H/L/J/N 各覆盖了多少，min-max 到 0..1。
#   24h(只有 A)和关闭(只有 G)没有"选哪个窗口"这回事，desirability 恒为 0。
#   效果：当覆盖需求允许【同一时长但不同窗口】之间二选一时，把需求覆盖更多的窗口给评分更高的台。
#   权重比 PERF_WEIGHT 小一个量级 —— 这是同长度内的"细"排序，不应该反过来影响
#   "选哪个时长类别"或覆盖本身的决定。设 0 关闭这项（只按覆盖挑窗口，如旧版）。
WINDOW_WEIGHT = 0.05

# 人工偏好项：目标里加  PREF_WEIGHT * Σ 偏离罚分。
#   现在业绩排名是决定班次长短的【主】信号，人工偏好只是【弱】微调，所以默认很小。
#   想让 preferred_open_hours 起主导作用 -> 调大 --pref-weight（或调小 --perf-weight）。
#   设 0 可完全忽略 preferred_open_hours。
PREF_WEIGHT = 0.10

DEFAULT_TIME_LIMIT_S = 60   # 每天求解时间上限（模型很小，通常 1 秒内出最优）
