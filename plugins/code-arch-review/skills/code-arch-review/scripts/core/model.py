"""语言无关的**事实模型**:各语言后端把源码解析成这些事实,规则引擎只认事实。

为什么要有这一层:原来的闸把「解析」与「判规则」写在一起,`scan()` 与 `_coverage()`
各自走一遍 AST、各写一套谓词,结果两套谓词分叉过(整个 if 只看前一行、行尾注释判断写反),
**而分叉时两个数都不报错** —— 读者无法判断哪个是真的。

拆成「后端产事实 / 引擎判规则」之后,四种语言共用一套谓词,分叉在结构上不可能发生:
覆盖率分子与违规清单由**同一次**事实遍历算出。

后端只负责把语言语法翻译成这里的数据类,不做任何阈值判断 ——
阈值属于规则引擎,换语言不该换阈值。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FunctionFact:
    """一个函数/方法的可判定事实。

    由各语言 AST 或结构解析器提取,归一化记录接口签名、体长、嵌套层数与文档元数据,
    供规则引擎判定上帝函数、参数过多、深嵌套与文档完备性。

    Attributes:
        name: 函数名;匿名函数(箭头函数等)用空串,报告里退化成行号。
        line: 定义起始行号,1 基。
        end_line: 定义结束行号,1 基。
        body_lines: 函数体行数,判 `long-function` 用。
        params: 参数名列表,已剔除 `self` / `cls` 这类绑定实参。
        is_public: 是否公开(名字不以 `_` 开头)。只对公开函数判 `many-kwargs`。
        is_class: 这是不是类。类只判 `no-docstring` 与 `thin-docstring` ——
            参数表、函数体长度、嵌套层数、字符串键对类都不适用。
        doc: 文档注释正文;没有则 None。
        required_sections: 这门语言上该函数**必须**有的文档小节名列表,
            由后端按语言的文档约定给出(见 references/languages.md)。
        missing_sections: 文档里实际缺的小节名列表。
        string_key_count: 同一个对象上用过的最多字符串键数,判 `dict-as-type` 用。
        nesting_depth: 函数体内控制流嵌套层数,判 `deep-nesting` 用。
        doc_prose_lines: 文档摘要行之后、小节之外的解释文字行数,判 `thin-docstring` 用。
        declaration_count: 块内**直接**写了多少条声明。CSS 的规则块靠它判「太胖」,
            其他语言留 0 —— 于是那条规则在别的语言上永远不会触发。
    """

    name: str                       # 符号标识,匿名函数为空串
    line: int                       # 定义起始物理行号(1 基)
    end_line: int                   # 定义闭合物理行号(1 基)
    body_lines: int                 # 体物理行数(首末行差+1),用于上帝函数判定
    params: tuple[str, ...]         # 显式参数名列表,已剔除 self/cls
    is_public: bool                 # 是否为公开符号(非下划线开头),决定参数过多与文档小节强制性
    is_class: bool                  # 标记是否为类定义,用于免除参数表与嵌套深度审查
    doc: str | None                 # 提取的 docstring 原始文本,缺省为 None
    required_sections: tuple[str, ...] = ()  # 语言约定必需的文档小节列表
    missing_sections: tuple[str, ...] = ()   # 实际缺失的必需小节列表
    string_key_count: int = 0       # 单对象字符串下标最大取值频次,用于字典伪类型判定
    nesting_depth: int = 0          # 控制流语法树最大嵌套层级,用于深嵌套判定
    doc_prose_lines: int = 0        # 摘要之后不属于任何小节的散文解释行数
    declaration_count: int = 0      # 样式规则块直接声明数(仅 CSS 适用)


@dataclass(frozen=True)
class ConditionFact:
    """一条 `if` / `elif` 链。

    Python 后端一条链只产一条事实,记链头行号;注释也只要一条,写在链开头。
    其他语言后端按各自的语法粒度产出,规则引擎只认 `line`。

    Attributes:
        line: 链头 `if` 的起始行号。
        operand_lines: 布尔表达式摊平后的子条件行号。保留给后端诊断,
            **不参与注释规则与覆盖率**。
    """

    line: int                       # if/elif 语句起始物理行号(1 基)
    operand_lines: tuple[int, ...]  # 各子判据表达式起始行号序列,包含布尔操作数与重复行号


@dataclass(frozen=True)
class SimpleFact:
    """只按行号判定「上方有没有独立注释」的构造:循环 / raise / 字段 / 赋值 / return。

    抽象无需深层 AST 属性的单行语法构造,通过行号与独立整行/行尾注释行号集合做快速差集比对。

    Attributes:
        line: 构造所在行号,1 基。
        label: 报告里显示的标识(变量名、构造描述)。
        accepts_inline: 这一条是否接受**行尾**注释。字段与赋值接受(一行放得下),
            循环不接受(注释要写的东西一行放不下,且压行就丢了)。
    """

    line: int                       # 语法构造所在物理行号(1 基)
    label: str                      # 构造展示标签或变量名,用于违规报告文本
    accepts_inline: bool            # 判定口径开关:字段与赋值允许行尾注释,循环/分支/raise 严禁


@dataclass(frozen=True)
class BindingFact:
    """模块顶层的**直接**绑定,判 `duplicate-toplevel` 用。

    记录顶层直接声明的名字与绑定类型,结合自引用检测识别同模块内非故意的重复覆盖。

    Attributes:
        name: 被绑定的名字。
        kind: `def` 或 `assign`。
        line: 本次绑定的行号。
        references_self: 右侧表达式是否引用了同一个名字 ——
            那是扩展/规范化(`ROOTS = ROOTS + (...)`)而不是覆盖,不报。
    """

    name: str                       # 顶层绑定的目标变量名或函数名
    kind: str                       # 绑定构造种类:定义 def 或直接赋值 assign
    line: int                       # 该绑定语句所在物理行号(1 基)
    references_self: bool           # 右侧是否引用同名变量,True 表示属于配置扩展规范化而非覆盖


@dataclass
class FileFacts:
    """一个文件解析出来的全部事实。规则引擎只吃这个,不碰源码。

    将源码物理行数、注释分布特征与各类语法构造实体解耦为统一中间表示,
    实现单次语法遍历结果向违规检查与覆盖率统计的双重复用。

    Attributes:
        path: 文件路径。
        language: 语言名,报告里显示。
        total_lines: 文件总行数。
        comment_rows: 出现过注释的行号集合(**含行尾注释**)。覆盖率的行尾判据用它。
        whole_line_rows: **独立整行**注释所在行号集合。条件/循环/raise 只认这个。
        module_doc: 模块级文档注释正文;没有则 None。
        functions: 全部函数/方法事实。
        conditions: 全部函数内的 `if` / `elif` 链,判 `uncommented-condition`。
        loops: 需要注释的复杂循环,判 `uncommented-loop`。
        raises: 抛异常事实。保留给后端诊断,不再单独要求注释 —— 前提归 docstring 的 `Raises:`。
        fields: 字段定义,判 `uncommented-field`;类 docstring 有 `Attributes:` 时后端会跳过。
        assigns: 右侧是算式(运算/三元/比较)的赋值,判 `uncommented-assign`。
        returns: 算式 return 事实。保留给后端诊断,口径归 docstring 的 `Returns:`。
        silent_except_lines: 静默吞异常的位置(`except: pass` / 空 `catch`)。
        bindings: 模块顶层直接绑定,判 `duplicate-toplevel`。
        flat_runs: 函数内「连续一长串语句无注释」的段,元素是 (段首行号, 段长度)。
        layout_gaps: 顶层与类内定义间空行不足的位置,元素是 (行号, 定义名, 实际空行数, 需要的空行数)。
        heuristic: 本文件的结构度量是否来自启发式。True 时报告会标出来,
            且结构度量三条不参与退出码(见 references/languages.md 的启发式纪律)。
        test_kind: 这个文件属于哪一类测试相关文件(`''` / `'module'` / `'conftest'` /
            `'helper'`)。**判据是语言知识**,由后端给(见 `lang/python/tests.py`)——
            规则引擎只认这个分类,不自己判「什么算测试」。目前只有 Python 后端填,
            其余语言留空串,于是测试规则在那些语言上不触发。
        collectable: 会被测试框架收集的用例个数,判 `no-collectable-test` 用。
        syspath_lines: 改 `sys.path` 的语句行号,判 `test-syspath` 用。
        imports: `[(行号, 顶层模块名)]`。跨文件的规则要拿它去比对本次扫到的
            测试模块名,所以**只记顶层名** —— 全路径比对会漏掉 `from tests.test_x import`。
        import_details: `[(行号, 模块路径, 相对级别, 被导名字)]`。判 `sibling-import`
            与 `import-order` 用;只有模块顶层导入进这里,函数内导入不参与结构判据。
        multi_import_lines: `import a, b` 这类一行多个名字的行号,判 `multi-import` 用。
        allow_sibling_imports: 文件头是否声明豁免平级互导(`py-structure: allow-sibling-imports`)。
            入口脚本与判据模块天然同目录时用它;相对导入与排序仍然照查。
    """

    path: object                    # 源码文件 Path 对象或标识路径
    language: str                   # 注册的语言标识(如 python/powershell/bash)
    total_lines: int                # 文件物理总行数,用于单文件过长与说明密度计算
    comment_rows: set[int] = field(default_factory=set)        # 包含注释(含行尾注释)的物理行号集合(1 基)
    whole_line_rows: set[int] = field(default_factory=set)     # 独立整行注释物理行号集合(1 基)
    module_doc: str | None = None                              # 顶层模块文档正文,用于薄模块文档判定
    functions: list[FunctionFact] = field(default_factory=list)# 模块内全部函数与类定义事实列表
    conditions: list[ConditionFact] = field(default_factory=list) # 模块内全部分支条件与摊平子条件事实列表
    loops: list[SimpleFact] = field(default_factory=list)      # 循环语句事实列表
    raises: list[SimpleFact] = field(default_factory=list)     # 显式抛出异常语句事实列表
    fields: list[SimpleFact] = field(default_factory=list)     # 类与数据类字段声明事实列表
    assigns: list[SimpleFact] = field(default_factory=list)    # 计算及调用得出变量的赋值事实列表
    returns: list[SimpleFact] = field(default_factory=list)    # 携带算式的返回语句事实列表
    silent_except_lines: list[int] = field(default_factory=list) # 空 except 块起始物理行号集合
    bindings: list[BindingFact] = field(default_factory=list)  # 顶层直接名称绑定事实列表
    flat_runs: list[tuple[int, int]] = field(default_factory=list) # 连续无注释平铺代码段起点与长度列表
    layout_gaps: list[tuple[int, str, int, int]] = field(default_factory=list) # 顶层定义间空行不达标位置三元组列表
    heuristic: bool = False                                    # 解析精度分档标志,启发式模式下不拦截结构违规
    test_kind: str = ''                                        # 测试相关分类:空串/conftest/helper/module
    collectable: int = 0                                       # 会被测试框架收集的用例数
    syspath_lines: list[int] = field(default_factory=list)     # 改 sys.path 的语句物理行号集合
    imports: list[tuple[int, str]] = field(default_factory=list) # 导入声明 (行号, 顶层模块名) 列表
    import_details: list[tuple[int, str, int, tuple[str, ...]]] = field(default_factory=list) # 顶层导入 (行号, 模块路径, 相对级别, 被导名字)
    multi_import_lines: list[int] = field(default_factory=list)  # 一行多个名字的 import 行号
    allow_sibling_imports: bool = False                          # 文件头声明豁免平级互导


@dataclass(frozen=True)
class Finding:
    """一条违规。

    结构化记录代码结构或注释缺失违规详情,携带规则分类、人类可读说明与拦截级别标记。

    Attributes:
        path: 文件路径;目录级规则(flat-package 等)填目录路径。
        line: 行号,1 基。
        rule: 规则名,必须是 rules.RULES 里的键。
        detail: 具体说明(带实际数字)。
        why: 这条规则防的是什么,取自 rules.RULES。
        heuristic: 是否来自启发式判定。报告里标出来,且不参与退出码。
    """

    path: str                       # 违规目标文件或目录路径
    line: int                       # 违规定位物理行号(1 基)
    rule: str                       # 规则唯一标识枚举名,对应 RULES 字典键
    detail: str                     # 具体违规上下文说明,包含实际观测数值与阈值
    why: str                        # 规则设计背景与危害防范说明,全局统一口径
    heuristic: bool = False         # 标志该违规是否由启发式机制推导得出
