"""语言无关的规则引擎:吃 `model.FileFacts`,吐违规与覆盖率。

**为什么违规与覆盖率必须由同一个函数算出**:这两项从前各自由一套谓词算
(一个走扫描的分支,一个走覆盖率的分支),一度分叉过 ——
整个 `if` 只看前一行、行尾注释判断写反 —— 而**分叉时两个数都不报错**,
读者无法判断哪个是真的。

合并之后判据只剩两份,各在一个地方:**`text.explained()`** 判「这一行算不算已解释」
(本模块与 `coverage` 都调它),**`RULES`** 判「这条为什么是坏味道」(本模块与
`package` / `report` 都读它)。数分母的活单独在 `core/coverage.py`,它只数数,
判据仍调上面那一份,所以分叉在结构上不可能再发生。

`evaluate()` 只做编排:每一组规则的判据各自成函数,主流程只呈现阶段。
"""

from dataclasses import dataclass, field

# py-structure: allow-sibling-imports —— 同目录判据模块是这个 skill 的结构
from . import coverage
from .model import FileFacts, Finding
from .text import explained

RULES = {
    'long-function':   '函数体过长 —— 主流程该只呈现阶段,阶段内容归各自的方法',
    'fat-rule-block':  '单个规则块声明过多 —— 一个选择器管太多事,改动时看不出哪些声明是一组;'
                       '按职责拆成多个选择器,或把重复的值抽成共用变量',
    'many-kwargs':     '关键字参数过多 —— 调用方被迫组装被调用方的内部依赖',
    'dict-as-type':    '同一函数内多次按字符串键取值 —— 字段含义应写进数据类,不是键名',
    'deep-nesting':    '嵌套过深 —— 非法输入提前拒绝,别把正常路径包在多层 if 里',
    'no-docstring':    '公开类/函数缺文档注释 —— 读代码不该依赖作者口头解释',
    'thin-module-doc': '模块文档过薄 —— 需说明为什么存在、数据是什么、口径边界',
    'silent-except':   '异常被静默吞掉 —— 失败态与正常态同形,是最难查的一类 bug',
    'uncommented-condition': 'if/elif 链开头缺独立注释 —— 一条链只要一条,'
                             '写明整条链在判什么、判不过走哪条路;不必逐条件拆行加注释;'
                             '单条件卫语句不要求',
    'uncommented-flat': '连续一长串平铺语句没有任何注释 —— 读者只能逐行反推意图;'
                        '一组操作前面写一段多行块注释即可',
    'uncommented-loop': '复杂循环上方缺独立整行注释 —— while、循环体 ≥3 条语句、'
                        '或含 break/continue 时才要求,写明遍历什么、为什么必须循环',
    'packed-layout': '空行被删 —— 顶层定义之间要留空行、类内方法之间要留一行;'
                     '删空行是把行数压到阈值以下的作弊,也让文件失去段落',
    'long-module': '单文件过长 —— 一次改动要在无关代码里翻找,载入一个模块把整包拉进内存;'
                   '按职责切成子包,不是按行数机械切',
    'flat-package': '一个目录里平铺了太多模块 —— 一眼扫不完就等于没有导航,'
                    '读者只能靠猜文件名;按「一起改的东西放一起」拆子包',
    'duplicate-basename': '同名模块出现在多个目录 —— 报错栈、编辑器标签页、import 语句里'
                          '都分不清是哪一个',
    'duplicate-toplevel': '同一模块里顶层定义了两次同名的东西 —— 后定义的静默胜出,'
                          '两份实现不一致时没有任何东西会说话;文本切片式重构最容易产生它',
    'uncommented-field': '数值字段无注释 —— 字段名说不出单位、口径与取值范围;'
                         '字段上方/行尾写一行,或统一写进类 docstring 的 Attributes: 小节',
    'uncommented-assign': '算式赋值无注释 —— 变量名只说「是什么」,注释要说「怎么来的、'
                          '为什么这么算」;三元/比较、多运算符、魔数、取整取极值时要求,'
                          '纯函数调用与单运算符算式不要求',
    'thin-docstring':  '文档注释只有一行摘要 —— 摘要说「做什么」,读者要的是「为什么这么做、'
                       '什么前提下成立、边界在哪」;非平凡函数/类必须在摘要之后另起解释段',
    'docstring-sections': '文档注释缺必需小节 —— 应给出足够信息,'
                          '使人不看一行实现就能写出调用',
    'test-syspath': '测试代码改了 `sys.path` —— 「测的是哪一份代码」变成取决于执行顺序,'
                    '在 CI 里表现为莫名其妙的通过或失败;用 pytest 的 `pythonpath` 配置项'
                    '或 `--import-mode=importlib`,不要手改路径',
    'no-collectable-test': '测试模块里没有一个能被收集的用例 —— 文件看着是测试、'
                           '测试框架一个都不收;重构时改了函数名或整类被跳过时,'
                           '没有任何东西会告诉你这批用例已经不在跑了',
    'test-import-test': '测试模块之间互相 import —— 共享测试工具该进 `conftest.py` '
                        '或一个非 `test_` 命名的模块;`--import-mode=importlib` 下'
                        '测试模块根本不能被 import,现在能跑只说明还没换模式',
    'sibling-import': '包目录内模块之间互相导入 —— 依赖图从一棵树变成一张网,'
                      '改一个模块的导出会悄悄改掉另一个模块的行为;'
                      '共享逻辑下沉到子包,`__init__.py` 的 re-export 例外',
    'import-order': '导入分组顺序或组内字典序不合 Google 3.13 —— '
                    'future → 标准库 → 第三方/本仓库,同组内按全路径字典序;'
                    '标准库写在第三方之后,读者会误以为它是外部依赖',
    'multi-import': '一行写了多个 import —— 每行一个,排序与 diff 才可读(Google 3.13)',
}

