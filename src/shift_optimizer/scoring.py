"""
把每张台的业绩指标 (Theo per open hour, Patron Hands per hour) 变成一个
0..1 的综合评分，再据此排名。评分只用来在【同等覆盖】下决定"谁上长班次"。

新台没有历史业绩 (theo / hands 留空) -> 给它【当天有历史的台的评分中位数】，
既不因此被压到短班次，也不会挤掉真正的高价值台。
"""

from __future__ import annotations

from statistics import median

from .config import THEO_SHARE


def normalize(values: list[float]) -> list[float]:
    """min-max 归一化到 0..1。所有值相同时返回全 0（评分不产生偏向）。"""
    lo, hi = min(values), max(values)
    if hi - lo <= 1e-12:
        return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def performance_score(theo: list[float | None],
                      hands: list[float | None],
                      theo_share: float = THEO_SHARE) -> list[float]:
    """
    综合评分 = theo_share * Theo_norm + (1 - theo_share) * Hands_norm，范围 0..1。
    Theo 为主 (默认 0.8)，Patron Hands 为辅 (0.2)。

    theo[i] 或 hands[i] 为 None 视为"无历史"：
      * 有历史的台之间做归一化并算分；
      * 无历史的台拿"有历史台评分"的中位数；
      * 全部无历史 -> 全 0（业绩项不起作用）。
    """
    known = [i for i in range(len(theo)) if theo[i] is not None and hands[i] is not None]
    if not known:
        return [0.0] * len(theo)

    tn = normalize([float(theo[i]) for i in known])
    hn = normalize([float(hands[i]) for i in known])
    known_score = {i: theo_share * a + (1.0 - theo_share) * b
                   for i, a, b in zip(known, tn, hn)}
    fill = median(known_score.values())
    return [known_score.get(i, fill) for i in range(len(theo))]


def ranking(scores: list[float]) -> list[int]:
    """返回每张台的名次（1 = 评分最高）。评分相同则按原下标先后。"""
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    rank = [0] * len(scores)
    for position, idx in enumerate(order, start=1):
        rank[idx] = position
    return rank
