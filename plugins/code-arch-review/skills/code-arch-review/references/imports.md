> 本文件由 `SKILL.md` 拆出,**不单独生效** —— 入口永远是 `SKILL.md`。

# 导入结构:平级互导与导入顺序

依据 **Google Python Style Guide**。闸能查的用 `check.py`;`sibling-import` 这一条
由**回合结束提醒**（Stop hook）给出,不阻断操作。

## Google 原文四条

- **2.2.4**:Do not use relative names in imports. 同一包内也写完整包名。
- **2.3.3**:All new code should import each module by its full package name.
  指南点名 `import jodie` 这种裸模块名是反例 —— 它可能命中第三方包,而不是同目录文件。
- **3.13**:每个 import 单独一行;顺序 future → 标准库 → 第三方 → 本仓库;
  同组内按全路径字典序（忽略大小写）。分组之间可以空行。
- **3.19.14**:循环依赖是 code smell,应重构,而不是靠延迟导入掩盖。

## 本闸加严的一条:平级模块禁止互相导入

Google 允许用完整包名导入同级模块;本 skill 按用户 2026-10-17 的口述**加严**:
同一目录下的模块之间一条都不许导,全路径写法也不许。四种写法都算违规:

```python
from one import X            # 裸名
from pkg.one import X        # 全路径
from .one import X           # 一级相对导入
from . import one            # from . import 形式
```

`__init__.py` **豁免**平级互导 —— 它是包的公开出口,re-export 是它的职责;
但 `__init__.py` 里的相对导入仍然违规,re-export 也要写完整包名。

共享逻辑的落点:**下沉到子包**（如 `pkg/_internal/`）,而不是横向引用。
入口脚本与判据模块必须同目录时,在文件头写
`# py-structure: allow-sibling-imports` 声明豁免;除这个场景外不要用。

## 平铺上限:一层最多 7 个模块

与 `check.py` 的 `flat-package` 同口径:数的是**非保留模块**,`__init__.py` 与
`__main__.py` 不计入;超过 7 个就提醒。目录里没有 `__init__.py` 时按入口脚本目录处理,
不受这条约束（`scripts/`、`tests/` 本来就该按文件平铺）。

## 提醒怎么工作

- 触发:**Stop**（回合结束）,不挂在 Write/Edit 上 —— 结构要看这一轮最终把树改成了什么样。
- 输出:`systemMessage` + exit 0。**只提醒,不阻断**,没有 `deny`,没有 `decision: block`。
- 扫描上限:默认 500 个 `.py`;达到上限会在末尾注明「剩余文件未检查」。
- 跳过目录:`.git`、`__pycache__`、`.venv`、`node_modules`、`vendor`、`site-packages`、
  `build`、`dist` 等生成物与第三方副本。
- 实测延迟（2026-10-17,本机）:16 个文件 0.09 s;345 个文件 0.45 s;
  500 个文件上限的最坏情况 0.78 s。行级解析,不用 `ast.parse`（后者在 345 个文件上要 1.2 s）。

## 改导入时的顺序

1. 先按 Google 3.13 分组并排序;能用 `isort` 就先用。
2. 同目录模块之间改成「下沉到子包」,不要换一种写法继续横向导。
3. 相对导入改完整包名;`__init__.py` 也一样。
4. 最后跑 `check.py`,目标 0 违规。
