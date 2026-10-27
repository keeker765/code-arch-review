> 入口:[SKILL.md](../SKILL.md) —— 本文件不单独生效。
> 相关:[comments.md](comments.md)(行内注释)、[opus-style.md](opus-style.md)(docstring 里该写什么)。

# 文档注释

标准是 **Google pyguide §3.8.3**(用户 2026-09-08 定)。判据一句话:
**不看一行实现就能写出调用。**

## 格式

公开且非平凡的函数必须有:一行摘要 → 解释段 → 分节。

```python
def build_pool_cache(handoff_path, output_dir, *, start, end):
    """把按时间排的费用表重写成按池有序的 SQLite 衍生缓存。

    源表按时间排、所有池交错,所以"查一个池"必然全扫。本缓存是可重建的派生物,
    源表不动。

    Args:
        handoff_path: 源费用表 manifest 的路径。
        output_dir: 缓存输出目录;必须不存在,存在即拒绝(防覆盖)。
        start: 覆盖窗起点,UTC 秒,闭端。
        end: 覆盖窗终点,UTC 秒,**开端**。

    Returns:
        写好的数据库文件路径。

    Raises:
        ValueError: 源 manifest 校验和不匹配。
    """
```

其它语言只换小节名(Python 的 `Args/Returns/Raises` ↔ JSDoc 的
`@param/@returns/@throws` ↔ PS 的 `.PARAMETER/.OUTPUTS`),判据不变。

## 🔴 一行式文档不算写了(`thin-docstring`)

```python
# ❌ 摘要把函数名重复了一遍,「为什么向上舍入、边界在哪」一个字没有
def sqrt_ratio_at_tick_up(tick):
    """按 TickMath 计算 tick 对应的向上舍入 Q64.96 平方根价格。"""

# ✅ 摘要之后另起解释段
def sqrt_ratio_at_tick_up(tick):
    """按 TickMath 计算 tick 对应的向上舍入 Q64.96 平方根价格。

    向上舍入是**必需的不是风格**:合约算区间上界用的就是上舍入,取下舍入会让
    仓位在边界 tick 上比链上多算一个 tick 的流动性。要下界用
    `sqrt_ratio_at_tick_down`,不要自己减一。
    """
```

判定口径:

- 闸数的是**摘要行之外、且不在 `Args:` / `Returns:` / `Raises:` 等小节里的散文行**,
  至少 1 行。只有一排小节不算。
- 函数体超过 `--trivial-body`(Python 默认 10 行,其他语言 5 行;**docstring 本身不计入体长**)
  才要求解释段与 `Args` / `Returns`;不超过的短函数,一行摘要即合格(2026-10-27 用户定)。
- **私有函数、类同样受约束** —— 写了文档就要解释完整。例外:没有 `__init__` / `__post_init__`
  的 dataclass 只是一组字段,一行摘要即合格。
- 带参数的函数必须写 `Args`;`Raises` 只在真的抛异常时写。

## 迁移口径

新写或改动过的函数必须合规;碰到哪个文件就顺手把那个文件补齐(童子军规则),
不专门开一轮重注释。

## 不要堆废话过闸

覆盖率的分母由代码结构决定,堆废话只能过 `thin-docstring`,过不了 review。
判据仍是:**不看一行实现就能写出调用。**
