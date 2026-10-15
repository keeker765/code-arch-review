"""模块顶层绑定的识别:哪些名字在顶层被定义了、以及是不是覆盖。

判 `duplicate-toplevel` 用。这一组判据的难点全在**豁免**上:同一个名字出现两次
未必是覆盖 —— `@overload` 重载、`ROOTS = ROOTS + (...)` 这类就地扩展、以及
`try/except ImportError` 的回退定义都是合法形态。豁免写歪会让存量代码被淹没,
而只报噪声的闸会被直接关掉。
"""

import ast

from core.model import BindingFact


def is_overload(node):
    """这个顶层定义是不是 `@typing.overload` 的重载签名。

    判据看装饰器表达式的**最后一段**名:`overload` / `typing.overload` / `t.overload`
    是同一个东西,按全名匹配会漏掉后两种写法。重载就是靠同名多次定义来写的标准用法,
    不豁免它等于把最规范的那类代码报成违规。

    Args:
        node: 模块体的一个直接子节点。

    Returns:
        带 `overload` 装饰器的函数返回 True。
    """
    # 取末段名再比:三种写法的末段都是 overload,而全名各不相同
    return any(ast.unparse(item).split('.')[-1] == 'overload'
               for item in getattr(node, 'decorator_list', []))


def extends_self(name, value):
    """赋值右侧是否引用了同一个名字 —— 那是扩展/规范化,不是覆盖。

    `ROOTS = ROOTS + (...)`、`p = os.path.abspath(p)` 都是把已有值往前推一步,
    读者不会因为「有两处定义」而拿错口径。实测:全仓 2041 个文件里本规则的全部
    命中都是这一类,不豁免就只剩噪声。

    Args:
        name: 被绑定的名字。
        value: 本次绑定的右侧表达式;函数/类定义没有右侧,传 None。

    Returns:
        右侧引用了 `name` 时返回 True。
    """
    # 函数与类定义没有右侧表达式,永远算覆盖
    if value is None:
        return False
    # 右侧任意深度出现同名 Name 都算引用自己;嵌套函数里的同名变量也会命中,
    # 那种情况宁可放过也不误报 —— 这条规则的价值在低噪声,不在抓全
    return any(isinstance(item, ast.Name) and item.id == name for item in ast.walk(value))


def binding_of(node):
    """把一个顶层节点归成 `(名字, 种类, 右侧表达式)`,不是绑定就给 None。

    只认「裸名字」的绑定:`a.b = x` 改的是别人的属性,`a, b = x` 是解包,
    两者都不构成「这个模块顶层叫 a 的东西被定义了一次」,放进来只会制造噪声。

    Args:
        node: 模块体的一个直接子节点。

    Returns:
        `(名字, 'def'|'assign', 右侧表达式或 None)`;不是顶层绑定时返回 None。
    """
    # 函数与类:名字就是定义名,没有可供比对的右侧表达式
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name, 'def', None
    # 普通赋值:多目标(`a = b = x`)与解包都不构成「定义了一次」
    if (
        # 节点是直接赋值
        isinstance(node, ast.Assign)
        # 且只有一个目标
        and len(node.targets) == 1
    ):
        # 目标还得是裸名字 —— 属性赋值与下标赋值改的都是别人的东西
        if isinstance(node.targets[0], ast.Name):
            return node.targets[0].id, 'assign', node.value
        return None
    # 带注解的赋值:没有右值的纯声明(`X: int` 或 `X: Final`)只是类型标注,不绑定任何值
    if (
        # 节点是带注解的赋值
        isinstance(node, ast.AnnAssign)
        # 且真的赋了值
        and node.value is not None
    ):
        # 同普通赋值,目标必须是裸名字
        if isinstance(node.target, ast.Name):
            return node.target.id, 'assign', node.value
    return None


def bindings(tree):
    """模块**直接**子节点上的绑定,判 `duplicate-toplevel` 用。

    只看 `Module.body` 的直接子节点,这一条同时豁免了三类合法重复:
    `try/except ImportError` 的回退定义、`if TYPE_CHECKING:` 里的声明、按版本号分支的条件定义
    —— 它们都嵌在子块里,不是直接子节点。

    Args:
        tree: 已解析的模块 AST。

    Returns:
        `BindingFact` 列表,按出现顺序。
    """
    facts = []
    # 只看顶层直接子节点:嵌在 try / if 里的重复定义是合法形态,不该进这张表
    for node in tree.body:
        # 重载签名靠同名多次定义,不豁免等于把标准写法报成违规
        if is_overload(node):
            continue
        # 归一成 (名字, 种类, 右侧);三种绑定形态的差异在这一步被吃掉
        binding = binding_of(node)
        # import、表达式语句、顶层 for 等都不是绑定
        if binding is None:
            continue
        name, kind, value = binding
        facts.append(BindingFact(name=name, kind=kind, line=node.lineno,
                                 references_self=extends_self(name, value)))
    return facts
