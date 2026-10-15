"""JS / TS 启发式降级的**文本层**:把源码抹成骨架,并读文档注释。

这一层不知道闸有哪些规则,只回答三件事:这一行有没有注释、这段注释是不是文档注释、
一个括号配到哪里结束。上层(`js_lines` 与 `js_fallback`)拿它去认构造。

为什么必须抹字符串而不是直接拿正则扫:`const u = 'http://x'` 里的 `//` 不是注释起点,
正则字面量里的斜杠也一样。不抹掉就会凭空多出注释行 —— 而计数只加不减,
「上方缺注释」这条会被静默抵消,于是闸零违规、代码却没有注释。

这一层出来的行都**保持列对齐**(每个被抹掉的字符换成一个空格),所以列号可以直接
拿去切片,不必维护第二张位置表。
"""

import re

# 文档小节头:`@param {T} name` 这一行之后的缩进内容都归该小节,不算解释段
_TAG_LINE_RE = re.compile(r'^@\w')
_PARAM_TAG_RE = re.compile(r'@param\b')                          # `@param` 小节
_RETURN_TAG_RE = re.compile(r'@returns?\b')                      # `@return` 与 `@returns` 同义
_THROW_TAG_RE = re.compile(r'@throws?\b|@exception\b')           # `@exception` 是 JSDoc 的别名

# `return` 后面跟东西(判函数有没有返回值,也用来认「return 一个算式」)
RETURN_EXPR_RE = re.compile(r'\breturn\s+([^\s;].*)$')
THROW_RE = re.compile(r'\bthrow\b')                               # `throw` 语句


def balanced_span(masked, row, column, opening='(', closing=')'):
    """从 `(row, column)` 处的开括号找到配对的闭括号。

    行号是 1 基、列号是 0 基,和骨架行列表的下标口径一致。

    Args:
        masked: 骨架行。
        row: 起始行号,1 基。
        column: 起始列,0 基,必须落在开括号上。
        opening: 开括号字符。
        closing: 闭括号字符。

    Returns:
        `(括号之间的文本, 闭括号所在行, 闭括号所在列)`;没配上时文本取到文末。
    """
    # 从 1 起算:进来时已经站在开括号里面,开括号本身不进正文
    depth = 1
    pieces = []
    # 逐行推进:括号可能横跨多行
    for index in range(row - 1, len(masked)):
        line = masked[index]
        start = column + 1 if index == row - 1 else 0     # 首行从开括号之后开始
        scan = line[start:]
        found = -1
        # 在直线上数括号深度,回到 0 的就是配对的那个
        for offset, char in enumerate(scan):
            # 开括号进一层
            if char == opening:
                depth += 1
                continue
            # 不是闭括号的字符与深度无关
            if char != closing:
                continue
            depth -= 1
            # 深度归零 ⇒ 配对完成,正文到此为止
            if not depth:
                found = offset
                break
        # 这一行就配上了,把这一行之前的整行都收进正文
        if found >= 0:
            pieces.append(scan[:found])
            return '\n'.join(pieces), index + 1, start + found
        pieces.append(scan)
    return '\n'.join(pieces), len(masked), 0


def split_top(text):
    """按最外层的逗号切分,括号与花括号里的逗号不算分隔符。

    参数表与解构都靠它:`({a, b}, c)` 是两个参数,不是三个。

    Args:
        text: 待切分的文本。

    Returns:
        切好的片段列表。
    """
    pieces = []
    depth = 0
    head = 0
    # 逐字符推进,只有深度为 0 的逗号才切
    for index, char in enumerate(text):
        # 开括号进一层
        if char in '([{':
            depth += 1
            continue
        # 闭括号出一层
        if char in ')]}':
            depth -= 1
            continue
        # 深度为 0 的逗号才是真的分隔符
        if (
            # 位置上是逗号
            char == ','
            # 而且不在任何括号里
            and not depth
        ):
            pieces.append(text[head:index])
            head = index + 1                        # 下一段从这里开始
    pieces.append(text[head:])
    return pieces


