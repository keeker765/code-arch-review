> 本文件由 `SKILL.md` 拆出,**不单独生效** —— 入口永远是 `SKILL.md`。
> 写非 Python 语言前读这页:同一条规则换成那门语言对应到哪个语法。

# 各语言怎么查

## 用什么解析

| 语言 | 档位 | 解析手段 | 缺依赖时 |
|---|---|---|---|
| Python | 精确 | stdlib `ast` + `tokenize` | 不可能缺 |
| PowerShell | 精确 | `[System.Management.Automation.Language.Parser]` | 不可能缺(Win 自带;Linux 需 `pwsh`) |
| JS / TS | **半精确** | `node` + TS 的 `ts.createSourceFile`(只 parse 不 typecheck) | **默认就是它** —— 见下面 JS 一节的实测偏差 |
| CSS | 精确 | 手写 tokenizer(字符串/注释/转义感知) | 不可能缺 |
| Bash | 最低 | 无 —— `bash -n` 只验语法 | 无降级 |

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

### 🔴 默认跑的是启发式,不是精确档

这一门标着「半精确」,但**半精确的默认状态就是降级**,不是开箱即用:

- 精确档要 `node` **和一个 `typescript` 包**。本机实测:node 在,但**没有全局装的
  typescript**,项目本地通常也没有 —— 于是**每一次都是启发式**,报告里每条会带
  `(启发式)` 标记,stderr 另有一行 `⚠ JS/TS 后端降级为启发式:找不到 typescript 包`。
- 要精确档,二选一:装 `typescript`(`npm i -g typescript`,或装进项目本地),
  或者设环境变量指到任意一份包目录:

  ```
  CODE_ARCH_REVIEW_TS="<某个 node_modules/typescript 的路径>" python scripts/check.py <路径>
  ```

  VS Code 自带一份(`…/Programs/Microsoft VS Code/<hash>/resources/app/extensions/node_modules/typescript`),
  指过去就能用。**判据是 stderr 里没有那行降级提示** —— 两次跑出来的报告长得一样,
  只有这一行能说明跑的是哪条路径。

### 两档差多少(2026-10-15 实测)

语料 `copilot_auth` + `aiedio`(76 个含违规的 JS/TS 文件),同一份代码跑两遍比
`(文件, 行, 规则)` 三元组:

| | 条数 |
|---|---|
| 精确档 | 1994 |
| 启发式 | 1965 |
| 交集 | 1889 |
| **只有精确档报出**(启发式漏) | **37** |
| **只有启发式报出**(启发式多报) | **8** |

**偏差方向是清楚的,而且是危险的那一头**:

- **漏报**(37 条):`uncommented-loop` 9、`no-docstring` 7、`deep-nesting` 6、
  `long-function` 5、`uncommented-assign` 5、`uncommented-flat` 4、`uncommented-return` 1。
  结构度量那三条不是「量不准」而是**根本没量** —— 启发式把 `body_lines`、`nesting_depth`
  `string_key_count` 一律给 0,`fields` / `flat_runs` / `layout_gaps` 留空,
  于是 `long-function`、`deep-nesting`、`packed-layout`、`uncommented-flat` 在那一档**永不触发**。
- **多报**(8 条):6 条 `uncommented-condition` + 1 条 `uncommented-assign` + 1 条 `thin-module-doc`。

⇒ **`(启发式)` 标记下的零违规不等于真的零违规**:结构度量整类看不见。要拿这个数做验收,
先把 `CODE_ARCH_REVIEW_TS` 设上。

### 启发式的已知多报形态

1. **顶层脚本里的 `if`**:精确档只收**函数体内**的条件;顶层脚本(`bench*.mjs`、
   `test_sdk.mjs` 这类)里包在顶层 `for await` / `try` 块中的 `if` 仍会被报出来。
   启发式用花括号深度当代理,分不出「在函数里」和「在顶层的块里」。
2. **跨行的右侧表达式**:`const shown = [...new Set(Object.entries(MODEL_MAP)` 断成多行时,
   启发式只看得到第一行,拼不出形状。
3. **`#!` 开头的文件**:shebang 会让模块文档的起算位置与精确档差一行。

### 启发式的已知漏报形态

1. **模板串插值**:骨架里模板串内容被抹成空格,`` const u = `${a}/${b}` `` 因此判不出
   「算出来的」,`uncommented-assign` 漏一条。
2. **跨行表达式**:同上,只看第一行。
3. **结构度量**:见上,那一类是给 0 而不是估算 —— 与其报个错的数,不如不报。

### 写 JS/TS 时要知道的口径

- **`deep-nesting` 不能只数 `{`**:对象字面量、模板字符串插值、解构都加深度。
  只有**控制流**加层(if/for/while/switch/try),函数体不加,嵌套函数另起作用域。
- **`duplicate-toplevel` 只对 `var` 和 `function` 成立**。`let`/`const` 同作用域重复声明是**语法错误**
  (引擎自己会报);`function f(){} function f(){}` 与 `var` 是**静默后者胜出** —— 顶层的
  `let`/`const` **不要**放进 bindings,会产生假阳性。
- **`dict-as-type` 只在 TS 上有意义**:纯 JS 里对象就是惯用的记录类型。TS 上对应
  「该用 `interface`/`type` 而不是裸对象字面量当接口」。
- **箭头函数的名字来自父节点**:`const f = () => {}` 报的名字是 `f`,它的 JSDoc 写在
  整条声明上方就算数(与函数声明同等待遇)。匿名回调(直接当参数传的箭头)没有对外名字,
  报告里退化成 `:行号`,也不要求文档。
- **类与函数共用一条事实**:类只查文档;参数表、嵌套层数、字符串键三项对类都归零。
- **「就地接线」不要求文档,但仍查体量与嵌套**(2026-10-15 加):接到**成员表达式**上的函数
  一律算接线 —— `{f: () => {}}`(对象字面量)、`el.onload = () => {}`(DOM 节点)、
  `exports.foo = function () {}`(导出对象)。理由是名字由别人定或根本没有名字,能写的 JSDoc
  只剩复述右侧那串 `() => {}`,而要绕开还得改成 `addEventListener`,属于为过闸改行为。
  它们**留在 `functions` 里**,所以 `long-function` / `deep-nesting` / `many-kwargs` 照样量它 ——
  一个几百行的事件处理器该被抓出来。赋给**裸名字**的(`foo = function () {}`)不算接线,名字是作者起的。
  ⚠ 只在精确档生效;启发式那档本来就不认这类赋值,所以它既不报文档也不量体量(见上面的已知漏报)。
- **`.mjs` / `.cjs` 也在扫描范围内**(闸的扩展名表里有),`.js`/`.mjs`/`.cjs` 按 JSX 变体解析,
  所以同一份源码带不带 JSX 都能过。本仓库自己的 `scripts/lang/javascript/*.mjs` 因此也归闸管。
- **一次 `node` 进程要 50~200 ms**:整批文件一次传给它,别一个文件起一次。

## CSS

CSS 的「函数」是**规则块**,选择器是名字;`duplicate-toplevel` 对应**同块头重定义**
(层叠静默让后一个胜出,与 Python 重复顶层定义同形)。哪些规则不查见 `SKILL.md` 档位表。

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
