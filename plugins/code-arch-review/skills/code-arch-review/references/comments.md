> 本文件由 `SKILL.md` 拆出,**不单独生效** —— 入口永远是 `SKILL.md`。

# 注释写在哪、写什么

## 🔴 if / raise:一个条件一行,注释一行(用户 2026-09-08 定)

对函数内**全部** `if` / `elif`,**包括顶层守卫**(点名:`if self.source is not None` 也要写):

1. **一个条件占一行** —— `a and b` 挤在同一行算违规。布尔组合按 `and`/`or` 摊平后逐个数,
   每个都是一次「判不过就走另一条路」的分叉。
2. **每个条件上面一行是独立的整行注释** —— **行尾注释不算**。写清:它在判什么、**判不过会怎样**。

```python
# ✅
if (
    # 几何缺失 ⇒ 开不出仓,不是零收益
    row.geometry_status != 'ok'
    # 热度出带 ⇒ 入场即触发出场,白付两条腿 gas
    or not config.heat_low <= row.heat_1h <= config.heat_high
    # 新池深度不可信,range_liquidity_floor 会虚高
    or at - pools[row.pool_id].created_at < config.min_age_seconds
):
    continue

# ❌ 挤行
if row.geometry_status != 'ok' or not config.heat_low <= row.heat_1h <= config.heat_high:

# ❌ 行尾注释(会被漏读,且一压行就更长)
if (row.geometry_status != 'ok'            # 几何缺失
        or row.fee_pips < config.min_fee_pips):   # 费率太低
```

**为什么是「上面一行」而不是行尾**:行尾注释挤在长条件之后,是压行的另一种形态,
换行/重排时最先被弄丢;独立成行的注释与条件一一对应,增删条件时不会串位。
与「不要压行」是同一条纪律:**能把注释挤没的写法,迟早会被挤没。**

`raise` 同理:上面一行独立注释,写明**什么前提被破坏了、调用方该怎么改**。
异常消息面向运行时,注释面向读代码的人。

```python
# 路径网格必须严格递增:重复或倒退的秒会让区间差算出负费用
if numpy.any(numpy.diff(grid) <= 0):
    # 上游 snapshot 排序坏了,继续算会静默产出负收益而不是报错
    raise ValueError('path grid must be strictly increasing integer UTC seconds')
```

**与"先减嵌套再写注释"不冲突**:先把能拆的嵌套拆掉;剩下的、确实必须存在的嵌套条件,
**一个都不许无注释**。注释不替代拆分,但拆不掉的地方必须逐条解释。

## 🔴 扁平代码 / 循环(用户 2026-09-08 定)

**扁平代码**:每个语义段前面加一行独立注释,说明这一段在干什么。闸按「连续 > 5 条语句无注释」报。

**循环**要求更高 —— 上面那行要写清三件事:**遍历什么、每轮做什么、为什么必须循环**
(即为什么不能向量化)。这条与「能向量化就向量化」配套:写不出"为什么不能向量化",
说明它本来就该向量化。

```python
# 逐行累加:行与行之间有 carry 依赖,顺序是语义,向量化会改变结果
for row in rows:
    carry = carry + row.fee_raw

# ① 把 W-无关的量算一次,后面 evaluate 就能纯 numpy
returns = stack.forward_returns()
funding = stack.funding_total()
# ② 成本口径从 yaml 取,不在这里造默认值
fee_rate = config.fee_rate
slip_rate = config.slip_rate
```

**范本 = `fast_books/ctx.py`**(用户点名)。数据类每个字段后面跟着**形状 + 含义 + 口径**:

```python
R: np.ndarray                 # [T, N] forward return (engine's, honours pit fill lag)
uf: object | None = None      # bare MultiSleeveStrategy exposing the REAL
                              # _universe_filter_drop (W-dependent: the 8%
                              # tail is taken among the book's own names)
```

它写的不是「这是什么类型」(注解已经说了),而是**形状 `[T, N]`、单位、以及这个值怎么来的、
什么时候是 0**。**字段注释是唯一被认可的"行尾注释"场景** —— 它与字段一一对应,不是压行。

## 🔴 踩过的坑当场写(用户 2026-09-08 定)

