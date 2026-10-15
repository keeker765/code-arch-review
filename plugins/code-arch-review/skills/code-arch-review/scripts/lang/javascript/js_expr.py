"""表达式形状:从骨架行判断一个右侧表达式「算不算算出来的」。

这一层存在的理由是**两档必须同口径**。精确档用 `isComputed` 看的是 TypeScript 节点的
种类,判据是「最外层是什么」;启发式手上只有一行文本,如果改成「出现过运算符就算」,
`ctx.starts[row - 1]`(减号在下标里)与 `[...runs.values()]`(括号在数组字面量里)
就会被稳定多报 —— 而那些多报的条目长得和真违规一模一样,读者分不出来。

所以这里逐字符走一遍,只在**括号深度为 0** 的地方认运算符,并把字面量、取值链、
箭头函数这三类最外层形状挡掉。字符串与注释在骨架行里已经抹成空格,可以放心逐字符扫。

已知的两处偏差(见 `references/languages.md` 的 JS 一节):模板串的插值在骨架里被
抹掉了,跨行的表达式又只看得到第一行 —— 这两处的右侧拿不到判据,会漏报。
"""

import re

# 顶层运算符:出现这些字符说明右侧是算出来的。字符串与注释在骨架里已经抹掉了,
# 所以逐字符扫是安全的 —— 但**只在括号深度为 0 的地方算数**(见 looks_computed)。
_OPERATOR_CHARS = frozenset('+-*/%<>=!?&|')

# 取值链的开头:裸名字或 `this`
_BARE_NAME_RE = re.compile(r'(?:this|[A-Za-z_$][\w$]*)')

# 取值链的一段:`.名字` 或 `[下标]`,接在裸名字或 `this` 后面
_PROPERTY_STEP_RE = re.compile(r'\.[A-Za-z_$#][\w$]*')

# 前缀一元运算符:它们改变的是写法,不是「这个值怎么来的」
_UNARY_WORDS = ('typeof ', 'void ', 'delete ')


def looks_computed(value):
    """右侧文本是不是「算出来的」——与精确档的 `isComputed` 同口径。

    判的是**最外层形状**,不是「出现过运算符」。这一条正是两档分叉的地方:

    * `ctx.starts[row - 1]` —— 减号在下标里面,精确档按「取值」处理,不算算出来的;
    * `[...runs.values()]` —— 括号在数组字面量里面,精确档只看最外层节点,也不算。

    只扫字符会让启发式在这两处稳定多报,而多报的条目长得和真违规一模一样,
    读者分不出来。反过来,取值与字面量一律不算:变量名说得出「是什么」的,
    就不该再要求一行注释解释「怎么来的」。

    Args:
        value: 赋值的右侧文本,或 `return` 后面的表达式(骨架行,字符串已抹成空格)。

    Returns:
        算出来的给 True。
    """
    text = _lead_value(value)                           # 切到第一条语句的那个表达式
    # 切完为空说明右侧本来就什么都没有
    if not text:
        return False
    # 最外层是字面量或整条取值链:精确档都不认它们是「算出来的」
    if _is_plain_value(text):
        return False
    # 以 `)` 收尾的是调用或 new:值取决于被调方的契约
    if text.endswith(')'):
        return True
    # await:值取决于异步结果,不是眼前的字面量
    if _is_await(text):
        return True
    # 箭头函数:精确档只认节点种类,箭头不在清单里,所以右边什么都不算
    if _has_top_arrow(text):
        return False
    stripped = _strip_unary(text)                       # 剥掉前缀一元运算符
    # 剥完为空说明右侧只有一个一元运算符,那本身也不是算式
    if not stripped:
        return False
    trimmed = _strip_postfix(stripped)                  # 后缀自增自减同样是「一个值」
    # 剥完为空说明整段只剩一个自增自减,那也不是算式
    if not trimmed:
        return False
    return _has_top_operator(trimmed)


def _lead_value(value):
    """去掉末尾分号与最外层括号,留下能用来判形状的那段文本。

    先切到第一个顶层 `;` 或 `,`:一行里可能塞了两条语句(`const a = []; const b = [];`),
    或者一个声明里有两个变量(`const a = 0, b = false`)。不切的话右侧文本会把后一条
    一起带上,里面的 `=` 就被当成运算符,凭空多报一条。

    括号是写法不是值:精确档的 `isComputed` 遇到 `ParenthesizedExpression` 会往里
    再看一层,这里用「剥」来对上。剥到不再是整体括号为止,是因为它们可以叠。

    Args:
        value: 赋值的右侧文本。

    Returns:
        去掉外层包装之后的那段表达式。
    """
    text = _cut_at(value, ';,').strip()                 # 切到第一个顶层分号或逗号
    # 括号只影响写法,一层层脱掉再判里面
    while (
        # 以圆括号开头
        text.startswith('(')
        # 而且那对括号一直盖到末尾
        and _closes_at_end(text, '(', ')')
    ):
        text = text[1:-1].strip()                       # 丢掉首尾那两个括号字符
    return text


