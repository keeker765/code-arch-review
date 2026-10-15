"""Python 后端:把源码解析成 `core.model.FileFacts`。**精确档**,stdlib `ast`,无依赖。

这个包只有入口与编排。语法树的翻译在 `structure.py`,注释行与空行在 `layout.py`,
顶层绑定在 `bindings.py`,文档小节在 `docstrings.py` —— 拆开是因为这四组判据的
失败方式互不相同,而入口本身应该能一眼读完。
"""

import ast
from pathlib import Path

from core.model import FileFacts

from . import bindings, layout, structure

LANGUAGE = 'python'
EXTS = ('.py',)


def parse(path: Path) -> FileFacts:
    """解析一个 Python 文件,产出语言无关的事实。

    编排 AST 遍历、词法扫描与文档小节抽取,将 Python 语法特性翻译成通用的 FileFacts 结构。
    解析失败时直接抛出异常交给调用方处理,不在此层做静默容错。

    Args:
        path: 文件路径。

    Returns:
        该文件的事实。

    Raises:
        SyntaxError: 文件不是合法 Python —— 不吞掉,让调用方决定怎么报。
        OSError: 文件读不动。
    """
    # 统一使用 utf-8 读取完整源码,保留原始换行供 1 基行号映射
    source = path.read_text(encoding='utf-8')
    # 行列表按 '\n' 切、行数按 splitlines:前者给 1 基行号索引,后者不含末尾空行
    lines = source.split('\n')
    # 解析生成标准 AST 树,遇到语法错误由外部捕获
    tree = ast.parse(source)
    # 利用 tokenize 抽取包含行尾注释在内的所有注释物理行号集合
    all_comments = layout.comment_rows(source)
    # 独立整行注释:行尾注释不算。条件/循环/抛异常/平铺段只认这一种
    whole_line = {row for row in all_comments if lines[row - 1].lstrip().startswith('#')}
    loops, raises, fields, assigns, returns, silent = structure.simple_facts(tree)
    return FileFacts(
        path=path,
        language=LANGUAGE,
        total_lines=len(source.splitlines()),
        comment_rows=all_comments,
        whole_line_rows=whole_line,
        module_doc=ast.get_docstring(tree),
        functions=structure.function_facts(tree),
        conditions=structure.conditions(tree),
        loops=loops,
        raises=raises,
        fields=fields,
        assigns=assigns,
        returns=returns,
        silent_except_lines=silent,
        bindings=bindings.bindings(tree),
        flat_runs=layout.flat_runs(tree, whole_line),
        layout_gaps=layout.packed_layout(tree, lines),
        heuristic=False)


def parse_many(paths) -> list:
    """批量解析。单文件后端里它只是逐个调用,存在的意义是与多文件后端同签名。

    解析失败的文件会被**跳过而不是中断整批**;调用方按「发现数 vs 解析数」的差额察觉
    —— 静默少扫几个文件等于把「零违规」变成谎话。

    Args:
        paths: 文件路径列表。

    Returns:
        `FileFacts` 列表。
    """
    facts = []
    # 逐文件解析:各文件语法树与注释分布互不依赖,容许个别损坏文件单独跳过
    for path in paths:
        # 各文件的语法树互不依赖:一个损坏文件不该让整批扫不出结果
        try:
            facts.append(parse(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
    return facts
