"""闸口径一致性的最小验证件。

只放「该解释的构造」各一个,全部按规则解释到位,用来验证
「注释类规则零违规」与「覆盖率 100%」是同一个口径。
raise 与算式 return 故意不写注释:2026-10-18 起它们不计入分母。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    """一条样本。

    字段用行尾注释,验证行尾说明能同时被 scan 与覆盖率认作已解释。
    """

    lower: int  # 区间下界,闭端。
    upper: int  # 区间上界,开端。


def pick(sample, scale):
    """按缩放系数取区间宽度。

    存在的理由是把「上界开端」这件事收在一处,调用方不必各自减一。

    Args:
        sample: 一条 Sample。
        scale: 缩放系数,无量纲。

    Returns:
        缩放后的区间宽度,单位与 tick 相同。

    Raises:
        ValueError: 区间为空。
    """
    # 上界必须严格大于下界:相等表示空区间,继续算会得到 0 宽度的假仓位。
    if sample.upper <= sample.lower:
        raise ValueError("empty range")
    # 宽度按 tick 计,先取差再缩放,避免两次取整放大误差。
    width = (sample.upper - sample.lower) * scale
    return width + 0
