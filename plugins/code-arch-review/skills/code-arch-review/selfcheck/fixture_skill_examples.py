"""SKILL.md 的最低通过样本:照一页速查表写,闸必须判 0 违规与 100% 覆盖。

它不追求功能,只要求把「条件 / 循环 / 字段 / 计算赋值 / 算式 return / 文档」
各放一个,并且全部解释到位 —— 每类构造都在,覆盖率才可能到 100%。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    """一个左闭右开的计数窗口。

    存在的理由是让所有调用方共用同一个边界口径,不必各自减一。
    """

    start: int  # 起点,闭端。
    stop: int  # 终点,开端。


def total(window, values):
    """累加窗口内的整数。

    只加窗口内的元素,窗口外的值不参与。窗口为空时返回 0,不抛异常 ——
    调用方对空输入有统一处置,这里抛异常只会让每个调用方都写一遍 try。

    Args:
        window: 计数窗口。
        values: 待累加的整数列表。

    Returns:
        窗口内的元素之和,单位与输入相同。
    """
    # 空窗口直接返回 0:后面逐个取下标会越界。
    if window.start >= window.stop:
        return 0
    # 从 0 起累加;顺序不影响结果,写循环是为了让越界判断只做一次。
    subtotal = 0
    # 逐个取窗口内的元素。
    for index in range(window.start, window.stop):
        # 累加当前元素;整数相加,不引入浮点误差。
        subtotal = subtotal + values[index]
    # 返回值口径:整数和,不缩放、不取整。
    return subtotal + 0