def _cut_at(text, stops):
    """切到第一个位于括号外的 `stops` 字符。

    只在深度为 0 的地方切,是因为 `f(a, b)` 与 `[a, b]` 里的逗号属于同一个表达式 ——
    切错一处就会把调用判成取值,而那是漏报。

    Args:
        text: 骨架行上的一段文本。
        stops: 停下来的字符集合。

    Returns:
        切好的那一段。
    """
    depth = 0
    # 逐字符推进,遇到括号外的停靠字符就收工
    for index, char in enumerate(text):
        # 开括号进一层
        if char in '([{':
            depth += 1
            continue
        # 闭括号出一层
        if char in ')]}':
            depth -= 1
            continue
        # 只有顶层的那几个字符才算分隔
        if (
            # 已经退回到最外层
            not depth
            # 而且这个字符是停靠字符
            and char in stops
        ):
            return text[:index]
    return text


def _is_plain_value(text):
    """最外层是不是一个字面量或一条取值链。

    这三类在精确档里分别是 `ArrayLiteralExpression`、`ObjectLiteralExpression` 与
    两个取值表达式,都不在 `isComputed` 的清单里 —— 判据是「读者能不能一眼看出
    值是什么」,而不是「里面有没有出现调用」。

    Args:
        text: 已经去掉外层包装的表达式文本。

    Returns:
        是这三类之一给 True。
    """
    # 数组字面量
    if (
        # 以方括号开头
        text.startswith('[')
        # 而且那对方括号一直盖到末尾
        and _closes_at_end(text, '[', ']')
    ):
        return True
    # 对象字面量
    if (
        # 以花括号开头
        text.startswith('{')
        # 而且那对花括号一直盖到末尾
        and _closes_at_end(text, '{', '}')
    ):
        return True
    return _is_access_chain(text)                       # 整条取值链


def _is_await(text):
    """这段文本是不是一个 `await` 表达式。

    精确档里 `AwaitExpression` 算「算出来的」:值取决于异步结果,不是眼前的字面量。
    三种写法都要认,否则 `await(x)` 会被漏掉。

    Args:
        text: 已经去掉外层包装的表达式文本。

    Returns:
        是 await 表达式给 True。
    """
    # 裸 `await`
    if text == 'await':
        return True
    # 后面跟着一个空格
    if text.startswith('await '):
        return True
    # 直接贴着括号调用
    return text.startswith('await(')


def _strip_unary(text):
    """剥掉开头的一元运算符(`!x`、`-x`、`typeof x`)。

    不剥的话 `const ok = !flag` 会因为那个 `!` 被判成算出来的 —— 而精确档认的是
    `PrefixUnaryExpression`,它不在 `isComputed` 的清单里。剥到没有为止是因为
    一元运算符可以叠(`!!x`、`-+x`)。

    Args:
        text: 骨架行上的一段表达式。

    Returns:
        剥掉前缀运算符之后的文本。
    """
    current = text
    # 一元运算符可以叠,剥到剥不动为止
    while current:
        head = current[0]
        # 符号型一元运算符只占一个字符
        if head in '!-+~':
            current = current[1:].lstrip()              # 剥掉它,再从头看一次
            continue
        # 关键字型一元运算符要一个个试:它们必须后面跟空格才是运算符
        for word in _UNARY_WORDS:
            # 命中就把关键字连同空格一起剥掉
            if current.startswith(word):
                current = current[len(word):].lstrip()  # 关键字本身也要剥掉
                break
        else:
            break
    return current


def _strip_postfix(text):
    """剥掉末尾的自增自减(`i++` / `j--`)。

    后缀自增在精确档里是 `PostfixUnaryExpression`,不在 `isComputed` 的清单里 ——
    它把值改掉,但改出来的不是「算出来的值」。不剥的话那个 `+` 会被当成加法运算符,
    `let n = nextBlockIdx++;` 这种极常见的写法就会被误报。

    Args:
        text: 已经剥掉前缀一元运算符的表达式文本。

    Returns:
        剥掉后缀运算符之后的文本。
    """
    current = text.rstrip()                             # 末尾空白不算表达式的一部分
    # 后缀运算符只可能出现在最末尾,而且一次只可能有一个
    if (
        # 自增
        current.endswith('++')
        # 或自减
        or current.endswith('--')
    ):
        return current[:-2].rstrip()
    return current


def _has_top_operator(text):
    """括号深度为 0 的地方有没有运算符。

    深度是关键:`f(a - b)` 里的减号属于被调方的参数,不影响「这个值怎么来的」。

    Args:
        text: 骨架行上的一段表达式。

    Returns:
        顶层有运算符给 True。
    """
    depth = 0
    # 逐字符推进,只认深度为 0 的那些运算符
    for char in text:
        # 开括号进一层
        if char in '([{':
            depth += 1
            continue
        # 闭括号出一层
        if char in ')]}':
            depth -= 1
            continue
        # 只有顶层(深度 0)的运算符才算「算出来的」
        if (
            # 已经退回到最外层
            not depth
            # 而且这个字符是运算符
            and char in _OPERATOR_CHARS
        ):
            return True
    return False


