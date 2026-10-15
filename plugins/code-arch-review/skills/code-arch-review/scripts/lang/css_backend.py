"""CSS 后端:纯手写扫描器,把样式表切成块并数出声明条数,不装任何依赖、不起子进程。

为什么手写而不找现成解析器:闸不许外部依赖,而 CSS 的块结构只有一层花括号 ——
难点不在语法树,在**哪些 `{` `}` `;` 不是结构**:字符串里的、注释里的、`url(...)`
里的、`@media (...)` 条件括号里的。`_mark_kinds()` 把这些一次标干净,后面所有扫描
只认代码字符,坑就只踩一次。

事实映射(与 Python 后端的差异):一个块 = 一个 `FunctionFact`,块内**直接**写的
`prop: value` 数进 `declaration_count`,块外还套着几层记在 `nesting_depth`;
`if` / 循环 / `return` / 文档注释这些 CSS 里不存在的东西一律留空。`is_public` 固定
填 False —— 于是 `no-docstring` 与 `many-kwargs` 在 CSS 上永远不会触发。
"""

from bisect import bisect_right
from dataclasses import dataclass

from core.model import BindingFact, FileFacts, FunctionFact
from core.text import comment_rows, whole_line_comment_rows

# 注册表按扩展名找后端;CSS 只有这一个后缀
EXTS = ('.css',)

# `_mark_kinds()` 的四种取值,后面所有结构判断只看 CODE
CODE = 0
STRING = 1
COMMENT = 2
ESCAPED = 3

# 括号配对表:先配平括号,括号里的分号与花括号才不会被当成结构
PAREN_STEP = {'(': 1, '[': 1, ')': -1, ']': -1}


@dataclass
class _Block:
    """扫描中攒出来的一个块(规则块或 at-rule 块),尾部的三项要等 `}` 才填得出。

    为什么可变:块头的名字在 `{` 处就知道了,但块尾行、块内行数与声明条数必须等
    配对的 `}` 出现才数得出来 —— 拆成两半反而要维护两份平行列表。
    """

    name: str          # 块头原文(选择器或 at-rule 条件),空白已归一、注释已去
    line: int          # 块头第一个代码字符所在行,1 基
    end_line: int      # 配对的 `}` 所在行,1 基
    body_lines: int    # 花括号之间内容的行数;空块为 0
    depth: int         # 块外还套了几层块;顶层 0,`@media { .a {} }` 里的 `.a` 为 1
    declarations: int  # 块内**直接**写的声明条数,不含嵌套子块里的
    head_start: int    # 块头在源码里的起始下标,顶层绑定要按它切选择器
    head_end: int      # 块头的结束下标,即 `{` 的位置


def _line_starts(source):
    """每行起始字符的下标,后面用它把字符下标换算成行号。"""
    # 每个换行之后就是新一行的起点;末尾那个换行不额外产生空行
    return [0] + [index + 1 for index, char in enumerate(source) if char == '\n']


def _line_of(starts, index):
    """字符下标 → 1 基行号(`bisect_right` 数的是「有几个行起点在这个下标之前」)。"""
    return bisect_right(starts, index)


def _string_end(source, start):
    """从开引号往后找出字符串的结束位置。

    两个次级坑:① 转义,`content: "a\\"b"` 中间那个引号不是结束(反斜杠吃掉下一个
    字符);② 坏字符串,CSS 的字符串不许跨行,一个落单的引号若一路吞到文件末尾,
    后面所有块结构就全丢了 —— 所以遇到换行就当它在本行收尾。
    """
    quote = source[start]
    index = start + 1                                 # 从开引号的下一个字符起走
    # 逐字符走,直到配对引号、转义或换行
    while index < len(source):
        # 反斜杠吃掉下一个字符:被吃掉的引号不结束字符串
        if source[index] == '\\':
            index += 2
            continue
        # 换行终止:坏字符串在行尾收尾,不让一个引号吞掉整份文件
        if source[index] == '\n':
            return index
        # 配对的引号:字符串在它之后结束
        if source[index] == quote:
            return index + 1                          # 越过闭引号,字符串到它为止
        index += 1
    # 走到文件末尾都没闭合:这个字符串一直到结尾都算字符串
    return len(source)