# 这三条量的是结构形状,启发式后端上会误报 ⇒ 只报不拦(见 references/languages.md)。
STRUCT_RULES = ('long-function', 'deep-nesting', 'many-kwargs')

# 超过这个行数的文件才要求模块文档 —— 短文件没什么可交代的
_MODULE_DOC_THRESHOLD = 80


@dataclass(frozen=True)
class Thresholds:
    """规则阈值。**换语言不换阈值** —— 阈值属于规则,不属于语法。

    定义用于衡量代码体量、复杂度、文档完备性与目录层级的核心数值上限。
    跨不同语言后端时保持统一评判口径,仅通过命令行参数显式覆盖。
    """

    max_body: int = 60              # 函数体行数上限,超过视为上帝函数
    max_declarations: int = 30      # 单个样式规则块声明上限,超过视为胖块
    max_kwargs: int = 5             # 公开函数入参个数上限,超过视为调用方组装内部依赖
    max_keys: int = 4               # 单对象字符串下标取值上限,超过视为 dict 当类型
    max_depth: int = 4              # 控制流嵌套深度上限,超过应提前守卫返回
    min_module_doc: int = 3         # 超过 80 行的文件模块文档最小散文行数
    max_modules: int = 7            # 单目录同层平铺模块数上限,超过应切子包
    max_module_lines: int = 500     # 单文件最大物理行数,超过应拆分子模块
    max_flat: int = 10              # 连续无注释平铺语句条数上限,超过应加块注释分段
    trivial_body: int = 5           # 平凡短函数体行数上限,不超过时不强制要求文档小节


@dataclass(frozen=True)
class Outcome:
    """一个文件的判定结果。违规与覆盖率**同出一次调用**,不可能对不上。

    包含该源码文件的全部违规项,以及注释覆盖率的已解释数与总数。
    """

    findings: list = field(default_factory=list)  # 该文件命中的全部违规项列表
    covered: int = 0                              # 已写明注释的语法构造总数(分子)
    total: int = 0                                # 必须写注释的语法构造总数(分母)


def _label(fn):
    """函数在报告里的标识。匿名函数(箭头函数等)没有名字,退化成行号。

    用于违规提示文本中的主体名称格式化,优先使用具体符号名,缺省时回退为匿名函数标签。

    Args:
        fn: 函数事实。

    Returns:
        函数名;名字为空时返回 `<匿名函数@行号>`。
    """
    return fn.name or f'<匿名函数@{fn.line}>'