def _has_top_arrow(text):
    """括号深度为 0 的地方有没有 `=>`。

    有就说明整段是个箭头函数,而精确档的 `isComputed` 不认箭头 —— 它认的是节点种类,
    箭头函数是「一个值」而不是「算出来的值」。不下钻是因为 `rows.map((r) => r.x)`
    这种写法整体已经是调用,前面那一支就返回了。

    Args:
        text: 骨架行上的一段表达式。

    Returns:
        顶层有箭头给 True。
    """
    depth = 0
    index = 0
    # 逐字符推进,记下每一处的括号深度
    while index < len(text):
        char = text[index]
        # 开括号进一层
        if char in '([{':
            depth += 1
        # 闭括号出一层
        elif char in ')]}':
            depth -= 1
        # 顶层出现这两个字符就是箭头本身
        elif (
            # 已经退回到最外层
            not depth
            # 而且从这里起就是箭头
            and text.startswith('=>', index)
        ):
            return True
        index += 1
    return False


def _is_access_chain(text):
    """整段文本是不是一条取值链(裸名字或 this,后接若干段 `.名字` / `[下标]`)。

    取值链在精确档里是 `PropertyAccessExpression` 与 `ElementAccessExpression`,
    两者都不在 `isComputed` 的清单里。可选链(`a?.b`、`a?.[0]`)也算取值:它在 AST 里
    仍是同一个节点,只是多一个问号标记。逐段走完才算,是为了不把 `ctx.text.slice(...)`
    那种「取值之后再调用」也吞掉 —— 那一段整体是调用,该算算式。

    Args:
        text: 骨架行上的一段表达式。

    Returns:
        整段都是取值给 True。
    """
    found = _BARE_NAME_RE.match(text)                   # 开头的裸名字或 this
    # 开头不是裸名字或 this,就不是取值链
    if not found:
        return False
    index = found.end()                                 # 从名字后面接着走
    # 一段接一段往下走,走完才算整段都是取值
    while index < len(text):
        char = text[index]
        # 可选链的问号只是写法:跳过它,让下面按 `.` 或 `[` 处理
        if (
            # 这一格是问号
            char == '?'
            # 而且它后面真的跟着点(不是三元运算符)
            and text.startswith('?.', index)
        ):
            index += 1                                  # 只跳过问号,点留给下一段
            # `?.[0]` 的点后面直接是下标,再跳一格让下面按下标处理
            if text.startswith('.[', index):
                index += 1
            char = text[index]
        # 属性取值
        if char == '.':
            step = _PROPERTY_STEP_RE.match(text, index)  # 这一段 `.名字`
            # 点后面不是名字,这条链就断了
            if not step:
                return False
            index = step.end()                           # 走到这一段末尾
            continue
        # 下标取值
        if char == '[':
            close = _matching_index(text, index, '[', ']')    # 下标那对方括号的收尾
            # 下标没配上,这条链就断了
            if close < 0:
                return False
            index = close + 1                            # 跳过整个下标
            continue
        return False
    return True


def _closes_at_end(text, opening, closing):
    """开头那个括号是不是正好在末尾合上。

    `[...xs]` 与 `[a, b][0]` 的区别全在这里:前者那对括号盖到末尾,是数组字面量;
    后者后面还跟着一段下标,整体是取值。判错一个就会把字面量当成算式多报一条。

    Args:
        text: 骨架行上的一段表达式。
        opening: 开括号字符。
        closing: 闭括号字符。

    Returns:
        正好在末尾合上给 True。
    """
    # 配对位置就是最后一个字符,说明这对括号从头盖到尾,中间没有别的东西
    return _matching_index(text, 0, opening, closing) == len(text) - 1


def _matching_index(text, start, opening, closing):
    """`start` 处开括号的配对闭括号下标;没配上给 -1。

    只数字符、不认引号:传进来的文本是骨架行,字符串与注释已经抹成空格了。

    Args:
        text: 骨架行上的一段表达式。
        start: 开括号所在的下标。
        opening: 开括号字符。
        closing: 闭括号字符。

    Returns:
        配对闭括号的下标;没配上给 -1。
    """
    depth = 0
    # 从开括号起逐字符数深度
    for index in range(start, len(text)):
        char = text[index]
        # 开括号进一层
        if char == opening:
            depth += 1
            continue
        # 不是闭括号的字符与深度无关
        if char != closing:
            continue
        depth -= 1
        # 深度归零就是配对的那一个
        if not depth:
            return index
    return -1    # 扫到末尾还在层里,说明括号没配上
