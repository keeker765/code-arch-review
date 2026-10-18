"""Bash / Shell 后端 —— 最低档:纯行级启发式,不调任何外部进程。

为什么不做真解析:bash 没有可行的解析器(`bash -n` 只验语法),所以按 `languages.md` 只查
条件/循环/抛失败态/扁平段,文档约定与结构度量不查;也不用 `core.text` 的通用注释扫描,因为
bash 多两条它不认的规则。三条边界写在对应代码的位置上:heredoc 体不是代码(`#` 与 `if` 都
不算);行尾反斜杠与行尾 `&&` 是续行(按行数判会把一条条件算成两条);引号能跨物理行。
"""

from dataclasses import dataclass
from pathlib import Path
import re

from core.model import ConditionFact, FileFacts, SimpleFact

# 与 `lang.registry` 的 shell 配置一致;`looks_like_shell` 用它兜住无扩展名的脚本
EXTS = ('.sh', '.bash', '.zsh', '.ksh')
# 报告里显示的语言名,与注册表里的 `Language('shell', ...)` 对齐
LANGUAGE = 'shell'

# 行尾出现这些记号时换行只当空白 —— 下一物理行仍属同一语句(续行)
_CONTINUATION = ('\\', '&&', '||', '|')

# 命令位置 = 行首,或这些记号之后;只有命令位置上的词才算关键字。
# 反引号也算 `_OPERATOR`:`` `if ...; fi` `` 里的 `if` 是真的条件(子 shell 代码)
_OPERATOR = re.compile(r'&&|\|\||[;&|({`]')
# shell 里的一个词:关键字识别与 heredoc 终止符名都按它取
_WORD = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
# 条件摊平只认这两个(`|` 是管道,两边不是同一个判据)
_CONDITION_OPERATOR = re.compile(r'&&|\|\|')
# 非零退出码:`exit 0` 不是失败态,所以把 0 直接从模式里排掉,代码里不必再比一次零
_EXIT_CODE = re.compile(r'-?[1-9][0-9]*|-?0[0-9]+')
# 函数定义:`name() {` 或 `function name` —— 平铺段在它这里切断
_FUNCTION_DEF = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*\{|function\s+[A-Za-z_]')

# 命令位置上的这些词自带结构,不算平铺语句,也切断当前平铺段
_STRUCTURE_WORDS = {'if', 'then', 'elif', 'else', 'fi', 'for', 'while', 'until',
                    'do', 'done', 'case', 'esac', 'select'}
# bash 只有这两种条件关键字(`then` / `fi` 是块标记,不是条件)
_CONDITION_WORDS = {'if', 'elif'}
# 循环关键字(`do` / `done` 是块标记)
_LOOP_WORDS = {'for', 'while', 'until'}
# 这些词之后又是一个命令位置(`then if ...` 里的 `if` 是真条件)
_BLOCK_WORDS = {'then', 'do', 'else'}
# shebang 里认得出来的 shell 解释器名
_SHELL_NAMES = {'sh', 'bash', 'zsh', 'ksh', 'dash'}


@dataclass(frozen=True)
class _CodeLine:
    """一行**物理**源码的扫描结果;heredoc 体不会变成 `_CodeLine`。

    存遮罩文本而不是原文 —— bash 的关键字判定只能在没有引号内容的文本上做。
    """

    row: int                  # 行号,1 基
    masked: str               # 代码文本:引号内内容已抹成空格,注释已切掉
    whole_line_comment: bool  # 本行第一个非空白字符就是 `#`(条件/循环/raise 只认这种)
    has_comment: bool         # 本行出现过注释,含行尾(覆盖率的分母判据)


@dataclass(frozen=True)
class _LogicalLine:
    """一条**逻辑**语句 —— 若干物理行用续行记号拼起来的结果。

    `text` 与 `part_starts` 分开存,是为了把字符偏移映射回物理行号。
    """

    text: str                     # 拼接后(片段间补空格)的遮罩文本
    part_starts: tuple[int, ...]  # 每个物理片段在 text 里的起始下标,升序
    part_rows: tuple[int, ...]    # 与 part_starts 一一对应的物理行号


def parse(path: Path) -> FileFacts:
    """把一个 shell 脚本解析成闸认的事实。

    只填最低档查得到的那几项,其余保持空列表 —— 空列表在引擎里就是「这条规则不查」。

    Args:
        path: 脚本路径。

    Returns:
        该文件的 `FileFacts`;结构度量一律标 `heuristic=True`,由报告决定哪几条只报不拦。

    Raises:
        OSError: 文件读不到。
    """
    # 真实脚本里有 GBK 编码的,硬解 utf-8 会直接崩;替换字符只影响正文显示,行号不受影响
    text = path.read_text(encoding='utf-8', errors='replace')
    raw_lines = text.splitlines()      # 与 `wc -l` 同口径:末行没有换行也算一行
    records = _code_lines(raw_lines)   # 已剔除 heredoc 体的代码行
    lines = _logical_lines(records)    # 续行拼好的逻辑语句
    conditions, loops, raises = _control_facts(lines)
    # 两份注释行集合:含行尾的那份给覆盖率,只算独立整行的那份给条件/循环/raise
    comment_rows = {record.row for record in records if record.has_comment}
    whole_line_rows = {record.row for record in records if record.whole_line_comment}
    return FileFacts(
        path=path,
        language=LANGUAGE,
        total_lines=len(raw_lines),
        comment_rows=comment_rows,
        whole_line_rows=whole_line_rows,
        conditions=conditions,
        loops=loops,
        raises=raises,
        flat_runs=_flat_runs(records, whole_line_rows),
        heuristic=True)


def parse_many(paths: list) -> list:
    """批量解析。单文件后端里它只是逐个调用,签名与多文件后端(起一次子进程)一致。

    读不动或解码不了的文件跳过而不是中断整批 —— 差额由调用方按文件数察觉,不是静默吞掉。

    Args:
        paths: 文件路径列表。

    Returns:
        `FileFacts` 列表,可能短于入参。
    """
    facts = []
    # 逐个解析:一个坏文件不该让整批扫描失败
    for path in paths:
        # 只有读不动与解码不了算「这个文件跳过」,别的异常照旧抛出去
        try:
            facts.append(parse(path))
        except (OSError, UnicodeDecodeError):
            continue
    return facts


def looks_like_shell(path: Path) -> bool:
    """判断一个文件该不该交给本后端 —— 扩展名之外还认 shebang。

    真实脚本里有不少没有扩展名的(`bin/deploy` 之类),只看扩展名会把它们整片漏掉。

    Args:
        path: 文件路径。

    Returns:
        扩展名命中 `EXTS`,或首行 `#!` 的解释器是 sh / bash / zsh / ksh / dash 时为 True;
        读不到文件时为 False。
    """
    # 扩展名是首选判据,命中就不必开文件
    if path.suffix.lower() in EXTS:
        return True
    try:
        with path.open(encoding='utf-8', errors='replace') as handle:
            head = handle.readline()   # shebang 里的名字是 ASCII,首行就够
    except OSError:
        return False
    # 首字符不是 `#!` 就不是 shebang
    if not head.startswith('#!'):
        return False
    # `#!` 之后按空白切词:第一个词是解释器路径,`env bash` 时它是 env、名字在参数里
    names = [token.replace('\\', '/').rsplit('/', 1)[-1] for token in head[2:].split()]
    # 空 shebang(`#!` 后面什么都没有)不是 shell
    if not names:
        return False
    # 直接写解释器名:`#!/bin/sh`、`#!/usr/bin/bash`
    if names[0] in _SHELL_NAMES:
        return True
    # `env bash` / `env -S bash -e`:解释器名在 env 的参数里
    if names[0] != 'env':
        return False
    return any(name in _SHELL_NAMES for name in names[1:])


def _scan_line(raw: str, quote: str = '') -> tuple:
    """扫一行物理行:代码部分、遮罩部分、注释起点,以及行末仍开着的引号。

    引号**本身**留在遮罩里、只抹掉里面的内容 —— 于是 `echo "a#b"` 里的 `#` 被抹掉(不是
    注释),而 `echo "x"#y` 后面的 `#` 前面紧贴着一个词,也判不成注释。返回的 quote 要交给下一行。
    """
    spans = []          # 引号内内容的区间,遮罩时抹成空格
    comment_col = None
    start = 0           # 当前这段引号内容的起点
    index = 0
    # 逐字符走:引号内不判注释,直到配对的收尾引号出现
    while index < len(raw):
        char = raw[index]
        # 引号内部:只有配对的收尾引号才结束这段字符串
        if quote:
            # 双引号里的反斜杠转义下一个字符;单引号里它只是普通字符
            if quote == '"':
                # 被转义的那个字符整个跳过,它既不开引号也不开注释
                if char == '\\':
                    index += 2
                    continue
            # 收尾引号:记下引号之间的区间,遮罩时抹掉它
            if char == quote:
                spans.append((start, index))
                quote = ''
            index += 1
            continue
        # 引号起点:引号字符本身留在遮罩里当词的边界,只抹它里面的内容
        if char in '\'"':
            quote = char
            start = index + 1          # 内容从开引号的下一个字符起
            index += 1
            continue
        # `\#` 与 `\"` 是转义的字面字符,两个字符一起跳过
        if raw[index:index + 2] in ('\\#', '\\"', "\\'", '\\\\'):
            index += 2
            continue
        # `#` 只有落在词的边界上才算注释起点;`a#b` 里的它是普通字符
        if char == '#':
            # 行首取到的是空串,而空串在下面这串边界记号里 —— 行首本来就是边界
            if raw[index - 1:index] in ' \t;&|(){}':
                comment_col = index
                break
        index += 1
    # 引号到行尾还没闭合(跨行字符串):本行余下部分全是引号内容,状态交给下一行
    if quote:
        spans.append((start, len(raw)))
    # 注释起点之后的一切都不是代码,两个文本都要抹掉
    cut = len(raw) if comment_col is None else comment_col
    code, masked = _blank_masked(raw, spans, cut)
    return code, masked, comment_col, quote


def _blank_masked(raw: str, spans: list, cut: int) -> tuple:
    """把引号内的区间与注释段抹成空格,返回与 raw 等长的 `(code, masked)`。

    长度必须不变:子条件的行号靠字符偏移映射回去,抹短一个字符就会串行。
    """
    masked = list(raw)                 # 与原文等长,后面按偏移抹字符
    # 引号内的内容:只抹到注释起点为止
    for begin, end in spans:
        # 同一个区间里逐字符抹,`min` 保证不越过注释起点
        for position in range(begin, min(end, cut)):
            masked[position] = ' '
    # 注释段:整段抹成空格
    for position in range(cut, len(masked)):
        masked[position] = ' '
    # 原文只在注释处截断(heredoc 终止符要从原文读),尾部补空格保持等长
    code = raw[:cut] + ' ' * (len(raw) - cut)
    return code, ''.join(masked)


def _pending_heredocs(code: str, masked: str) -> list:
    """找出一行里全部 heredoc 起点,返回 `[(终止符, 是否允许前导制表符)]`。

    在**遮罩**上定位 `<<`(字符串里的不算),再到**原文**上读终止符 —— `<<'EOF'` 的引号
    在遮罩里被抹掉了内容,只有原文里读得出名字。
    """
    found = []
    index = masked.find('<<')          # 逐个找起点
    # 一行里可能有多个 heredoc(`cat <<A <<B`),顺着找下去
    while index >= 0:
        end = index + 2                             # 跳过 `<<`
        # `<<<` 是 here-string(`grep <<< "$x"`),没有终止符
        if masked[end:end + 1] != '<':
            strip_tabs = code[end:end + 1] == '-'   # `<<-` 允许终止符带前导制表符
            # `<<-` 的名字从 `-` 之后开始
            if strip_tabs:
                end += 1
            # 跳过终止符前的空白,`<< EOF` 与 `<<EOF` 等价
            while code[end:end + 1] in (' ', '\t'):
                end += 1
            name = _read_name(code, end)        # 读不出名字说明这不是 heredoc
            # 读不出名字说明这不是 heredoc(如算术左移 `$((1 << 3))`)
            if name:
                found.append((name, strip_tabs))
        index = masked.find('<<', index + 2)   # 从当前起点之后继续找
    return found


def _read_name(code: str, index: int) -> str:
    """从原文的 index 处读一个 heredoc 终止符名;读不出时返回空串。

    裸名字必须字母或下划线开头 —— 算术左移 `$((1 << 3))` 里的 `3` 就是在这一步挡掉的。
    """
    # 带引号的终止符:引号里的字面量就是名字,引号本身不算
    if code[index:index + 1] in ('"', "'"):
        stop = code.find(code[index], index + 1)   # 收尾引号的位置
        # 引号没闭合:名字读不出来,宁可不认这个 heredoc
        if stop == -1:
            return ''
        return code[index + 1:stop]
    match = _WORD.match(code, index)   # 裸名字:字母或下划线开头
    # 裸名字必须字母或下划线开头 —— 算术左移 `$((1 << 3))` 里的 `3` 在这里被挡掉
    return match.group() if match else ''


def _code_lines(raw_lines: list) -> list:
    """把整个文件扫成逐行的代码记录,heredoc 体整段剔出去。

    剔除是必须的,不是优化:`cat <<'PY'` 里嵌一整段 Python 时,里面的 `#` 会被当成 shell
    注释、`if` 会被当成 shell 条件,计数整体失真而**不报任何错**。
    """
    records = []
    pending = []
    quote = ''
    # 逐行走:heredoc 体只吃不记,代码行才过 `_scan_line`
    for offset, raw in enumerate(raw_lines):
        # 还在 heredoc 体里:整行都不是代码,只看它是不是终止符
        if pending:
            name, strip_tabs = pending[0]
            # `<<-` 的终止符可以带前导制表符;两边都 strip 是放宽,只会提前收尾(少吞行)
            probe = raw.lstrip('\t') if strip_tabs else raw
            # 命中终止符就弹出;后面还有待匹配的,继续等下一个
            if probe.strip() == name:
                pending.pop(0)
            continue
        code, masked, comment_col, quote = _scan_line(raw, quote)
        pending.extend(_pending_heredocs(code, masked))
        # 整行注释 = 注释起点之前只有空白;行尾注释不算(条件/循环/raise 只认独立整行)
        whole_line = comment_col is not None and not raw[:comment_col].strip()
        records.append(_CodeLine(offset + 1, masked, whole_line, comment_col is not None))
    return records


def _logical_lines(records: list) -> list:
    """把逐行记录按续行记号拼成逻辑语句,返回 `_LogicalLine` 列表(保持源码顺序)。

    空行与整行注释不参与拼接,也不切断上一条 —— 与 bash 的续行语义一致。
    """
    # 逐行攒:pieces 是拼出来的片段,starts 是各片段在拼接文本里的起点,rows 是对应行号
    lines = []
    pieces = []
    starts = []
    rows = []
    size = 0
    # 逐行走:续行记号把若干物理行粘成一条逻辑语句
    for record in records:
        # 空行与整行注释不是语句:跳过
        if not record.masked.strip():
            continue
        stripped = record.masked.rstrip()          # 去掉尾空白,好看续行记号
        # 行尾反斜杠是纯换行标记,拼接时去掉;`&&` 是条件摊平的依据,必须留下
        piece = stripped[:-1] if stripped.endswith('\\') else stripped
        # 记下这个片段在拼接文本里的起点,以及它对应的物理行号
        starts.append(size)
        rows.append(record.row)
        pieces.append(piece)
        size += len(piece) + 1
        # 行尾不是续行记号 ⇒ 一条逻辑语句到此为止
        if not stripped.endswith(_CONTINUATION):
            lines.append(_LogicalLine(' '.join(pieces), tuple(starts), tuple(rows)))
            pieces, starts, rows, size = [], [], [], 0
    # 文件以续行记号结尾:最后半条语句也要交出去,不能静默丢掉
    if pieces:
        lines.append(_LogicalLine(' '.join(pieces), tuple(starts), tuple(rows)))
    return lines


def _row_at(line: _LogicalLine, offset: int) -> int:
    """把逻辑行里的字符偏移映射回物理行号。

    片段按下标升序排,最后一个「起点不超过 offset」的片段就是它所在的物理行。
    """
    row = line.part_rows[0]
    # 顺着片段走,越过 offset 就停
    for start, candidate in zip(line.part_starts, line.part_rows):
        # 这一段的起点已经越过 offset,上一段才是它所在的物理行
        if start > offset:
            break
        row = candidate
    return row


def _command_words(text: str) -> list:
    """找出每个命令的首词,返回 `[(下标, 词)]`。

    只有**命令位置**上的词才算关键字:命令位置 = 行首,或 `;` / `&&` / `||` / `|` / `(` /
    `{` / `then` / `do` / `else` 之后。不判位置的话,`notify` 里的 `if` 也会被当成条件。
    """
    starts = [0]
    starts.extend(match.end() for match in _OPERATOR.finditer(text))
    starts.extend(match.end() for match in _WORD.finditer(text) if match.group() in _BLOCK_WORDS)
    found = {}
    # 每个命令位置只取它后面第一个词,取不到就是没有首词
    for offset in sorted(starts):
        head = offset + len(text[offset:]) - len(text[offset:].lstrip())   # 跳过位置与首词间的空白
        match = _WORD.match(text, head)   # 首词必须是完整的词,不是词的一部分
        # 命令位置上不是词(如 `[`、`"`、路径):这个位置没有首词
        if match:
            found[match.start()] = match.group()
    return sorted(found.items())


def _condition_fact(line: _LogicalLine, offset: int, word: str) -> ConditionFact:
    """把一条 `if` / `elif` 摊成各个子条件所在的行号。

    同一行上出现两个子条件就记两次,保留在 `operand_lines` 里作诊断。
    2026-10-18 起注释规则只看条件起始行。条件体到第一个命令位置上的 `then` 为止。
    """
    head = offset + len(word)   # 条件体从关键字之后开始
    stop = len(line.text)       # 没有 `then` 时条件体取到行尾
    # 找条件体的终点:`then` 之后就是命令体,不再算条件
    for later_at, later_word in _command_words(line.text):
        # 只认 `then` 这个词
        if later_word != 'then':
            continue
        # `then` 可能另起一行,那时它不在本逻辑行里,条件体就取到行尾
        if later_at >= head:
            stop = later_at
            break
    body = line.text[head:stop]
    cuts = [0]
    # 每个 `&&` / `||` 切一刀;片段按 (前一段终点, 后一段起点) 两两配对
    for match in _CONDITION_OPERATOR.finditer(body):
        cuts.extend((match.start(), match.end()))
    cuts.append(len(body))
    rows = []
    # 逐片段定位:一个片段就是一个子条件
    for begin, end in zip(cuts[0::2], cuts[1::2]):
        piece = body[begin:end]
        # 被 `&&` 拆出来的空片段(如 `cmd &&` 后直接换行)不是一个判据
        if not piece.strip():
            continue
        # 记在判据自己那一行上;同一物理行出现两个判据时会有重复行号
        rows.append(_row_at(line, head + begin + len(piece) - len(piece.lstrip())))
    return ConditionFact(line=_row_at(line, offset), operand_lines=tuple(rows))


def _control_facts(lines: list) -> tuple:
    """一次遍历产出 `(条件事实, 循环事实, 抛失败态事实)` 三个列表。

    合成一次而不是三遍,不只是省时间:`_command_words` 是这三个事实唯一的依据,分三处算就
    有三份实现分叉的余地,而分叉时两个数都不报错。循环与失败态的注释要写「为什么必须循环」
    「什么前提被破坏」,一行放不下,所以 `accepts_inline` 一律 False。
    """
    conditions = []
    loops = []
    raises = []
    # 逐条逻辑语句看:每个命令位置都可能是一个关键字
    for line in lines:
        # 一条逻辑语句上可能有多个命令位置(`foo; if ...`),逐个判
        for offset, word in _command_words(line.text):
            # if / elif:摊平子条件,记各自的行号
            if word in _CONDITION_WORDS:
                conditions.append(_condition_fact(line, offset, word))
            # 循环:标签只留关键字 —— 报告里循环那条根本不显示标签,别造没人看的字
            if word in _LOOP_WORDS:
                loops.append(SimpleFact(line=_row_at(line, offset), label=word,
                                        accepts_inline=False))
            # exit:bash 里唯一读得出数值的抛失败态
            if word == 'exit':
                # 关键字之后可能有空白,`match` 从位置 0 起匹配,必须先 lstrip
                match = _EXIT_CODE.match(line.text[offset + len(word):].lstrip())
                # 只有字面非零码才算;`exit` / `exit $?` 读不出数值,不记
                if match:
                    raises.append(SimpleFact(line=_row_at(line, offset),
                                             label=f'exit {match.group()}',
                                             accepts_inline=False))
    return conditions, loops, raises


def _flat_runs(records: list, whole_line_rows: set) -> list:
    """找「连续一长串语句、一行注释都没有」的平铺段,返回 `[(段首行号, 段长度)]`。

    只记每段的**最终长度**,不比阈值 —— 阈值属于规则引擎(`core.rules.evaluate` 判 `length > max_flat`)。
    """
    runs = []
    run = []
    # 逐行走:注释行与控制流把长段切开,其余的行攒进当前段
    for record in records:
        # 空行不是语句:与规则口径一致,它只是空白
        if not record.masked.strip():
            continue
        # 上一行是独立注释 ⇒ 这一段已被说明,收口重算;本行仍是新段的第一条语句
        if record.row - 1 in whole_line_rows:
            runs.append(run)
            run = [record.row]
            continue
        # 控制流与函数定义自带结构提示,不算平铺,并且切断当前段
        if _starts_structure(record.masked):
            runs.append(run)
            run = []
            continue
        run.append(record.row)
    runs.append(run)
    # 空段(刚被切断)不算;段长交给规则引擎比阈值,这里只负责把它记全
    return [(segment[0], len(segment)) for segment in runs if segment]


def _starts_structure(masked: str) -> bool:
    """这一行是不是控制流、函数定义或 case 臂的边界 —— 是就不算平铺语句。

    控制流与定义自带结构提示,把整整一屏 `if` / `fi` / `done` 算进平铺段是纯噪声。
    """
    stripped = masked.strip()   # 去掉首尾空白,下面按第一个字符判结构
    # `{` 与 `}` 单独成行时没有首词,但它们确实是块边界
    if stripped[:1] in ('{', '}'):
        return True
    # case 分支臂的边界有两种写法:`;;` 单独成行,或 `pattern) cmd ;;` 挤在一行。
    # 不认的话一个多分支 case 会被拼成一条十几条的平铺段(实测 conda 的 shell 钩子与
    # flatbuffers 的 build_apk.sh 都这样被误报)—— 而分支臂自带结构提示,正是平铺段的反面
    if stripped.startswith((';;', ';&')):
        return True
    # 臂体多行时以 `;;` 收尾,同样算边界
    if stripped.endswith((';;', ';&')):
        return True
    # `name() {` / `function name`:定义本身不是平铺语句
    if _FUNCTION_DEF.match(stripped):
        return True
    words = _command_words(masked)   # 首词是控制流关键字(if / fi / for / done …)也算结构提示
    return bool(words) and words[0][1] in _STRUCTURE_WORDS
