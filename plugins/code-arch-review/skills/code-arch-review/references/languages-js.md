> 入口:[SKILL.md](../SKILL.md) —— 本文件不单独生效。总体档位见 [languages.md](languages.md)。

# JavaScript / TypeScript 深水区

## 🔴 默认跑的是启发式,不是精确档

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

## 两档差多少(2026-10-15 实测)

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

- **漏报**(37 条,旧口径):`uncommented-loop` 9、`no-docstring` 7、`deep-nesting` 6、
  `long-function` 5、`uncommented-assign` 5、`uncommented-flat` 4、`uncommented-return` 1
  (`uncommented-return` 已于 2026-10-18 取消,这一项只存历史)。
  结构度量那三条不是「量不准」而是**根本没量** —— 启发式把 `body_lines`、`nesting_depth`
  `string_key_count` 一律给 0,`fields` / `flat_runs` / `layout_gaps` 留空,
  于是 `long-function`、`deep-nesting`、`packed-layout`、`uncommented-flat` 在那一档**永不触发**。
- **多报**(8 条):6 条 `uncommented-condition` + 1 条 `uncommented-assign` + 1 条 `thin-module-doc`。

⇒ **`(启发式)` 标记下的零违规不等于真的零违规**:结构度量整类看不见。要拿这个数做验收,
先把 `CODE_ARCH_REVIEW_TS` 设上。

## 启发式的已知多报形态

1. **顶层脚本里的 `if`**:精确档只收**函数体内**的条件;顶层脚本(`bench*.mjs`、
   `test_sdk.mjs` 这类)里包在顶层 `for await` / `try` 块中的 `if` 仍会被报出来。
   启发式用花括号深度当代理,分不出「在函数里」和「在顶层的块里」。
2. **跨行的右侧表达式**:`const shown = [...new Set(Object.entries(MODEL_MAP)` 断成多行时,
   启发式只看得到第一行,拼不出形状。
3. **`#!` 开头的文件**:shebang 会让模块文档的起算位置与精确档差一行。

## 启发式的已知漏报形态

1. **模板串插值**:骨架里模板串内容被抹成空格,`` const u = `${a}/${b}` `` 因此判不出
   「算出来的」,`uncommented-assign` 漏一条。
2. **跨行表达式**:同上,只看第一行。
3. **结构度量**:见上,那一类是给 0 而不是估算 —— 与其报个错的数,不如不报。

## 写 JS/TS 时要知道的口径

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