def param_names(text):
    """从参数表文本里切出参数名。

    TS 的 `this` 形参与 Python 的 self 同类:调用方从不传它,不计入参数个数。
    解构与默认值退化成一段文本 —— 启发式认不出里面的绑定名,但也不该因此漏掉整个参数。

    Args:
        text: 括号之间的参数表文本。

    Returns:
        参数名列表。
    """
    names = []
    # 逗号只在最外层才是分隔符,解构里的逗号属于同一个参数
    for piece in split_top(text):
        item = piece.split('=')[0].split(':')[0].strip()   # 去掉默认值与类型标注
        # 空片段与 `this` 都不是调用方要传的参数
        if (
            # 空片段说明这一段没有内容
            not item
            # `this` 是 TS 的绑定形参,调用方从不传
            or item == 'this'
        ):
            continue
        names.append(item)
    return names


def module_doc(lines, whole_rows):
    """文件开头的注释块 —— 模块文档在 JS 里的对应物。

    判据是「这段注释之前没有任何代码,中间允许有空行」:`'use strict'` 之类的语句
    算代码,它之后的注释就不是模块文档了。空行只是被跳过,不进正文 —— 文件头
    常见的「license 注释 + 空行 + 模块说明」要一起算进来。

    Args:
        lines: 文件按行切好的原文。
        whole_rows: 独立整行注释的行号集合。

    Returns:
        注释正文;文件不是以注释开头时返回 None。
    """
    collected = []
    row = 1
    # 从第 1 行起往下一路收:遇到第一行代码就停
    while (
        # 还没走到文件末尾
        row <= len(lines)
        # 而且这一行不是代码
        and not _is_code_line(lines, whole_rows, row)
    ):
        # 只收注释行;空行只是被跳过,不进正文
        if row in whole_rows:
            collected.append(lines[row - 1])
        row += 1
    # 头一段里一行注释都没有 ⇒ 这个文件没有模块文档
    if not collected:
        return None
    return strip_doc('\n'.join(collected))


def _is_code_line(lines, whole_rows, row):
    """这一行算不算「文件头注释块」之外的代码。

    空行与整行注释都不是代码:空行让注释块能与后面的代码隔开,而整行注释
    本身就是注释块的一部分。

    Args:
        lines: 文件按行切好的原文。
        whole_rows: 独立整行注释的行号集合。
        row: 行号,1 基。

    Returns:
        是代码行时为 True。
    """
    # 空行不是代码,也不是终点
    if not lines[row - 1].strip():
        return False
    # 整行注释要收进文件头
    if row in whole_rows:
        return False
    return True


def strip_doc(block):
    """把注释块还原成正文(去掉定界符与行首的星号或 `//`)。

    还原出来的正文要能直接参与「摘要行 + 解释段」的计数,所以每行的前导装饰
    (`*`、`//`、`/**`、`*/`)都得去掉,否则每一行都会被算成有内容的解释行。

    Args:
        block: 注释块原文,可能多行。

    Returns:
        正文文本。
    """
    lines = []
    # 逐行去掉行首行尾的注释装饰
    for raw in block.split('\n'):
        text = raw.strip()                      # 定界符判定要在去掉缩进之后做
        # JSDoc / 块注释的开头定界符
        if text.startswith('/**'):
            text = text[3:]
        # 块注释的结尾定界符
        if text.endswith('*/'):
            text = text[:-2]
        # 行注释的定界符
        if text.startswith('//'):
            text = text[2:]
        lines.append(text.lstrip('*').strip())
    return '\n'.join(lines).strip('\n')