def _mark_kinds(source):
    """把每个字符标成代码 / 字符串 / 注释。

    这是整个后端唯一一次逐字符扫描:第 1 条坑(字符串里的 `}` 不是块结束)、第 2 条坑
    (注释里的 `{` `}` `;` 都不是代码)与第 7 条坑(转义序列)都在这里解决,别处不用再想。

    第 7 条坑是拿真实样式表对拍才暴露的:Tailwind 之类生成的选择器把类名里的标点转义,
    写出 `.before\\:content-\\[\\'\\'\\]` 这种块头 —— 那个 `'` 是**被转义的字符**,不是
    字符串的开引号。不认转义的话,它会开一个字符串并一路吞到下一个引号,整份文件后半段
    的块结构全丢(实测一个 2695 个花括号的文件只认出 2012 个,差的全在这一个坑里)。
    """
    kinds = [CODE] * len(source)          # 先全标成代码,下面把注释段与字符串段改掉
    index = 0
    # 一次线性扫描:注释、字符串与转义序列整段标掉,剩下的都是代码
    while index < len(source):
        # 转义序列:被转义的字符属于标识符,不是结构也不是引号
        if source[index] == '\\':
            end = min(index + 2, len(source))         # 末尾那个落单的反斜杠只吃自己
            kinds[index:end] = [ESCAPED] * (end - index)
            index = end
            continue
        # 注释块:整段标成 COMMENT,不闭合就一直标到文件末尾
        if source.startswith('/*', index):
            close = source.find('*/', index + 2)      # 找配对的 `*/`,没有就是到文件末尾
            end = len(source) if close < 0 else close + 2   # 注释段的下标范围
            kinds[index:end] = [COMMENT] * (end - index)
            index = end
            continue
        # 字符串:`"` 与 `'` 都要认,内部还有转义
        if source[index] in ('"', "'"):
            end = _string_end(source, index)          # 字符串整段的下标范围
            kinds[index:end] = [STRING] * (end - index)
            index = end
            continue
        index += 1
    return kinds


def _normalize(text):
    """归一化块头:连续空白压成一个空格并去掉首尾空白,同一个选择器只留一个名字。"""
    return ' '.join(text.split())


def _head_text(source, kinds, start, end):
    """块头原文,**去掉注释**。

    为什么必须去:`.a { }` 上方紧贴一行 `/* 说明 */` 时,块头的起点在上一处分界
    (`}` 或 `;`)之后,注释会被一起切进来 —— 不去掉的话同一个选择器在有注释与没注释
    时算出两个名字,`duplicate-toplevel` 就永远抓不到它。注释换成**一个空格**而不是
    直接删:注释在 CSS 里是 token 边界(`a/*x*/b` 是两个 token),删成 `ab` 会改语义。
    """
    pieces = []
    index = start
    # 逐字符抄,遇到注释段就换成一个空格
    while index < end:
        # 注释整段跳过
        if kinds[index] == COMMENT:
            # 整段注释一起吃,不要一个字符一个字符地补空格
            while index < end and kinds[index] == COMMENT:
                index += 1
            pieces.append(' ')
            continue
        pieces.append(source[index])
        index += 1
    return ''.join(pieces)


def _module_doc(source):
    """文件开头那段 `/* ... */` 注释的正文;没有则 None。

    判据与 Python 的模块 docstring 同构:它之前**不能有代码**,空行不算代码,而
    `@charset` / `@import` 算 —— 注释写在它们后面就不再是「模块说明」,而是那条语句
    的旁注。只取第一段:紧挨着的第二段已经是普通注释,Python 那边同样只认第一条字符串。
    返回值是注释正文(去掉首尾空白,多行用 `\\n`);文件不以注释块开头时返回 None。
    """
    # 注释块之前只允许空白:第一个非空白字符的位置就是判据
    index = next((item for item, char in enumerate(source) if not char.isspace()), len(source))
    # 开头不是注释块:要么是代码,要么整个文件都是空白
    if not source.startswith('/*', index):
        return None
    close = source.find('*/', index + 2)          # 找配对的 `*/`
    end = len(source) if close < 0 else close     # 不闭合的注释一直到文件末尾
    return source[index + 2:end].strip()


