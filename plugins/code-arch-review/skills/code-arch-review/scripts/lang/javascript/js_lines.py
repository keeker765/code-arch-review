"""JS / TS 启发式降级的**行级构造层**:在骨架行上认出条件、循环、赋值、绑定。

这一层的判据都是「一眼看得出来的形状」:关键字加括号、`=` 右边有没有运算。
它不追求精确(精确那份在 `js_probe.mjs` 里,走 TypeScript 编译器),追求的是
拿不到 node 时**不要把没有的东西报出来** —— 数不准的项一律不报。

见 `references/languages.md` 的启发式纪律:启发式档会误报,而只报噪声的闸会被关掉。
"""

import re

from core.model import BindingFact, ConditionFact, SimpleFact
# py-structure: allow-sibling-imports —— JS 降级层按职责拆在同目录
from .js_expr import looks_computed
from .js_text import RETURN_EXPR_RE, THROW_RE, balanced_span

_IF_RE = re.compile(r'\b(?:else\s+)?if\s*\(')                    # `if (` 与 `else if (`
_LOOP_RE = re.compile(r'\b(for|while)\s*\(')                     # `for (` 与 `while (`
_DO_RE = re.compile(r'\bdo\s*\{')                                # `do {` 的关键字在循环体之前
_OF_RE = re.compile(r'\bof\b')                                   # `for (x of xs)`
_IN_RE = re.compile(r'\bin\b')                                   # `for (k in obj)`
_DECLARE_RE = re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(.*)$')   # `const x = ...`
_ASSIGN_RE = re.compile(r'^\s*([A-Za-z_$][\w$]*)\s*(?:[+\-*/%|&^]|\*\*|\?\?|\|\||&&)?=(?!=)\s*(.*)$')   # `x = ...` / `x += ...`

# 顶层绑定只认 `function` / `class` / `var`:只有这两种东西的重复声明是静默后者胜出
_TOP_FUNCTION_RE = re.compile(r'^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)')
_TOP_CLASS_RE = re.compile(r'^(?:export\s+)?(?:default\s+)?class\s+([\w$]+)')           # 顶层 `class`
_TOP_VAR_RE = re.compile(r'^(?:export\s+)?var\s+([\w$]+)\s*(?:=\s*(.*))?$')           # 顶层 `var`
_SILENT_CATCH_RE = re.compile(r'\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}')     # 空体的 catch



def condition_facts(masked):
    """全部 `if` / `else if`,含布尔组合摊平后逐个子条件的行号。

    2026-10-18 起注释规则只要求每条条件前面一条说明,`operand_lines` 保留给诊断,
    不参与违规与覆盖率计数。

    只收**花括号里**的:与精确档一样,模块顶层的 `if` 不算条件。脚本文件里顶层的
    `if (!res.ok)` 是启动流程的分支,不是业务判据,给它要注释只会制造噪声。

    用花括号深度而不是「已知的函数行区间」来判:函数区间依赖前面那一趟的识别结果,
    漏认一个函数就会把它里面的条件整片丢掉 —— 那是**漏报**,比多报一条难发现得多。

    Args:
        masked: 抹掉注释与字符串后的骨架行。

    Returns:
        `ConditionFact` 列表。
    """
    facts = []
    depths = _brace_depths(masked)                      # 每一行开始时的花括号深度
    # 逐行找 `if (`
    for row, line in enumerate(masked, start=1):
        # 顶层那一行整行跳过,省掉后面那一串解析
        if not depths[row - 1]:
            continue
        # 一行里可能不止一个 `if (`,每一个都要单独摊平
        for found in _IF_RE.finditer(line):
            text = balanced_span(masked, row, found.end() - 1)[0]   # 括号里的条件文本
            # 子条件的行号 = 条件起始行 + 它前面跨了几行
            operands = [row + text.count('\n', 0, offset) for offset, _ in split_operands(text)]
            # 一个判据都没有说明括号没配对,这一条干脆不报
            if operands:
                facts.append(ConditionFact(line=row, operand_lines=tuple(operands)))
    return facts


