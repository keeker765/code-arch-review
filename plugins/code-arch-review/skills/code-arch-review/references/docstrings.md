> 本文件由 `SKILL.md` 拆出,**不单独生效** —— 入口永远是 `SKILL.md`。

# 文档注释

标准是 **Google pyguide §3.8.3**(用户 2026-09-08 定)。判据一句话:
**不看一行实现就能写出调用。**

## 格式

公开且非平凡的函数必须有:一行摘要 → 解释段 → 分节。

```python
def build_pool_cache(handoff_path, output_dir, *, start, end):
    """把按时间排的费用表重写成按池有序的 SQLite 衍生缓存。

    源表按时间排、所有池交错,活跃池散在几乎每个 row group 里,所以"查一个池"
    必然全扫。本缓存是可重建的派生物,源表不动。

    Args:
        handoff_path: 源费用表 manifest 的路径。
        output_dir: 缓存输出目录;必须不存在,存在即拒绝(防覆盖)。
        start: 覆盖窗起点,UTC 秒,闭端。
        end: 覆盖窗终点,UTC 秒,**开端**。

    Returns:
        写好的数据库文件路径;manifest 在全部校验通过后才发布。

    Raises:
        OSError: 输出目录或临时目录可用空间不足 8GiB。
        ValueError: 源 manifest 校验和不匹配。
    """
```

其它语言只换小节名(Python 的 `Args/Returns/Raises` ↔ JSDoc 的 `@param/@returns/@throws`
↔ PS 注释式帮助的 `.PARAMETER/.OUTPUTS`),判据不变。见 `languages.md`。

## 🔴 一行式文档不算写了(`thin-docstring`)

```python
# ❌ 摘要把函数名重复了一遍,读者要的「为什么向上舍入、边界在哪」一个字没有
def sqrt_ratio_at_tick_up(tick):
    """按 TickMath 计算 tick 对应的向上舍入 Q64.96 平方根价格。"""
```

```python
# ✅ 摘要之后另起解释段
def sqrt_ratio_at_tick_up(tick):
    """按 TickMath 计算 tick 对应的向上舍入 Q64.96 平方根价格。

    向上舍入是**必需的不是风格**:合约在计算区间上界时用的就是上舍入,取下舍入会让
    仓位在边界 tick 上比链上多算一个 tick 的流动性,回测出现链上不存在的成交。
    调用方若要下界,用 `sqrt_ratio_at_tick_down`,不要自己减一。
    """
```

判定口径:

- 闸数的是**摘要行之外、且不在 `Args:` / `Returns:` / `Raises:` / `Yields:` 等小节里的散文行**
  —— 小节是接口清单,不是解释。至少要有 1 行。
- 函数体超过 `--trivial-body`(默认 5 行)才要求,**真正平凡的一行函数照旧放行**。
- **私有函数也算** —— 它写了文档就说明作者认为需要解释,那就解释完整。
- 类同样受约束。

## 迁移口径

- **新写或改动过的函数必须合规** —— 碰到哪个函数就按此写,不用等专项治理。
- **存量是欠账不是阻塞**:来源仓库的 `onchain_lp` 当时有 86 处,不要求一次补完;
  碰到哪个文件就顺手把那个文件补齐(童子军规则)。
- 散文体不是错,**分节是必需的** —— 先写一段「为什么存在」,再跟 Args/Returns/Raises。

## 不要堆废话过闸

覆盖率的分母由代码结构决定,堆废话只能过 `thin-docstring` 这一条,过不了 review。
判据仍是 `rationale.md` 那条:**不看一行实现就能写出调用**。
