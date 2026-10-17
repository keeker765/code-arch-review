"""目录级检查:平铺过多的包、跨目录重名的模块、包内互导与导入顺序。

这些都不是单文件能看出来的 —— 每个文件本身都合规,合在一起却无法导航或缠成网。
所以它们**不参与覆盖率**:分母是「该解释的构造」,而这里量的是目录与依赖形状。
"""

import sys

# py-structure: allow-sibling-imports —— 同目录判据模块是这个 skill 的结构
from .model import Finding
from .rules import RULES


def package_shape(paths, max_modules, reserved):
    """按目录归堆,查平铺过多与跨目录重名。

    名字里的保留项是**语言规定的**,不是作者选的,所以两条规则对它们都不成立:
    `__init__.py` 标记包、`index.ts` 是目录入口,它们从不出现在 import 语句里
    (引用它们只能通过包名/目录名),而 `flat-package` 数的是「要读几个模块才看得懂这一层」,
    入口文件是一个十来行的转发壳,不是一个要读的模块。
    **按「哪种推断不成立」写规则,不是按「哪种东西」写规则** —— 只豁免一个名字
    而理由是「它特殊」,换个语言就会漏掉它的对偶。

    Args:
        paths: 本次扫描到全部目标文件(已按语言筛过)。
        max_modules: 一个目录里允许平铺的模块数上限。
        reserved: 该语言的保留文件名集合。

    Returns:
        违规列表,字段与单文件规则一致。
    """
    found = []
    groups = {}
    names = {}
    # 按所在目录归堆,同时记下每个 basename 出现在哪些目录
    for path in paths:
        groups.setdefault(path.parent, []).append(path)
        # 保留文件名由语言机制决定,不参与跨目录同名冲突检测
        if path.name not in reserved:
            names.setdefault(path.name, []).append(path.parent)

    # 逐目录检查平铺数量:每个目录是独立作用域,必须独立汇总其非保留模块总数
    for folder, members in sorted(groups.items()):
        modules = [item for item in members if item.name not in reserved]
        # 有子包说明作者已经在分组了,只看这一层平铺了多少
        if len(modules) > max_modules:
            found.append(Finding(
                path=str(folder), line=1, rule='flat-package',
                detail=f'{len(modules)} 个模块平铺在同一层 > {max_modules}',
                why=RULES['flat-package']))

    # 跨目录同名会造成导入歧义与阅读误导,同名出现在两个及以上目录时报警
    for name, folders in sorted(names.items()):
        # 只出现在一个目录的名字不构成歧义
        if len(folders) <= 1:
            continue
        # 取前 3 个目录路径格式化为逗号分隔文本,作为违规位置展示
        where = ', '.join(str(folder) for folder in sorted(folders)[:3])
        found.append(Finding(
            path=where, line=1, rule='duplicate-basename',
            detail=f'{name} 出现在 {len(folders)} 个目录',
            why=RULES['duplicate-basename']))
    return found


def test_imports(facts_list):
    """测试模块之间互相 import 的判定。

    **必须是跨文件规则**:判据是「import 的名字能不能解析到本次扫描到的另一个测试模块」,
    单看一个文件分不出 `from test_options import ...`(同目录的兄弟测试模块,该报)
    与 `from aiohttp.test_utils import ...`(第三方包名尾巴恰好带 `test_`,不该报)。

    只比对**文件名主干**:`from tests.test_x import` 的顶层名是 `tests`,不是 `test_x`,
    而 `from test_x import` 的顶层名才是模块本身 —— 两种写法都指向同一个测试模块,
    所以两侧都按「文件名去掉 .py」归一后再比。

    Args:
        facts_list: 本次扫描到的全部文件事实。

    Returns:
        违规列表。
    """
    # 先收齐本次扫到的测试模块主干名,再拿它当白名单去比对导入
    test_modules = {facts.path.stem for facts in facts_list if facts.test_kind == 'module'}
    found = []
    # 白名单已经收齐,逐个文件看它导入了谁;遍历顺序不影响结果,报出顺序按扫描顺序
    for facts in facts_list:
        # 只查测试模块:辅助文件与 conftest 之间的导入是正常组织方式
        if facts.test_kind != 'module':
            continue
        # 同一个模块名在多处出现时,按行号逐个报,便于读者定位
        for line, name in facts.imports:
            # 导入自己不算互相导入
            if name == facts.path.stem:
                continue
            # 解析不到本次扫描内的测试模块 —— 是第三方包或普通模块,不报
            if name not in test_modules:
                continue
            found.append(Finding(
                path=str(facts.path), line=line, rule='test-import-test',
                detail=f'import 了另一个测试模块 `{name}`',
                why=RULES['test-import-test']))
    return found