def _brace_depths(masked):
    """每一行**开始时**的花括号深度,下标是 0 基行号。

    深度为 0 就是模块顶层。这一判断与「哪些行在函数体里」并不完全同义(顶层对象
    字面量里也会深于 0),但差的那几种在 JS 里极少见,而它有一个决定性的好处:
    不依赖函数识别的结果,漏认一个函数不会连带丢掉它里面的条件。

    Args:
        masked: 抹掉注释与字符串后的骨架行。

    Returns:
        深度列表,长度与 `masked` 相同。
    """
    depths = []
    depth = 0
    # 逐行记下进入这一行时的深度,再按本行的括号更新
    for line in masked:
        depths.append(depth)
        depth += line.count('{') - line.count('}')
    return depths


def split_operands(text):
    """把条件文本按最外层的 `&&` / `||` 切开,给出每个子条件的起始偏移。

    括号里的 `&&` 属于同一个判据(那是一个整体表达式),不当成分叉 —— 摊平到括号
    里面去会把一个判断说成两个,读者照着数注释就会发现对不上。

    Args:
        text: 条件文本,可能多行。

    Returns:
        `[(子条件起始偏移, 子条件文本)]`。
    """
    pieces = []
    depth = 0
    head = 0
    index = 0
    # 逐字符推进:只有深度为 0 的 `&&` / `||` 才是分叉
    while index < len(text):
        char = text[index]
        # 开括号进一层
        if char in '([{':
            depth += 1
        # 闭括号出一层
        elif char in ')]}':
            depth -= 1
        # 深度为 0 的 `&&` / `||` 才是分叉点:切开,记下前一段
        elif (
            # 括号里的运算符属于同一个判据,不算分叉
            not depth
            # 而且当前位置真的写着 `&&` 或 `||`
            and text.startswith(('&&', '||'), index)
        ):
            pieces.append((head, text[head:index]))
            index += 2
            head = index
            continue
        index += 1
    pieces.append((head, text[head:]))
    trimmed = []
    # 每个子条件前面的空白不算它的起始位置,行号要按第一个真字符算
    for start, piece in pieces:
        stripped = piece.lstrip()                   # 前导空白与换行都不算位置
        # 空的片段(比如行尾多写了一个 `&&`)不是判据
        if not stripped:
            continue
        trimmed.append((start + len(piece) - len(stripped), stripped.rstrip()))
    return trimmed


def line_facts(masked):
    """循环 / 抛异常 / 赋值 / `return` / 空 catch 这几类按行判定的构造。

    这几类都走 `SimpleFact`,区别只在接不接受行尾注释,所以一起产出省一趟遍历。

    Args:
        masked: 抹掉注释与字符串后的骨架行。

    Returns:
        `(循环, 抛异常, 赋值, return, 空 catch 行号)`。
    """
    loops = []
    raises = []
    assigns = []
    returns = []
    # 逐行认这些一眼看得出来的构造
    for row, line in enumerate(masked, start=1):
        # 一行里可能出现多个循环关键字,逐个记
        for found in _LOOP_RE.finditer(line):
            header = balanced_span(masked, row, found.end() - 1)[0]   # `for (...)` 里的头
            loops.append(SimpleFact(line=row, label=loop_label(found.group(1), header),
                                    accepts_inline=False))
        # `do { ... } while (...)` 的关键字在循环体之前,单独认一次
        if _DO_RE.search(line):
            loops.append(SimpleFact(line=row, label='do', accepts_inline=False))
        # 抛异常是把失败态交给调用方,上方必须有独立注释行
        if THROW_RE.search(line):
            raises.append(SimpleFact(line=row, label='throw', accepts_inline=False))
        name, value = assignment(line)              # 这一行是不是「裸名字被赋值」
        # 同一行既要有名字、右侧还要是算出来的才要求注释
        if (
            # 拿得出被赋值的名字
            name
            # 右侧是算出来的,不是字面量也不是取值
            and looks_computed(value)
        ):
            assigns.append(SimpleFact(line=row, label=name, accepts_inline=True))
        found = RETURN_EXPR_RE.search(line)     # 这一行有没有 `return <表达式>`
        # `return x` 与裸 `return` 都不进清单,只有算式才要求写返回值口径
        if (
            # 这一行确实有 `return <表达式>`
            found
            # 而且那个表达式是算出来的
            and looks_computed(found.group(1))
        ):
            returns.append(SimpleFact(line=row, label='return', accepts_inline=True))
    return loops, raises, assigns, returns, silent_catches(masked)