def doc_above(lines, whole_rows, row):
    """定义上方**紧贴**的 `/** ... */` 块。

    「紧贴」= 中间没有空行:隔了空行的注释是文件里的段落说明,不是这个函数的契约。
    同一个注释段里最后那个 `/**` 才算了数 —— 上面单独的 `//` 行属于文件段落。

    Args:
        lines: 文件按行切好的原文。
        whole_rows: 独立整行注释的行号集合。
        row: 定义所在行,1 基。

    Returns:
        文档正文;上方没有紧贴的 JSDoc 块时返回 None。
    """
    head = row - 1                              # 从定义的上一行往上找注释块
    # 定义上方紧贴的整行注释都属于这个定义,空行会在它们之前
    while (
        # 还没走到文件开头
        head >= 1
        # 而且这一行是整行注释
        and head in whole_rows
    ):
        head -= 1
    head += 1                                   # 退回第一个不是注释的行
    # 上一行不是整行注释 ⇒ 没有贴着的注释块
    if head == row:
        return None
    run = lines[head - 1:row - 1]
    start = None
    # 取这一段里最后一个 `/**` 行
    for offset, raw in enumerate(run):
        # 只有 `/**` 才是文档注释,`/*` 是普通块注释
        if raw.lstrip().startswith('/**'):
            start = offset
    # 整段里一个 `/**` 都没有 ⇒ 这不是文档注释
    if start is None:
        return None
    return strip_doc('\n'.join(run[start:]))


def prose_lines(doc):
    """摘要行之后、不在任何 `@标签` 行里的非空行数。

    一行式文档只限真正平凡的函数:一行摘要把「做什么」重复一遍(函数名已经说了),
    而「为什么这么做、什么前提下成立」全靠读实现反推。

    Args:
        doc: 文档正文。

    Returns:
        解释段的行数。
    """
    prose = 0
    in_section = False
    # 小节一旦开始就延续到下一个小节头或文末,里面的内容不是解释段
    for line in doc.split('\n')[1:]:
        text = line.strip()                     # 空行与缩进都不算内容
        # 空行不算解释
        if not text:
            continue
        # 命中小节头 ⇒ 从这里开始都归小节
        if _TAG_LINE_RE.match(text):
            in_section = True
            continue
        # 已经在小节里 ⇒ 这一行是小节内容
        if in_section:
            continue
        prose += 1
    return prose


def section_facts(doc, params, body):
    """按 JSDoc 约定算必需小节与缺失小节。

    没有文档时不报缺小节 —— 那一条由 `no-docstring` 说,一个错不记两次。

    Args:
        doc: 文档正文;没有文档时传 None。
        params: 参数名列表。
        body: 函数体文本,用来粗判有没有 return / throw。

    Returns:
        `(必需小节, 缺失小节)`。
    """
    required = []
    # 有参数就要参数说明:不看一行实现就能写出调用,靠的就是它
    if params:
        required.append('@param')
    # 有 `return <表达式>` 才要 `@returns`,裸 `return` 没有口径可写
    if RETURN_EXPR_RE.search(body):
        required.append('@returns')
    # 会抛异常就要写清什么前提被破坏
    if THROW_RE.search(body):
        required.append('@throws')
    # 没有文档时缺小节由 no-docstring 一条说清,这里不重复报
    if not doc:
        return required, []
    return required, [item for item in required if not has_tag(doc, item)]


def has_tag(doc, section):
    """文档里有没有这个 JSDoc 小节(`@returns` 与 `@return` 是同一个)。

    `@exception` 也算抛出说明:JSDoc 里它是 `@throws` 的别名,写了就该认,
    不认会让人以为写了没用。

    Args:
        doc: 文档正文。
        section: 小节名。

    Returns:
        有这个标签时为 True。
    """
    # 参数小节
    if section == '@param':
        return bool(_PARAM_TAG_RE.search(doc))
    # 返回值小节,单数复数都认
    if section == '@returns':
        return bool(_RETURN_TAG_RE.search(doc))
    return bool(_THROW_TAG_RE.search(doc))
