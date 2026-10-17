> 入口:[SKILL.md](../SKILL.md) —— 本文件不单独生效。
> 写非 Python 语言前读这页:同一条规则换成那门语言对应到哪个语法。
> JS / TS 的降级实测与口径单独在 [languages-js.md](languages-js.md)。

# 各语言怎么查

## 用什么解析

| 语言 | 档位 | 解析手段 | 缺依赖时 |
|---|---|---|---|
| Python | 精确 | stdlib `ast` + `tokenize` | 不可能缺 |
| PowerShell | 精确 | `[System.Management.Automation.Language.Parser]` | 不可能缺(Win 自带;Linux 需 `pwsh`) |
| JS / TS | **半精确** | `node` + TS 的 `ts.createSourceFile`(只 parse 不 typecheck) | **默认就是它** —— 见下面 JS 一节的实测偏差 |
| CSS | 精确 | 手写 tokenizer(字符串/注释/转义感知) | 不可能缺 |
| Bash | 最低 | 无 —— `bash -n` 只验语法 | 无降级 |

## 档位矩阵

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
| `fat-rule-block` | — | — | — | — | ✅ 30 |
| `no-docstring` / `-thin` / `-sections` | ✅ Google | ✅ 注释式帮助 | ✅ JSDoc | — | — |
| `thin-module-doc` | ✅ | ✅ | ✅ | — | — |
| `duplicate-toplevel` | ✅ | ✅ | ⚠️ 仅 `var`/`function` | — | ✅ 同块头 |
| `silent-except` | ✅ | ✅ | ✅ | — | — |
| `dict-as-type` | ✅ | — | ⚠️ 仅 TS | — | — |
| `test-syspath` / `no-collectable-test` / `test-import-test` | ✅ | — | — | — | — |
| `sibling-import` / `import-order` / `multi-import` | ✅ | — | — | — | — |

⚠️ **JS/TS 的 `⚠️` 只在精确档成立**。默认降级成启发式时,`long-function`、`deep-nesting`、
`packed-layout`、`uncommented-flat` 根本不触发 —— 不是「可能误报」而是「没查」。
判据是 stderr 有没有那行降级提示,见 [languages-js.md](languages-js.md)。

Bash 的 `⬜` 四条**已实现**,默认关掉只因检查密度太高;要开就在
`scripts/lang/registry.py` 删掉 `_SHELL_DISABLED` 里的名字。
PowerShell 的 `dict-as-type` 也关了:`$obj.A` 分不清哈希表与强类型属性。
**只报噪声的闸和没有一样**,这是取舍不是遗漏。

`packed-layout` / `uncommented-flat` 依赖后端产出的 `layout_gaps` / `flat_runs`;
PowerShell / Bash / CSS 后端留空这两项,所以格子是 `—` 而不是漏做。
它们正是防「删空行压行」的那条,那三门语言目前挡不住这种压行。

## 注释与文档注释

| | Python | PowerShell | JS / TS | CSS | Bash |
|---|---|---|---|---|---|
| 行注释 | `#` | `#` | `//` | — | `#` |
| 块注释 | — | `<# #>` | `/* */` | `/* */` | — |
| **文档注释** | 函数体首条字符串 | 函数体首条 `<# #>` | 定义上方紧贴 `/** */` | — | — |
| 文档小节 | `Args:` `Returns:` `Raises:` `Yields:` | `.PARAMETER` `.OUTPUTS` `.NOTES` | `@param` `@returns` `@throws` | — | — |

判据不变:文档要**不看一行实现就能写出调用**。换语言只换小节名。

## 规则 → 语法

| 规则 | Python | PowerShell | JS / TS | CSS |
|---|---|---|---|---|
| 条件 | `if` / `elif` | `if` / `elseif` | `if` / `else if` | — |
| 布尔组合(要摊平) | `and` `or` | `-and` `-or` | `&&` `\|\|` | — |
| 循环 | `for` `while` | `foreach` `for` `while` `do` | `for` `while` `do` | — |
| 抛异常 | `raise` | `throw` | `throw` | — |
| 静默吞异常 | `except: pass` | 空 `catch` | 空 `catch` | — |
| 字段 | 数据类字段 / 类级 `x: int` | 类内 `[type]$x` | 类字段 / TS 属性签名 | — |
| 算出来的赋值 | `x = <运算/调用>` | `$x = <运算/调用>` | `const x = ...` | — |
| 算式 return | `return <表达式>` | `return <表达式>` | `return <表达式>` | — |
| 函数定义 | `def` / `async def` | `function` / `filter` | 函数 / 箭头 / 方法 | **规则块** |
| 保留文件名 | `__init__.py` `__main__.py` | — | `index.*` | — |

## Python 的测试三条

只有 Python 有。判据分两级,**混成一级必错**:

| 判什么 | 怎么判 | 判错的后果 |
|---|---|---|
| 归属(是不是测试区) | 路径任一段 ∈ `test` / `tests` / `testing` | — |
| 角色(是不是测试模块) | 文件名命中 `test_*.py` 或 `*_test.py` | 把 `tests/helpers.py` 当测试模块 → 误报零用例 |

依据一律是 pytest 的 `python_files` / `python_functions` 默认值,不另立一套。

| 规则 | 判据 | 实测(2026-10-15) |
|---|---|---|
| `test-syspath` | `sys.path.insert(...)` / `.append(...)` 的调用行 | 7 个仓库 177 个测试文件 0 命中 |
| `no-collectable-test` | 模块命名空间里 `test*` / `Test*` 的绑定数为 0 | 16 个真实 `tests/` 剩 1 命中(dill 的脚本式测试模块,确实零收集项) |
| `test-import-test` | import 的顶层名解析到**本次扫描到的**另一个测试模块 | 4 命中全是 dill 的 `import test_mixins as module` 式真缺陷 |

