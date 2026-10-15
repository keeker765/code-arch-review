"""注释行、平铺段、定义间空行 —— 与「文件排布」有关的那三组事实。

这一组判据的公共点:它们量的都是**读代码时的落脚点**,不是逻辑正确性。
而它们同时是三种作弊手法的对手戏:删空行压行数、堆注释刷密度、
把长逻辑写成一段没有结构提示的平铺。阈值判定留在规则引擎,
这里只把「哪几行有注释」「哪几段没注释」「哪两个定义贴太紧」数清楚。

注释行号走 `tokenize` 而不是扫字符:Python 的 `#` 会出现在字符串与 f-string 里,
`f'#{x}'` 扫字符会把它当注释起点,于是「上方缺注释」这条会被误判成已注释。
"""

import ast
import io
import tokenize

# 自带结构提示、因此不计入平铺段并切断当前段的语句
_CONTROL_FLOW = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor,
                 ast.AsyncWith, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# 定义之间的空行数:PEP 8 要求顶层 2 行、类内方法 1 行
_TOPLEVEL_GAP, _METHOD_GAP = 2, 1


def comment_rows(source):
    """用 tokenize 找出真正的注释所在行,避开字符串里的 `#`。

    依赖 Python 标准词法分析器按物理 token 提取注释行号,有效规避字符串与 f-string 内部字符干扰。

    Args:
        source: 整个文件的源码文本。

    Returns:
        含注释的行号集合(1 基),含行尾注释。
    """
    # 存储包含有效注释的物理行号集合(1 基)
    rows = set()
    try:
        # 遍历词法标记流:仅提取 COMMENT 类型 token 的起始行号
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            # 只收 COMMENT token:它已经由词法器从字符串、f-string、正则里区分出来了
            if token.type == tokenize.COMMENT:
                rows.add(token.start[0])
    except (tokenize.TokenError, IndentationError):
        pass  # 语法已由 ast.parse 把关,这里只做尽力而为
    return rows


def blocks(node):
    """一个语句节点直接拥有的语句块(体、else、finally、except 体)。

    生成语句节点直接嵌套的代码块列表,便于按块递归扫描无注释平铺代码段。

    Args:
        node: 任意 ast 语句节点。

    Yields:
        每个块的语句列表。
    """
    # 三种块字段名在 ast 里是固定的;反射取比逐个 isinstance 分支短,也覆盖未来新增的类型
    for field_name in ('body', 'orelse', 'finalbody'):
        # 反射提取节点上可能存在的直属代码块语句列表
        group = getattr(node, field_name, None)
        if (
            # 该节点有这个字段
            isinstance(group, list)
            # 且非空 —— 空块没有语句,不必产出
            and group
        ):
            yield group
    # except 体不在上面三个字段里,单独取;没有 handlers 的节点返回空列表
    for handler in getattr(node, 'handlers', []):
        yield handler.body


def _flush(runs, run):
    """把一段平铺语句收进结果,只有一条的不算「一长串」。

    单条语句不构成平铺坏味道:一段里至少两条才有「读者要连续反推」的问题。

    Args:
        runs: 结果列表,原地追加。
        run: 当前累积的语句列表。
    """
    # 单条语句不构成平铺坏味道:一段里至少两条才有「读者要连续反推」的问题
    if len(run) > 1:
        runs.append((run[0].lineno, len(run)))


def _runs_in_group(group, whole_line):
    """数一个语句块里的平铺段。

    线性扫描语句,遇到控制流或被独立注释覆盖的语句时结算并重置累积段。

    Args:
        group: 一个语句块(if 体、循环体、函数体……)的语句列表。
        whole_line: 独立整行注释所在的行号集合。

    Returns:
        `[(段首行号, 段长)]`。
    """
    runs, run = [], []
    # 逐条扫描块内语句以寻找未被独立注释分隔的长代码段
    for stmt in group:
        # 控制流自带结构提示,不算平铺,并且切断当前段
        if isinstance(stmt, _CONTROL_FLOW):
            _flush(runs, run)
            run = []
            continue
        # 语句自己这一行或上一行有独立注释 ⇒ 它已被说明,自己另起一段。
        # 看「上一行」是因为注释写在语句上方才是本 skill 要求的写法
        if any(row in whole_line for row in range(stmt.lineno - 1, stmt.lineno + 1)):
            _flush(runs, run)
            run = [stmt]
            continue
        run.append(stmt)
    _flush(runs, run)
    return runs


