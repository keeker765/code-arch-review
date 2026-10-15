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

HERE = pathlib.Path(__file__).resolve().parent
# check.py 入口脚本绝对路径,用于 subprocess 驱动自身执行
CHECK = HERE.parent / 'scripts' / 'check.py'


def run(target):
    """跑一次闸,拿它的标准输出。

    刻意不看退出码:坏样本本来就该退出 1,把它当异常会让阳性对照本身变成错误。
    断言一律落在输出文本上(数违规条数、读覆盖率)。

    Args:
        target: 要扫的文件或目录。

    Returns:
        闸的标准输出。
    """
    return subprocess.run([sys.executable, str(CHECK), str(target)],
                          capture_output=True, text=True).stdout


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

    Args:
        out: 闸在夹具上的一次输出。

    Returns:
        没扫到东西时返回 True。
    """
    return '没有匹配到任何目标文件' in out or '不认得的文件类型' in out


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


def main():
    """依次跑全部自检,任一条不成立就让它抛出(不吞异常)。

    包含 Python 满覆盖自检、duplicate-toplevel 阳性对照与各语言合规样本扫描。
    任何一项失败立即抛出 AssertionError 中断流程,全绿时输出包含 SELFCHECK_OK 的状态串。
    """
    # 依次执行满覆盖断言、重复顶层定义阳性对照与各语言合规及坏样本校验
    results = [check_python_fixture(), check_duplicate_fixture()]
    clean_ok, clean_skip = check_clean_fixtures()
    bad_ok, bad_skip = check_bad_fixtures()
    results.append(f'合规样本 0 违规:{", ".join(clean_ok) or "无"}')
    results.append(f'坏样本报违规:{", ".join(bad_ok) or "无"}')
    # 合并两组测试中跳过的语言扩展名后缀集合
    skipped = sorted(set(clean_skip) | set(bad_skip))
    # 跳过的夹具没被真正扫过,必须显式报出来 —— 否则「全绿」里混着没跑过的项
    if skipped:
        results.append(f'⚠ 跳过(后端不可用):{", ".join(skipped)}')
    print('SELFCHECK_OK ' + ';'.join(results))


if __name__ == '__main__':
    main()
