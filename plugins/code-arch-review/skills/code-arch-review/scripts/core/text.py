"""各语言后端共用的文本工具:注释识别、行切片、空行判断。

**为什么单独一层**:注释判定是违规与覆盖率唯一的公共依据,四个后端各写一遍就会各错各的
—— 原闸的教训正是「两套谓词分叉而两个数都不报错」。凡是「哪些行有注释」这类判断,
都收在这里,后端只负责给出该语言的注释**标记**(`#` / `//` / `/* */`)。

Python 不在这里做:它的 `#` 必须过 `tokenize` 才能躲开字符串与 f-string 里的假注释,
那件事在 `lang/python/layout.py` 里做。
"""


def scan_comment_spans(line, line_marker, block_open=None, block_close=None):
    """在一行里找出**引号之外**的注释起始位置。

    简易状态机:逐字符走,遇到引号翻转状态,只有引号外的标记才算注释起点。
    不做转义序列的完整处理 —— 那只在一行的范围内就够了,跨行字符串由调用方
    (`split_line_comments`)按块注释状态接管。

    Args:
        line: 源码整行文本(未去尾空白)。
        line_marker: 行注释标记,如 `#` 或 `//`。
        block_open: 块注释起始标记,如 `/*`;没有块注释的语言传 None。
        block_close: 块注释结束标记,如 `*/`;没有块注释的语言传 None。

    Returns:
        `(行注释起点列, 块注释起点列)`;没有则为 -1。块注释起点若在行注释之前,
        说明本行的行注释在块注释里面,不算。
    """
    quote = ''
    # 逐字符线性扫描单行源码:追踪引号配对状态并探测引号外的行/块注释起点
    for index, char in enumerate(line):
        # 引号内一律不判注释,直到配对的引号关上
        if quote:
            # 遇到匹配的闭合引号时退出字符串状态
            if char == quote:
                quote = ''
            continue
        # 命中单双引号且当前不在字符串内部时,记录当前引号类型进入字符串态
        if char in '"\'':
            quote = char
            continue
        if (
            # 存在行注释标记
            line_marker
            # 当前位置匹配行注释起始标记
            and line.startswith(line_marker, index)
        ):
            return index, -1
        if (
            # 语言配置了块注释起始标记
            block_open
            # 当前位置匹配块注释起始字符
            and line.startswith(block_open, index)
        ):
            return -1, index
    return -1, -1


def whole_line_comment_rows(lines, line_marker, block_open=None, block_close=None):
    """找出「整行都是注释」的行号。

    整行的判据是**注释起点之前只有空白** —— 与闸的口径一致:字段/赋值/return 接受
    行尾注释,但条件/循环/抛异常**只认上方独立整行注释**,所以这两种必须分开统计。

    Args:
        lines: 文件按行切好的列表,0 基。
        line_marker: 行注释标记。
        block_open: 块注释起始标记;没有则 None。
        block_close: 块注释结束标记;没有则 None。

    Returns:
        行号集合(1 基)。多行块注释的**每一行**都算 —— 块注释的首行以标记开头,
        续行也整行都在注释里;构造上方是跨行注释块时,紧邻构造的那一行正是它的续行,
        按「上方有没有独立注释」这条规则的本意,它就该算数。
    """
    # 存储命中独立整行注释的行号集合(1 基)
    rows = set()
    in_block = False
    # 逐行遍历源码文本:维护多行块注释状态机,提取所有仅包含注释的物理行号
    for index, line in enumerate(lines):
        # 将从 0 开始的行索引转为面向用户的 1 基行号
        row = index + 1
        # 块注释续行:整行都在注释里,直接算
        if in_block:
            rows.add(row)
            if (
                # 配置了块注释结束标记
                block_close
                # 本行包含块注释闭合标记,在此关闭块注释状态
                and block_close in line
            ):
                in_block = False
            continue
        # 去除行首尾空白,用于判断是否为整行注释起始
        stripped = line.strip()
        # 空行不包含任何注释内容,直接跳过
        if not stripped:
            continue
        # 整行块注释的开头:`/*` 之前只有空白
        if (
            # 语言支持块注释
            block_open
            # 去除前导空白后以块注释起始符开头
            and stripped.startswith(block_open)
        ):
            rows.add(row)
            # 块注释未在当前行立即闭合时,将状态标记为跨行块注释内部
            if not (block_close and block_close in stripped[len(block_open):]):
                in_block = True
            continue
        # 整行行注释
        if (
            # 配置了行注释标记
            line_marker
            # 去除前导空白后以行注释标记开头
            and stripped.startswith(line_marker)
        ):
            rows.add(row)
    return rows


