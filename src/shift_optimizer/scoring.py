"""
把每张台的业绩指标 (Theo per open hour, Patron Hands per hour) 变成一个
0..1 的综合评分，再据此排名。评分只用来在【同等覆盖】下决定"谁上长班次"。
"""

from __future__ import annotations

from .config import THEO_SHARE


def normalize(values: list[float]) -> list[float]:
    """min-max 归一化到 0..1。所有值相同时返回全 0（评分不产生偏向）。"""
    lo, hi = min(values), max(values)
    if hi - lo <= 1e-12:
        return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def performance_score(theo: list[float], hands: list[float],
                      theo_share: float = THEO_SHARE) -> list[float]:
    """
    综合评分 = theo_share * Theo_norm + (1 - theo_share) * Hands_norm，范围 0..1。
    Theo 为主 (默认 0.8)，Patron Hands 为辅 (0.2)。
    """
    tn = normalize(theo)
    hn = normalize(hands)
    return [theo_share * a + (1.0 - theo_share) * b for a, b in zip(tn, hn)]


def ranking(scores: list[float]) -> list[int]:
    """返回每张台的名次（1 = 评分最高）。评分相同则按原下标先后。"""
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    rank = [0] * len(scores)
    for position, idx in enumerate(order, start=1):
        rank[idx] = position
    return rank