def loop_label(keyword, header):
    """循环在报告里的标签:`for (const x of xs)` 报 `for-of`,不笼统地报 `for`。

    遍历什么决定了这条循环该怎么说明,标签里写清楚,读报告的人不用翻回代码。

    Args:
        keyword: 正则抓到的关键字(`for` / `while`)。
        header: 括号里的循环头文本。

    Returns:
        标签字符串。
    """
    # `while` 没有 `of` / `in` 这两种形态,直接就是它自己
    if keyword == 'while':
        return keyword
    # `for (const x of xs)` 是遍历元素,不是按下标走
    if _OF_RE.search(header):
        return 'for-of'
    # `for (const k in obj)` 是遍历键
    if _IN_RE.search(header):
        return 'for-in'
    return keyword


def silent_catches(masked):
    """空 `catch` 的行号 —— `catch {}` 与 `catch (e) {}` 都算。

    在拼好的整份骨架上找,而不是逐行找:`catch` 与 `{}` 之间可能夹着换行,
    逐行会漏掉空体写在下一行的那种。

    Args:
        masked: 抹掉注释与字符串后的骨架行。

    Returns:
        行号列表。
    """
    joined = '\n'.join(masked)                      # 拼回去,跨行的空体才看得见
    # 命中位置前面有几个换行,它就在第几行
    return [joined.count('\n', 0, found.start()) + 1
            for found in _SILENT_CATCH_RE.finditer(joined)]


def assignment(line):
    """从一行里取出 `(变量名, 右侧文本)`。

    只认裸名字被赋值:`this.x = f()` 与解构都不进来 —— 与 Python 后端跳过
    `self.x = ...` 同口径,免得同一件事在两门语言里报出不同的数。

    Args:
        line: 骨架行文本。

    Returns:
        `(变量名, 右侧文本)`;这一行不是赋值时给 `('', '')`。
    """
    found = _DECLARE_RE.match(line)             # 声明式赋值在前
    # 先认声明式:`const x = ...`
    if found:
        return found.group(1), found.group(2)
    found = _ASSIGN_RE.match(line)              # 普通赋值与复合赋值在后
    # 再认赋值式:`x = ...` 与 `x += ...`
    if found:
        return found.group(1), found.group(2)
    return '', ''


def bindings(masked):
    """模块顶层的 `function` / `class` / `var` 绑定。

    只有 `var` 与 `function` 的重复声明是**静默后者胜出**(`let` / `const` 重复声明
    是语法错误,引擎自己会报),所以只收这三种(见 `references/languages.md`)。

    Args:
        masked: 抹掉注释与字符串后的骨架行。

    Returns:
        `BindingFact` 列表。
    """
    found = []
    # 顶层 = 顶格写;缩进过的都在某个块里,不是模块顶层的直接绑定
    for row, line in enumerate(masked, start=1):
        # 顶格才算顶层:缩进过的都在某个块里
        if line[:1].isspace():
            continue
        match = _TOP_FUNCTION_RE.match(line)    # 函数声明
        # 函数声明:同名再声明一次就是静默覆盖,没有右侧表达式可谈
        if match:
            found.append(BindingFact(name=match.group(1), kind='def', line=row, references_self=False))
            continue
        match = _TOP_CLASS_RE.match(line)       # 类声明
        # 类声明同理
        if match:
            found.append(BindingFact(name=match.group(1), kind='def', line=row, references_self=False))
            continue
        match = _TOP_VAR_RE.match(line)         # `var` 声明
        # `var` 的重复声明同样是静默后者胜出,但右侧可能引用自己(那是规范化,不报)
        if match:
            found.append(BindingFact(name=match.group(1), kind='assign', line=row,
                                     references_self=mentions(match.group(2), match.group(1))))
    return found


def mentions(text, name):
    """右侧表达式有没有引用同一个名字 —— 那是扩展/规范化,不是覆盖。

    `ROOTS = ROOTS.concat(...)` 这类写法要豁免:读者不会因为「有两处定义」而拿错
    口径,不豁免的话这一条就只剩噪声(见 `core.rules` 里同一段的说明)。

    Args:
        text: 赋值右侧的骨架文本;没有右侧时是 None。
        name: 被绑定的名字。

    Returns:
        引用了这个名字时为 True。
    """
    # 没有右侧表达式就谈不上引用自己
    if not text:
        return False
    # 词边界要挡住 `foo` 命中 `foobar`:那不是一个名字
    return bool(re.search(r'\b%s\b' % re.escape(name), text))
