"""注释策略的阳性/阴性对照(2026-10-18)。

这份夹具故意同时含有该报与不该报的形态。`selfcheck/run.py` 按规则计数:
条件链只报链头、简单 for 不报、while 必报、纯调用赋值不报、Attributes 字段不报。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Documented:
    """字段由 Attributes 小节统一说明。

    Attributes:
        alpha: 第一个值,单位个。
        beta: 第二个值,单位个。
    """

    alpha: int
    beta: int


@dataclass(frozen=True)
class Bare:
    """字段没有注释,也没有 Attributes 小节。

    这份类只用来验证缺注释仍会被报出来。
    """

    gamma: int


def branches(value):
    """按符号分类。

    负数、零、正数各走一条路,链头一条注释覆盖整条链。

    Args:
        value: 待分类的数。

    Returns:
        分类名。
    """
    # 负数、零、正数走不同分支;elif 不再单独要求注释
    if value < 0:
        return "neg"
    elif value == 0:
        return "zero"
    return "pos"


def simple_loop(values):
    """逐项累加。

    单句 for 不要求注释;循环体里的算式赋值仍要求一条。

    Args:
        values: 整数列表。

    Returns:
        累加结果。
    """
    total = 0
    # 逐个累加;整数相加不引入浮点误差
    for value in values:
        total = total + value
    return total


def complex_loop(values):
    """把总数抬到十以上。

    while 是复杂循环,上方必须有一条独立注释。

    Args:
        values: 未使用的输入,只为保持签名。

    Returns:
        不小于十的总数。
    """
    total = 0
    while total < 10:
        # 每轮加一,直到达到下界
        total = total + 1
    return total


def assignments(values):
    """纯调用与算式各一条。

    只有算式赋值要求注释;`len(values)` 是纯调用,不要求。

    Args:
        values: 任意序列。

    Returns:
        两个数的和。
    """
    size = len(values)
    total = 0 + 1
    return size + total


def failures(value):
    """失败态与返回值都不再单独要求注释。

    raise 的前提与 return 的口径归 docstring 的 Raises / Returns 小节。

    Args:
        value: 输入数。

    Returns:
        大于零时返回加一后的值。

    Raises:
        ValueError: 输入为负数。
    """
    if value < 0:
        raise ValueError(value)
    return value + 1