def _duplicate_bindings(bindings):
    """找出同一模块里被**直接**定义了两次的顶层名字。

    Python / PowerShell / JS 的 `var`、`function` 对重复定义都不报错,后写的静默胜出。
    右侧引用了自己的那种是扩展/规范化(`ROOTS = ROOTS + (...)`)而不是覆盖,不报 ——
    实测全仓 2041 个文件里本规则的全部命中都是这一类,不豁免就只剩噪声。

    Args:
        bindings: 模块顶层的**直接**绑定,已按出现顺序排列。

    Returns:
        `[(行号, 名字, 种类, 首次定义行号)]`。
    """
    seen = {}
    dups = []
    # 后出现的同名绑定若未引用自身即构成覆盖,排除 a = a + 1 这类就地扩展
    for binding in bindings:
        # 第一次见到这个名字:记下位置,是不是重复要等第二次才知道
        if binding.name not in seen:
            seen[binding.name] = binding.line
            continue
        # 右侧引用了自己 ⇒ 扩展或规范化,不是覆盖,不报
        if not binding.references_self:
            dups.append((binding.line, binding.name, binding.kind, seen[binding.name]))
        seen[binding.name] = binding.line
    return dups


def _check_module(facts, thresholds, add):
    """文件级三条:长度、模块文档、重复顶层定义。

    检查单文件总代码行是否超标、大文件是否包含充足的顶层模块说明文档,
    以及同模块内是否存在被静默覆盖的重复顶层声明。

    Args:
        facts: 该文件的事实。
        thresholds: 阈值。
        add: 记一条违规的回调 `(行号, 规则, 说明)`。
    """
    # 文件长度本身就是拆分触发条件:超了就该按职责切子包,不是按行数机械切
    if facts.total_lines > thresholds.max_module_lines:
        add(1, 'long-module', f'{facts.total_lines} 行 > {thresholds.max_module_lines}')

    # 模块文档是唯一能说「这个文件为什么存在」的地方;文件越大越必须说
    doc_lines = len((facts.module_doc or '').splitlines())
    # 超过 80 行的文件必须有足够的模块文档交代背景与口径
    if facts.total_lines > _MODULE_DOC_THRESHOLD and doc_lines < thresholds.min_module_doc:
        add(1, 'thin-module-doc', f'{doc_lines} 行 < {thresholds.min_module_doc}')

    # 重复顶层定义:引擎静默让后者胜出,所以它必须由闸来说,没有别的东西会说
    for line, name, kind, first in _duplicate_bindings(facts.bindings):
        add(line, 'duplicate-toplevel', f'{kind} {name} 重复定义(首次在 :{first})')


def _check_conditions(facts, add):
    """条件:每条 `if` / `elif` 链开头一行独立注释。

    只认链头那一行 —— `elif` 的前提通常已在同一条注释里覆盖。行尾注释不算,
    因为它压在被解释的代码旁边,读者仍然要倒着找。

    Args:
        facts: 该文件的事实。
        add: 记一条违规的回调。
    """
    for condition in facts.conditions:
        # 链头上一行必须是独立整行注释;elif 不单独要求
        if condition.line - 1 not in facts.whole_line_rows:
            add(condition.line, 'uncommented-condition',
                'if/elif 链开头缺独立注释行(整链一条即可)')


def _check_layout(facts, thresholds, add):
    """空行与平铺段。

    空行被删是压行作弊的入口,必须与行数上限一起查;平铺段则是「连续语句里一行注释都没有」。

    Args:
        facts: 该文件的事实。
        thresholds: 阈值。
        add: 记一条违规的回调。
    """
    # 顶层定义与类方法上方的空行必须满足间隔规范,防范删空行压行作弊
    for row, name, got, need in facts.layout_gaps:
        add(row, 'packed-layout', f'{name} 上方 {got} 个空行 < {need}')

    # 后端记的是每段的**最终长度**(它不比阈值 —— 阈值属于规则引擎),这里才判够不够长
    for line, length in facts.flat_runs:
        # 连续无注释语句条数超过阈值,判定为平铺代码段违规
        if length > thresholds.max_flat:
            add(line, 'uncommented-flat',
                f'连续 {length} 条语句无注释行 > {thresholds.max_flat}')