def comment_rows(lines, line_marker, block_open=None, block_close=None):
    """找出「这一行出现过注释」的行号,含**行尾注释**。

    与 `whole_line_comment_rows` 的区别就是行尾注释:字段与算出来的赋值允许把说明写在
    本行末尾,所以覆盖率要用这一份;而条件/循环/抛异常只认独立整行注释,用上面那份。

    Args:
        lines: 文件按行切好的列表,0 基。
        line_marker: 行注释标记。
        block_open: 块注释起始标记;没有则 None。
        block_close: 块注释结束标记;没有则 None。

    Returns:
        行号集合(1 基)。
    """
    # 存储包含任意有效注释(含行尾注释)的行号集合(1 基)
    rows = set()
    in_block = False
    # 逐行遍历源码文本:识别含块注释续行、块注释起始或行尾注释的行号
    for index, line in enumerate(lines):
        # 换算为 1 基物理行号
        row = index + 1
        # 块注释续行:本行出现过注释文字,计入
        if in_block:
            rows.add(row)
            if (
                # 配置了块注释闭合标记
                block_close
                # 当前行包含闭合标记时退出块注释状态
                and block_close in line
            ):
                in_block = False
            continue
        line_at, block_at = scan_comment_spans(line, line_marker, block_open, block_close)
        # 块注释先出现:本行算有注释,并进入块状态直到遇上结束标记
        if (
            # 本行探测到了块注释起始标记
            block_at >= 0
            and (
                # 行内不存在行注释标记
                line_at < 0
                # 或者块注释先于行注释出现
                or block_at < line_at
            )
        ):
            rows.add(row)
            # 当前行未包含闭合标记时,标记进入跨行块注释内部
            if not (block_close and block_close in line[block_at + len(block_open):]):
                in_block = True
            continue
        # 命中行注释标记且非块注释时,计入带注释行
        if line_at >= 0:
            rows.add(row)
    return rows


def code_part(line, line_marker):
    """返回一行里注释之前的部分,供「行尾注释」判断使用。

    踩过的坑:一度直接写 `'#' not in code_part(line)` 做判断,但 `code_part` 的职责
    正是在引号外遇到标记就截掉,返回值里永远不可能有标记,于是那个判断恒为真,
    所有已经写了行尾说明的字段被误报成缺注释。判断必须**比长度**。

    Args:
        line: 源码整行文本。
        line_marker: 行注释标记。

    Returns:
        标记之前的代码部分;没有标记时返回原行。
    """
    line_at, _block_at = scan_comment_spans(line, line_marker)
    # 引号外未命中行注释标记时保留整行,命中时截断至标记前位置
    return line[:line_at] if line_at >= 0 else line


def has_inline_comment(line, line_marker):
    """这一行的代码后面是否跟了行尾注释。

    先截取引号外注释标记之前的有效代码,通过比对截取长度与原行长度确认是否存在
    注释标记,并进一步确认注释前存在非空白代码(排除纯注释行与空行)。

    Args:
        line: 源码整行文本(未去尾空白)。
        line_marker: 行注释标记。

    Returns:
        引号外存在标记,且标记之前有非空白代码时为 True。
    """
    # 截取引号外行注释标记之前的代码有效部分
    cut = code_part(line, line_marker)
    return len(cut) != len(line) and bool(cut.strip())


def is_blank(line):
    """这一行是否为空行(只有空白)。

    去除前后空白字符后判定剩余长度是否为 0,用于布局检查统计类与函数间的空行间隔。

    Args:
        line: 源码整行文本。

    Returns:
        去掉首尾空白后为空时为 True。
    """
    return not line.strip()


def explained(facts, row, accepts_inline):
    """某个构造是否已经被解释过。**全引擎唯一的注释判据**,违规与覆盖率共用。

    🔴 这个函数放在这里而不是 `core.rules` 里,是因为它的输入是**行号集合**,
    不是规则知识 —— 与上面几个「哪些行有注释」的函数同源。原实现把违规判据与
    覆盖率判据各写一份,分叉过一次(整个 `if` 只看前一行、行尾注释判断写反),
    **而分叉时违规数与覆盖率都不报错**。收在一个模块里,分叉在结构上不可能发生。

    Args:
        facts: 该文件的事实。
        row: 构造所在行号,1 基。
        accepts_inline: 这条规则是否接受**行尾**注释。

    Returns:
        上方有独立整行注释,或(该规则接受行尾注释且本行有行尾注释)时为 True。
    """
    # 独立整行注释在构造的上一行 —— 条件/循环/抛异常只认这一种
    if row - 1 in facts.whole_line_rows:
        return True
    # 只有接受行尾注释的规则才看本行;字段与赋值一行放得下,所以接受
    if (
        # 当前规则允许行尾注释(如字段与算式赋值)
        accepts_inline
        # 当前物理行本身包含注释标记
        and row in facts.comment_rows
    ):
        return True
    return False
