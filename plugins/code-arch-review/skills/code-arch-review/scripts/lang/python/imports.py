#!/usr/bin/env python3
"""Python 顶层导入的结构事实:给 `sibling-import` / `import-order` / `multi-import` 用。

只扫模块顶层语句:函数内局部导入与 `TYPE_CHECKING` 块不参与「这一层模块怎么组织」
的判断。事实只记录形状,判据在 `core/package.py` —— 换语言时换的是这个抽取器,
不是判据。

为什么单独一个模块:导入结构与测试判据(另一个导入走查)关注点不同 ——
测试判据要全树、只要顶层名;这里要顶层、保留相对级别与被导名字。
"""
import ast


def import_facts(tree):
    """抽取顶层导入的结构事实。

    记录每条导入的行号、模块路径、相对级别与被导名字,并单列「一行多个名字」
    的行号。非导入语句与嵌套导入一律忽略。

    Args:
        tree: 模块的 AST。

    Returns:
        `{'import_details': [(行号, 模块路径, 相对级别, 被导名字元组)], 'multi_import_lines': [行号]}`。
    """
    details = []
    multi_lines = []
    # 只看模块顶层:嵌套导入不在结构判据范围
    for node in tree.body:
        # `import a, b`:一行多个名字要单独记,结构判据要求每行一个
        if isinstance(node, ast.Import):
            # 这一行导入的全部模块路径
            names = tuple(alias.name for alias in node.names)
            # 多于一个名字时记下行号,判 multi-import
            if len(names) > 1:
                multi_lines.append(node.lineno)
            # 每个别名各记一条,排序判据按模块路径逐条比
            for name in names:
                details.append((node.lineno, name, 0, ()))
            continue
        # `from x import y`:相对级别与被导名字都要留下
        if isinstance(node, ast.ImportFrom):
            # 这一行被导入的名字;`from . import x` 靠它认兄弟模块
            imported = tuple(alias.name for alias in node.names)
            details.append((node.lineno, node.module or '', node.level, imported))
    return {'import_details': details, 'multi_import_lines': multi_lines}