def import_structure(facts_list, reserved):
    """判包内模块互导、导入分组顺序与一行多个 import。

    这些判据要拿**同目录的其他文件**当白名单,所以是跨文件规则;只有后端填了
    `import_details` 的语言才会命中(目前只有 Python)。`sibling-import` 只对
    **有 `__init__.py` 的包目录**生效 —— 脚本目录里 `run.py` 导入同层的 `helper.py`
    是正常组织方式,不是依赖成网。`__init__.py` 豁免平级互导,因为它是包的公开出口;
    相对导入指向包内同层模块时按平级导入处理。

    Args:
        facts_list: 本次扫描到的全部文件事实。
        reserved: 该语言的保留文件名集合。

    Returns:
        违规列表。
    """
    groups = {}
    # 按目录归堆:平级关系只存在于同一层
    for facts in facts_list:
        # 非路径事实(理论上没有)跳过,不让它中断整批
        if not hasattr(facts.path, 'parent'):
            continue
        groups.setdefault(facts.path.parent, []).append(facts)
    found = []
    # 逐目录判:同层的模块名集合是这一层所有文件共享的白名单
    for folder, members in sorted(groups.items(), key=lambda item: str(item[0])):
        # 只有包目录才有平级互导问题;脚本目录不受这条约束
        is_package = (folder / '__init__.py').is_file()
        # 本层非保留模块的主干名;非包目录不需要白名单
        stems = {item.path.stem for item in members if item.path.name not in reserved} \
            if is_package else set()
        dirname = folder.name
        # 逐文件判:每个文件都要拿本层白名单比对
        for facts in members:
            found.extend(_file_import_findings(facts, stems, dirname, is_package))
    return found


def _file_import_findings(facts, stems, dirname, is_package):
    """判一个文件的导入结构。

    平级互导按「导入的模块是不是同目录的另一个文件」判,只在包目录生效;
    顺序判据只对绝对导入生效,相对导入已经由平级互导覆盖,再按分组报一次只是重复。

    Args:
        facts: 一个文件的事实。
        stems: 同目录非保留模块主干名;非包目录为空集。
        dirname: 当前目录名。
        is_package: 该目录是不是包(有 `__init__.py`)。

    Returns:
        违规列表。
    """
    found = []
    # 导入自己不算平级互导
    siblings = stems - {facts.path.stem}
    # __init__.py 是包的公开出口,豁免平级互导
    is_init = facts.path.name == '__init__.py'
    # 文件头声明豁免时只去掉平级互导;排序与一行多个仍然照查
    allow_sibling = getattr(facts, 'allow_sibling_imports', False)
    ordered = []
    # 同一行同一规则只报一次
    seen = set()
    # 一行多个 import 与 Google 3.13 冲突
    for line in facts.multi_import_lines:
        found.append(Finding(
            path=str(facts.path), line=line, rule='multi-import',
            detail='一行写了多个 import', why=RULES['multi-import']))
    # 非包目录、文件头声明豁免或 __init__.py 时不判平级互导
    sibling_allowed = is_package and not is_init and not allow_sibling
    # 逐条顶层导入判平级互导,并攒排序素材
    for line, module, level, names in facts.import_details:
        # 相对导入:只有一级指向当前目录,里面的名字才可能是平级模块
        if level > 0:
            # 豁免文件与 __init__.py 不判平级互导
            if sibling_allowed:
                _check_relative(found, seen, facts, line, module, level, names, siblings)
            continue
        # 绝对导入:裸名与「包名.兄弟」都可能是平级互导
        if sibling_allowed:
            # 命中同层模块时记一条违规
            if _is_sibling(module, siblings, dirname):
                _append_sibling(found, seen, facts, line, module, names)
        ordered.append((line, module, _group(module)))
    found.extend(_ordering_findings(facts.path, ordered))
    return found


def _check_relative(found, seen, facts, line, module, level, names, siblings):
    """判一条相对导入,命中平级模块时记违规。

    只有一级相对导入指向当前目录;更深的指向父包,由相对导入判据负责,
    不在平级互导这里重复。

    Args:
        found: 违规列表,原地追加。
        seen: 已报过的 (行号, 规则) 集合。
        facts: 当前文件事实。
        line: 导入行号。
        module: 模块路径,可能为空。
        level: 相对级别。
        names: 被导名字元组。
        siblings: 同目录非保留模块主干名。
    """
    # 只有命中平级模块才记违规
    if _relative_sibling(level, module, names, siblings):
        _append_sibling(found, seen, facts, line, module, names)


