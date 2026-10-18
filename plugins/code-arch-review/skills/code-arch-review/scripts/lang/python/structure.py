"""语句与定义的翻译:把 Python 语法树里「有形状的东西」翻成语言无关的事实。

这一层回答三个问题:**这个函数有多大、有多深、参数有几个**(`function_facts`)、
**它里面有哪些分支**(`conditions`)、**哪些语句需要一句说明**(`simple_facts`)。
判得对不对全在阈值那边(`core.rules`),这里只负责把数数准。

`bindings.py` 管顶层绑定的覆盖判定,`layout.py` 管注释行与空行,`docstrings.py` 管文档小节
—— 拆开是因为四组判据的失败方式完全不同:绑定错在豁免写宽、空行错在漏数、
文档错在小节名过时。混在一个文件里,改一处要在几百行里翻找。
"""

import ast

from core.model import ConditionFact, FunctionFact, SimpleFact

# py-structure: allow-sibling-imports —— Python 后端按职责拆在同目录
from . import docstrings

# 右侧算「算出来的」的表达式类型 —— 纯函数调用与字面量都不要求注释
_COMPUTED_ASSIGN = (ast.BinOp, ast.IfExp, ast.Compare)

# 算式 return 的事实保留作诊断;口径归 docstring 的 Returns:,不再要求注释
_COMPUTED_RETURN = (ast.BinOp, ast.IfExp, ast.Compare)

# 算控制流嵌套层数的语句类型 —— 函数/类定义**不算**,否则嵌套函数会被重复计入
_NESTING_STMT = (ast.If, ast.For, ast.While, ast.With, ast.Try)


def body_lines(node):
    """函数/类的体有多少行。

    闭区间统计首语句起始行至末语句结束行的总行数,用于度量函数体量与判定平凡短函数。

    Args:
        node: 函数或类的 ast 节点。

    Returns:
        从体首行到体末行的行数(含首尾)。
    """
    # 闭区间:末语句的结束行减首语句的起始行加一。
    # `end_lineno` 在旧版本 Python 上可能缺失,那时退回定义行本身
    return (node.body[-1].end_lineno or node.lineno) - node.body[0].lineno + 1


def depth(node, level=0):
    """函数体内控制流嵌套的最大层数。

    🔴 **函数与类定义不加层**:否则一个嵌套函数会被外层和内层各数一次,
    同样的代码在「抽成小函数」和「内联」两种写法下报出不同的深度,
    而抽函数正是本闸鼓励的方向。

    Args:
        node: 起始 ast 节点。
        level: 当前已经套了几层。

    Returns:
        最深的层数。
    """
    worst = level
    # 递归整棵子树,每层取「本级」与「子树最深」的较大者
    for child in ast.iter_child_nodes(node):
        # 只有控制流加层;`isinstance` 返回 bool,正好当 0/1 用
        step = level + isinstance(child, _NESTING_STMT)
        # 持续保留整棵子树中发现的最深嵌套层数
        worst = max(worst, depth(child, step))
    return worst


def _chain_heads(nodes):
    """去掉 elif 节点,只留每条 `if` / `elif` 链的头。

    `elif` 在 AST 里就是父节点 `orelse` 里的 `If`。`else:` 里面再写 `if` 也是这个形状,
    所以还要比列号:真 `elif` 与父 `if` 同列,嵌套的那种多一层缩进。

    Args:
        nodes: 同一个函数里的全部 `ast.If` 节点。

    Returns:
        链头节点列表,顺序不变。
    """
    elif_ids = set()
    # 父节点的 orelse 里同列的 If 就是 elif;记下来,后面整批排除
    for node in nodes:
        for child in node.orelse:
            # 同列的 If 才是 elif;多一层缩进是 else 里的嵌套 if
            if isinstance(child, ast.If) and child.col_offset == node.col_offset:
                elif_ids.add(id(child))
    return [node for node in nodes if id(node) not in elif_ids]


