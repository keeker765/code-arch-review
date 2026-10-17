"""文档自检:入口与分册的尺寸、链接、规则覆盖与最小例子。

SKILL.md 是唯一入口,它的价值是**读完就能过闸**。这份自检把「读完就能过」
拆成可执行的断言:入口够短(省 context)、链接都可达、代码里的每条规则在入口
出现一次、照着入口写的最小文件真的 0 违规。

跑:`python <skill目录>/selfcheck/run.py`(它调用本模块)。
"""

from pathlib import Path
import re
import subprocess
import sys

_HERE = Path(__file__).resolve().parent
# 入口与分册的根目录
_ROOT = _HERE.parent
# 入口文件
_SKILL = _ROOT / 'SKILL.md'
# 分册目录
_REFS = _ROOT / 'references'
# 闸脚本目录
_SCRIPTS = _ROOT / 'scripts'
# 闸的入口脚本
_CHECK = _SCRIPTS / 'check.py'
# 照着入口写的最小样本
_EXAMPLES = _HERE / 'fixture_skill_examples.py'

sys.path.insert(0, str(_SCRIPTS))

from core.rules import RULES  # noqa: E402

# 入口必须短:它每轮都进 context;95 是盲测后给例子留的上限
_MAX_SKILL_LINES = 95
# 分册只按需加载,但也别长到读不完
_MAX_REF_LINES = 180
# 入口至少要有的 Python 例子段数:一段完整函数 + 一段导入对照
_MIN_EXAMPLES = 2
# Markdown 链接的目标
_LINK = re.compile(r'\]\(([^)]+)\)')
# 反引号里的规则 id;必须带连字符,排除 `check.py` 与 `--exclude`
_RULE_ID = re.compile(r'`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`')


def check():
    """跑完全部文档断言,返回一行结论。

    四条断言各自独立:某一条写宽了,另一条不会替它兜住。

    Returns:
        可拼进 SELFCHECK_OK 的结论串。
    """
    # 入口正文;后三条断言都在这份文本上做
    skill = _SKILL.read_text(encoding='utf-8')
    # 尺寸与链接只关心文件本身,先跑
    _check_sizes()
    _check_links(skill)
    # 规则覆盖与例子都走入口正文,后跑
    _check_rules(skill)
    _check_examples(skill)
    return '文档自检 尺寸/链接/规则覆盖/最小例子 4/4'


def _check_sizes():
    """入口与每个分册不得超过行数上限。

    上限是设计值,不是历史快照:入口每涨一行都会挤掉例子或表项。
    """
    # 入口的行数;超过上限说明细节没有下沉到分册
    lines = len(_SKILL.read_text(encoding='utf-8').splitlines())
    assert lines <= _MAX_SKILL_LINES, \
        f'SKILL.md {lines} 行 > {_MAX_SKILL_LINES},细节该下沉到 references/'
    # 逐个分册查上限,防止某一册又长回入口的规模
    for path in sorted(_REFS.glob('*.md')):
        # 这一册的行数
        count = len(path.read_text(encoding='utf-8').splitlines())
        assert count <= _MAX_REF_LINES, f'{path.name} {count} 行 > {_MAX_REF_LINES}'


def _check_links(skill):
    """入口的每个相对链接都必须可达,每个分册都必须从入口链到。

    链接是入口与分册之间唯一的路;断一条,那一册就等于没写。

    Args:
        skill: SKILL.md 的全文。
    """
    # 入口链到过的绝对路径
    linked = set()
    # 逐个检查入口里的链接目标
    for target in _LINK.findall(skill):
        # 外链不归这里管
        if '://' in target:
            continue
        # 页内锚点没有文件可查
        if target.startswith('#'):
            continue
        # 链接目标的绝对路径
        path = (_SKILL.parent / target).resolve()
        assert path.exists(), f'SKILL.md 链接指向不存在的文件:{target}'
        linked.add(path)
    # 每个分册都必须从入口可达,否则等于没写
    for ref in sorted(_REFS.glob('*.md')):
        assert ref.resolve() in linked, f'分册没有从 SKILL.md 链到:{ref.name}'
        # 分册头部的前五行;要有一条回入口的链接
        head = ref.read_text(encoding='utf-8').splitlines()[:5]
        assert any('SKILL.md' in line for line in head), f'{ref.name} 头部缺回入口的链接'


def _check_rules(skill):
    """代码里的每条规则在入口出现且只出现一次;入口表格里的 id 必须已注册。

    两个方向都要查:文档漏规则,读者不知道;文档多规则,代码没实现。

    Args:
        skill: SKILL.md 的全文。
    """
    # 正向:代码注册的每条规则都要在入口出现,而且只出现一次
    for rule in RULES:
        # 这条规则在入口被反引号引用的次数
        count = skill.count(f'`{rule}`')
        assert count == 1, f'{rule} 在 SKILL.md 出现 {count} 次,应正好 1 次'
    # 反向:速查表里写出来的 id 必须是代码真的注册过的
    for rule in _RULE_ID.findall(_speed_table(skill)):
        assert rule in RULES, f'SKILL.md 速查表写了未注册的规则:{rule}'


def _speed_table(skill):
    """截取速查表那一节。

    只取这一段,免得反向检查扫到例子里的规则名。

    Args:
        skill: SKILL.md 的全文。

    Returns:
        速查表小节的文本;找不到这一节时抛 StopIteration。
    """
    # 按行切,才能定位章节边界
    lines = skill.splitlines()
    # 速查表标题所在行
    start = next(index for index, line in enumerate(lines) if line.startswith('## 速查表'))
    # 下一个二级标题;没有就到文件末尾
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith('## ')), len(lines))
    # 返回值口径:速查表标题到下一个标题之前的文本
    return '\n'.join(lines[start:end])


def _check_examples(skill):
    """入口至少要有若干代码例子;照着入口写的最小文件必须真的过闸。

    例子是入口的可执行部分;代码块数得住,文字说得对不对住不住,所以另跑夹具。

    Args:
        skill: SKILL.md 的全文。
    """
    # 入口里的 Python 代码段数
    fences = skill.count('```python')
    assert fences >= _MIN_EXAMPLES, \
        f'SKILL.md 的 Python 例子只有 {fences} 段,应至少 {_MIN_EXAMPLES} 段'
    # 用闸跑一遍最小样本,验「照着入口写」真的能过
    done = subprocess.run([sys.executable, str(_CHECK), str(_EXAMPLES)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # 最小样本必须是零违规且满覆盖
    assert '0 处违规' in done.stdout, f'照着 SKILL.md 写的最小文件没通过闸:\n{done.stdout}'
    assert '注释覆盖率 100.0%' in done.stdout, f'最小文件不是满覆盖:\n{done.stdout}'