def _first_code(source, kinds, start, end):
    """`[start, end)` 里第一个非空白代码字符的下标;没有则 -1。

    块头行号取它:选择器上方单独一行的注释不属于块头,否则同一个选择器会因为
    注释写法不同而报在不同行上,那种噪声没法排查。
    """
    # 注释、字符串与空白都不是块头的第一个字符
    return next((item for item in range(start, end)
                 if kinds[item] == CODE and not source[item].isspace()), -1)


def _edge(source, span):
    """在 span 这个下标区间里找第一个非空白字符;走到头都没有则 -1。

    区间由调用方给出**方向**:顺走取块内首字符、倒走取块内尾字符,一个函数就够。
    """
    # 非空白字符就是块内内容的边界
    return next((item for item in span if not source[item].isspace()), -1)


def _body_lines(source, starts, brace, close):
    """花括号之间内容的行数;空块(含只写了注释的块)为 0。

    量的是一行式规则块 `.a { color: red }` 也要算成 1 行 —— 报「块有多大」时,
    把它算成 0 行会让最紧凑的写法反而显得最轻。
    """
    first = _edge(source, range(brace + 1, close))    # 块内第一个非空白字符
    # 花括号之间什么都没有:空块没有内容行
    if first < 0:
        return 0
    last = _edge(source, range(close - 1, brace, -1))  # 倒着走,取块内最后一个非空白字符
    # 首尾同行的一行式规则块(`.a { color: red }`)算 1 行
    return _line_of(starts, last) - _line_of(starts, first) + 1


def _is_declaration(source, kinds, start, end):
    """这一段文本是不是一条声明(`prop: value`)—— 判据是括号之外有一个冒号。

    第 3 条坑:`url(data:image/svg+xml;base64,...)` 的冒号与分号都在括号里,那是值的
    一部分,既不是 `prop:` 的分界,也不是声明的分界。
    """
    depth = 0
    index = start
    # 逐字符找括号之外的冒号
    while index < end:
        # 字符串与注释里的括号是字面量,不改变括号深度
        if kinds[index] == CODE:
            char = source[index]
            # 冒号:只有括号之外的才是 `prop:` 的分界
            if char == ':':
                # 命中:这一段带顶层冒号就是一条声明
                if depth == 0:
                    return True
            # 括号:进出来回都用它,好在括号不会嵌套太深
            elif char in PAREN_STEP:
                depth += PAREN_STEP[char]
        index += 1
    return False


def _count_declaration(source, kinds, levels, end):
    """把当前这一层攒下的那段文本判成声明,是就记到这一层的计数上。

    `;` 与 `}` 都会调它:块里最后一条声明常常不带分号,那时只有闭合的 `}` 能叫停它。
    """
    level_start, declarations = levels[-1]
    # 顶层不在任何块里:那里的 `;` 属于 `@import url(...);` 这类语句(第 5 条坑)
    if len(levels) < 2:
        return
    # 这一段带顶层冒号 ⇒ 是一条声明
    if _is_declaration(source, kinds, level_start, end):
        levels[-1][1] = declarations + 1


def _make_block(source, kinds, starts, levels, brace):
    """在 `{` 处造一个块:块头是这一层从上个分界到这里的文本。

    多行选择器以最后一行的 `{` 结束,但名字与行号都从第一行算起。
    """
    head_start = levels[-1][0]
    # 块头行号取第一个代码字符的行 —— 压在上方的注释行不算块头
    hit = _first_code(source, kinds, head_start, brace)
    # 块头整段是注释或空白(源码多打了一个 `{`)时退化成 `{` 自己那一行
    if hit < 0:
        hit = brace
    # 名字用原文归一化,并与选择器拆分共用同一套去注释口径
    name = _normalize(_head_text(source, kinds, head_start, brace))
    return _Block(name=name, line=_line_of(starts, hit), end_line=_line_of(starts, brace),
                  body_lines=0, depth=len(levels) - 1, declarations=0,
                  head_start=head_start, head_end=brace)


