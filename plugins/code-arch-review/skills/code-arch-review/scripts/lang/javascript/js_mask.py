"""把源码抹成骨架:字符串与注释的内容换成空格,代码原样留着。

**为什么必须抹而不是直接拿正则扫**:`const u = 'http://x'` 里的 `//` 不是注释起点,
正则字面量里的斜杠也一样,`<div>https://x</div>` 在 JSX 里同样如此。不抹掉就会凭空多出
注释行 —— 而注释计数只加不减,「上方缺注释」这条会被静默抵消,于是闸零违规、
代码却没有注释。

**为什么不是「一行一状态」的简易状态机**:那样处理不了两种嵌套,而两种都在真实
代码里很常见。这一层的代价是**静默的**:状态机卡在字符串里,后面成片的真代码会被
当成字符串内容抹掉,那一片就再也报不出任何东西,而报告上完全看不出来(实测
`client/script.js` 因此丢掉 30 行、`sdk/internal/utils/path.js` 丢掉 22 行)。

* **嵌套模板串**:`` `${items.map((x) => `...`)}` `` 里那个反引号属于内层模板,
  简易状态机会把它当成外层的收尾,从此错位。
* **正则字面量**:`/[^&']+/` 里那个引号只是字符类里的一个字符,却能开出一个
  永不闭合的「字符串」。

所以这里是一个带**状态栈**的单遍扫描:字符串、模板串、`${}` 插值、正则、块注释
各占一帧,只有栈顶那一帧能决定下一个字符怎么吃。抹出来的骨架与原文字符数严格相等,
后面的正则与列号切片都靠这一点。
"""

import re

# 状态帧的种类:字符串、模板串正文、插值里的代码、正则字面量、块注释
_TEXT = 'text'          # 引号字符串内部
_TMPL = 'tmpl'          # 模板串的正文部分
_CODE = 'code'          # `${ ... }` 里的代码部分
_REGEX = 'regex'        # 正则字面量内部
_BLOCK = 'block'        # 块注释内部

# 出现这些字符之后的那颗斜杠是**除号**,不是正则的起点
_DIVISION_AFTER = frozenset(
    ')]}' + 'abcdefghijklmnopqrstuvwxyz'
    + 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' + '0123456789_$'
)

# 这些关键字后面那颗斜杠一定是正则:`return /re/.test(x)`
_REGEX_KEYWORDS = frozenset({
    'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void',
    'case', 'do', 'else', 'yield', 'await',
})

# 取骨架行末尾那个完整的标识符,用来判「关键字后面跟斜杠」
_TRAILING_WORD_RE = re.compile(r'([A-Za-z_$][\w$]*)$')


def mask_source(text):
    """逐行抹掉字符串内容与注释,同时记下哪些行有注释。

    抹的是**内容**而不是整行:骨架行要留着语法形状,后面的正则才能继续用。
    两个集合都要算 —— 行尾注释与整行注释在规则里的待遇不同,合起来就分不开了。

    Args:
        text: 整个文件的源码。

    Returns:
        `(骨架行列表, 注释行号集合, 独立整行注释的行号集合)`。
    """
    masked_lines = []
    comment_rows = set()                        # 出现过注释的行
    whole_rows = set()                          # 其中整行都是注释的行
    stack = []                                  # 跨行状态:字符串、模板串、块注释都可能跨行
    # 逐行走状态机,状态带着走到下一行
    for row, raw in enumerate(text.split('\n'), start=1):
        masked, has_comment, stack = mask_line(raw, stack)
        masked_lines.append(masked)
        # 这一行没碰到注释就没什么可记的
        if not has_comment:
            continue
        comment_rows.add(row)
        # 整行注释:骨架里一个字都不剩,但这一行确实有注释
        if not masked.strip():
            whole_rows.add(row)
    return masked_lines, comment_rows, whole_rows


