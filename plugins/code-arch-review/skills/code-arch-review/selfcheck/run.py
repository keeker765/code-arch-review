"""闸自身的回归自检:把「零违规」与「覆盖率 100%」钉成同一个口径。

为什么需要:这两个数各自由一套谓词算出来,一度不一致(整个 if 只看前一行、
行尾注释判断写反),而**不一致时两个数都不报错** —— 读者无法判断哪个是真的。
`fixture_full_coverage.py` 是一份「每类该解释的构造各一个、且全部解释到位」的样本,
闸对它必须同时给出 0 违规与 100.0%。任何一边的谓词被改歪,这里就红。

跑:`python <skill目录>/selfcheck/run.py`

每种语言各有一对夹具:`fixture_clean.<扩展名>` **故意写得完全合规**,闸必须报 0 违规;
`fixture_bad.<扩展名>` 故意踩坑,闸必须报出违规。两个方向缺一不可 ——
只有阴性对照时,一个恒绿的空后端能骗过全部自检。
"""

import pathlib
import subprocess
import sys
import tempfile

import doccheck

HERE = pathlib.Path(__file__).resolve().parent
# check.py 入口脚本绝对路径,用于 subprocess 驱动自身执行
CHECK = HERE.parent / 'scripts' / 'check.py'


def run(target):
    """跑一次闸,拿它的输出。

    刻意不看退出码:坏样本本来就该退出 1,把它当异常会让阳性对照本身变成错误。
    断言一律落在输出文本上(数违规条数、读覆盖率)。

    🔴 **stderr 并进 stdout**:闸用 `sys.exit('<消息>')` 报「一个目标都没扫到」,
    而那句走的是 stderr。只收 stdout 的话 `fixture_unavailable` 拿到的是空串,
    于是一台缺 pwsh 的机器上 PowerShell 夹具会被判成「合规样本报了违规」——
    报错信息与真实原因完全无关,查半天查不到点上。

    Args:
        target: 要扫的文件或目录。

    Returns:
        闸的标准输出与标准错误的合并文本。
    """
    # 用 stdout=PIPE + stderr=STDOUT 而不是 capture_output:后者与 stderr 重定向互斥
    return subprocess.run([sys.executable, str(CHECK), str(target)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True).stdout


def check_python_fixture():
    """Python 样本必须**同时**零违规且满覆盖 —— 两个断言缺一不可。

    只断言其一,谓词歪掉时另一半照样静默通过,而这里正是为了抓那次分叉才存在的。

    Returns:
        该类样本的一行结论。
    """
    # 扫描满覆盖样本,输出文本用于核对 0 违规与 100% 覆盖两个指标
    out = run(HERE / 'fixture_full_coverage.py')
    assert '0 处违规' in out, f'夹具不该有违规:\n{out}'
    assert '注释覆盖率 100.0%' in out, f'零违规却不是满覆盖,两套谓词又分叉了:\n{out}'
    return 'Python 满覆盖夹具 0 违规 / 100% 覆盖'


def check_duplicate_fixture():
    """`duplicate-toplevel` 的阳性对照:坏样本上必须报出正好 2 处。

    单验阳性不够 —— 豁免写歪了会把存量代码淹掉,那种闸会被直接关掉,和没有一样。

    Returns:
        该类样本的一行结论。
    """
    # 扫描阳性对照样本,捕获针对重复顶层定义的违规明细
    out = run(HERE / 'fixture_duplicate_toplevel.py')
    # 只数明细行,不数末尾的汇总行:「2  uncommented-loop」这类行首是数字,汇总行首不是
    hits = [line for line in out.splitlines()
            if 'duplicate-toplevel' in line and ':' in line.split()[0]]
    # 这里唯独写死 2 处而不像 check_bad_fixtures 那样只断言「非零」:
    # 要同时钉住「重复 def 报得出来」与「就地扩展/overload 不误报」,条数本身就是判据
    assert len(hits) == 2, f'坏样本该报正好 2 处 duplicate-toplevel,实报 {len(hits)}:\n{out}'
    assert any('compute' in hit for hit in hits), f'漏了重复的 def:\n{out}'
    assert any('LIMIT' in hit for hit in hits), f'漏了重复的常量:\n{out}'
    return 'duplicate-toplevel 阳性对照 2/2'


def fixture_unavailable(out):
    """这份夹具是不是因为后端起不来而没被真正扫到。

    后端起不来(缺 node / 缺 pwsh / 后端还没写完)时**跳过并说明**,不算失败 ——
    否则一台没装 node 的机器会让整个自检红,而那条信息是噪声不是缺陷。
    代价是跳过的夹具也不能算通过,所以调用方必须把跳过项单独报出来。

    🔴 报告里那行 `⚠ 跳过 <语言>` 也算数:后端起不来时的完整流程是「发现文件 → 起不来 →
    记成跳过」,这时报告仍会打出「0 处违规」。只认前两种就绪失败的写法,会把
    **「一门语言整批没扫」认成「这门语言合规」** —— 一台没装 pwsh 的机器上,
    PowerShell 夹具会假绿,而假绿正是这套自检存在的理由要挡的东西。

    Args:
        out: 闸在夹具上的一次输出。

    Returns:
        没扫到东西时返回 True。
    """
    return (
        # 一个目标文件都没认出来(路径写错、扩展名不支持)
        '没有匹配到任何目标文件' in out
        # 或认出来了但一门语言都没接住
        or '不认得的文件类型' in out
        # 或文件认出来了、后端却起不来,整门语言被跳过
        or '⚠ 跳过' in out
    )


def check_clean_fixtures():
    """每种语言的合规样本都必须报 0 违规。

    阴性对照:合规样本报出违规,说明某条判据过宽。

    Returns:
        `(通过的语言后缀列表, 跳过的语言后缀列表)`。
    """
    passed = []
    skipped = []
    # 逐语言扫描合规样本:各语言样本独立跑闸,验证零缺陷时均报 0 违规
    for fixture in sorted(HERE.glob('fixture_clean.*')):
        # 执行该语言的合规样本,捕获标准输出用于后续断言
        out = run(fixture)
        # 该语言运行环境不可用时跳过,不误判为测试失败
        if fixture_unavailable(out):
            skipped.append(fixture.suffix)
            continue
        assert '0 处违规' in out, f'{fixture.name} 该是合规样本,却报了违规:\n{out}'
        passed.append(fixture.suffix)
    return passed, skipped


def check_bad_fixtures():
    """每种语言的坏样本都必须报出违规。

    阳性对照:断言的是「不为零」而不是具体条数 —— 条数会随后端实现调整而变化,
    写死条数会让每次改判据都变成改测试,于是没人再改判据。
    缺了这条,一份恒绿的空后端能骗过全部阴性对照。

    Returns:
        `(通过的语言后缀列表, 跳过的语言后缀列表)`。
    """
    passed = []
    skipped = []
    # 缺了阳性对照,一个恒绿的空后端能骗过全部阴性对照:必须断言坏样本能报出违规
    for fixture in sorted(HERE.glob('fixture_bad.*')):
        # 运行坏样本捕获输出;断言非零而不是具体条数,避免写死条数导致改判据变成改测试
        out = run(fixture)
        # 该语言运行环境不可用时跳过,不误判为测试失败
        if fixture_unavailable(out):
            skipped.append(fixture.suffix)
            continue
        assert '0 处违规' not in out, f'{fixture.name} 该是坏样本,闸却报 0 违规:\n{out}'
        passed.append(fixture.suffix)
    return passed, skipped


def check_test_fixture():
    """测试特有的三条规则必须**各报一次、且只报该报的**。

    这个夹具是一整个目录而不是单文件,因为其中一条(`test-import-test`)是跨文件判据 ——
    它要拿「本次扫到的另一个测试模块」当白名单,单文件跑不出这个场景。

    🔴 断言里**必须包含阴性的一半**:`tests/helpers.py` 在测试目录里、也改了 `sys.path`,
    但它不是测试模块,三条规则一条都不该命中它。只断言「报出了三条」的话,
    一个把所有 `tests/` 下的文件都当测试模块的实现也会通过 —— 而那正是这套判据
    最容易写错的地方(目录判归属 vs 文件名判是不是测试模块,混成一级)。

    Returns:
        该类样本的一行结论。
    """
    # 这一份是目录夹具:三条规则里有一条要跨文件才判得出来,单文件跑不出那个场景
    out = run(HERE / 'fixture_tests')
    expected = ('test-syspath', 'no-collectable-test', 'test-import-test')
    # 三条各断言一次:「报出了违规」不等于「三条都报出来了」
    for rule in expected:
        assert f'[{rule}]' in out, f'夹具该报出 {rule},却没报:\n{out}'
    # 阴性面:辅助模块不该出现在任何一条测试规则的明细里
    assert 'helpers.py' not in out, f'helpers.py 不是测试模块,不该被测试规则命中:\n{out}'
    return '测试规则阳性 3/3 且未误伤辅助模块'


def check_import_structure():
    """导入结构三条规则必须有阳性、阴性、单文件展开与脚本目录四种对照。

    阳性:包内同层导入必须报 `sibling-import`。阴性:`__init__.py` 的完整包名
    re-export 不算违规,合规包必须 0 违规。展开:只点名一个文件时,同层模块要
    自动纳入,否则平级互导永远判不出来。脚本目录:没有 `__init__.py` 的目录
    不受这条约束,同层导入必须放行。

    Returns:
        该类样本的一行结论。
    """
    # 阳性:坏包里 beta 导入了同目录的 alpha
    bad = run(HERE / 'fixture_imports' / 'bad_pkg')
    assert '[sibling-import]' in bad, f'坏包该报 sibling-import:\n{bad}'
    # 阴性:合规包必须 0 违规
    good = run(HERE / 'fixture_imports' / 'good_pkg')
    assert '0 处违规' in good, f'合规包该是 0 违规:\n{good}'
    # 单文件展开:只点名 beta.py,也要因为它所在的包而报出平级互导
    single = run(HERE / 'fixture_imports' / 'bad_pkg' / 'beta.py')
    assert '[sibling-import]' in single, f'单文件该自动带上同层模块:\n{single}'
    # 脚本目录没有 __init__.py,同层导入是正常组织,必须 0 违规
    scripts = run(HERE / 'fixture_imports' / 'script_dir')
    assert '0 处违规' in scripts, f'脚本目录的同层导入不该算平级互导:\n{scripts}'
    return '导入结构阳性/阴性/单文件展开/脚本目录 4/4'


def check_fix_mode():
    """`--fix` 必须真的把导入排好,不能只打印成功。

    修完的文件要自己再扫一遍,以闸的判据为准 —— 工具说「已处理」不算数。

    Returns:
        该类样本的一行结论;没有 ruff 时返回跳过说明。
    """
    # 在临时目录里复制夹具:--fix 会改文件,不能动仓库里的样本
    with tempfile.TemporaryDirectory() as folder:
        # 本次要修的副本
        target = pathlib.Path(folder) / 'order.py'
        # 夹具原文写到副本里
        target.write_text((HERE / 'fixture_fix' / 'order.py').read_text(encoding='utf-8'),
                          encoding='utf-8')
        # 先跑一次 --fix
        fixed = subprocess.run([sys.executable, str(CHECK), '--fix', str(target)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # 没有 ruff 就显式跳过,不算通过
        if '需要 ruff' in fixed.stdout:
            return '⚠ 跳过(--fix 需要 ruff)'
        # 修完再扫:导入顺序规则必须消失
        out = run(target)
        assert '[import-order]' not in out, f'--fix 没有排好导入顺序:\n{out}'
        assert '0 处违规' in out, f'--fix 后的样本仍有违规:\n{out}'
    return '--fix 自动排序 1/1'


def check_comment_policy():
    """新注释口径的阳性与阴性必须同时成立。

    这条断言钉的是 2026-10-18 的规则:条件链只查链头、简单 for 不要注释、
    while 必查、纯调用赋值不查、Attributes 字段豁免、raise 与 return 不查;
    以及 2026-10-27 的放宽:卫语句、单运算符赋值、非数值字段、记录类与短函数的一行文档不查。
    只验阳性会把「规则被放大」放过,只验阴性会把「规则被删掉」放过。

    Returns:
        该类样本的一行结论。
    """
    # 夹具同时含该报与不该报的形态,按规则名计数
    out = run(HERE / 'fixture_comment_policy.py')
    expected = {
        'uncommented-condition': 1,  # 只有 compound_guard;failures 是卫语句,elif 不单独报
        'uncommented-loop': 1,       # 只有 while;单句 for 被后端滤掉
        'uncommented-field': 1,      # 只有 Bare.gamma;Documented 走 Attributes,label 不是数值
        'uncommented-assign': 1,     # 只有 assignments 的魔数算式;total + value 是单运算符
        'thin-docstring': 0,         # Record 是记录类,short 体长不过门槛
        'docstring-sections': 0,     # short 体长不过门槛,不要求 Args/Returns
    }
    for rule, count in expected.items():
        assert out.count(f'[{rule}]') == count, \
            f'{rule} 应报 {count} 处,实际输出:\n{out}'
    # 两条已被取消的规则不得再出现
    assert '[uncommented-raise]' not in out, f'raise 不应再要求注释:\n{out}'
    assert '[uncommented-return]' not in out, f'return 不应再要求注释:\n{out}'
    return '注释策略阳性/阴性 8/8'


def main():
    """依次跑全部自检,任一条不成立就让它抛出(不吞异常)。

    包含 Python 满覆盖自检、duplicate-toplevel 阳性对照、各语言合规样本扫描
    与文档结构自检。任何一项失败立即抛出 AssertionError 中断流程,全绿时输出
    包含 SELFCHECK_OK 的状态串。
    """
    # 汇总核心覆盖率断言、阳性对照、多语言样本与文档结构的校验结果
    results = [check_python_fixture(), check_comment_policy(), check_duplicate_fixture(),
               check_test_fixture(), check_import_structure(), check_fix_mode(), doccheck.check()]
    clean_ok, clean_skip = check_clean_fixtures()
    bad_ok, bad_skip = check_bad_fixtures()
    results.append(f'合规样本 0 违规:{", ".join(clean_ok) or "无"}')
    results.append(f'坏样本报违规:{", ".join(bad_ok) or "无"}')
    # 取好坏两组对照测试中跳过语言的并集,确保任一阶段跳过均显式汇报
    skipped = sorted(set(clean_skip) | set(bad_skip))
    # 跳过的夹具没被真正扫过,必须显式报出来 —— 否则「全绿」里混着没跑过的项
    if skipped:
        results.append(f'⚠ 跳过(后端不可用):{", ".join(skipped)}')
    print('SELFCHECK_OK ' + ';'.join(results))


if __name__ == '__main__':
    main()
