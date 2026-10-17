"""把判定结果印成人能读的样子,并给出两个汇总指标。

**说明密度**与**注释覆盖率**都要给,但它们的地位不同:密度的分母(总行数)可以被压缩
—— 实测抓到过把空行删光让密度上升的;覆盖率的分母由代码结构决定,压不动。
所以报告里必须把「完整性看哪个」写出来,否则读者会去优化那个能被优化的数。
"""

# py-structure: allow-sibling-imports —— 同目录判据模块是这个 skill 的结构
from .rules import STRUCT_RULES

# 说明密度低于这个数,基本可以判定「只有一行式文档,没有解释为什么」。
# 参照:2026-09-08 在来源仓库实测,被当作范本的包 32.3%,被当作反例的包 6.0%。
DENSITY_REFERENCE = 20.0


def density(facts_list):
    """注释行 + 文档行占总行数的比例。

    汇总所有文件的整行独立注释与模块、函数文档行数,除以物理总行数得出说明密度。
    该指标容易被空行删减人为拉高,因此仅作为参考基线,不作为唯一的验收判据。

    Args:
        facts_list: 本次扫描的全部文件事实。

    Returns:
        百分比;总行数为 0 时返回 0.0。
    """
    total = 0
    spoken = 0
    # 逐文件累加行数:遍历各模块的事实结构,累计物理总行数与有效说明行数
    for facts in facts_list:
        total += facts.total_lines
        # 整行注释数与文档行数才是「说出来的话」;行尾注释不另计,它已在整行里被排除
        spoken += len(facts.whole_line_rows)
        spoken += len((facts.module_doc or '').splitlines())
        # 函数与类的 docstring 多行文本同样算入「解释代码的话」
        for fn in facts.functions:
            spoken += len((fn.doc or '').splitlines())
    # 说明密度口径为 [0.0, 100.0],无源码行时取 0.0 避免除零
    return spoken / total * 100 if total else 0.0


def blocking(findings):
    """从违规里挑出**要计入退出码**的那些。

    启发式后端量不准结构形状,那三条只报不拦 —— 拦了就会出现「闸说违规、但代码明明是对的」,
    而只报噪声的闸会被直接关掉。其余规则照常拦:注释存在性这类判定在启发式档上仍够可靠。

    Args:
        findings: 全部违规。

    Returns:
        参与退出码的违规列表。
    """
    return [item for item in findings
            if not (item.heuristic and item.rule in STRUCT_RULES)]


def render(findings, file_count, skipped, covered, total_constructs):
    """印出违规明细与汇总。

    格式化按规则、路径、行号排序的违规明细列表,追加扫描概况、跳过后端说明、
    注释覆盖率指标以及按频次降序排列的违规规则分类清单。

    Args:
        findings: 全部违规。
        file_count: 实际扫描的文件数。
        skipped: `[(语言名, 原因)]`,说明哪些语言这次没跑成。
        covered: 已解释的构造数。
        total_constructs: 该解释的构造总数。

    Returns:
        要打印的整段文本。
    """
    lines = []
    # 按规则类型、文件路径和代码行号稳定排序违规项,逐条格式化为终端易读行
    for item in sorted(findings, key=lambda x: (x.rule, x.path, x.line)):
        # 启发式条目带标记,让人能区分「确凿」与「可能需要看一眼」
        mark = ' (启发式)' if item.heuristic else ''
        lines.append(f'{item.path}:{item.line}  [{item.rule}]{mark} {item.detail}')

    lines.append('')
    lines.append(f'扫描 {file_count} 个文件,{len(findings)} 处违规'
                 f'(其中 {len(blocking(findings))} 处计入退出码)')
    # 依赖缺失等跳过原因必须显式展示,防止调用方将「未扫描」误当作「零违规通过」
    for language, reason in skipped:
        lines.append(f'⚠ 跳过 {language}:{reason}')

    # 无任何待解释构造时按 100.0% 满分通过,分子与分母同为 0 时不报除零
    percent = 100.0 if not total_constructs else covered / total_constructs * 100
    lines.append(f'注释覆盖率 {percent:.1f}%  '
                 f'({covered}/{total_constructs} 个该解释的构造已注释)'
                 f'   ← 完整性看这个,密度可以靠堆废话拉高')

    counts = {}
    # 统计各违规规则命中次数:归纳频次用于按严重程度/普遍度排序展示
    for item in findings:
        counts[item.rule] = counts.get(item.rule, 0) + 1
    # 按出现次数降序展示各规则违规汇总:优先呈现违规高发规则以引导修改
    for rule, number in sorted(counts.items(), key=lambda pair: -pair[1]):
        lines.append(f'  {number:3d}  {rule:22s} {item_why(rule, findings)}')
    return '\n'.join(lines)


def item_why(rule, findings):
    """取某条规则的说明文字(同一条规则的所有违规共用一句 why)。

    从当前违规集合中检索首个匹配该规则名称的条目,返回其内置的规则设计意图说明;
    若未检索到对应规则则回退为空字符串。

    Args:
        rule: 规则名。
        findings: 全部违规,用于取任意一条的 why。

    Returns:
        规则说明;取不到时返回空串。
    """
    # 线性检索违规项集合:同一规则的 why 描述一致,取首个命中项说明即满足要求
    for item in findings:
        # 命中相同规则类型时直接返回其 why 说明文字
        if item.rule == rule:
            return item.why
    return ''
