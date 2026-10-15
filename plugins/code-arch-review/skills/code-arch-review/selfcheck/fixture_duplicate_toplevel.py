"""`duplicate-toplevel` 的阳性对照 —— 一份【故意写坏】的样本。

闸对本文件必须报出 2 处 `duplicate-toplevel`(一个 def、一个常量),同时**不能**报出
下面那三类合法重复(try 回退、TYPE_CHECKING、扩展自身)。这两个方向缺一不可:
只验阳性,豁免写歪了会把存量代码淹掉;只验阴性,规则整个被删掉也照样绿。

形态取自 2026-09-17 真实事故:按文本位置切片搬函数(`s[s.index("def A"):s.index("def B")]`),
那一刀把两个函数各复制了一份进同一个文件,而当时的闸报 0 违规。
"""
import os
from typing import TYPE_CHECKING, overload

# ── 下面三类是【合法】重复,闸不许报 ──────────────────────────────

# try 回退:两个 `fast_json` 定义,但第二个嵌在 except 里,不是直接子节点
try:
    import orjson as fast_json
except ImportError:
    import json as fast_json

if TYPE_CHECKING:
    # 类型检查期的声明,与运行期的同名对象共存是标准写法
    PathLike = str

# 扩展自身:右侧引用了 `ROOTS`,是追加不是覆盖
ROOTS = ("a", "b")
ROOTS = ROOTS + ("c",)

# 规范化自身:同上,右侧引用了 `HOME`
HOME = os.path.expanduser("~")
HOME = os.path.abspath(HOME)


@overload
def pick(x: int) -> int:
    """重载签名之一 —— `typing.overload` 就是靠同名多次定义工作的。

    它在运行期会被最后那个真实现覆盖,这是语言设计如此,不是缺陷。
    """


@overload
def pick(x: str) -> str:
    """重载签名之二,同上。

    两个 `@overload` 加一个真实现,三个同名 def,闸一个都不该报。
    """


def pick(x):
    """`pick` 的真实现 —— 原样返回。

    Args:
        x: 任意值。

    Returns:
        原样的 `x`;这里不做转换,重载只用来描述类型关系。
    """
    # 重载只描述类型,运行期行为是恒等
    return x


# ── 下面两处是【该报】的重复,各一个 def 和一个常量 ────────────────

LIMIT = 5


def compute(x):
    """第一份实现 —— 返回两倍。

    Args:
        x: 被乘的数。

    Returns:
        `x` 的两倍;这一份在运行期永远不会被调用到。
    """
    # 两倍是最初的口径
    return x * 2


def compute(x):
    """第二份实现 —— 返回三倍,与第一份口径不一致。

    Args:
        x: 被乘的数。

    Returns:
        `x` 的三倍;调用方实际拿到的是这一份,而 grep 会先命中上面那份。
    """
    # 三倍是切片之后误留的口径
    return x * 3


LIMIT = 9