def flat_runs(tree, whole_line):
    """找出函数里「连续一长串语句、中间一行注释都没有」的平铺段。

    控制流语句(if/for/while/with/try)自带结构提示,不计入平铺;它们同时切断当前段。

    🔴 这里记录**整段的最终长度**而不在这里比阈值:阈值属于规则引擎,
    换语言不该换阈值。上报由 `core.rules` 按 `--max-flat` 判。

    Args:
        tree: 模块的 ast 节点。
        whole_line: 独立整行注释所在的行号集合。

    Returns:
        `[(段首行号, 段长)]`。
    """
    runs = []
    # 平铺段只在函数体内数:模块层的连续语句是导入与常量,没有「读者要连续反推」的问题
    for func in ast.walk(tree):
        # 排除非函数节点,把统计范围限制在函数体内
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 函数体内每个块单独数:嵌套块会由它自己的节点再走一遍,不在这里合并
        for node in ast.walk(func):
            # 遍历该 AST 节点直接包含的所有独立语句块
            for group in blocks(node):
                runs.extend(_runs_in_group(group, whole_line))
    return runs


def _layout_head(node, lines):
    """一个定义的头:装饰器与紧贴上方的整行注释都属于这个定义。

    装饰器写在定义上一行,紧贴的注释又是给定义看的 —— 空行要在它们**之前**,
    否则 `@decorator` 与 `def` 会被空行拆开,注释也会飘离它说明的对象。

    Args:
        node: 定义节点。
        lines: 文件按行切好的列表,0 基。

    Returns:
        定义起始行号(1 基),已把上方紧贴的注释块算进去。
    """
    # 取定义语句与其所有装饰器中最早的那一行
    row = min([node.lineno] + [item.lineno for item in getattr(node, 'decorator_list', [])])
    # 继续向上吃掉紧贴的整行注释块,直到撞上非注释行或文件头
    while row > 1 and lines[row - 2].lstrip().startswith('#'):
        row -= 1
    return row


def _layout_gaps(body, need, lines):
    """查一个语句块内定义之间的空行。

    向上回溯定义前置的物理空行数,当实际空行不足规定间隔时记录缺口位置。

    Args:
        body: 该块的语句列表。
        need: 需要几个空行。
        lines: 文件按行切好的列表,0 基。

    Returns:
        `[(行号, 定义名, 实际空行数, 需要的空行数)]`。
    """
    gaps = []
    # 遍历块内直接子节点,排查相邻函数与类定义之间的空行距离
    for index, node in enumerate(body):
        # 只查函数与类定义:变量赋值之间的空行是排版权,不是结构信号
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        # 块内第一个定义没有上一个兄弟,空行由外层的规则负责
        if index == 0:
            continue
        # 计算包含装饰器与前置注释的定义逻辑起始物理行号
        row = _layout_head(node, lines)
        got = 0
        # row-1-got 是往上数第几个空行;越过文件头当作已满足,避免首个定义误报
        while got < need and (row - 1 - got < 1 or not lines[row - 2 - got].strip()):
            got += 1
        # 空行不足就报:删空行是压行数作弊的入口,必须与 long-module 一起查
        if got < need:
            gaps.append((row, node.name, got, need))
    return gaps


def packed_layout(tree, lines):
    """按 PEP 8 查顶层与类内定义之间的空行,顶层 2 行、类内 1 行。

    这条不是排版洁癖:删空行能把行数压到 `long-module` 阈值以下,而「说明密度」
    的分母也跟着变小,于是作弊反而让两项指标都变好看。要堵这个口子,空行必须是硬要求。

    Args:
        tree: 模块的 ast 节点。
        lines: 文件按行切好的列表,0 基。

    Returns:
        `[(行号, 定义名, 实际空行数, 需要的空行数)]`。
    """
    # 顶层要 2 个空行,这是 PEP 8 的硬规定,也是文件里最大的两处分段
    gaps = list(_layout_gaps(tree.body, _TOPLEVEL_GAP, lines))
    # 类内方法之间要 1 个空行:比顶层紧凑,但同样不能贴在一起
    for node in ast.walk(tree):
        # 只有类体需要这一层检查
        if isinstance(node, ast.ClassDef):
            gaps.extend(_layout_gaps(node.body, _METHOD_GAP, lines))
    return gaps