**`no-collectable-test` 只按名字数,不判类会不会被收走**:pytest 收的是所有
`unittest.TestCase` 子类,而继承链可能跨模块(`class FilesConfigTest(base.BaseTestCase)`
的基类在 pbr 包里又继承 testtools)、类可能被 `as` 改名
(`from unittest import TestCase as NonLeakingTestCase`)—— 静态判不准。
起先按「直接基类里有没有 `TestCase`」判,实测在 16 个目录上误报 5 处,改成按名字数之后归零。
同理**不按「有没有 TestCase 子类」判是不是测试文件**:那样会把 `tests/base.py` 这种
共享基类当成测试模块,连带让别的模块 `from .base import ...` 撞上 `test-import-test`。
绑定要连**块体内**的算(`if cond: def test_x()` 与 `TestDraft = Suite().to_testcase()`
这两种写法 pytest 都收),所以数名字时要走进 `if` / `try` / `with` / 循环的块体。

**不做的**(依据不足或与 linter 重复,`references/rationale.md` 有完整清单):
`tests/` 要不要 `__init__.py`(pytest 官方两处文档自相矛盾,实测 10 个仓库 7:3)、
单元/集成/e2e 要不要分目录(零权威依据,httpx 用 marker 不分目录)、
`Test` 类不得有 `__init__`(pytest 自己就发警告)、测试函数必须有断言
(实测 56 命中里近半是合法写法:断言在 helper 里、或不抛异常即通过)。

# 各语言要点

## PowerShell

用 AST,拿 `Extent`,**绝不数大括号**:

```powershell
$err = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$err)
$ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
```

四条坑(为什么不能数括号):

- `{}` 同时是 scriptblock 定界符、哈希表字面量、`where {}` 参数块 —— `@{ a = 1 }` 会让深度算错。
- 字符串与 here-string(`@" "@`)里什么都有,包括 `{}` 和 `#`。
- `$()` 子表达式、`@()` 数组、`${ var }` 变量定界都改深度。
- **行尾反引号是续行**:`if ($a -and \`` 换行后 `$b)` 是**同一个条件**;按行数会误判成两个,方向正好相反。

**模块文档的口径由 PowerShell 自己定,与 Python 不同,而且是故意不同**:

- 取的是**第一行代码之前的所有注释** —— 块注释与 `#` 行注释都算,行与行之间允许空行;
  `#Requires` 是给引擎看的编译指令,跳过它、**不算进正文**,它也不终结文档。
- 别拿 Python 的取法来「统一」:Python 只认模块第一个字符串字面量,那是因为 `#` 注释在 Python 里
  **语法上就当不了 docstring**,而 PowerShell 里根本没有 docstring 节点,文件开头的注释块
  就是它唯一的模块说明位置。规则是「模块要有说明」,「什么算说明」由语言语法决定。
- 这条口径修掉过一个真实误报:948 行的 `claude-privacy-audit.ps1` 开头是 `#Requires` 加一个
  完整帮助块,按「第一个有意义的 token 必须直接是块注释」的老口径会被判成没写模块文档。

## JavaScript / TypeScript

默认跑的是启发式,不是精确档;`(启发式)` 标记下的零违规不等于真的零违规。
两档实测偏差、已知多报/漏报形态与写法口径见 [languages-js.md](languages-js.md)。

## CSS

CSS 的「函数」是**规则块**,选择器是名字;`duplicate-toplevel` 对应**同块头重定义**
(层叠静默让后一个胜出,与 Python 重复顶层定义同形)。哪些规则不查见上面的档位矩阵。

七条坑(手写 tokenizer 必须处理,按踩到的顺序):

1. 字符串 `"..."` `'...'` 里的 `}` `{` `;` 不是结构,含转义 `\"`。
2. `/* */` 可跨行,里面的 `{ } ;` 全不是代码。
3. `url(data:image/svg+xml;base64,...)` 里的 `;` 不是声明分隔符。
4. `@media (min-width: 600px)` 的**括号要先配平**,再看花括号。
5. `@import url(...);` / `@charset "utf-8";` **没有花括号**,以分号结束,不是块。
6. 单行多块 `.a { } .b { }` 要切成两个。
7. 🔴 **转义序列**:Tailwind 等压缩输出里有 `.before\:content-\[\'\'\]{...}` ——
   那个 `'` 是**被转义的字符,不是开引号**。误判会拿它开一个跨几十 KB 的"字符串",
   把文件后半段全吞掉。tokenizer 必须认转义,被转义的字符既不是结构也不是引号。

## Bash(最低档)

只查 `long-module`(300)、`flat-package`、`duplicate-basename`。
注释四条**已实现但默认不拦** —— 要开在 `scripts/lang/registry.py` 删 `_SHELL_DISABLED` 里的名字。

不查文档约定、`long-function`、`deep-nesting`、`many-kwargs`、`duplicate-toplevel`、`silent-except`。
`long-function` 是**做不到**而非不查:heredoc、续行、子 shell、`{ }` 分组都会骗过扫描器,
量不准的指标不如不量。

两条扫描器必须处理的边界:**heredoc 内部不是代码**(里面的 `#` 不是注释、`if` 不是条件);
**行尾 `\` 是续行**,续行后是同一行。

# 启发式/低档的纪律

1. 报告里**标出哪些条目来自启发式**,让人能区分确凿与待看。
2. 结构度量三条(`long-function`/`deep-nesting`/`many-kwargs`)在启发式档**只报不拦**,不计入退出码。
3. 某条规则在某语言上误报率不可接受时,**关掉它并在这里写明为什么**,
   不要留着让人自己过滤。
