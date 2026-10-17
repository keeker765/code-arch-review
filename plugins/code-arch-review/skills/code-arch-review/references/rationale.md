> 入口:[SKILL.md](../SKILL.md) —— 本文件不单独生效,它在对应位置指过来。
> 相关:[opus-style.md](opus-style.md)(闸量不到的那一层)、[languages.md](languages.md)(各语言依据)。

## 闸拦不住的,必须人看

工具只能量形状。以下靠 review,漏了照样是烂代码:

1. **类不是装函数的袋子。** 把长函数机械拆成一串私有方法,`long-function`
   会变绿而可读性更差。看的是:每个方法有没有独立可陈述的职责。
2. **注释要解释为什么,不是复述步骤。** "读取数据""计算费用"这种等于没写。
   关键类/方法要答:为什么存在 / 数据是什么(字段·单位·形状·轴) /
   谁准备谁调用谁持有状态谁校验 / 口径边界 / 为什么不能随意改。
3. **顺序约束要写下来。** 阶段之间"A 必须在 B 之前"是语义,不写就会被人重排。
4. **性能与数值口径。** numpy 里 `dtype=object` 的广播是逐元素 Python 调用,
   形状是矩阵不等于向量化;整数地板除与真除的边界一改就是静默错值。

## 参照实现

来源仓库的 `src/evaluation/backtest/fast_books/` —— 一个完整的正面例子(路径在别的项目里不存在):
`BookStack` 表达数据、`prepare` 完成准备、`Ctx` 持有计算上下文并提供清晰操作,
包入口 docstring 说明 WHY / 口径 / 用法。**说明密度 32.3%,对照
`onchain_lp/` 的 6.0%。**

## 依据 —— 这些规则不是我编的

**语言与风格(权威,大厂事实标准)**
* [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) —— Shopify、
  Chromium、Android 都是"follow Google + 少数例外"。**§3.8.3 是本闸 `docstring-sections`
  的依据**:docstring 应给出足够信息,使人**不看一行实现就能写出调用**;
  Args 逐项并标类型,Returns / Raises / Yields 各自成节。
* PEP 8 / PEP 257 —— 命名与 docstring 的底线。

**架构(公开且完整的少数几份)**
* [kiarina/crystal-architecture](https://github.com/kiarina/crystal-architecture) —— Python
  模块设计指南,最贴近本 skill 需要:功能从文件树可读、一文件一公开元素、功能拆子包、
  内部实现目录加 `_` 前缀、公开 API 收在子包 `__init__`、**依赖单向**、
  跨子包用绝对 import 而包内用相对 import(从 import 形式就能看出是碰自己内部还是别人公开 API)。
* [evrone-python-guidelines](https://github.com/evrone/evrone-python-guidelines/blob/master/EN.md)
  —— 少见地给了**硬数字**:函数 ≤50 行、模块 ≤300 行、行宽 100。本闸 `--max-body`
  默认 60 比它宽,收紧到 50 即与之对齐。
* [GitLab Handbook · Python Guide](https://handbook.gitlab.com/handbook/enterprise-data/platform/python-guide/)
  —— 大厂公开手册,含类型标注、docstring、异常、目录结构。
* [openai-guardrails-python · AGENTS.md](https://github.com/openai/openai-guardrails-python/blob/main/AGENTS.md)
  —— **专门写给 AI agent 的编码契约**:`@dataclass(frozen=True, slots=True)` 作为记录默认、
  一模块一公开概念 + `__all__` 再导出、公开 API 全类型标注、禁 bare `except`、
  Google 风格 docstring 必须有 Args/Returns/Raises。

⚠ **两处已知冲突,本 skill 按用户口径取舍**:crystal-architecture 第 7 条与
`python-coding-agent-skill` 都主张"注释与 docstring 尽量少,靠命名和类型表达"。
本 skill 要求相反 —— 参照 `fast_books` 的详细程度,因为这里的口径边界
(整数与浮点语义、时间半开区间、carry 顺序、筛选层 vs 入书层)**无法用命名和类型表达**,
写不下来就会被下一个人改坏。**架构原则采纳它们,注释密度不采纳。**

## 为什么不是 ruff / black

格式问题没人吵,也早有工具。吵的全是结构 —— 上述七条 linter 一条都不查。
两者不冲突:格式交给格式化工具,结构交给这个闸。
