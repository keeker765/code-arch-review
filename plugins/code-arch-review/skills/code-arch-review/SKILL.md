---
name: code-arch-review
description: 【强制,非可选】代码结构验收闸,用户 2026-09-08 定,2026-10-15 扩到多语言。**全局生效,不限仓库** —— Python / PowerShell / JavaScript / TypeScript / Bash / CSS 都适用。写或改这些语言的代码、交付重构或新模块之前必须先读本 skill 再动手,交付前必须跑到零违规(顺序:先完成代码与主任务,注释最后统一补,闸只在最后跑一次——用户 2026-09-09 定);也用于验收别人的实现,或用户说「代码质量差」「太扁平」「看不懂」时先跑它拿客观清单。细则按主题拆在 references/ 下(注释/docstring/写法风格/目录布局/各语言档位/依据),入口是 SKILL.md。查的是结构不是格式:上帝函数、dict 当接口、参数表暴露内部依赖、深嵌套、缺 docstring 与注释、静默吞异常。
---

# 代码结构验收

🔴 **强制标准,不是建议**(用户 2026-09-08)。**动手前**读本页,不是写完再来对照。
交付前自己跑到零违规 —— 让 review 发现违规,等于把返工成本转嫁给下一轮。

适用 Python / PowerShell / JS / TS / Bash / CSS,各语言档位见下。
出处:原为 `trade_quant` 的仓库级闸,2026-10-07 提升为全局,2026-10-15 改名扩语言。
`references/` 里的 `src/evaluation/backtest/...`、`fast_books`、`onchain_lp` 都出自那个仓库,
在别的项目里只作**写法参照**,路径不存在。

## 顺序(用户 2026-09-09)

```
能跑的代码 → 主任务闭环 → 统一补注释与 docstring → 跑一次闸
```

边写边补注释会在关键路径上停下做一件不影响成败的事。派活给别人时把这条写进分派信,
否则 agent 会把注释覆盖率当完成条件。

**当场写、不许延后的三种**:踩过的坑;涉钱/涉安全/信任边界的那一个关键检查;
故意切掉的角(上限与升级路径)。

## 一个文件一次改完(用户 2026-09-08)

判据:**两次 Edit 之间没跑任何东西,那它们本来就该是一次。** 新文件用 Write 一次写完。

## 什么时候用

| 用 | 不用 |
|---|---|
| 写或改上述语言之后、交付之前(自检) | 只改文档、配置、注释本身 |
| 交付新模块或重构之前 | 临时脚本(见下) |
| 验收别人交的实现 | |
| 用户说「代码质量差」「太扁平」「看不懂」 | |

**临时脚本不受管束**(用户 2026-10-10)。同时满足三条才算:用完即删且不进仓库、
不被任何人 import/require/dot-source、只服务本轮任务。任一条不满足即回到管束。
不受管束**只指注释密度与结构规则,不指正确性** —— 照样要备份原文件、不许静默失败。

## 怎么跑

```bash
python "${CLAUDE_SKILL_DIR}/scripts/check.py" <路径...>
```

把 `CLAUDE_SKILL_DIR` 展开成实际路径再交给 Bash —— 该变量不进 Bash 的环境变量。
退出码 1 = 有违规。**只跑一次**,不要每改一个函数跑一次。
纯 stdlib 无依赖;PowerShell 档位要 `pwsh`,JS/TS 档位要 `node`,缺哪个自动跳过并报出来。
目录里一个认得的目标都没有时**报错退出**,不让空集冒充通过。

放宽阈值(如 `--max-body`)**必须在交付说明里写明放宽了哪条、为什么** —— 不许静默改数。

## 档位表(2026-10-15 定)

`✅` 查、`⚠️` 查但可能误报(报告标注)、`⬜` 已实现但默认不拦、`—` 明确不查。

| 规则 | Python | PowerShell | JS / TS | Bash | CSS |
|---|---|---|---|---|---|
| `long-module` | ✅ 500 | ✅ 500 | ✅ 500 | ✅ 300 | ✅ 800 |
| `flat-package` / `duplicate-basename` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `packed-layout` | ✅ 2/1 | — | ✅ 1/1 | — | — |
| `uncommented-condition` / `-loop` / `-raise` | ✅ | ✅ | ⚠️ | ⬜ | — |
| `uncommented-field` / `-assign` / `-return` | ✅ | ✅ | ⚠️ | ⬜ | — |
| `uncommented-flat` | ✅ | — | ⚠️ | ⬜ | — |
| `long-function` / `deep-nesting` / `many-kwargs` | ✅ 60/4/5 | ✅ 80/4/8 | ⚠️ 50/4/5 | — | — |
| `fat-rule-block`(单块声明数) | — | — | — | — | ✅ 30 |
| `no-docstring` / `thin-docstring` / `docstring-sections` | ✅ Google | ✅ 注释式帮助 | ✅ JSDoc | — | — |
| `thin-module-doc` | ✅ | ✅ | ✅ | — | — |
| `duplicate-toplevel` | ✅ | ✅ | ⚠️ 仅 `var`/`function` | — | ✅ 同块头重定义 |
| `silent-except` | ✅ | ✅ | ✅ | — | — |
| `dict-as-type` | ✅ | — | ⚠️ 仅 TS | — | — |

`⬜` 与 `—` 的区别:Bash 那四条**已经实现**,默认关掉只因为 `if [ -f "$f" ]` 这类检查密度太高,
逐条要求注释会让人把闸关掉 —— 要开就在 `scripts/lang/registry.py` 删掉 `_SHELL_DISABLED` 里的名字。
CSS 不查逐块注释同理。**只报噪声的闸和没有一样**,这是取舍不是遗漏。

