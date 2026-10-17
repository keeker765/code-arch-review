---
name: code-arch-review
description: 【强制,非可选】代码结构验收闸,用户 2026-09-08 定,2026-10-15 扩到 Python / PowerShell / JS / TS / Bash / CSS,**全局生效,不限仓库**。写或改这些语言的代码、交付重构或新模块之前先读本页;交付前必须跑到零违规,顺序是先完成代码与主任务、注释最后统一补、闸只跑一次。也用于验收别人的实现,或用户说「代码质量差」「太扁平」「看不懂」时先跑它拿客观清单。查的是结构:上帝函数、dict 当接口、参数表暴露内部依赖、深嵌套、缺 docstring 与注释、静默吞异常、目录平铺、包内互导、导入顺序。
---

# 代码结构验收

🔴 强制标准,不是建议。动手前读本页,不是写完再来对照。

## 顺序

能跑的代码 → 主任务闭环 → 统一补注释与 docstring → 跑一次闸。当场写、不许延后:踩过的坑;涉钱/涉安全/信任边界的关键检查;故意切掉的角;同一个文件一次改完。

## 怎么跑

```bash
python "${CLAUDE_SKILL_DIR}/scripts/check.py" <路径...>
```

退出码 1 = 有违规。只跑一次。纯 stdlib;PowerShell 要 `pwsh`,JS/TS 要 `node`。
显式点名单个文件时,父目录有 `__init__.py` 就自动带上同层文件一起判。
目录里一个可识别的目标都没有时**报错退出**,空集不算通过。
跳过目录、`--exclude` 与各语言档位见 [languages.md](references/languages.md)。

## 速查表

| 规则 | 阈值 | 防的是 | 分册 |
|---|---|---|---|
| `long-module` / `packed-layout` / `long-function` / `many-kwargs` / `deep-nesting` / `fat-rule-block` | 500 行 / 空行 / 60 行 / 5 个 / 4 层 / 30 条声明 | 上帝函数;删空行压行;一个选择器管太多事 | [layout](references/layout.md) · [languages](references/languages.md) |
| `dict-as-type` / `uncommented-field` / `uncommented-assign` / `uncommented-return` / `uncommented-flat` | 4 键 / 每处 / 连续 5 条 | 字段含义与计算口径藏在名字里;注释要紧贴该行 | [comments](references/comments.md) |
| `uncommented-condition` / `uncommented-loop` / `uncommented-raise` / `silent-except` | 每处 | 条件一行一注释;循环写遍历什么;失败态不许静默 | [comments](references/comments.md) |
| `no-docstring` / `thin-docstring` / `docstring-sections` / `thin-module-doc` | 见分册 | 不看实现就能写出调用 | [docstrings](references/docstrings.md) |
| `flat-package` / `duplicate-basename` / `duplicate-toplevel` | 7 个 / 跨目录重名 / 顶层重定义 | 扫不完等于没有导航;后定义静默胜出 | [layout](references/layout.md) |
| `sibling-import` / `import-order` / `multi-import` | 包内禁互导 / Google 3.13 | 依赖成网;导入分组可读 | [imports](references/imports.md) |
| `test-syspath` / `no-collectable-test` / `test-import-test` | 仅测试模块 | 测哪份代码靠猜;用例静默不跑 | [languages](references/languages.md) |

## 最小例子

```python
# ❌ 条件挤行,且没有独立注释
if row.ok and row.fee > 0: ...

# ✅ 一个条件一行,每行上方独立注释
if (
    # 几何缺失 ⇒ 开不出仓
    row.ok
    # 费用为 0 ⇒ 没有经济意义
    and row.fee > 0
): ...
```

```python
# ❌ 一行式文档:把函数名重复了一遍
def settle(order):
    """结算订单。"""

# ✅ 摘要 + 解释段:写清为什么与边界
def settle(order):
    """结算订单,按成交价扣双边手续费。

    手续费在成交时锁定,不随之后的价格更新变化。
    """
```

```python
from one import helper                     # ❌ 包内平级互导
from pkg._internal.helper import helper    # ✅ 下沉到子包,写完整包名
```

## 验收与派活

违规数 = 0,注释覆盖率 100%(标了 `(启发式)` 的除外)。改过闸就跑一次自检:

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