def _close_block(source, kinds, starts, levels, open_blocks, brace):
    """在 `}` 处闭合一个块:补数最后一条声明,再填块尾行与块内行数。

    第 6 条坑:`}` 之后必须把父层的「当前语句起点」挪到它后面 —— 否则
    `.a { color: red } .b { color: blue }` 会被当成一个块,第二段选择器变成第一段的尾巴。
    """
    # 多出来的 `}`(源码本身不平衡):没有块可闭合,把这一层重新起头就行
    if not open_blocks:
        levels[-1][0] = brace + 1
        return
    # 块尾那条声明通常不带分号,闭合时要再数一次
    _count_declaration(source, kinds, levels, brace)
    block = open_blocks.pop()                         # 最内层的那个块就是被闭合的块
    # 声明条数攒在这一层上,块头到块尾的跨度就是它的
    block.declarations = levels.pop()[1]
    block.end_line = _line_of(starts, brace)
    block.body_lines = _body_lines(source, starts, block.head_end, brace)
    # 父层的下一段从这里重新起算
    levels[-1][0] = brace + 1


def _seal_unclosed(source, starts, levels, open_blocks, total_lines):
    """给源码末尾没闭合的块兜底(少打了一个 `}`)。

    不兜底的话这些块的块尾会停在块头行、块内行数算成负数 —— 宁可给出「到文件末尾
    为止」的保守事实,也不要给出错的事实。
    """
    # 从最内层往外收,每层都补齐块尾与块内行数
    while open_blocks:
        block = open_blocks.pop()                     # 没闭合的块按从内到外的顺序收
        block.declarations = levels.pop()[1]
        block.end_line = total_lines
        block.body_lines = _body_lines(source, starts, block.head_end, len(source))


def _blocks(source, kinds, starts, total_lines):
    """切出全部块(规则块与 at-rule 块),按文档顺序。

    只认**代码字符**上的花括号,而且要求括号已配平 —— 第 4 条坑:`@media (min-width:
    600px) {` 里括号必须先配平,否则条件括号里的花括号会让块边界算错。无花括号的
    at-rule(第 5 条)靠分号那条分支自然跳过,不会被当成块的开始。
    """
    blocks = []
    open_blocks = []
    # 每层一个 `[当前语句/块头起点, 本层已数到的声明条数]`,栈底是文件顶层
    levels = [[0, 0]]
    # 括号深度:括号里的 `;` 是值的一部分,不是声明的分界
    depth = 0
    index = 0
    # 一次线性扫描,只处理代码字符(第 1、2 条坑已由 `_mark_kinds()` 解决)
    while index < len(source):
        # 字符串与注释里的字符不是结构
        if kinds[index] != CODE:
            index += 1
            continue
        char = source[index]
        # 括号配对要先于花括号(第 4 条坑)
        if char in PAREN_STEP:
            depth += PAREN_STEP[char]
            index += 1
            continue
        # 分号:只有括号之外的才是声明或语句的分界(第 3、5 条坑)
        if char == ';':
            # 括号里的分号是值的一部分
            if depth == 0:
                _count_declaration(source, kinds, levels, index)
                levels[-1][0] = index + 1
            index += 1
            continue
        # 花括号:同样只在括号之外才是块边界
        if char in '{}':
            # 括号里出现的花括号(`url()` 里的 svg 之类)不是结构
            if depth == 0:
                # `{` 开一个块:它进两张表,blocks 保顺序、open_blocks 管闭合
                if char == '{':
                    block = _make_block(source, kinds, starts, levels, index)  # 块头到 `{` 为止
                    blocks.append(block)
                    open_blocks.append(block)
                    levels.append([index + 1, 0])
                # `}` 闭合最内层的那个块
                else:
                    _close_block(source, kinds, starts, levels, open_blocks, index)
        index += 1
    _seal_unclosed(source, starts, levels, open_blocks, total_lines)
    return blocks


