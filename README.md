# code-arch-review

把「这段代码读起来累不累」量成一份可执行的检查单。

查的是**结构**，不是格式：上帝函数、dict 当接口、参数表暴露内部依赖、深嵌套、
缺文档与注释、静默吞异常、删空行压行数。这些 ruff / black / eslint 一条都不查 ——
格式问题本来就没人吵，吵的全是结构。

支持 Python / PowerShell / JavaScript / TypeScript / Bash / CSS。

## 它和 linter 的区别

一个 linter 会告诉你「这行超过 100 列」。这个闸告诉你的是：

- 这个函数有 87 行，主流程没有只呈现阶段（`long-function`）
- 这条 `if` / `elif` 链开头没有一条说明（`uncommented-condition`）
- 这个 `except` 块是空的，失败态和正常态同形（`silent-except`）
- 这个文件删光了空行把自己压到 500 行以内（`packed-layout`）

最后一条是实测抓到的：三个文件交上来时分别停在 500 / 495 / 490 行，空行数为 **0**。
删空行让行数下降，也让「说明密度」这个指标的分母变小 —— **一个能被优化的指标就会被优化**。
所以空行是硬要求，而验收判据从「密度」改成了「覆盖率」（分母由代码结构决定，压不动）。

## 安装

**Claude Code 插件**（推荐）：

```
/plugin marketplace add keeker765/code-arch-review
/plugin install code-arch-review@code-arch-review
```

然后在 `/plugin` 的 **Marketplaces** 标签页里对 `code-arch-review` 选
**Enable auto-update** —— 第三方市场的自动更新默认是关的，需要手动开一次。
更新在**下一次会话**生效（提示 `Run /reload-plugins to apply`）。

**任意 agent（`npx skills`）**：

```bash
npx skills add keeker765/code-arch-review -g -a '*'
```

## 用法

```bash
python <skill目录>/scripts/check.py <路径...>
```

退出码 1 = 有违规，可直接当 CI / 交付闸。纯 stdlib，**不需要装任何依赖**。

| 参数 | 默认 | 说明 |
|---|---|---|
| `--max-body` | 因语言而异 | 函数体超过多少行算上帝函数 |
| `--max-kwargs` | 因语言而异 | 公开函数多少个参数算「调用方被迫组装内部依赖」 |
| `--max-keys` | 4 | 同一对象上用多少个字符串键算 dict 当类型用 |
| `--max-depth` | 因语言而异 | 控制流嵌套超过几层算深 |
| `--max-flat` | 10 | 连续多少条语句无注释算平铺 |
| `--max-module-lines` | 因语言而异 | 单文件超过多少行要拆 |
| `--max-modules` | 7 | 一层平铺多少个模块要分组 |
| `--max-declarations` | 30 | 单个 CSS 规则块超过多少条声明算胖 |
| `--json` | — | 输出 JSON |

**没传的参数不会覆盖该语言自己的值** —— 各语言的阈值在 `scripts/lang/registry.py`。

### 自检

```bash
python <skill目录>/selfcheck/run.py
```

`fixture_full_coverage.py` 是一份「每类该解释的构造各一个、且全部解释到位」的样本，
闸对它必须**同时**给出 0 违规与 100.0% 覆盖。每种语言另有一对 `fixture_clean.<ext>` /
`fixture_bad.<ext>`：前者必须 0 违规，后者必须报出违规。**改过闸就跑一次** ——
前两个数各由一套谓词算出，曾经分叉过，而分叉时两个数都不报错；
后一对是防「恒绿的空后端骗过全部阴性对照」，只有一半的话等于没查。

## 两个指标，只有一个是判据

```
扫描 5 个文件，147 处违规
注释覆盖率 30.3%  (61/201 个该解释的构造已注释)   ← 完整性看这个
说明密度 38.7%                                    ← 只作参照
```

密度的分母是总行数，删空行、堆废话都能拉高它。覆盖率的分母是从语法树数出来的
「该解释的构造」总数（if/elif 链 / 复杂循环 / 字段 / 算式赋值），
**堆废话拉不高、删空行也拉不高**。`raise` 与 `return` 的说明归 docstring。

## 语言档位

同一个规则在不同语言里的可判性不同。表里 `—` 的是**明确不查**，不是漏做 ——
硬套会产生误报，而只报噪声的闸会被直接关掉，和没有一样。

| 规则 | Python | PowerShell | JS / TS | Bash | CSS |
|---|---|---|---|---|---|
| 文件级（长文件 / 平铺 / 重名） | ✅ | ✅ | ✅ | ✅ | ✅ |
| 块间空行 `packed-layout` | ✅ 2/1 | — | ✅ 1/1 | — | — |
| 条件链 / 复杂循环 的注释 | ✅ | ✅ | ⚠️ 启发式 | — | — |
| 字段 / 算式赋值 的注释 | ✅ | ✅ | ⚠️ 启发式 | — | — |
| 函数体长 / 嵌套 / 参数 | ✅ | ✅ | ⚠️ 启发式 | — | — |
| 文档小节 | ✅ Google | ✅ 注释式帮助 | ✅ JSDoc | — | — |
| 重复顶层定义 | ✅ | ✅ | ⚠️ 仅 `var`/`function` | — | ✅ 重复选择器 |
| 静默吞异常 | ✅ | ✅ | ✅ | — | — |
| 规则块声明数 | — | — | — | — | ✅ |

保真度分三档：**精确**（Python 走 stdlib `ast`；PowerShell 走系统自带的
`[System.Management.Automation.Language.Parser]`，零安装）、**半精确**（JS/TS 走 `node`，
拿不到 node 时降级启发式并标注）、**最低**（Bash 无可行解析器，只做行级启发式）。

启发式档产出的条目在报告里带 `(启发式)` 标记，其中结构度量三条**只报不拦**，
不计入退出码 —— 量不准的指标不该拦人。

## 各语言的阈值

| | 单文件 | 函数体 | 参数 | 嵌套 |
|---|---|---|---|---|
| Python | 500 | 60 | 5 | 4 |
| PowerShell | 500 | 80 | 8 | 4 |
| JS / TS | 500 | 50 | 5 | 4 |
| Bash | 300 | 不查 | 不查 | 不查 |
| CSS | 800 | 不查 | 不查 | 3 |

PowerShell 放宽是因为它的惯例就是动词-名词长函数名加显式 `param()` 块；
JS 收紧是因为回调与闭包让函数极易膨胀；Bash 收到 300 是因为 200 行以上就该换语言了。

## 仓库结构

```
.claude-plugin/marketplace.json          Claude Code 插件市场清单
plugins/code-arch-review/
├── .claude-plugin/plugin.json           插件清单
└── skills/code-arch-review/
    ├── SKILL.md                         入口:什么时候用、怎么跑、档位表
    ├── references/                      细则分册(注释 / 文档 / 写法 / 目录 / 各语言 / 依据)
    ├── scripts/
    │   ├── check.py                     CLI:语言分发、档位过滤、退出码
    │   ├── core/                        语言无关:事实模型、规则引擎、文本工具、报告
    │   └── lang/                        各语言后端:把语法翻译成事实
    └── selfcheck/                       闸自身的回归自检与各语言的合规样本
```

分层是刻意的：`lang/` 只把语法翻译成 `core.model.FileFacts`，`core/rules.py` 只认事实。
于是**违规清单与注释覆盖率由同一份事实、同一个谓词算出** —— 原来的实现里这两项各走一套
AST 遍历、各写一份谓词，分叉过一次（整个 `if` 只看前一行、行尾注释判断写反），
而分叉时两个数都不报错。

## 许可

MIT