def _check_commented(facts, add):
    """按「上方有没有注释」判的几类构造。

    循环只认独立整行注释;字段与算式赋值接受行尾注释 —— 后者一行放得下,
    而循环要写的东西一行放不下、一压行就被推到屏幕外。raise 与 return 不单独要求:
    失败前提与返回口径归 docstring 的 `Raises:` / `Returns:` 小节。

    Args:
        facts: 该文件的事实。
        add: 记一条违规的回调。
    """
    # 后端只送来复杂循环;简单单句 for 不进这个列表
    for loop in facts.loops:
        # 循环上方紧邻的上一行缺失独立整行注释
        if loop.line - 1 not in facts.whole_line_rows:
            add(loop.line, 'uncommented-loop', '上方缺独立注释行,写明遍历什么/为什么必须循环')

    # 字段是「这个数是什么、什么单位」的唯一落点;只有名字读者得去猜
    for field_fact in facts.fields:
        # 类/数据类字段既无上方独立注释也无行尾注释
        if not explained(facts, field_fact.line, True):
            add(field_fact.line, 'uncommented-field',
                f'字段 {field_fact.label} 缺注释(单位/口径/范围)')

    # 算式赋值:名字说「是什么」,注释才说「怎么来的」。纯调用与字面量不算
    for assigned in facts.assigns:
        # 运算/三元/比较得出的赋值既无上方独立注释也无行尾注释
        if not explained(facts, assigned.line, True):
            add(assigned.line, 'uncommented-assign', f'{assigned.label} 由算式得出,上方缺注释')

    # 空异常块让失败态与正常态同形 —— 最难查的一类 bug
    for line in facts.silent_except_lines:
        add(line, 'silent-except', '异常被静默吞掉(空处理块)')


def _check_docs(fn, thresholds, add):
    """一个函数/类的文档与人眼可见的接口形状。

    类只判文档:参数表、体长、嵌套、字符串键对类都不适用。

    Args:
        fn: 函数/类事实。
        thresholds: 阈值。
        add: 记一条违规的回调。
    """
    # 公开元素没有文档 ⇒ 读代码只能依赖作者口头解释
    if (
        # 符号为公开接口(名字非下划线开头)
        fn.is_public
        # 且未声明任何 docstring 文档
        and not fn.doc
    ):
        add(fn.line, 'no-docstring', _label(fn))
    # 缺小节只对公开、非平凡、且不是类的函数要求 —— YAGNI 对文档同样适用
    elif (
        # 属于公开函数接口
        fn.is_public
        # 已经声明了 docstring
        and fn.doc
        # 排除类定义(类不要求 Args/Returns 小节)
        and not fn.is_class
        # 函数体代码量超出平凡短函数门槛
        and fn.body_lines > thresholds.trivial_body
        # 存在缺失的必需格式小节(如 Args/Returns/Raises)
        and fn.missing_sections
    ):
        add(fn.line, 'docstring-sections', f"{_label(fn)} 缺 {'/'.join(fn.missing_sections)}")
    # 一行式文档只对真正平凡的短函数成立;有体量的必须写出「为什么」。
    # 私有函数同样受约束 —— 它写了文档就说明作者认为需要解释,那就解释完整。
    if (
        # 已经声明了 docstring 文档
        fn.doc
        # 函数体代码量超出平凡短函数门槛
        and fn.body_lines > thresholds.trivial_body
        # 摘要行之外缺少解释段散文行
        and fn.doc_prose_lines == 0
        # 只装字段的记录类,一行摘要已说清它是什么
        and not fn.plain_record
    ):
        add(fn.line, 'thin-docstring', f'{_label(fn)} 摘要行之后没有解释段')