def string_keys(node):
    """同一个对象上最多按几个字符串键取值。

    统计同一变量名被当成字典下标索引的不同字符串键总数,用于判定 dict-as-type。

    Args:
        node: 函数的 ast 节点。

    Returns:
        最大的键数;没有下标取值时返回 0。
    """
    seen = {}
    # 统计单变量在当前函数体内的字典键使用离散度
    for child in ast.walk(node):
        # 只认 `名字['字符串']` 这一种形态:属性访问(`a.b`)与数字下标(`a[0]`)
        # 都不是「按字段名取值」,放进来会误报
        if (
            # 节点是下标取值
            isinstance(child, ast.Subscript)
            # 下标是字面常量
            and isinstance(child.slice, ast.Constant)
            # 常量是字符串
            and isinstance(child.slice.value, str)
            # 被取值的是裸变量名,不是更复杂的表达式
            and isinstance(child.value, ast.Name)
        ):
            seen.setdefault(child.value.id, set()).add(child.slice.value)
    # 取「同一个变量上键最多」的那个数;没有任何下标取值时是 0
    return max((len(keys) for keys in seen.values()), default=0)


def conditions(tree):
    """产出每个函数体内每条 `if` / `elif` 链的头节点。

    模块层的 `if __name__ == ...` 不算 —— 那里没有业务判据。函数内的条件链一律算,
    **包括顶层守卫**(用户 2026-09-08 明确:顶层 `if self.source is not None` 也要注释)。
    一条链只产一条事实:注释写在链开头,`elif` 的前提由同一条注释覆盖。

    Args:
        tree: 模块的 ast 节点。

    Returns:
        `ConditionFact` 列表,按行号排序。
    """
    seen = {}
    # 条件分支仅在函数体内才具业务判定意义,排除模块层守卫
    for func in ast.walk(tree):
        # 只看函数体:模块层与类体里的 if 没有业务分支的含义
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 嵌套函数会被外层再走一遍,按节点 id 去重,否则同一处报两次
        for node in ast.walk(func):
            # elif 在 ast 里就是 orelse 里的 If,这一条把它一并收进来
            if isinstance(node, ast.If):
                seen[id(node)] = node
    facts = []
    # 排序后再去掉 elif:顺序稳定,链头自然落在它自己那一行
    ordered = sorted(seen.values(), key=lambda item: item.lineno)
    for node in _chain_heads(ordered):
        # operand_lines 留给后端诊断;注释规则不再逐个 operand 计数
        facts.append(ConditionFact(line=node.lineno, operand_lines=()))
    return facts


def _class_shape(node, doc):
    """类在参数表、字符串键、嵌套层数、文档小节上的取值。

    这四项对类都不适用,所以不查。**显式返回空值而不是另开一条分支**,
    是为了让 `FunctionFact` 的构造只有一条路径 —— 少一个分支就少一处将来会分叉的地方。

    Args:
        node: 已确认是类的 ast 节点。
        doc: 该类的文档正文;没有则 None。

    Returns:
        `(params, keys, nesting, missing)` 四元组,类上恒为 `((), 0, 0, ())`。
    """
    return (), 0, 0, ()


def _function_shape(node, doc):
    """函数在参数表、字符串键、嵌套层数、文档小节上的取值。

    提取去除 self/cls 后的公开形参、字典键取值频次、嵌套深度及缺失文档小节。

    Args:
        node: 已确认是函数的 ast 节点。
        doc: 该函数的文档正文;没有则 None。

    Returns:
        `(params, keys, nesting, missing)` 四元组;`params` 已剔除绑定的 self/cls。
    """
    bound = [*node.args.posonlyargs, *node.args.args]
    names = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    # 有位置参数且第一个是 self/cls ⇒ 这是绑定实参
    if bound and bound[0].arg in ('self', 'cls'):
        # self / cls 是绑定实参,调用方从不传,不该计入「被迫组装的依赖」
        names = [item for item in names if item is not bound[0]]
    # 有文档才谈得上「缺哪个小节」;没有文档是 no-docstring 那条规则的事
    missing = tuple(docstrings.missing_sections(node, doc)) if doc else ()
    return tuple(item.arg for item in names), string_keys(node), depth(node), missing