def mask_line(raw, stack):
    """抹掉一行里的非代码内容,只留骨架。

    循环每走一步只看**栈顶那一帧**:在字符串里就只认转义与闭合引号,在模板串里
    就还要认 `${`,在代码里才认注释与引号。帧的种类见文件头的说明。

    Args:
        raw: 整行原文(不含换行)。
        stack: 上一行遗留的状态栈;首行传空列表。

    Returns:
        `(骨架行, 这一行有没有注释, 新的状态栈)`。
    """
    masked = []
    frames = list(stack)                                # 复制一份再改,调用方的栈不受影响
    # 从块注释里续下来的行:这一行一个字都没写进代码,但它确实带着注释
    has_comment = bool(frames) and frames[-1][0] == _BLOCK
    index = 0
    # 逐字符推进:换行不在这一行里,所以循环内的位置都是行内位置
    while index < len(raw):
        char = raw[index]
        top = frames[-1][0] if frames else ''           # 栈空表示在最外层,按代码处理
        # 块注释里:只有 `*/` 能让状态回到上一层
        if top == _BLOCK:
            index = _eat_block(raw, index, masked, frames)      # 位置由它推进
            continue
        # 字符串里:转义与闭合引号都要认
        if top == _TEXT:
            index = _eat_text(raw, index, masked, frames)       # 位置由它推进
            continue
        # 模板串正文:转义、收尾的反引号、以及插值的 `${`
        if top == _TMPL:
            index = _eat_template(raw, index, masked, frames)   # 位置由它推进
            continue
        # 正则字面量:转义、字符类、收尾的斜杠
        if top == _REGEX:
            index = _eat_regex(raw, index, masked, frames)      # 位置由它推进
            continue
        # 以下都是「在代码里」(`${}` 里的代码与最外层一样地扫)
        index, has_comment = _eat_code(raw, index, masked, frames, has_comment)
    return ''.join(masked), has_comment, frames


def _eat_code(raw, index, masked, frames, has_comment):
    """代码里的一个字符:可能开出一段注释、字符串、模板串或正则。

    `${}` 里的代码也走这里,区别只在于它多一层花括号计数 —— 数到 0 就弹回模板串。

    Args:
        raw: 整行原文。
        index: 当前位置。
        masked: 已产出的骨架片段。
        frames: 状态栈,函数会就地增删。
        has_comment: 到目前为止这一行有没有出现注释。

    Returns:
        `(新位置, 新的 has_comment)`。
    """
    char = raw[index]
    # 行注释:这一行剩下的都是注释,骨架到此为止
    if raw.startswith('//', index):
        return len(raw), True
    # 块注释开始
    if raw.startswith('/*', index):
        frames.append([_BLOCK])
        masked.extend('  ')
        return index + 2, True
    # 引号开始(单双引号都是普通字符串)
    if char in '"\'`':
        frames.append([_TMPL if char == '`' else _TEXT, char])
        masked.append(' ')
        return index + 1, has_comment
    # 插值里的花括号要计数:数回 0 才是插值结束
    if char == '{':
        _bump_brace(frames, 1)
        masked.append(char)
        return index + 1, has_comment
    # 闭合花括号同理,数回 0 时弹回模板串
    if char == '}':
        closed = _bump_brace(frames, -1)                # 它是不是插值的收尾
        masked.append(' ' if closed else char)          # 是就跟着 `${` 一起抹掉,保住括号配平
        return index + 1, has_comment
    # 斜杠:看着像正则就开一段正则,否则是除号,原样留着
    if (
        # 这一格是斜杠
        char == '/'
        # 而且它前面的位置该出现一个表达式
        and _starts_regex(masked)
    ):
        frames.append([_REGEX, False])
        masked.append(' ')                              # 正则内容不进骨架
        return index + 1, has_comment
    masked.append(char)                                 # 普通代码字符原样留着
    return index + 1, has_comment                       # 位置前进一格


def _bump_brace(frames, step):
    """给插值里的花括号计数;数回 0 就弹掉这一层插值。

    只有栈顶是插值时才有计数器 —— 最外层的花括号属于语法结构,不归这里管。
    返回值告诉调用方这一格是不是插值的收尾:是的话它必须跟着 `${` 一起抹掉,
    否则骨架里会多出一个无主的 `}` —— 而骨架的括号配平是后面判「在不在函数里」
    的唯一依据,少一个 `{` 会让整个文件的深度一路偏负,顶层的 `if` 就再也认不出来。

    Args:
        frames: 状态栈,函数会就地改动。
        step: `{` 传 1,`}` 传 -1。

    Returns:
        这一格弹掉了插值的收尾帧给 True。
    """
    # 栈顶不是插值(或栈空)时什么都不做
    if (
        # 栈里一帧都没有
        not frames
        # 或者栈顶不是插值
        or frames[-1][0] != _CODE
    ):
        return False
    frames[-1][1] += step
    # 数回 0 说明这段插值写完了,回到模板串的正文
    if frames[-1][1] <= 0:
        frames.pop()
        return True
    return False


