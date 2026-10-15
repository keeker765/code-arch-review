"""测试代码的识别与测试特有的事实抽取。

**为什么单独一层**:「什么算测试」是 Python 这门语言的**生态知识**(pytest 认什么文件名、
什么函数名、`unittest` 的 pattern 是什么),不是通用规则知识 —— 与「Python 的 `#` 怎么扫」
同类,所以按现有分层放进语言后端。别的语言将来各自实现一份,从这份推导。

🔴 **判据必须两级,混成一级必错**:

* **目录判归属** —— 路径里出现 `test` / `tests` / `testing` 段,说明这一整块是测试区;
* **文件名判是不是测试模块** —— 只有命中 pytest `python_files` 默认值(`test_*.py` /
  `*_test.py`)的文件才是测试模块。

只按目录判,`tests/helpers.py`、`tests/strategies.py`、`tests/conftest.py` 这些
**在测试目录里但不是测试模块**的文件会被按测试口径豁免;只按文件名判,则漏掉
自定义 `python_files` 的项目。两者各管一段。

口径与 pytest 的默认值对齐(pytest 认什么,这里就认什么),不另立一套:
`python_files = test_*.py *_test.py`、`python_functions = test*`。

🔴 **不按「有没有 `unittest.TestCase` 子类」判是不是测试文件**:实测这一条会误报。
pytest 收集的是**所有** `unittest.TestCase` 子类,而继承链可能跨模块(`class
FilesConfigTest(base.BaseTestCase)` 里基类在 pbr 包里、又继承 testtools),
类也可能被 `as` 改名(`from unittest import TestCase as NonLeakingTestCase`)——
静态判不准,就会把这类标准写法判成「一个用例都收不到」。而文件名这条判据
pytest 自己是硬闸:名字不匹配的文件它根本不看,所以按文件名判既准确又简单。
"""

import ast

# pytest `python_files` 的默认值 —— 两边都收,没有「哪个才对」
_TEST_PREFIX = 'test_'
_TEST_SUFFIX = '_test.py'

# 目录归属:路径里出现这几段就说明进了测试区。
# `t` 不在里面 —— celery 用 `t/unit` 是它的项目约定,不是通行写法,收进来会误判
_TEST_DIR_NAMES = frozenset({'test', 'tests', 'testing'})

# 测试基础设施的文件名。它提供 fixture 而不是测试用例,不该被要求「有可收集的测试项」
CONFTEST = 'conftest.py'

# `test_kind` 的四种取值。空串表示这不是测试相关文件
KIND_NONE = ''
KIND_MODULE = 'module'
KIND_CONFTEST = 'conftest'
KIND_HELPER = 'helper'

# 改 sys.path 的两个方法名 —— `sys.path.insert(0, ...)` 与 `sys.path.append(...)`
_SYSPATH_METHODS = frozenset({'insert', 'append'})

# 语句块容器:块里的名字绑定仍落在模块作用域里,数用例时要往里走一层。
# 函数体与类体不在此列 —— 那里面定义的东西 pytest 在模块命名空间里看不到
_SCOPE_CONTAINERS = (ast.If, ast.Try, ast.With, ast.AsyncWith,
                     ast.For, ast.AsyncFor, ast.While)


def in_test_dir(path):
    """这个文件在不在测试目录里。

    这是**判归属**而不是判「是不是测试模块」:目录名相符的文件可能是共享辅助
    (`tests/helpers.py`),它既不该被要求提供用例,也不该被豁免注释要求。两者混成
    一级是这套判据最容易写错的地方,所以这里只回答「在不在」,是不是测试模块看文件名。

    Args:
        path: 文件路径。

    Returns:
        路径的**任何一层**目录名是测试目录时返回 True。
    """
    # 看除文件名以外的所有路径段:测试目录可能嵌套很深(`tests/unit/api/`)
    return any(part in _TEST_DIR_NAMES for part in path.parts[:-1])


def test_kind(path):
    """这个文件属于哪一类测试相关文件。

    分类的用途是**分工**:测试模块才被要求「有可收集的用例」,`conftest.py` 与共享辅助
    不被要求;反过来 `test-import-test` 又只认测试模块之间的互相导入。所以这一层必须
    比 `in_test_dir` 更细 —— 目录只说明归属,文件名才说明角色。

    只看文件名、不看 AST:是不是测试模块由 pytest 的 `python_files` 决定,而那是一条
    纯文件名判据。想从语法里再补一条,就会踩到跨模块继承与 `as` 改名这两个坑(见模块
    docstring),把 `tests/base.py` 这类共享基类误判成「零用例的测试模块」。

    Args:
        path: 文件路径。

    Returns:
        `KIND_MODULE` / `KIND_CONFTEST` / `KIND_HELPER` / `KIND_NONE` 之一。
    """
    name = path.name
    # conftest 是基础设施,优先级高于一切 —— 它既不是测试模块也不该被当普通辅助文件
    if name == CONFTEST:
        return KIND_CONFTEST
    # `test_*.py` 是 pytest 默认 pattern,在哪一层目录都算测试模块
    if name.startswith(_TEST_PREFIX):
        return KIND_MODULE
    # `*_test.py` 是另一条默认 pattern,两类文件名地位相同
    if name.endswith(_TEST_SUFFIX):
        return KIND_MODULE
    # 名字不像测试,但人在测试目录里:是共享辅助(helpers / strategies / 假数据工厂)
    if in_test_dir(path):
        return KIND_HELPER
    return KIND_NONE