def function_facts(tree):
    """把每个函数/类翻译成 `FunctionFact`。

    遍历全模块函数与类定义节点,归一化抽取体长、签名、文档与结构形态指标。

    Args:
        tree: 模块的 ast 节点。

    Returns:
        `FunctionFact` 列表。
    """
    facts = []
    # 函数与类是架构度量的主要载体,提取接口签名、体长与文档事实
    for node in ast.walk(tree):
        # 只有函数与类才有「公开/私有、体长、文档」这一组属性
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        # 提取当前函数或类的 docstring 文档正文
        doc = ast.get_docstring(node)
        # 标记当前节点是否为类定义
        is_class = isinstance(node, ast.ClassDef)
        # 类与函数分开取形状:类上那四项一律为空,免得后面到处判 is_class
        if is_class:
            params, keys, nesting, missing = _class_shape(node, doc)
        else:
            params, keys, nesting, missing = _function_shape(node, doc)
        facts.append(FunctionFact(
            name=node.name, line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            body_lines=body_lines(node), params=params,
            is_public=not node.name.startswith('_'), is_class=is_class, doc=doc,
            missing_sections=missing, string_key_count=keys, nesting_depth=nesting,
            doc_prose_lines=docstrings.prose_lines(doc) if doc else 0))
    return facts


def _try_facts(node, silent):
    """把一个 try 语句里的静默吞异常记下来。

    排查 try 块内各 except 处理器是否仅包含 pass 占位语句,收集空处理块行号。

    Args:
        node: 已确认是 `ast.Try` 的节点。
        silent: 收集行号的列表,原地追加。
    """
    # except 体若仅含 pass 会导致错误被静默吞掉,记录其所在物理行号
    for handler in node.handlers:
        # except 体只有一条 pass ⇒ 失败态与正常态同形
        if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
            silent.append(handler.lineno)


def _has_loop_control(node):
    """循环体里有没有 `break` / `continue`。

    不进入嵌套循环、函数与类:`break` 属于最近的那层循环,不是外层这个。

    Args:
        node: 循环节点。

    Returns:
        体内有循环控制语句时为 True。
    """
    pending = list(node.body)
    # 用显式栈遍历,避免递归;嵌套边界在循环里剪掉
    while pending:
        child = pending.pop()
        # 嵌套的循环/函数/类有自己的控制范围,跨过去就不是本循环的 break
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                              ast.For, ast.AsyncFor, ast.While)):
            continue
        # 命中 break/continue 就说明这个循环有提前退出
        if isinstance(child, (ast.Break, ast.Continue)):
            return True
        pending.extend(ast.iter_child_nodes(child))
    return False


def _needs_loop_comment(node):
    """这个循环要不要注释。

    简单单句 `for` 不要求 —— 读一行就知道在遍历什么。只有 `while`(退出条件要解释)、
    体 ≥ 3 条语句(一轮做几件事)、或含 `break` / `continue`(提前退出要解释)才算复杂循环。

    Args:
        node: 循环节点。

    Returns:
        需要注释时为 True。
    """
    return (
        # while 的退出条件一般不是「遍历完就停」,必须说明何时停
        isinstance(node, ast.While)
        # 循环体一轮做三件以上的事,读者需要一句总述
        or len(node.body) >= 3
        # 有提前退出/跳过,控制流不再是单纯的「每条都做」
        or _has_loop_control(node)
    )


