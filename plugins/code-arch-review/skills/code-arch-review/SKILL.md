---
name: code-arch-review
description: 【强制,非可选】代码结构验收闸,用户 2026-09-08 定,2026-10-15 扩到 Python / PowerShell / JS / TS / Bash / CSS,**全局生效,不限仓库**。写或改这些语言的代码、交付重构或新模块之前先读本页;交付前必须跑到零违规,顺序是先完成代码与主任务、注释最后统一补、闸只跑一次。也用于验收别人的实现,或用户说「代码质量差」「太扁平」「看不懂」时先跑它拿客观清单。查的是结构:上帝函数、dict 当接口、参数表暴露内部依赖、深嵌套、缺 docstring 与注释、静默吞异常、目录平铺、包内互导、导入顺序。
---

# 代码结构验收

🔴 强制标准,不是建议。动手前读本页,不是写完再来对照。

## 动手前两问

用户 2026-11-13 定,写任何代码之前先答这几题,答不上就先去查:

1. **这个功能有没有?** 先搜仓库(函数名、命令表、README、相邻目录)和记忆库,已有或有半成品就复用、扩展,不另造一份。
2. **放的位置对不对?** 和逻辑归属一致、和仓库现有目录惯例一致、方便管理;只看文件树路径就能猜出它是干什么的。新入口登记进已有的命令表或 README,不散放脚本。
3. **要新建文件夹?** 新文件夹就是新模块:先想清它管什么,在仓库根 `DIRS.md` 补一行 ``- `路径` — 一句话说明``(只写模块级目录),和新目录同一次提交;说不清就别建,放进已有模块。没有 `DIRS.md` 的仓库,建第一个目录时一并建它。

## 顺序

能跑的代码 → 主任务闭环 → 跑一次闸。当场写、不许延后:踩过的坑;涉钱/涉安全/信任边界的关键检查;故意切掉的角;同一个文件一次改完。
注释与 docstring 已不再要求补(2026-11-03 起),见下。

## 怎么跑

```bash
python "${CLAUDE_SKILL_DIR}/scripts/check.py" <路径...>
```

**默认只查结构。** 2026-11-11 起两类噪声默认关:注释与文档那九条(速查表第二、三、四行)要 `--comments` 才查,单文件 500 行上限要 `--long-module` 才查。补注释纯耗额度、几十处一起报会把真结构问题淹掉;分层模块与数据表天然过千行。旧 `--no-comments` 保留为别名(传了等于没传)。

退出码 1 = 有违规。只跑一次。纯 stdlib;PowerShell 要 `pwsh`,JS/TS 要 `node`;`--fix` 用 ruff 自动排导入顺序。显式点名单个文件时,父目录有 `__init__.py` 就自动带上同层文件一起判。目录里一个可识别的目标都没有时**报错退出**,空集不算通过。跳过目录、`--exclude` 与各语言档位见 [languages.md](references/languages.md)。

## 速查表

| 规则 | 阈值 | 防的是 | 分册 |
|---|---|---|---|
| `long-module` / `packed-layout` / `long-function` / `many-kwargs` / `deep-nesting` / `fat-rule-block` | 500 行 / 空行 / 60 行 / 5 个 / 4 层 / 30 条声明 | 上帝函数;删空行压行;一个选择器管太多事;行数那条默认关 | [layout](references/layout.md) · [languages](references/languages.md) |
| `dict-as-type` / `uncommented-field` / `uncommented-assign` / `uncommented-flat` | 4 键 / 每处 / 算式赋值 / 连续 10 条 | 字段含义与计算口径藏在名字里;字段写行尾或类 docstring 的 `Attributes:`;一组操作前一段块注释即可 | [comments](references/comments.md) |
| `uncommented-condition` / `uncommented-loop` / `silent-except` | 每条链 / 复杂循环 / 每处 | 每条 if/elif 链一条注释,写在链开头,单条件卫语句除外;while、体 ≥3 条或含 break/continue 的循环要说明;失败态不许静默 | [comments](references/comments.md) |
| `no-docstring` / `thin-docstring` / `docstring-sections` / `thin-module-doc` | 见分册 | 不看实现就能写出调用;摘要后必须有解释段(类也一样) | [docstrings](references/docstrings.md) |
| `flat-package` / `flat-dirs` / `duplicate-basename` / `duplicate-toplevel` | 7 个模块 / 12 个子目录(SQL、数据目录也算) / 跨目录重名 / 顶层重定义 | 扫不完等于没有导航;后定义静默胜出 | [layout](references/layout.md) |
| `sibling-import` / `import-order` / `multi-import` | 包内禁互导 / future→stdlib→其余,组内字典序 / 每行一个 | 依赖成网;导入顺序可读 | [imports](references/imports.md) |
| `test-syspath` / `no-collectable-test` / `test-import-test` | 仅测试模块 | 测哪份代码靠猜;用例静默不跑 | [languages](references/languages.md) |

## 最小例子

```python
def settle(order, balance):
    """结算订单,返回扣款后的余额。

    手续费在成交时锁定;余额不足时整笔拒绝,不做部分扣款。
    Args:
        order: 待结算的订单。
        balance: 结算前余额,单位分。

    Returns:
        扣款后的余额,单位分。
    Raises:
        ValueError: 状态不是 open。
    """
    # 状态不是 open ⇒ 不可结算;失败前提归 docstring 的 Raises:
    if order.status != "open":
        raise ValueError(order.order_id)
    # 扣款后的余额;失败时保持原值
    balance = balance - order.total
    return balance
```

```python
for order in orders:
    try:
        # 扣款后的余额;失败时保持原值
        balance = settle(order, balance)
    except ValueError:
        continue
```

```python
from one import helper                     # ❌ 包内平级互导
from pkg._internal.helper import helper    # ✅ 下沉到子包,写完整包名
```

## 验收与派活

违规数 = 0(标了 `(启发式)` 的除外)。加了 `--comments` 时另要求注释覆盖率 100%;默认档不量覆盖率。改过闸就跑一次自检:

```bash
python "${CLAUDE_SKILL_DIR}/selfcheck/run.py"
```

改动 > 200 行、跨 ≥ 3 个目录、或一次交付多个模块 ⇒ 派 subagent,附本页与相关分册。
主 agent 必须读 diff、逐条核对规则,再自己跑 `check.py` 与测试;不接受只报「0 违规」。

## 分册

| 要做什么 | 读这本 |
|---|---|
| 注释:条件、循环、字段、坑 | [comments.md](references/comments.md) |
| 文档注释与内容标准 | [docstrings.md](references/docstrings.md) · [opus-style.md](references/opus-style.md) |
| 导入结构:包内互导、分组顺序 | [imports.md](references/imports.md) |
| 各语言档位、语法、已知缺口 | [languages.md](references/languages.md) · [languages-js.md](references/languages-js.md) |
| 目录、拆包、层数 | [layout.md](references/layout.md) |
| 规则依据、闸拦不住的 | [rationale.md](references/rationale.md) |