def _append_sibling(found, seen, facts, line, module, names):
    """把一条平级互导违规追加到结果里。

    同一行可能被多个名字命中(`from . import a, b`),按 (行号, 规则) 去重,
    只报一条。模块路径为空时用被导名字做说明。

    Args:
        found: 违规列表,原地追加。
        seen: 已报过的 (行号, 规则) 集合。
        facts: 当前文件事实。
        line: 导入行号。
        module: 模块路径,可能为空。
        names: 被导名字元组。
    """
    key = (line, 'sibling-import')
    # 同一行已经报过就跳过
    if key in seen:
        return
    seen.add(key)
    # 说明里优先用模块路径,`from . import x` 没有路径时用名字
    label = module or ', '.join(names)
    found.append(Finding(
        path=str(facts.path), line=line, rule='sibling-import',
        detail=f'导入了平级模块 `{label}`',
        why=RULES['sibling-import']))


def _relative_sibling(level, module, names, siblings):
    """判一级相对导入是否指向平级模块。

    `from .x import y` 看模块路径的第一段;`from . import x` 看被导的名字。
    两级以上的相对导入指向父包,不算平级。

    Args:
        level: 相对级别。
        module: 点号之后的模块路径,可能为空。
        names: 被导名字元组。
        siblings: 同目录非保留模块主干名。

    Returns:
        True 表示指向平级模块。
    """
    # 只有一级相对导入指向当前目录
    if level != 1:
        return False
    # 有模块路径时看第一段
    if module:
        # 返回值口径:模块路径第一段是否是同目录模块
        return module.split('.')[0] in siblings
    # `from . import x`:被导的名字本身可能就是模块
    # 返回值口径:被导名字里是否有同目录模块
    return any(name in siblings for name in names)


def _is_sibling(module, siblings, dirname):
    """判绝对导入是否指向同目录模块。

    裸名的根名直接是模块;全路径要前一段等于本目录名。

    Args:
        module: 点分模块路径。
        siblings: 同目录非保留模块主干名。
        dirname: 当前目录名。

    Returns:
        True 表示指向平级模块。
    """
    parts = [part for part in module.split('.') if part]
    # 空模块路径没有可判的东西
    if not parts:
        return False
    # 裸写法:根名就是同目录的模块
    if parts[0] in siblings:
        return True
    # 全路径写法:前一段是本目录名、末段是兄弟模块
    # 返回值口径:是否命中「包名.兄弟」这种全路径写法
    return len(parts) > 1 and parts[-2] == dirname and parts[-1] in siblings


def _group(module):
    """给导入分组:Google 3.13 的 future → 标准库 → 其余。

    第三方与本仓库从写法上分不开,合并成最后一组;组内不查字典序,
    否则 `from book...`(本仓库)与 `import cryptography`(第三方)的先后会被误判。

    Args:
        module: 点分模块路径。

    Returns:
        组号,越小越靠前。
    """
    root = module.split('.')[0]
    # future 永远在最前
    if root == '__future__':
        return 0
    # 标准库用运行时清单判断,不维护自己的名单
    if root in sys.stdlib_module_names:
        return 1
    # 其余(第三方与本仓库)归最后一组
    return 2


def _ordering_findings(path, ordered):
    """判分组顺序与 future/标准库两组的组内字典序。

    第三方与本仓库在写法上分不开,混在最后一组、组内不查字典序。

    Args:
        path: 文件路径。
        ordered: (行号, 模块路径, 分组) 列表,按源码顺序。

    Returns:
        违规列表。
    """
    found = []
    # 相邻比较:组号必须非递减
    for previous, current in zip(ordered, ordered[1:]):
        _, prev_key, prev_group = previous
        line, curr_key, curr_group = current
        # 组号倒退:标准库写在了外部导入之后
        if curr_group < prev_group:
            found.append(Finding(
                path=str(path), line=line, rule='import-order',
                detail=f'`{curr_key}` 应排在 `{prev_key}` 之前(分组顺序)',
                why=RULES['import-order']))
            continue
        # 跨组不查字典序
        if curr_group != prev_group:
            continue
        # 组内字典序只查 future 与标准库两组
        if curr_group not in (0, 1):
            continue
        # 当前键小于前一个键就是逆序,忽略大小写
        if curr_key.lower() < prev_key.lower():
            found.append(Finding(
                path=str(path), line=line, rule='import-order',
                detail=f'`{curr_key}` 应排在 `{prev_key}` 之前(组内字典序)',
                why=RULES['import-order']))
    return found
