"""Python 文档注释的分析:必需小节、解释段行数。

单独一个模块是因为这两项判据都很「细」而且各自被引用多次 —— 混在 AST 遍历里,
改一处小节名要在一个五百行的文件里翻找。`SKILL.md` 要求「按职责切子包」,
而「文档写得够不够」和「语法树长什么样」确实是两件事。
"""

import ast

# docstring 小节头。小节一旦开始就一直延续到下一个小节头或文末。
# 列全一点是有意的:`Attributes:` / `Examples:` / `Note:` 虽然不是本闸强制要求的,
# 但它们出现在文档里时必须被认出来是**小节**,否则「摘要之后的解释段」会把它们的内容
# 误算成散文,于是 `thin-docstring` 在写得最全的那些函数上反而不报。
_DOC_SECTIONS = ('Args:', 'Arguments:', 'Returns:', 'Return:', 'Yields:', 'Raises:',
                 'Attributes:', 'Examples:', 'Example:', 'Note:', 'Notes:')


def missing_sections(node, doc):
    """按 Google pyguide §3.8.3 找出文档缺的必需小节。

    只对**公开且非平凡**的函数要求(有参数 / 有返回值 / 会抛异常),
    平凡的一行函数不强求 —— YAGNI 对文档同样适用。

    Args:
        node: 已确认是公开函数的 ast 节点。
        doc: 该节点的文档正文,调用方保证非空。

    Returns:
        缺失小节名的列表;齐备时为空列表。
    """
    args = node.args
    names = [item.arg for item in (*args.posonlyargs, *args.args, *args.kwonlyargs)
             if item.arg not in ('self', 'cls')]
    # 裸 return 与 return None 属于无值退出,仅带表达式的 return 才要求 Returns 小节
    returns = any(isinstance(item, ast.Return) and item.value is not None
                  for item in ast.walk(node))
    # 生成器函数写 Yields 而非 Returns,需扫描 yield 与 yield from 两类产出节点
    yields = any(isinstance(item, (ast.Yield, ast.YieldFrom)) for item in ast.walk(node))
    # 递归子节点排查显式 raise 语句,只要会抛异常就必须在文档中声明 Raises 小节
    raises = any(isinstance(item, ast.Raise) for item in ast.walk(node))
    missing = []
    if (
        # 存在排除 self/cls 后的有效参数,必须在文档中说明入参含义
        names
        # 文档缺少 Args 格式小节头
        and 'Args:' not in doc
    ):
        missing.append(f'Args({len(names)} 个参数)')
    # Yields 与 Returns 互斥:生成器写 Yields,普通函数写 Returns
    if (
        # 语法树包含 yield/yield from 构造,属于生成器函数
        yields
        # 文档缺少 Yields 格式小节头
        and 'Yields:' not in doc
    ):
        missing.append('Yields')
    elif (
        # 函数存在非 None 的返回路径
        returns
        # 且非生成器形态
        and not yields
        # 文档缺少 Returns 格式小节头
        and 'Returns:' not in doc
    ):
        missing.append('Returns')
    if (
        # 函数体存在显式 raise 语句
        raises
        # 文档缺少 Raises 格式小节头
        and 'Raises:' not in doc
    ):
        missing.append('Raises')
    return missing


def prose_lines(doc):
    """数文档里「摘要行之外的解释文字」有几行。

    一行式文档只限真正平凡的函数 —— 一行摘要把「做什么」重复一遍(函数名已经说了),
    而「为什么这么算、什么前提下成立」全靠读实现反推。所以只数摘要之后的散文行,
    **Args/Returns/Raises 小节里的内容不算** —— 那些是接口清单,不是解释。

    Args:
        doc: 节点的文档正文,调用方保证非空。

    Returns:
        摘要行之后、不属于任何小节的非空行数。
    """
    prose = 0
    in_section = False
    # 跳过首行摘要:逐行遍历 docstring 的后续各行以统计解释段与排除小节内容
    for line in doc.splitlines()[1:]:
        # 去除行首尾空白字符,便于精准前缀比对与空行判定
        stripped = line.strip()
        # 命中小节头:此后的内容归该小节,直到出现下一个小节头
        if stripped.startswith(_DOC_SECTIONS):
            in_section = True
            continue
        # 空行不断开小节;小节内的内容不是解释段
        if (
            # 空白行不计入解释性散文行数
            not stripped
            # 当前行位于特定小节块内部,属于接口清单而非散文解释段
            or in_section
        ):
            continue
        prose += 1
    return prose
