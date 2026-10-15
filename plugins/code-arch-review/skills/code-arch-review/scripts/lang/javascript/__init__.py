"""JavaScript / TypeScript 后端:把源码解析成 `core.model.FileFacts`。**半精确档。**

这个包只有对外接口;真正的实现在几个平级的模块里,按「答案从哪来」分开:

* `js_node` —— 怎么跑 node、怎么把它的 JSON 翻成事实
* `js_env` —— 这台机器上有没有 node 与 typescript 包
* `js_fallback` —— 拿不到上面的东西时的启发式降级(定义识别与拼装)
* `js_text` / `js_lines` —— 启发式那一档用的文本层与行级构造层
* `js_probe.mjs` 加五个 `js_*.mjs` —— node 侧的真解析器(TypeScript 编译器,只 parse 不 typecheck)

模块名一律带 `js_` 前缀:`text.py` / `lines.py` 这种通用名会与 `core/` 撞上
(`duplicate-basename`),而报错栈里两个 `text.py` 分不出是谁的。

拆开不是因为行数,是因为每一层都要写满注释与文档:合在一起会超过单文件 500 行的硬闸。
"""

from pathlib import Path

from core.model import FileFacts

from .js_node import EXTS, LANGUAGE, facts_from_json, parse_with_node, usable
from .js_fallback import facts_for as _fallback_facts

__all__ = ['EXTS', 'LANGUAGE', 'parse', 'parse_many']


def parse(path: Path) -> FileFacts:
    """解析一个 JS / TS 文件,产出语言无关的事实。

    单文件调用也要起一次 node —— 精确档的代价就在这里;批量扫描请用 `parse_many`,
    它会把整批文件合并成一次进程调用。

    Args:
        path: 文件路径。

    Returns:
        该文件的事实;走 node 真解析时为 `heuristic=False`。

    Raises:
        OSError: 文件读不到 —— 不吞掉,让调用方决定怎么报。
    """
    target = Path(path)                                 # 统一成 Path,后面两处都要它
    data = usable(parse_with_node([target]).get(0))     # 单个文件的解析结果
    # node 侧没解析成(读不动、或整台机器拿不到 typescript)就自己数一遍
    if not data:
        return _fallback_facts(target)
    return facts_from_json(target, data)


def parse_many(paths) -> list:
    """批量解析。整批文件只起一次 node 进程。

    单个文件读不动时跳过它而不是中断整批 —— 调用方按文件数差额察觉,不静默当作通过。

    Args:
        paths: 文件路径列表。

    Returns:
        `FileFacts` 列表,顺序与 `paths` 一致(读不动的除外)。
    """
    targets = [Path(item) for item in paths]
    parsed = parse_with_node(targets)                   # 整批的结果,按位置索引
    facts = []
    # 逐文件翻译:node 的结果直接拿来用,没有结果才回落到启发式
    for index, target in enumerate(targets):
        data = usable(parsed.get(index))                # 这一份的解析结果,可能没有
        try:
            facts.append(facts_from_json(target, data) if data else _fallback_facts(target))
        except OSError:
            continue
    return facts