def _attributes_documented(tree):
    """类 docstring 用 `Attributes:` 交代过字段的行号。

    字段的说明有两条合法落点:字段自己的上方/行尾,或类 docstring 的 `Attributes:` 小节。
    写了小节就把这批字段从「缺注释」里豁免,避免同一件事写两遍。

    Args:
        tree: 模块的 ast 节点。

    Returns:
        已由 `Attributes:` 小节覆盖的 `AnnAssign` 行号集合。
    """
    rows = set()
    # 遍历全部节点,只处理写了 Attributes: 小节的类
    for node in ast.walk(tree):
        # 只有类才有 Attributes 小节
        if not isinstance(node, ast.ClassDef):
            continue
        # 类文档没写 Attributes: 就谈不上豁免
        if 'Attributes:' not in (ast.get_docstring(node) or ''):
            continue
        # 只认类体直接声明的带注解字段,方法内部的赋值不算
        for stmt in node.body:
            # 字段必须是裸名字上的注解赋值
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                rows.add(stmt.lineno)
    return rows


def simple_facts(tree):
    """收集循环、字段、算式赋值、空异常块,以及保留作诊断的 raise / return。

    前四类参与注释规则;`raises` 与 `returns` 只保留事实,失败前提与返回口径
    归 docstring。六类都只要一个行号,所以单遍 `ast.walk` 一次收齐。

    Args:
        tree: 模块的 ast 节点。

    Returns:
        `(loops, raises, fields, assigns, returns, silent_lines)` 六元组。
    """
    loops, raises, fields, assigns, returns, silent = [], [], [], [], [], []
    # 类 docstring 已用 Attributes: 交代过的字段,不再逐字段要注释
    documented = _attributes_documented(tree)
    # 六类构造互不依赖,所以共用这一遍遍历
    for node in ast.walk(tree):
        # 只有复杂循环才要求说明;简单单句 for 不增加阅读负担
        if (
            isinstance(node, (ast.For, ast.AsyncFor, ast.While))
            and _needs_loop_comment(node)
        ):
            loops.append(SimpleFact(line=node.lineno, label='', accepts_inline=False))
        # 抛异常事实只作诊断;失败前提归 docstring 的 Raises:
        if isinstance(node, ast.Raise):
            raises.append(SimpleFact(line=node.lineno, label='', accepts_inline=False))
        # 字段是「这个数是什么、什么单位」的唯一落点
        if (
            # 带注解的赋值
            isinstance(node, ast.AnnAssign)
            # 目标是裸名字(给属性加注解是另一回事)
            and isinstance(node.target, ast.Name)
            # 类 docstring 的 Attributes: 小节已经交代过,不必再写一遍
            and node.lineno not in documented
        ):
            fields.append(SimpleFact(line=node.lineno, label=node.target.id,
                                     accepts_inline=True))
        # 算出来的变量:名字说「是什么」,注释才说「怎么来的」
        if (
            # 普通赋值节点且具有明确赋值目标
            isinstance(node, ast.Assign)
            # 右侧是运算/调用/三元/比较 —— 字面量赋值不要求注释
            and isinstance(node.value, _COMPUTED_ASSIGN)
        ):
            names = [item.id for item in node.targets if isinstance(item, ast.Name)]
            # 目标是属性或下标时没有「变量名」可报,这类赋值跳过
            if names:
                assigns.append(SimpleFact(line=node.lineno, label=','.join(names),
                                          accepts_inline=True))
        # 算式 return 事实只作诊断;返回口径归 docstring 的 Returns:
        if (
            # return 语句
            isinstance(node, ast.Return)
            # 且返回的是算式,不是裸变量或常量
            and isinstance(node.value, _COMPUTED_RETURN)
        ):
            returns.append(SimpleFact(line=node.lineno, label='', accepts_inline=True))
        # 空 except 块让失败态与正常态同形,是最难查的一类 bug
        if isinstance(node, ast.Try):
            _try_facts(node, silent)
    return loops, raises, fields, assigns, returns, silent