def _check_shape(fn, thresholds, add):
    """一个函数的形状:长度、参数个数、字符串键、嵌套层数、规则块胖瘦。

    度量函数的物理体长、入参个数、字符串字典键使用频次、嵌套深度及声明数,
    超出阈值时报告对应结构性坏味道。

    Args:
        fn: 函数事实(调用方已保证不是类)。
        thresholds: 阈值。
        add: 记一条违规的回调。
    """
    # 函数体行数超过阈值,判定为上帝函数
    if fn.body_lines > thresholds.max_body:
        add(fn.line, 'long-function',
            f'{_label(fn)} 体 {fn.body_lines} 行 > {thresholds.max_body}')
    # 规则块的胖瘦按声明条数算,不按行数 —— CSS 一条声明可以写很长,也可以一行多条
    if fn.declaration_count > thresholds.max_declarations:
        add(fn.line, 'fat-rule-block',
            f'{_label(fn)} 有 {fn.declaration_count} 条声明 > {thresholds.max_declarations}')
    # 只对公开函数判参数过多:私有函数是内部实现,调用方就是作者自己
    if (
        # 属于公开函数接口
        fn.is_public
        # 参数个数超出关键字参数阈值上限
        and len(fn.params) > thresholds.max_kwargs
    ):
        add(fn.line, 'many-kwargs',
            f'{_label(fn)} 有 {len(fn.params)} 个参数 > {thresholds.max_kwargs}')
    # 单个对象内按字符串取值频次超出上限,判定为将字典作为伪类型
    if fn.string_key_count > thresholds.max_keys:
        add(fn.line, 'dict-as-type',
            f'{_label(fn)} 对同一对象用了 {fn.string_key_count} 个字符串键 '
            f'> {thresholds.max_keys}')
    # 语法树控制流嵌套深度超出层级上限
    if fn.nesting_depth > thresholds.max_depth:
        add(fn.line, 'deep-nesting',
            f'{_label(fn)} 嵌套 {fn.nesting_depth} 层 > {thresholds.max_depth}')


def _check_functions(facts, thresholds, add):
    """逐个函数/类判文档与形状。

    遍历模块内搜集的所有函数与类定义事实,依次进行文档完备性校验与结构形态审查。

    Args:
        facts: 该文件的事实。
        thresholds: 阈值。
        add: 记一条违规的回调。
    """
    # 函数与类先统一检验文档完备性,函数再额外审查形状指标(类不判形状)
    for fn in facts.functions:
        _check_docs(fn, thresholds, add)
        # 类只判文档,形状那几条对类不成立
        if fn.is_class:
            continue
        _check_shape(fn, thresholds, add)


def _check_tests(facts, add):
    """判测试特有的两条单文件规则。

    **只对测试模块生效**(`test_kind == 'module'`):`conftest.py` 与测试目录里的共享辅助
    既不提供用例也不该被要求提供用例,拿这两条去套它们全是误报。

    Args:
        facts: 该文件的事实。
        add: 记一条违规的回调。
    """
    # 不是测试模块就整段跳过 —— 分类由语言后端给,这里只认分类
    if facts.test_kind != 'module':
        return
    # 逐行报:一个文件里可能在几处各改了一次路径,读者要分别去处理
    for row in facts.syspath_lines:
        add(row, 'test-syspath', '改 sys.path 让被测代码取决于执行顺序')
    # 零个可收集用例才报:分母是「会不会被收集」,不是「写了多少函数」
    if facts.collectable == 0:
        add(1, 'no-collectable-test', '测试模块里没有名字能被收集的用例')


def evaluate(facts: FileFacts, thresholds: Thresholds, disabled=frozenset()) -> Outcome:
    """判一个文件的全部规则,同时数出覆盖率。

    综合执行模块级、分支条件、代码布局、必要注释与函数接口文档等全套规则检查,
    并在同一次求值中通过统一口径汇总已解释构造与总构造覆盖率数据。

    Args:
        facts: 该文件解析出来的事实。
        thresholds: 阈值。
        disabled: 这门语言**明确不查**的规则名。它们同时要从覆盖率的分母里扣掉 ——
            否则报告会给出「注释覆盖率 18.2%」这种数字,而那几条规则根本不拦,
            读者会以为这门语言遍地欠注释。

    Returns:
        违规清单与覆盖率分子分母。
    """
    findings = []

    def add(line, rule, detail):
        """记一条违规。启发式后端产出的条目带上标记,报告里能区分「确凿」与「待看」。"""
        findings.append(Finding(str(facts.path), line, rule, detail, RULES[rule],
                                heuristic=facts.heuristic))

    # 模块级与分支条件:顶层结构、import、if/elif 的写法
    _check_module(facts, thresholds, add)
    _check_conditions(facts, add)
    # 排版与注释:空行、行宽、复杂循环与算式赋值的说明是否到位
    _check_layout(facts, thresholds, add)
    _check_commented(facts, add)
    # 函数接口文档,以及只对测试模块生效的那几条
    _check_functions(facts, thresholds, add)
    _check_tests(facts, add)

    # 通过唯一注释判据统计该文件的已解释构造数与待解释构造总数
    covered, total = coverage.tally(facts, disabled)
    return Outcome(findings=findings, covered=covered, total=total)
