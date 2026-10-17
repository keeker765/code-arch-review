"""JS / TS 的**启发式降级**:拿不到 node 或 typescript 包时,用正则与括号计数兜底。

这一档只保证**行级**事实可靠(注释在哪、`if` / 循环 / `throw` / 赋值 / `return` 在哪),
结构度量一律置 0 或留空 —— 数不准就不报(见 `references/languages.md` 的启发式纪律):

* `body_lines` / `nesting_depth` / `string_key_count` 置 0,于是 `long-function`、
  `deep-nesting`、`dict-as-type` 永不触发
* `fields` / `flat_runs` / `layout_gaps` 留空列表

本文件负责**定义识别**(函数、类、方法)与最后拼装;文本层在 `js_text`,
行级构造在 `js_lines`。拆开是因为每一层都要写满注释与文档,合在一个文件里
会超过单文件 500 行的硬闸 —— 这不是按行数切,是按「答案从哪来」切。
"""

from pathlib import Path
import re

from core.model import FileFacts, FunctionFact
# py-structure: allow-sibling-imports —— JS 降级层按职责拆在同目录
from . import js_lines as lines
from .js_mask import mask_source
from .js_text import (
    balanced_span,
    doc_above,
    module_doc,
    param_names,
    prose_lines,
    section_facts,
)

LANGUAGE = 'javascript'

# 函数声明的四种写法。都锚在行首(允许缩进),免得把调用表达式也认成定义
_FUNCTION_RE = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]*)\s*\(')
_CLASS_RE = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([\w$]+)')   # `class Name`
# `const f = () =>` 与 `const f = async (a) =>`:名字取变量名
_ARROW_RE = re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?'
                       r'(?:function\s*\*?\s*[\w$]*\s*)?\(([^)]*)\)\s*(?::[^=]*)?=>')
# `const f = function (a) {`:同样取变量名,匿名函数表达式也能拿到名字
_BOUND_FUNC_RE = re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?'
                            r'function\s*\*?\s*[\w$]*\s*\(')
# 类方法 / 对象成员:缩进 + `名字(...) {`
_METHOD_RE = re.compile(r'^(\s+)(?:public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+)*'
                        r'(?:get\s+|set\s+)?([\w$]+)\s*\(([^)]*)\)\s*(?::[^{;]*)?\{')
# 方法名位置上出现这些词说明它不是方法,是控制流
_KEYWORDS = frozenset({'if', 'for', 'while', 'switch', 'catch', 'function', 'return',
                       'do', 'else', 'try', 'with', 'typeof', 'new', 'await'})


def facts_for(path: Path) -> FileFacts:
    """把一个 JS / TS 文件按启发式翻成事实。

    启发式档没有精确的行号映射可用,所以行号全按 `\\n` 数(文件里有 `\\u2028`
    这种行分隔符时会与精确档差几行,那是这一档的已知代价)。

    Args:
        path: 文件路径。

    Returns:
        该文件的事实;`heuristic=True`,报告里会与精确档的条目分开标。

    Raises:
        OSError: 文件读不到。
    """
    # 真实项目里有 GBK 编码的 .js(本机 `脚本工具/` 下就有),硬解 utf-8 会直接崩;
    # 替换字符只影响正文显示,行号不受影响,而闸只看行号
    source = path.read_text(encoding='utf-8', errors='replace')
    raw_lines = source.split('\n')                      # 取文档注释要按行看原文
    # 先抹骨架:字符串与注释的内容换成空格,后面几趟都只认骨架
    masked, comment_rows, whole_rows = mask_source(source)
    # 行级构造:循环、抛异常、赋值、return、空 catch 一趟收齐
    loops, raises, assigns, returns, silent = lines.line_facts(masked)
    functions = _function_facts(masked, raw_lines, whole_rows)   # 函数与类的定义事实
    return FileFacts(
        path=path,
        language=LANGUAGE,
        total_lines=len(source.splitlines()),
        comment_rows=comment_rows,
        whole_line_rows=whole_rows,
        module_doc=module_doc(raw_lines, whole_rows),
        functions=functions,
        conditions=lines.condition_facts(masked),
        loops=loops,
        raises=raises,
        assigns=assigns,
        returns=returns,
        silent_except_lines=silent,
        bindings=lines.bindings(masked),
        heuristic=True,
    )


def _function_facts(masked, raw_lines, whole_rows):
    """找出函数、类与方法。

    `body_lines` 与 `nesting_depth` 一律置 0:启发式数不准体量与嵌套,置 0 之后
    `long-function` 与 `deep-nesting` 自然不触发 —— 与其报个错的数,不如不报。

    Args:
        masked: 抹掉注释与字符串后的骨架行。
        raw_lines: 文件按行切好的原文(取文档注释用)。
        whole_rows: 独立整行注释的行号集合。

    Returns:
        `FunctionFact` 列表,按行号排列。
    """
    facts = []
    spans = _class_spans(masked)                        # 类体的行区间,判方法要用
    # 逐行认定义:一行最多产出一条事实,免得同一个定义被两条正则各记一次
    for row, line in enumerate(masked, start=1):
        found = _definition_at(masked, spans, row, line)    # 这一行是不是定义
        # 不是定义就接着看下一行
        if not found:
            continue
        name, params, is_class = found
        doc = doc_above(raw_lines, whole_rows, row)     # 定义上方紧贴的 JSDoc,没有就是 None
        required, missing = section_facts(doc, params, _body_text(masked, row, line, is_class))
        facts.append(FunctionFact(
            name=name,
            line=row,
            end_line=_definition_end(masked, row, line),
            body_lines=0,
            params=params,
            is_public=bool(name) and not name.startswith('_'),
            is_class=is_class,
            doc=doc,
            required_sections=required,
            missing_sections=missing,
            doc_prose_lines=prose_lines(doc) if doc else 0,
        ))
    return facts