def _is_collectable_function(node):
    """这个函数会不会被 pytest 当测试用例收集。

    `python_functions` 默认值是 `test*` —— 是**前缀**不是 `test_`,所以 `testfoo`
    也会被收集。按 `test_` 判会漏掉那一类,并把「一个都收不到」误报成「有测试项」。

    Args:
        node: 函数定义节点。

    Returns:
        名字以 `test` 开头时返回 True。
    """
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test')


def _is_collectable_name(name):
    """这个名字会不会被 pytest 当用例收走。

    函数与类各有一条默认前缀(`test*` / `Test*`),两条都要认:只认小写会把
    `class TestFoo:` 这种标准写法算成零用例。

    Args:
        name: 模块命名空间里的名字。

    Returns:
        命中 `test*` 或 `Test*` 前缀时返回 True。
    """
    return name.startswith('test') or name.startswith('Test')


def _assigned_names(node):
    """一条赋值在模块命名空间里绑定了哪些裸名字。

    解包(`a, b = ...`)要逐个算;属性与下标赋值(`obj.x = ...`、`d[k] = ...`)
    不产生新的模块级名字,不算。判据要跟 pytest 一致 —— 它收的是命名空间里的名字,
    `TestDraft = Suite().to_testcase()` 这种动态生成正是靠这条被收走的。

    Args:
        node: `ast.Assign` 或 `ast.AnnAssign` 节点。

    Returns:
        绑定到的名字列表。
    """
    # Assign 有 targets 列表,AnnAssign 只有一个 target —— 归一成同一个形状
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = []
    # 逐个目标拆:元组/列表目标是解包,里面每个 Name 都是一个新名字
    for target in targets:
        names.extend(item.id for item in ast.walk(target) if isinstance(item, ast.Name))
    return names


def _bound_items(node):
    """一条语句在模块命名空间里留下几个名字像用例的绑定。

    分三种:类有自己的 `Test*` 前缀,方法还可以再各算一个;函数看 `test*` 前缀;
    赋值是动态生成用例的入口(`TestDraft = Suite().to_testcase()`)。其余语句
    不绑定名字,一律 0。

    Args:
        node: 一条语句。

    Returns:
        这条语句产生的收集项个数。
    """
    # 类:类名按 `Test*` 收,类里的 `test*` 方法各算一个 —— 两者都算,不相加去重
    if isinstance(node, ast.ClassDef):
        # 类名自己算一个:命中 `Test*` 才算,`FilesConfigTest` 这种不算
        own = 1 if _is_collectable_name(node.name) else 0
        # 类名不像测试的类(如 `FilesConfigTest`)也可能整类都是用例,所以方法单独数
        methods = sum(1 for item in node.body if _is_collectable_function(item))
        # 两者相加:类充当容器,它的名字与被收集的方法是两个不同层面的东西
        return own + methods
    # 函数:模块级的 `test*` 函数是最常见的写法
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # 命中 `test*` 前缀才算,其余函数(夹具/辅助)一个都不算
        hits = 1 if _is_collectable_name(node.name) else 0
        return hits
    # 赋值:动态生成的用例类/函数就是靠这一步进命名空间的
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        # 只数名字像用例的那几个;普通的数据变量不算
        return sum(1 for name in _assigned_names(node) if _is_collectable_name(name))
    # 其余语句(import / 表达式 / 控制流的头)都不在模块命名空间里留用例名
    return 0


def _inner_blocks(node):
    """一条语句内部还有哪些段语句属于**模块作用域**。

    只有 `if` / `try` / `with` / 循环这些块容器有:Python 没有块级作用域,它们块里的
    绑定照样落在模块命名空间里,pytest 照样收 —— 实测 `if cond: def test_x()`
    这种按平台裁剪用例的写法漏掉过一次。函数体与类体不返回,那里面定义的东西
    两种收集器在模块命名空间里都看不见。

    Args:
        node: 一条语句。

    Returns:
        各段语句的列表;不是块容器时为空元组。
    """
    # 不是块容器就没有内部语句段可走
    if not isinstance(node, _SCOPE_CONTAINERS):
        return ()
    # body / orelse / finally 三段用同一个取法,缺哪段就当空;散在各节点类型上的差异不必逐个判
    blocks = [node.body, getattr(node, 'orelse', ()), getattr(node, 'finalbody', ())]
    # except 处理器的体各算一段 —— `try: import x / except: def test_x()` 是真实写法
    blocks.extend(handler.body for handler in getattr(node, 'handlers', ()))
    return blocks