def _starts_regex(masked):
    """这颗斜杠是正则的起点还是除号。

    判据是**前一个有效字符**:只有表达式该出现的位置(`(`、`=`、`,` 之后)斜杠才是
    正则起点,跟在名字、`)`、`]` 后面的都是除号。

    单词结尾也是字母,所以还要单独认一遍关键字 —— 否则 `return /re/.test(x)` 里的
    `n` 会把那颗斜杠判成除号,正则内容不进骨架,里面若有个引号就会开出假字符串。

    Args:
        masked: 到目前为止的骨架片段。

    Returns:
        是正则起点给 True。
    """
    joined = ''.join(masked).rstrip()                   # 去掉行尾空白再判
    # 行首(前面什么都没有)按正则处理:`/re/.test(x)` 是常见写法
    if not joined:
        return True
    # 关键字后面那颗斜杠一定是正则:单词以字母收尾,不单独认就会被当成除号
    word = _TRAILING_WORD_RE.search(joined)
    if (
        # 末尾确实是一个完整单词
        word
        # 而且这个词是关键字
        and word.group(1) in _REGEX_KEYWORDS
    ):
        return True
    return joined[-1] not in _DIVISION_AFTER            # 其余看最后一个字符


def _eat_block(raw, index, masked, frames):
    """块注释里的一步:要么收掉 `*/`,要么再吃掉一个字符。

    收尾的两个字符一起抹掉是为了保住列对齐 —— 遮罩片段与被吃掉的原文必须等长,
    后面按列切片才不会错位。
    """
    # `*/` 是块注释唯一的出口
    if raw.startswith('*/', index):
        masked.extend('  ')
        frames.pop()
        return index + 2                                # 收尾的两个字符一起吃掉
    masked.append(' ')
    return index + 1                                    # 注释正文一次吃掉一个字符


def _eat_text(raw, index, masked, frames):
    """字符串里的一步:吃掉一个转义对,或在闭合引号处收尾。

    转义要单独处理:漏掉它,字符串里那个被转义的引号会被当成收尾,于是后面接着的
    `//` 变成注释行 —— 而注释计数只加不减,「上方缺注释」会被静默抵消。
    """
    char = raw[index]
    # 转义把后一个字符一起吞掉,`\'` 不结束字符串
    if char == '\\':
        masked.extend('  ')
        return index + 2                                # 转义符与被转义的那个字符一起吃掉
    masked.append(' ')
    # 见到同一个引号才是字符串结束
    if char == frames[-1][1]:
        frames.pop()
    return index + 1                                    # 字符串内容一次吃掉一个字符


def _eat_template(raw, index, masked, frames):
    """模板串正文里的一步:转义、收尾反引号,或插值的开头。

    插值那一步是这一层与「一行一状态机」的分水岭:压在栈上的插值帧记着花括号计数,
    里面还能再开一层模板串,`` `${items.map((x) => `...`)}` `` 这种嵌套才不会错位。
    """
    char = raw[index]
    # 转义把后一个字符一起吞掉,`` \\` `` 不结束模板串
    if char == '\\':
        masked.extend('  ')
        return index + 2                                # 转义符与被转义的那个字符一起吃掉
    # 反引号是模板串的收尾
    if char == '`':
        masked.append(' ')
        frames.pop()
        return index + 1                                # 收尾的反引号占一个字符
    # `${` 之后是代码,压一帧进去,花括号从这里开始计数
    if raw.startswith('${', index):
        masked.extend('  ')
        frames.append([_CODE, 0])
        return index + 2                                # `${` 两个字符一起吃掉
    masked.append(' ')
    return index + 1                                    # 模板正文一次吃掉一个字符


def _eat_regex(raw, index, masked, frames):
    """正则字面量里的一步:转义、字符类开合、收尾斜杠。

    字符类要单独跟:字符类里那个引号只是类中的一个字符,不认字符类边界的话它会开出
    一个永不闭合的字符串,后面整片代码都会被当成字符串抹掉 —— 而那是静默的。
    """
    char = raw[index]
    # 转义把后一个字符一起吞掉,`\\/` 不结束正则
    if char == '\\':
        masked.extend('  ')
        return index + 2                                # 转义符与被转义的那个字符一起吃掉
    # 字符类里的斜杠不是收尾:斜杠在字符类里只是一个普通字符
    if (
        # 这一格是左方括号
        char == '['
        # 而且还没进过字符类
        and not frames[-1][1]
    ):
        frames[-1][1] = True
        masked.append(' ')
        return index + 1                                # 进字符类的那个括号占一个字符
    # 字符类在 `]` 处结束
    if (
        # 这一格是右方括号
        char == ']'
        # 而且正待在字符类里
        and frames[-1][1]
    ):
        frames[-1][1] = False
        masked.append(' ')
        return index + 1                                # 出字符类的那个括号占一个字符
    masked.append(' ')
    # 字符类外的斜杠才是正则的收尾
    if (
        # 这一格是斜杠
        char == '/'
        # 而且不在字符类里
        and not frames[-1][1]
    ):
        frames.pop()
    return index + 1                                    # 正则正文一次吃掉一个字符