**修好之前写,修好之后也不要删。** 删掉等于把「为什么要这么写」一起删了 ——
下一个人看到绕弯的代码,第一反应是"这里可以简化",于是把坑重踩一遍。
**注释是坑的墓碑,不是待办事项。**

写三件:**症状 → 成因 → 为什么这个写法能挡住**。

```python
# 修好之后保留 —— 说清为什么不能简化
# float(H) + L 在超过 2^53 时会差 1 ULP(3.6e-16),而 L/(H+L) 的分母正好落在那个量级,
# 于是宽区间的仓位算出来的费用分配和窄区间不一致。必须整数相加再 true divide。
share = L / (H + L)

# 还没修 —— 写清现状边界和升级路径
# 已知上限:这里对每个池独立全扫费用表,池数一多就是 O(池数 × 全表)。
# 根因是源表按时间排、池交错,row group 剪枝按构造失效(实测 1978 行散在 42/47 组)。
# 升级路径 = 按池重排的衍生缓存,不是把这个循环写快。
for pool_id in pool_ids:
    rows = read_fee_rows(pool_id)
```

**边界**:写的是**这段代码本身的坑**,不是流水账。「2026-09-08 我试了 A 不行改用 B」
属于报告/记忆;**"为什么不能用 A"** 进代码。

## 🔴 变量与字段:名字说「是什么」,注释说「怎么来的」(用户 2026-09-08 定)

用户原话:「注释还是写的太少了……**特别是变量定义**」。

起因:`results/account_ledger.py` 说明密度 38.7%、旧闸零违规,但 **12 个数据类字段一个注释都没有**,
算出来的赋值 15 个里只有 5 个有注释 —— 旧闸只看 if / 循环 / raise / 扁平段 / docstring,
**完全不看变量定义**。

```python
@dataclass(frozen=True)
class PositionMark:
    # 池 tick 下界,闭端;与 tick_upper 一起定义仓位区间。
    tick_lower: int
    # 池 tick 上界,**开端** —— 与合约一致,等于 tick_upper 时不在区间内。
    tick_upper: int
    # 报价腿余额,raw 整数(未除 decimals);None = 该时点无法估值,不是 0。
    quote_raw: int | None
```

**算出来的变量**:右侧是运算 / 调用 / 三元 / 比较时要求注释。**字面量赋值不算** —— `limit = 8` 没什么可解释的。

```python
# ✅ 口径写在算式上面
# 池价来自 sqrtPriceX96,平方前先除 2^96;这里不做 decimals 归一,下游按 raw 口径消费。
ratio = (np.asarray(prices, dtype=float) / (1 << 96)) ** 2
```

**算式 return**:`return <算式>` 要求上方写明返回值口径 —— 单位、正负号约定、边界。
`return x`、`return None`、`return self.foo` 不算算式,不要求。

```python
# 返回净额:总价值扣掉本池手续费与单腿 gas,单位 = 报价腿 raw 整数,可能为负。
return value - coin_value * fee_rate - self.gas_quote_raw_per_leg
```

### 一条边界

这三条防的是「读者得去猜」,不是「每行都要有字」。
**注释重复代码等于没写** —— `# 把 a 和 b 相加` 会过闸但会被 review 打回。

## 🔴 删空行 = 作弊(2026-09-08 实测抓到)

`fees/cache.py` 交上来时 **500 行整,空行 0 个**;`matrix.py` 495、`source.py` 490 ——
三个文件全部卡在 500 行闸的线下。手法是把 PEP 8 的空行全删掉。

对照:`position/path.py` 空行 10.2%,`fast_books/ctx.py` 9.0%。**0.0% 不是风格,是压缩。**

更糟的是「说明密度」这个指标**奖励**了它:删掉空行,分母变小,密度反而上升。
**一个能被优化的指标,就会被优化。** 所以 `packed-layout` 现在是硬闸:
顶层 `def`/`class` 之间 2 个空行,类内方法 1 个(定义上方紧贴的注释块算定义的一部分,
空行要在注释块之前)。

**这条的意义不在排版**:空行是段落。删光之后 500 行是一整块,读者没有任何落脚点;
而且它让 `long-module` 这条硬闸失效 —— 任何文件都能靠删空行"变短"。
