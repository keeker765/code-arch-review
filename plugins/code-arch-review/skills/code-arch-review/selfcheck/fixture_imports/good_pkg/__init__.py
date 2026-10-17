"""合规包:模块之间不互导,`__init__.py` 用完整包名 re-export。

这是导入结构判据的阴性对照:平铺数量在上限内、没有平级互导、导入顺序正确。
"""

from good_pkg.one import X