def _definition_at(masked, spans, row, line):
    """这一行是不是一个函数 / 类定义,是的话给出它的名字与参数。

    认的顺序有讲究:先函数声明、再类、然后才是「赋给变量的函数」—— 最后那条最宽松,
    放前面会把别的东西也吞进来。匿名函数给空名字,报告里退化成行号。

    Args:
        masked: 骨架行。
        spans: 类体的行区间,判方法时用。
        row: 行号,1 基。
        line: 该行的骨架文本。

    Returns:
        `(名字, 参数名列表, 是不是类)`;不是定义时返回 None。
    """
    found = _FUNCTION_RE.match(line)                    # `function name(`
    # 函数声明:名字与参数都在这一行(参数可能跨行,交给括号配对去收)
    if found:
        params = param_names(balanced_span(masked, row, found.end() - 1)[0])    # 括号里的参数表
        return found.group(1) or '', params, False
    found = _CLASS_RE.match(line)                       # `class Name`
    # 类声明:参数表对类没有意义,给空列表
    if found:
        return found.group(1), [], True
    found = _ARROW_RE.match(line)                       # `const f = (...) =>`
    # 赋给变量的箭头函数:名字取变量名,报告里才认得出是哪一个
    if found:
        return found.group(1), param_names(found.group(2)), False
    found = _BOUND_FUNC_RE.match(line)                  # `const f = function`
    # 赋给变量的函数表达式:同理,名字取变量名
    if found:
        params = param_names(balanced_span(masked, row, found.end() - 1)[0])    # 括号里的参数表
        return found.group(1), params, False
    # 类体里的方法:`  render(a, b) {`
    if _inside(spans, row):
        found = _METHOD_RE.match(line)                  # 缩进的 `名字(...) {`
        # 名字位置上出现关键字说明它不是方法,是控制流(`if (x) {`)
        if (
            # 形状上确实像「名字 + 参数 + 花括号」
            found
            # 而且那个名字不是 `if` / `for` / `catch` 这类关键字
            and found.group(2) not in _KEYWORDS
        ):
            return found.group(2), param_names(found.group(3)), False
    return None


def _class_spans(masked):
    """类体的行区间,判一行在不在类体里要靠它。

    只看 `class` 那一行上有没有 `{`:写成 Allman 风格(大括号另起一行)的类认不出来,
    那种类的成员就不查了 —— 少报总比把对象字面量的成员误认成方法好。

    Args:
        masked: 抹掉注释与字符串后的骨架行。

    Returns:
        `[(类所在行, 类体结束行)]`。
    """
    spans = []
    # 逐行找 class 声明,再用配对的大括号量出它的体有多长
    for row, line in enumerate(masked, start=1):
        found = _CLASS_RE.match(line)                   # 这一行是不是类声明
        # 不是类声明就接着看下一行
        if not found:
            continue
        column = line.find('{')                         # 类体的开括号在哪一列
        # 大括号写在下一行的写法认不出来,那种类的成员就不查了
        if column < 0:
            continue
        spans.append((row, balanced_span(masked, row, column, '{', '}')[1]))
    return spans


def _inside(spans, row):
    """这一行在不在某个类体里。

    判据是左开右闭:`class` 那一行自己不算「在里面」,否则 `class A { render() {} }`
    会把类名那行也当成方法行。

    Args:
        spans: `_class_spans` 给出的区间。
        row: 行号,1 基。

    Returns:
        在里面时为 True。
    """
    return any(start < row <= end for start, end in spans)


def _body_text(masked, row, line, is_class):
    """定义的花括号体文本(判有没有 return / throw 用)。

    没有花括号体的定义(单表达式箭头函数)给空串:那种函数体里不可能有 `return`,
    判 `@returns` 小节时也就不会凭空要求它。

    Args:
        masked: 骨架行。
        row: 定义所在行,1 基。
        line: 定义行的骨架文本。
        is_class: 类体不判 return / throw,直接给空串。

    Returns:
        体的文本;没有花括号体时给空串。
    """
    # 类是类型定义,它里面的 `return` 属于某个方法,不属于这个类
    if is_class:
        return ''
    column = line.find('{')                             # 函数体的开括号在哪一列
    # 没有花括号体的定义就没有体可判
    if column < 0:
        return ''
    return balanced_span(masked, row, column, '{', '}')[0]


def _definition_end(masked, row, line):
    """定义的结束行(报告里显示范围用)。

    与 `_body_text` 分开是刻意的:体文本用来判文档小节,结束行只用来显示范围,
    两个消费者对同一段括号的用法不同,合成一个函数的返回值反而要两边都拆。

    Args:
        masked: 骨架行。
        row: 定义所在行,1 基。
        line: 定义行的骨架文本。

    Returns:
        结束行号;没找到花括号体时就是起始行。
    """
    column = line.find('{')                             # 函数体的开括号在哪一列
    # 没有花括号体的定义(单表达式箭头函数)一行就是全部
    if column < 0:
        return row
    return balanced_span(masked, row, column, '{', '}')[1]
