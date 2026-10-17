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

# 右侧算「算出来的」的表达式类型 —— 字面量赋值没什么可解释的
_COMPUTED_ASSIGN = (ast.BinOp, ast.Call, ast.IfExp, ast.Compare)

# return 一个算式才要求注释:`return x` / `return None` 不算
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


def operands(test):
    """把条件摊平成一个个独立判据。

    `a and b` 是**两个**判据不是一个。嵌套里每一个都要单独说明,
    因为每一个都是一次「判不过就走另一条路」的分叉 —— 而「判不过会怎样」
    正是闸要求写在注释里的东西。

    Args:
        test: If 节点的 test 表达式。

    Returns:
        判据节点列表;非布尔组合时就是它自己一个。
    """
    # 布尔组合递归摊平;`and` 与 `or` 一样处理,闸只关心「有几个分叉」
    if isinstance(test, ast.BoolOp):
        return [item for value in test.values for item in operands(value)]
    return [test]


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
    """产出每个函数体内的 if/elif 及其摊平后的子条件。

    模块层的 `if __name__ == ...` 不算 —— 那里没有业务判据。函数内的 if 一律算,
    **包括顶层守卫**(用户 2026-09-08 明确:顶层 `if self.source is not None` 也要注释)。
    elif 在 ast 里就是 orelse 里的 If,自动被覆盖。

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
    # 按物理行号升序遍历去重后的条件节点,收集各子条件行号事实
    for node in sorted(seen.values(), key=lambda item: item.lineno):
        facts.append(ConditionFact(
            line=node.lineno,
            # 摊平成子条件**所在的行**:同一行两个子条件就记两次,判「条件挤行」靠这个重复
            operand_lines=tuple(item.lineno for item in operands(node.test))))
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
    if (
        # 有位置参数
        bound
        # 且第一个是 self/cls
        and bound[0].arg in ('self', 'cls')
    ):
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
        if (
            # except 体只有一条语句
            len(handler.body) == 1
            # 且那条就是 pass —— 失败态与正常态同形
            and isinstance(handler.body[0], ast.Pass)
        ):
            silent.append(handler.lineno)


def simple_facts(tree):
    """收集循环、抛异常、字段、赋值、算式 return、空异常块。

    这六类构造的共同点是**只需要一个行号**:规则引擎会去那一行附近找注释,
    这里不做任何取舍。所以单遍 `ast.walk` 一次收齐 —— 分成六次遍历只是白花六倍时间。

    Args:
        tree: 模块的 ast 节点。

    Returns:
        `(loops, raises, fields, assigns, returns, silent_lines)` 六元组。
    """
    loops, raises, fields, assigns, returns, silent = [], [], [], [], [], []
    # 六类构造互不依赖,所以共用这一遍遍历
    for node in ast.walk(tree):
        # 循环是读者最需要知道「在遍历什么、为什么不能向量化」的地方
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            loops.append(SimpleFact(line=node.lineno, label='', accepts_inline=False))
        # 抛异常是把失败态交给调用方的地方,注释要写「什么前提被破坏了」
        if isinstance(node, ast.Raise):
            raises.append(SimpleFact(line=node.lineno, label='', accepts_inline=False))
        # 字段是「这个数是什么、什么单位」的唯一落点
        if (
            # 带注解的赋值
            isinstance(node, ast.AnnAssign)
            # 目标是裸名字(给属性加注解是另一回事)
            and isinstance(node.target, ast.Name)
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
        # return 一个算式:调用方拿到的口径必须写出来,不能靠反推表达式
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