def _collected_in(body):
    """一段模块作用域语句能数出多少个收集项。

    分「这条语句自己绑定的」与「它块体里绑定的」两部分相加,两块各自递归下去 ——
    写成一条语句一个函数,是因为 `_collected_in` 只需要管「怎么把一段数完」,
    不必知道任何具体语句类型,那部分知识全在 `_bound_items` 与 `_inner_blocks` 里。

    Args:
        body: 语句列表。

    Returns:
        这一段里名字像用例的定义/赋值个数。
    """
    count = 0
    # 逐条语句算绑定,块容器再把它内部的各段递归数一遍
    for node in body:
        count += _bound_items(node)
        # 块容器才有内部语句段,不是块容器时这里拿到空元组,循环一次都不进
        for block in _inner_blocks(node):
            count += _collected_in(block)
    return count


def collectable_count(tree):
    """这个文件里有多少个名字像测试用例的东西。

    **只按名字与绑定数**,不问「这个类到底会不会被 pytest 收走」。后者要沿继承链跨
    模块解析(`class FilesConfigTest(base.BaseTestCase)` 的基类在别的包里,还带着
    `as` 改名),静态判不准,于是正常写法会被判成「零用例」。宁可漏判不可误报:
    这条规则要抓的是「把 `test_` 手滑改成 `make_` 之后没有一个用例在跑」,
    而不是对类继承与动态生成说三道四。

    Args:
        tree: 模块的 AST。

    Returns:
        可收集的测试项个数。
    """
    return _collected_in(tree.body)


def syspath_lines(tree):
    """文件里改 `sys.path` 的行号。

    判 `test-syspath` 用。`sys.path.insert(0, ...)` 与 `sys.path.append(...)` 都会
    让「测的是哪一份代码」取决于执行顺序 —— 在 tox / CI 里表现为莫名其妙的通过或失败。
    pytest 官方给的替代是 `pythonpath` 配置项与 `--import-mode=importlib`,不必手改路径。

    Args:
        tree: 模块的 AST。

    Returns:
        改 `sys.path` 的语句所在行号列表(可能重复,调用方按需去重)。
    """
    rows = []
    # 调用可以出现在任意表达式里(比如塞进 `if` 的判断),所以走整棵树而不只看语句
    for node in ast.walk(tree):
        # 形态:`sys.path.<method>(...)` —— 调用、属性名在 _SYSPATH_METHODS 里、
        # 且被取属性的对象是 `sys.path`
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # 只可能是属性访问:名字直接调用的(`path_insert(...)`)改不到 sys.path
        if not isinstance(func, ast.Attribute):
            continue
        # 方法名必须正好是 insert 或 append —— 读路径(`sys.path.copy()`)不算改路径
        if func.attr not in _SYSPATH_METHODS:
            continue
        # `func.value` 要正好是 `sys.path` 这个属性访问,别的链式访问不算
        if ast.unparse(func.value) == 'sys.path':
            rows.append(node.lineno)
    return rows


def imported_modules(tree):
    """文件 import 了哪些顶层模块名。

    判 `test-import-test` 用:测试模块之间互相 import 会让「共享工具放哪」变成隐式约定,
    而 `--import-mode=importlib` 下测试模块根本不能被 import(官方原文)。
    共享工具该进 `conftest.py` 或一个非 `test_` 命名的模块。

    只记顶层名字(`from a.b import c` 记 `a`),因为跨文件的判定要拿它去比对
    本次扫描到的测试模块名 —— 比对全路径会漏掉 `from tests.test_x import ...` 这种写法。

    Args:
        tree: 模块的 AST。

    Returns:
        `[(行号, 顶层模块名)]`,按出现顺序。
    """
    found = []
    # import 可以写在函数体里,所以走整棵树而不是只扫模块顶层语句
    for node in ast.walk(tree):
        # `from X import ...`:X 可能是 `a.b.c`,取第一段
        if isinstance(node, ast.ImportFrom):
            # 相对导入(`from . import x`)没有顶层名,不参与跨模块判定
            if node.module:
                found.append((node.lineno, node.module.split('.')[0]))
            continue
        # `import a.b`:每个别名各记一条,取第一段
        if isinstance(node, ast.Import):
            # `import a.b, c.d` 一行多个别名,逐个拆开各记一条
            for alias in node.names:
                found.append((node.lineno, alias.name.split('.')[0]))
    return found


def test_facts(path, tree):
    """把测试相关的全部事实一次抽齐。

    返回一个字典而不是多个函数各遍历一遍 AST:这四个问题共用同一次树遍历,
    分成四次 `ast.walk` 只是白花三倍时间,和 `structure.simple_facts` 同一个理由。

    Args:
        path: 文件路径。
        tree: 已解析的模块 AST。

    Returns:
        含 `test_kind` / `collectable` / `syspath_lines` / `imports` 四个键的字典。
    """
    return {
        'test_kind': test_kind(path),
        'collectable': collectable_count(tree),
        'syspath_lines': syspath_lines(tree),
        'imports': imported_modules(tree),
    }