def _selector_bindings(blocks):
    """顶层规则块 → 绑定事实,供 `duplicate-toplevel` 判重。一个块一条,名字是整个块头。

    只认顶层、且只认规则块:`@media` 里的 `.a` 是**条件生效**的定义,不是这个模块顶层的
    定义(与 Python 后端只认 `Module.body` 直接子节点同理);at-rule 的块头也不是选择器。

    🔴 口径是**整个块头**,不是逗号拆开的一个个选择器(2026-10-15 实测定的)。曾经按
    「每个选择器一条」实现,`.a, .b { }` 后面再单独出现 `.b { }` 就被判成「同一个名字
    定义了两次」—— 可那是选择器列表与单条规则并存,不是重复定义,方向错了。本机 180 个
    真实 CSS 的命中数对比:逗号拆 5048 处(91 个文件)、整块头 867 处(42 个文件);后者
    剩下的确实都是「同一个块头出现两次」,正是这条规则要抓的「grep 与编辑器跳转都指向
    第一份」。真要再按逗号拆,注意 `:not(.a, .b)` 的逗号在括号里、`[data-x="a,b"]` 的
    在字符串里,只有括号与字符串之外的逗号才是分隔符。
    """
    bindings = []
    # 按文档顺序过一遍块,只挑顶层规则块
    for block in blocks:
        # 嵌套块(`@media` 里、规则块里)不算模块顶层定义
        if block.depth != 0:
            continue
        # at-rule 的块头不是选择器,判「同一个选择器定义了两次」时不该算它
        if block.name.startswith('@'):
            continue
        bindings.append(BindingFact(name=block.name, kind='selector', line=block.line,
                                    references_self=False))
    return bindings


def _function_fact(block):
    """把一个块翻成一个 `FunctionFact`。

    CSS 没有参数、不是类、也没有文档约定,所以除位置与两个度量之外的字段一律留默认值:
    留空即「这门语言上没有这件事」,规则引擎那边对应几条永远不触发。
    """
    return FunctionFact(name=block.name, line=block.line, end_line=block.end_line,
                        body_lines=block.body_lines, params=(), is_public=False,
                        is_class=False, doc=None, nesting_depth=block.depth,
                        declaration_count=block.declarations)


def parse(path):
    """把一份 CSS 文件解析成事实。

    块的边界由 `_blocks()` 一次扫描定出来,这里只做三件翻译:块 → `FunctionFact`、
    顶层选择器 → `BindingFact`、注释行 → 覆盖率用的行号集合。

    Args:
        path: `.css` 文件路径。

    Returns:
        该文件的事实。只填 CSS 上成立的那几项;`conditions` / `loops` / `raises` 这类
        构造 CSS 里没有对应物,一律留空。
    """
    source = path.read_text(encoding='utf-8')     # 带中文注释的样式表是常态,别用 locale 编码
    lines = source.splitlines()                   # 行号的口径在这里定死,后面都按它数
    # 行号换算与字符分类各做一遍,后面所有扫描都吃这两张表
    starts = _line_starts(source)
    kinds = _mark_kinds(source)                   # 逐字符分类:代码 / 字符串 / 注释
    blocks = _blocks(source, kinds, starts, len(lines))   # 切块:两张事实表都由它翻译
    # 每个块一个函数事实:CSS 的「函数」就是规则块与 at-rule 块
    functions = [_function_fact(block) for block in blocks]
    # 顶层块进 bindings,判「同一个块头定义了两遍」
    bindings = _selector_bindings(blocks)
    return FileFacts(path=path, language='css', total_lines=len(lines),
                     comment_rows=comment_rows(lines, None, '/*', '*/'),
                     whole_line_rows=whole_line_comment_rows(lines, None, '/*', '*/'),
                     module_doc=_module_doc(source),
                     functions=functions, bindings=bindings, heuristic=False)


def parse_many(paths):
    """批量解析。单文件后端里它只是逐个调用,存在的意义是与多文件后端同签名。

    注册表要求每个后端都有这个入口(JS 那边是一次 `node` 进程解析整批),所以这里
    哪怕只是循环一遍也必须存在,否则整门语言会被当成「后端没写完」跳过。

    Args:
        paths: 文件路径列表。

    Returns:
        `FileFacts` 列表;读不动或解码不了的文件跳过,不让一个坏文件拖垮整批 ——
        差额由调用方按文件数察觉,不是静默吞掉。
    """
    facts = []
    # 逐个解析,坏文件跳过而不是中断整批
    for path in paths:
        # 单个文件读不动不该让整批扫描失败
        try:
            facts.append(parse(path))
        except (OSError, UnicodeDecodeError):
            continue
    return facts
