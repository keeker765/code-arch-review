"""目录级检查:平铺过多的包,以及跨目录重名的模块。

这两项都不是单文件能看出来的 —— 每个文件本身都合规,合在一起却无法导航。
所以它们**不参与覆盖率**:分母是「该解释的构造」,而这里量的是目录形状。
"""

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
