> 入口:[SKILL.md](../SKILL.md) —— 本文件不单独生效。
> 相关:[opus-style.md](opus-style.md)(注释的内容标准)、[docstrings.md](docstrings.md)(函数文档)。

# 注释写在哪、写什么

依据 **Google Python Style Guide 3.8.5 Block and Inline Comments**:

> Complicated operations get a few lines of comments before the operations commence.
> Non-obvious ones get comments at the end of the line.
> Never describe the code.

一句原则:注释解释**为什么**。代码已经说清**做什么**时不写。

## if / elif:一条链一条注释(2026-10-18 用户定)

- Python 后端把 `elif` 归进同一条链,只检查链头。
- 注释写在链头 `if` 的上一行,一条覆盖整条链。
- 不要求把 `and` / `or` 拆行,也不要求逐个 operand 注释。
- **卫语句放行**(2026-10-27):单条件、无 `elif` / `else`、体只有一句
  `return` / `raise` / `continue` / `break` 的 `if` 不要求注释。带 `and` / `or` 的仍要求。
- **行尾注释不算**。说明压在代码旁边,读者仍要倒着找。

```python
# 几何缺失 ⇒ 开不出仓;热度出带 ⇒ 入场即触发出场,白付两条腿 gas
if row.geometry_status != 'ok' or not config.heat_low <= row.heat_1h <= config.heat_high:
    continue
```

`elif` 的前提通常已被同一条注释覆盖。真的需要单独说明时,写在该分支体里,
不要为每个 `elif` 再加一条链头注释。

## 循环:只要求复杂循环(2026-10-18)

满足任一条才要求注释:

1. `while` —— 退出条件一般不是「遍历完就停」。
2. 循环体 ≥ 3 条语句 —— 一轮做几件事。
3. 体里有 `break` / `continue` —— 有提前退出。

简单单句 `for` 不要求。注释写三件事:**遍历什么、每轮做什么、为什么必须循环**。

```python
# 逐行累加:行与行之间有 carry 依赖,顺序是语义,向量化会改变结果
for row in rows:
    carry = carry + row.fee_raw
```

## 赋值:只要求有口径的算式(2026-10-18,2026-10-27 放宽)

右侧是**三元 / 比较**,或运算里含**两个以上运算符、数字常数、`//` `%`、
`min` / `max` / `round` / `int` / `floor` / `ceil` 调用**时要求注释。
字面量、纯函数调用、`total + x` 这种单运算符算式不要求:

```python
limit = 8                       # 字面量:不要求
fee = compute_fee(order)        # 纯调用:不要求
total = total + fee             # 单运算符:不要求
# 手续费按两条腿的较小值收,避免单边深度不足时高估成本
fee = min(fee_a, fee_b) * config.fee_rate
```

变量名说「是什么」,注释说「怎么来的、为什么这么算」。

## raise / return:说明归 docstring(2026-10-18)

`raise` 与 `return` **不再单独要求注释**。失败前提写进 `Raises:`,返回口径写进
`Returns:`,两处都在函数 docstring 里。这样调用方不用读实现也能看到。

```python
def width(sample):
    """区间宽度。

    Returns:
        缩放后的宽度,单位与 tick 相同。

    Raises:
        ValueError: 上界不大于下界。
    """
    # 空区间继续算会得到 0 宽度的假仓位
    if sample.upper <= sample.lower:
        raise ValueError("empty range")
    # 先取差再缩放,避免两次取整放大误差
    return (sample.upper - sample.lower) * sample.scale
```

注释仍然可以写**踩过的坑**。上面两条注释留下,是因为它们解释了代码看不出的风险。

## 扁平代码:连续 > 10 条且整段无注释(2026-10-18)

判据只有一条:**连续 10 条以上语句,整段没有任何注释**。

- 一组操作前面写**一段多行块注释**即可,不必一行一条。
- **空行与注释块都会切断平铺段**。
- 由注释块引出的那一组,视为已说明,不按平铺上报。

```python
# 从原始成交重建持仓:先按时间排序,再逐笔合并,最后写回缓存。
# 三步共用同一份快照;中途任何一步失败都保持原缓存不动。
snapshot = load_snapshot(path)
snapshot.sort(key=lambda row: row.ts)
merged = merge_fills(snapshot, fills)
merged = normalize(merged)
save_snapshot(cache_path, merged)
```

## 字段:两种落点(2026-10-18)

只要求**数值字段**(注解里有 `int` / `float` / `Decimal` / `Fraction`,含 `int | None`);
`name: str` 这类名字已说清的字段不要求(2026-10-27)。数值字段二选一,不许两处都不写:

1. 字段上方一行独立注释,或本行行尾注释。
2. 类 docstring 的 `Attributes:` 小节统一说明。

```python
@dataclass(frozen=True)
class Quote:
    """一条报价。

    Attributes:
        quote_raw: 报价腿余额,raw 整数(未除 decimals);None = 无法估值,不是 0。
        updated_at: 报价时间,UTC 秒。
    """

    quote_raw: int | None
    updated_at: int
```

字段是唯一被认可的**行尾注释**场景。它一行放得下单位、口径与取值范围。

## 位置边界

链头与循环的注释必须**紧贴上一行**。写在 `try:` / `with:` 上方只解释了那个块,
不解释块内的算式赋值:

```python
# ❌ try 上方的注释不算给里面的赋值
try:
    balance = balance - fee

# ✅
try:
    # 扣款后的余额;失败时保持原值
    balance = balance - fee
```

## 踩过的坑当场写

**修好之前写,修好之后也不要删。** 注释是坑的墓碑,不是待办事项。
写三件:**症状 → 成因 → 为什么这个写法能挡住**。

```python
# float(H) + L 在超过 2^53 时会差 1 ULP,而 L/(H+L) 的分母正好落在那个量级,
# 于是宽区间的费用分配和窄区间不一致。必须整数相加再 true divide。
share = L / (H + L)
```

写的是**这段代码本身的坑**,不是流水账。「我试了 A 不行改用 B」进记忆;
「为什么不能用 A」进代码。

## 删空行 = 作弊

空行是段落。实测抓到过把 PEP 8 空行删光、让 500 行闸失效的交法:
`fees/cache.py` 500 行 0 空行,而正常文件是 9–10%。顶层定义之间 2 个空行,
类内方法 1 个;定义上方紧贴的注释块算定义的一部分,空行在注释块之前。
