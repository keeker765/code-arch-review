"""PowerShell 注释式帮助块(`<# ... #>`)的解析。

**为什么单独一层**:「写没写文档、缺哪个小节、摘要有几行解释」这三件事只有帮助块
自己知道,与起进程、组事实无关;混在后端里会让那个文件越过 `long-module` 的线。
这一层只看文本:输入是已经剥掉定界符的帮助正文,不碰 AST、不看源码行号。

判断口径与 `lang/python/docstrings.py` 一一对应,只是换了小节名 ——
两个语言的文档要求是同一条,不该在换语言时换标准。
"""

import re

# 帮助小节头:`.SYNOPSIS` / `.PARAMETER Name` / `.OUTPUTS`
_SECTION_RE = re.compile(r'^\s*\.([A-Za-z][A-Za-z0-9]*)')

# 正文属于「接口清单 / 元数据」的小节,不算解释段。
# `.DESCRIPTION` 与 `.NOTES` **故意不在这里** —— PowerShell 的「为什么这么写」
# 正写在 `.DESCRIPTION` 里;把整块帮助当小节一刀切,会让每个写对文档的函数
# 都被判 thin-docstring,而只报噪声的闸会被直接关掉。
_SUPPRESSING_SECTIONS = frozenset({
    'PARAMETER', 'EXAMPLE', 'OUTPUTS', 'INPUTS', 'LINK', 'COMPONENT', 'ROLE',
    'FUNCTIONALITY', 'REMOTEHELPRUNSPACE', 'FORWARDHELPTARGETNAME',
    'FORWARDHELPCATEGORY', 'EXTERNALHELP',
})


def clean(text):
    """剥掉帮助块的 `<#` / `#>` 定界符。

    定界符不属于文档内容;留着它会让「帮助块只有一行」与「帮助块根本没写」
    在报告里长得一样。

    Args:
        text: 后端给的帮助块原文;没有帮助块时是 None。

    Returns:
        帮助正文;空帮助块返回 None。
    """
    # 没有帮助块,与空帮助块一样归 None
    if not text:
        return None
    # 定界符不是文档内容,先脱掉再数行
    body = text.strip()
    # 开头是块注释起始标记就去掉它
    if body.startswith('<#'):
        body = body[2:]
    # 结尾是块注释结束标记就去掉它
    if body.endswith('#>'):
        body = body[:-2]
    # 去掉定界符后仍是空的帮助块等于没写文档,不能算「有」
    return body.strip() or None


def _tag_of(line):
    """这一行是不是帮助小节头(`.SYNOPSIS` 这类)。

    小节名大小写不敏感(`Get-Help` 两个都认),统一折成大写再比。
    """
    matched = _SECTION_RE.match(line)  # 不是小节头时是 None
    # 不是小节头就返回 None,调用方据此区分「正文」与「小节名」
    if matched:
        return matched.group(1).upper()
    return None


def _has_tag(doc, name):
    """帮助块里是否写了某个小节。

    只判「在不在」不判重复:同一个 `.PARAMETER` 写两遍是排版问题,
    `docstring-sections` 管的是缺不缺。
    """
    # 逐行看:小节头可能出现在帮助块的任何位置
    for line in doc.splitlines():
        # 命中同名小节就够了,后面的行不必再看
        if _tag_of(line.strip()) == name:
            return True
    return False


def _summary_index(lines):
    """找出摘要行在帮助块里的下标。

    摘要有两种写法:`.SYNOPSIS` 小节里的第一行正文,或整块没有 `.SYNOPSIS` 时的
    第一行正文。摘要是标题,等于复述函数名,不能算进「解释段」的行数 ——
    不排掉它,每个只写了 `.SYNOPSIS` 的函数都会显得像写了三行解释。
    """
    after_synopsis = False
    # 第一遍:只认 .SYNOPSIS 小节里的第一行正文
    for index, line in enumerate(lines):
        tag = _tag_of(line.strip())  # 当前行的小节名
        # 撞到小节头就切换状态,并继续往下找正文
        if tag:
            after_synopsis = tag == 'SYNOPSIS'  # 只有 .SYNOPSIS 的正文才算摘要
            continue
        if (
            # 空行不是摘要
            line.strip()
            # 且必须真的在 .SYNOPSIS 小节里
            and after_synopsis
        ):
            return index
    # 第二遍:整块没有 .SYNOPSIS 时,退化成「第一行非空正文」
    for index, line in enumerate(lines):
        if (
            # 第一行非空正文
            line.strip()
            # 且不是小节头本身
            and not _tag_of(line.strip())
        ):
            return index
    return -1


def prose_lines(doc):
    """数帮助块里「摘要之后、解释段之内」的非空行数。

    判 `thin-docstring` 用:只有摘要(等于复述函数名)的文档要报出来。
    小节内容分两类 —— `.PARAMETER` / `.EXAMPLE` 是接口清单,不算解释;
    `.DESCRIPTION` / `.NOTES` 算,那正是「为什么这么写」。

    Args:
        doc: 帮助正文,调用方保证非空。

    Returns:
        解释段行数。
    """
    lines = doc.splitlines()  # 摘要与解释都按行数
    summary = _summary_index(lines)  # 摘要行是标题,不算解释
    prose = 0
    suppressing = False
    # 逐行累计:遇到小节头就切换「要不要计」的状态
    for index, line in enumerate(lines):
        tag = _tag_of(line.strip())  # 当前行的小节名
        # 小节头本身不是解释,它只决定后面的正文算不算
        if tag:
            suppressing = tag in _SUPPRESSING_SECTIONS  # 接口清单小节的正文不计
            continue
        if (
            # 空行不是解释
            not line.strip()
            # 接口清单小节的正文也不是解释
            or suppressing
        ):
            continue
        # 摘要行是标题,不是解释段
        if index != summary:
            prose += 1
    return prose


def missing_sections(doc, params, has_return):
    """列出帮助块里缺的必需小节。

    口径与 Python 侧同一条,只是换小节名:有参数就要求 `.PARAMETER`,
    有返回值就要求 `.OUTPUTS`。只查小节在不在,不查每个参数是否都写了 ——
    那要逐参数对齐,这里不假装做到。

    Args:
        doc: 帮助正文,调用方保证非空。
        params: 参数名元组。
        has_return: 函数体里是否出现 `return <算式>`。

    Returns:
        `(必需小节元组, 缺失小节元组)`;缺失项带上参数个数,报告里看得出规模。
    """
    required = []
    # 有参数就必须交代每个参数的语义,对应 Python 的 Args
    if params:
        required.append('.PARAMETER')
    # 有返回值就必须交代返回口径,对应 Python 的 Returns
    if has_return:
        required.append('.OUTPUTS')
    missing = []
    # 逐个必需小节回查帮助块,缺的收进 missing
    for name in required:
        # 前导点只在人类可读的报表里出现,比对小节名时要脱掉
        if _has_tag(doc, name[1:]):
            continue
        # 参数小节的缺失要带个数,读者才知道要不要现在就补
        if name == '.PARAMETER':
            missing.append(f'{name}({len(params)} 个参数)')
        else:
            missing.append(name)
    return tuple(required), tuple(missing)