**已知缺口(2026-10-15 实测)**:`packed-layout` 与 `uncommented-flat` 依赖后端产出的
`layout_gaps` / `flat_runs`。PowerShell / Bash / CSS 的后端**留空这两项**(语句流里混着
scriptblock、哈希表、heredoc 等,口径要另定一套,做不准比不做更坏),所以格子标 `—` 而非「漏做」。

`packed-layout` 不是可有可无的:它正是防「删空行把行数压到 `long-module` 阈值以下」的那条,
**那三门语言目前挡不住这种压行**。要补就在各自后端里产出 `layout_gaps`。

PowerShell 另关了一条 `dict-as-type`:`$obj.A` / `$obj.B` 既可能是哈希表也可能是强类型对象的
属性访问,没有类型信息分不开 —— 实测 20k 行命中 21 次,量级说明是噪声不是信号。

## 规则清单

| 规则 | 默认阈值 | 防的是 |
|---|---|---|
| `long-function` | 体 > 60 行 | 上帝函数。主流程该只呈现阶段 |
| `fat-rule-block` | 单块 > 30 条声明 | 一个选择器管太多事(CSS) |
| `many-kwargs` | 公开函数 > 5 个参数 | 调用方被迫组装被调用方的内部依赖 |
| `dict-as-type` | 同一对象 > 4 个字符串键 | dict 当类型用,字段含义藏在键名里 |
| `deep-nesting` | > 4 层 | 正常路径被包在多层 if 里;非法输入该提前拒绝 |
| `uncommented-condition` | 函数内任何 if/elif | 一个条件一行,上面一行独立注释;行尾注释不算 |
| `uncommented-loop` | 循环上方无独立整行注释 | 写明遍历什么、为什么不能向量化 |
| `uncommented-raise` | 抛异常上方无独立整行注释 | 什么前提被破坏、调用方该怎么改 |
| `uncommented-flat` | 连续 > 5 条语句无注释 | 平铺代码没有结构提示 |
| `uncommented-field` | 字段无注释(行尾可) | 字段名说不出单位、口径、范围 |
| `uncommented-assign` | 右侧是运算/调用的赋值无注释 | 变量名说「是什么」,注释说「怎么来的」 |
| `uncommented-return` | `return <算式>` 无注释 | 调用方拿到的口径不该靠反推 |
| `no-docstring` | 公开类/函数无文档 | 读代码不该依赖作者口头解释 |
| `thin-docstring` | 只有摘要行,之后无解释段 | 「为什么这么做、什么前提下成立」全缺 |
| `docstring-sections` | 缺必需小节 | 使人不看一行实现就能写出调用 |
| `thin-module-doc` | >80 行的文件说明 < 3 行 | 模块不说自己为什么存在、口径边界在哪 |
| `silent-except` | 空 except / catch | **失败态与正常态同形**,最难查的一类 bug |
| `long-module` | 单文件 > 500 行 | 见 `references/layout.md` |
| `packed-layout` | 定义间空行不足 | 删空行把 `long-module` 闸做废;空行是段落 |
| `flat-package` | 一层平铺 > 7 个模块 | 一眼扫不完等于没有导航 |
| `duplicate-basename` | 同名模块出现在多个目录 | import 谁靠猜 |
| `duplicate-toplevel` | 顶层同名定义两次 | 后定义的**静默胜出**,两份不一致时无人说话 |

## 验收判据是两个

```
扫描 5 个文件,147 处违规
注释覆盖率 30.3%  (61/201 个该解释的构造已注释)   ← 完整性看这个
说明密度 38.7%                                    ← 只作参照
```

1. **违规数归零** —— 每个该解释的地方都解释了。
2. **注释覆盖率** —— 分母是从语法树数出的「该解释的构造」总数(分支/循环/抛异常/字段/
   算出来的赋值/算式 return),**堆废话拉不高、删空行也拉不高**。

密度的分母(总行数)可压缩 —— 实测抓到过把空行删光让密度上升的。**一个能被优化的指标就会被优化。**
覆盖率只在精确档语言上有意义;启发式档的分母是估的,报告会标注。

**不许堆废话过闸**:注释重复代码等于没写,过得了闸、过不了 review。

## 自检

```bash
python "${CLAUDE_SKILL_DIR}/selfcheck/run.py"
```

`fixture_full_coverage.py` 必须**同时**给出 0 违规与 100.0% 覆盖 ——
两个数各由一套谓词算出,一度分叉过(整个 if 只看前一行、行尾注释判断写反),
而**分叉时两个数都不报错**。改过闸就跑一次。新增语言后端必须同时补阳性与阴性样本。

## 分册

| 要做什么 | 读这本 |
|---|---|
| 写注释:if / raise / 循环 / 扁平段 / 变量与字段 / 踩过的坑 | `references/comments.md` |
| 写文档注释:Google 分节、解释段要求、存量迁移 | `references/docstrings.md` |
| 注释与文档的**内容**(为什么不是另一个方案 / 边界成对写 / 归属日期 / 标记分级) | `references/opus-style.md` |
| **各语言怎么查**:语法对照、档位边界、已知误报 | `references/languages.md` |
| 建目录、拆包、分几层、单文件多长算长 | `references/layout.md` |
| 规则依据,以及闸拦不住、必须人看的部分 | `references/rationale.md` |

动手前至少读 `comments.md` + `docstrings.md` + `opus-style.md`(格式 + 内容),
写非 Python 语言时另加 `languages.md`。事后补是返工。
