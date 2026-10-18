"""注释覆盖率的计分:分母由代码结构决定,不是由总行数决定。

**为什么单独一层**:覆盖率是验收判据之一,而它的口径必须与违规清单**同源** ——
两边各写一份谓词,分叉过一次(整个 `if` 只看前一行、行尾注释判断写反),
**而分叉时两个数都不报错**,读者无法判断哪个是真的。所以本模块只做「数数」,
判「这一行算不算已解释」一律调 `text.explained` 那唯一一份谓词。

分母为什么不数总行数:总行数可以被压 —— 实测抓到过把空行删光让「说明密度」上升的。
**一个能被优化的指标就会被优化。** 这里的分母是「该解释的构造」个数,删空行、
堆废话都拉不动它。

被语言明确禁用的规则**同时从分母里扣掉**:否则报告会给出「注释覆盖率 18.2%」这种
数字,而那几条规则根本不拦,读者会以为这门语言遍地欠注释。
"""

# py-structure: allow-sibling-imports —— 同目录判据模块是这个 skill 的结构
from .text import explained


def tally(facts, disabled=frozenset()):
    """数出这个文件的「已解释构造数 / 该解释构造总数」。

    两个数在同一次遍历里一起累加,因为分母必须与分子同口径:先数分母再回头数分子,
    中间任何一次谓词判断的分叉都会让两个数来自不同的世界。

    Args:
        facts: 该文件的事实。
        disabled: 这门语言**明确不查**的规则名,其名下的构造不计入分母。

    Returns:
        `(已解释数, 总数)`;两者在没有任何待解释构造时都是 0。
    """
    covered = 0
    total = 0

    def count(row, accepts_inline):
        """把一个构造计入分母,并判断它是否已被解释。

        无条件累加总构造数,再调唯一那份注释谓词判它算不算已解释 ——
        与违规那一侧调的是同一个函数,这是两个数不打架的唯一保证。

        Args:
            row: 构造所在代码行号。
            accepts_inline: 是否允许行尾注释。
        """
        nonlocal covered, total
        total += 1
        # 命中唯一注释判定口径时,累计已解释构造计数
        if explained(facts, row, accepts_inline):
            covered += 1

    def count_rule(rows, rule, accepts_inline):
        """一条规则名下的全部构造计入分母;该规则被禁用时整批跳过。

        按规则成批处理而不是直接收一个总行号表,是因为禁用名单是**按规则**给的:
        `uncommented-loop` 被这门语言关掉时,要扣的正好是它名下那批行,不多不少。

        Args:
            rows: 目标构造的行号列表。
            rule: 规则名称。
            accepts_inline: 是否允许行尾注释。
        """
        # 规则在当前语言被明确禁用时,其名下的构造不计入分母
        if rule in disabled:
            return
        # 构造行号已按规则去重,逐行由 count 判定上方整行或行尾注释
        for row in rows:
            count(row, accepts_inline=accepts_inline)

    # 条件按**每条 if/elif 链**计一次,与违规那一侧同口径
    count_rule([item.line for item in facts.conditions], 'uncommented-condition', accepts_inline=False)
    # 循环只认上方独立整行注释;后端已经滤掉简单单句 for
    count_rule([item.line for item in facts.loops], 'uncommented-loop', accepts_inline=False)
    # 字段与算式赋值接受行尾注释,与违规那一侧同口径
    count_rule([item.line for item in facts.fields], 'uncommented-field', accepts_inline=True)
    count_rule([item.line for item in facts.assigns], 'uncommented-assign', accepts_inline=True)
    return covered, total
