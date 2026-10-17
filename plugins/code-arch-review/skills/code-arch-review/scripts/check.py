"""结构闸:量「读起来累不累」,不量风格。纯 stdlib,不装任何依赖。

为什么不是 ruff / black / eslint:格式问题本来就没人吵,吵的是结构 —— 上帝函数、
dict 当接口、深嵌套、没有文档的公开类。这些 linter 一条都不查。

用法:
    python <skill目录>/scripts/check.py <路径...> [--max-body 60] [--json] [--fix]

退出码 1 = 有违规(启发式档的结构度量三条只报不拦,不计入退出码),可直接当 CI / 交付闸。
一个目标都没匹配到时**报错退出**,不让空集冒充通过。
"""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

# 本文件是包的入口,要先把 scripts/ 放进搜索路径,后面的 core / lang 才导入得到。
# 这不是可以挪到文件顶部的风格问题 —— 导入必须先于路径设置。
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from core import package, report          # noqa: E402
from core.rules import evaluate           # noqa: E402
from lang import registry                 # noqa: E402

# 源码树扫描时要跳过的目录。这些不是「作者写的代码」,扫它们只会淹没真信号。
#
# `vendor` 与 `third_party` 和 `node_modules` 同类:放的是第三方的副本或压缩产物。
# 代价说清楚 —— 真有项目在里面手写代码,那些文件会被静默漏掉,所以这两个名字只在
# **整个目录名**匹配时跳过,`src/vendor_utils/` 这种不受影响。
_SKIP_DIRS = frozenset({
    '__pycache__', '.git', '.hg', '.svn', 'node_modules', '.venv', 'venv',
    '.mypy_cache', '.pytest_cache', '.ruff_cache', 'dist', 'build', '.tox',
    'vendor', 'third_party',
})


def discover(paths, skip_dirs):
    """把命令行给的文件与目录摊平成「认得的目标文件」列表。

    递归遍历指定目录并自动跳过缓存与虚拟环境等非业务目录,过滤出各后端已注册
    的有效源码文件;对于命令行显式传入的单文件,若不支持则记录至未识别列表以便告警。

    跳过名单由调用方给(默认名单 + `--exclude`),而不是直接读模块常量:
    仓库里夹着生成物(浏览器 profile、抓取缓存)时,调用方要能自己声明「这些不是代码」,
    否则只剩「把整个目录拆成文件清单」一条路。**跳过的名单只对目录递归生效**,
    显式点名的单文件一律照扫 —— 那是最直接的逃生口。

    Args:
        paths: 命令行给的文件或目录。
        skip_dirs: 递归时要跳过的目录名集合,整个目录名匹配。

    Returns:
        `(文件列表, 不认识但被显式点名的文件列表)`。显式点名一个闸不支持的文件要报出来,
        不能悄悄跳过 —— 那会让人以为它查过了。
    """
    found = []
    unknown = []
    # 显式点名的单文件与目录在此分流:文件单独判是否受支持,目录递归展开
    for path in paths:
        # 显式点名单文件必须回话,哪怕暂不支持也不能静默丢掉
        if path.is_file():
            # 显式点名一个文件:认不认得都要有回话
            if registry.detect(path) is None:
                unknown.append(path)
            else:
                found.append(path)
                # 包目录里的单文件要把同层模块一起纳入:平铺与平级互导判据要看整层
                if (path.parent / '__init__.py').exists():
                    found.extend(sibling for sibling in path.parent.iterdir()
                                 # 同层、受支持的文件才算上下文;目录在这里不递归
                                 if sibling.is_file() and registry.detect(sibling) is not None)
            continue
        # 目录才递归展开,与显式单文件分开收集
        for candidate in path.rglob('*'):
            # 先按目录剪枝,否则 node_modules 会把这一趟拖成分钟级
            if any(part in skip_dirs for part in candidate.parts):
                continue
            if (
                # 候选路径必须是实际文件而非目录或符号链接
                candidate.is_file()
                # 文件扩展名必须已被已注册的语言后端所支持
                and registry.detect(candidate) is not None
            ):
                found.append(candidate)
    return sorted(set(found)), unknown


def fix_imports(files):
    """用 ruff 的 isort 规则自动排好 Python 文件的导入顺序。

    只处理 `.py`:其它语言的导入语法不同,ruff 也不认。ruff 缺失时**明确报错退出**,
    不能把「没修」当成「已修」;退出码 1 表示还有未修复项,继续扫就是为了把它们报出来。

    Args:
        files: 本次扫描到的目标文件。
    """
    # 只有 Python 文件归 ruff 管
    targets = [str(item) for item in files if item.suffix == '.py']
    # 没有 Python 文件就没什么可修的
    if not targets:
        return
    # 先探一次 ruff:缺工具时要给出安装命令,而不是静默跳过
    probe = subprocess.run([sys.executable, '-m', 'ruff', '--version'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # 探不到 ruff 就停下,让调用方装好再来
    if probe.returncode != 0:
        sys.exit('--fix 需要 ruff:python -m pip install ruff')
    # 一次传给 ruff:按全路径排序(不按 import/from 分两段),起一个进程就够
    done = subprocess.run(
        [sys.executable, '-m', 'ruff', 'check', '--select', 'I', '--fix', '--quiet',
         '--config', 'lint.isort.force-sort-within-sections=true', *targets],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # 退出码 1 表示还有未修复项,不是失败;其它非零才是工具本身出错
    if done.returncode not in (0, 1):
        sys.exit(f'--fix 失败(退出码 {done.returncode}):{done.stdout.strip()[:300]}')
    print(f'--fix:ruff 已处理 {len(targets)} 个 Python 文件的导入顺序')


def apply_overrides(languages, args):
    """把命令行给的阈值覆盖到每门语言上。

    只覆盖**显式传了**的那几项。放宽阈值必须在交付说明里写明放宽了哪一条、为什么
    —— 闸不做静默改数。

    Args:
        languages: 可用的语言配置。
        args: 解析好的命令行参数。

    Returns:
        `{语言名: 阈值}`。
    """
    overrides = {}
    # 逐语言处理配置:独立构造每种语言最终生效的阈值对象以防跨语言污染
    for language in languages:
        changes = {}
        # 覆写项与 Thresholds 字段一一对应,None 表示调用方未在命令行指定
        for name in ('max_body', 'max_kwargs', 'max_keys', 'max_depth',
                     'min_module_doc', 'max_modules', 'max_flat', 'max_module_lines',
                     'max_declarations'):
            # 没传时不出现在 changes 里,保持该语言原本设定的默认阈值
            value = getattr(args, name)
            # 没传就保持该语言自己的值,不要拿默认值把它盖掉
            if value is not None:
                changes[name] = value
        overrides[language.name] = replace(language.thresholds, **changes) if changes \
            else language.thresholds
    return overrides


def run(paths, args):
    """扫一遍并把结果整理成可打印的数据。

    协调文件发现、后端可用性检测、按语言批处理解析与规则求值全流程。
    收集各文件事实后计算代码覆盖率与说明密度,并打包跳过原因与未识别文件清单。

    Args:
        paths: 命令行给的路径。
        args: 解析好的命令行参数。

    Returns:
        `(违规列表, 文件数, 跳过的语言, 已解释构造数, 构造总数, 密度, 未认得的文件)`。
    """
    # 默认跳过名单 + 调用方用 --exclude 声明的:后者是仓库里夹着生成物时的逃生口
    files, unknown = discover(paths, _SKIP_DIRS | frozenset(args.exclude))
    # 开了 --fix 就先排导入,再扫;否则扫的是修之前的树
    if args.fix:
        fix_imports(files)
    ready, failed = registry.available()
    # 结合命令行显式传入的阈值参数,生成各可用语言最终生效的阈值映射字典
    overrides = apply_overrides(ready, args)
    ready_names = {language.name for language in ready}
    # 分组:每种语言一次交给后端,好让需要 spawn 进程的后端只起一次
    grouped = {language.name: [] for language in ready}
    # 逐文件归类到对应语言分组,以便各语言后端执行整批解析
    for item in files:
        # 根据文件扩展名与命名规则探测所属编程语言配置
        language = registry.detect(item)
        # 后端起不来的语言(缺 node / 缺 pwsh)在这里被挡掉,原因已在 failed 里记着
        if language.name in ready_names:
            grouped[language.name].append(item)

    findings = []
    all_facts = []
    covered = 0
    total = 0
    # 按语言分组后分批喂给对应后端,使多文件共用一次 pwsh/node 子进程开销
    for language in ready:
        targets = grouped[language.name]
        # 当前语言未匹配到待扫描的目标文件时直接跳过,避免后端无效启动
        if not targets:
            continue
        # 一门语言一趟:解析、规则求值、跨文件的包级判据都在 scan_language 里
        found, facts, lang_covered, lang_total = scan_language(
            language, targets, overrides[language.name], failed)
        findings.extend(found)
        all_facts.extend(facts)
        covered += lang_covered
        total += lang_total
    return findings, len(all_facts), failed, covered, total, report.density(all_facts), unknown


def scan_language(language, targets, thresholds, failed):
    """把一门语言的这一批文件扫完,产出违规、事实与覆盖率的分子分母。

    单开一层是为了让 `run` 只呈现阶段:一门外语言的完整流程(解析 → 逐文件求值 →
    包级判据)与另外五门完全一样,混在主流程里会把「扫了哪些语言」这件主线淹掉。

    Args:
        language: 该语言的配置。
        targets: 这门语言的待扫文件。
        thresholds: 这门语言生效的阈值(可能已被命令行覆写)。
        failed: 跳过原因列表,原地追加。

    Returns:
        `(违规列表, 事实列表, 已解释构造数, 构造总数)`;后端起不来时四项都为空。
    """
    # 整批交由后端解析:语法分析不执行代码,多文件单次子进程拉起大幅缩短耗时。
    # 后端起不来**在这里兜住**:PowerShell 后端在没有 pwsh 的机器上是解析时才发现的,
    # 冒出去等于整趟扫描以 traceback 收场 —— 正确行为是记成「跳过这门语言」,
    # 与 `registry.available()` 那批一样进报告,读者才知道自己少扫了什么。
    try:
        # 后端起不来会在这个调用里抛,交给下面的 except 转成跳过原因
        facts_list = language.backend.parse_many(targets)
    except RuntimeError as error:
        failed.append((language.name, str(error)))
        return [], [], 0, 0
    # 后端跳过解析失败的文件 —— 这里按差额察觉,不静默当作「零违规」
    if len(facts_list) < len(targets):
        failed.append((language.name, f'{len(targets) - len(facts_list)} 个文件解析失败'))
    findings = []
    covered = 0
    total = 0
    # 事实与阈值比对是语言无关的通用规则逻辑,同一套规则解释多门语言
    for facts in facts_list:
        # 运行核心规则集合评估该文件的违规情况与注释覆盖度
        outcome = evaluate(facts, thresholds, language.disabled_rules)
        findings.extend(item for item in outcome.findings
                        if item.rule not in language.disabled_rules)
        covered += outcome.covered
        total += outcome.total
    # 包级形状(平铺目录、同名模块)要拿整批路径一起看,单个文件判不出来
    findings.extend(item for item in package.package_shape(targets, thresholds.max_modules,
                                                           language.reserved)
                    if item.rule not in language.disabled_rules)
    # 测试模块互相 import 是跨文件判据:要拿本次扫到的全部测试模块名当白名单
    findings.extend(item for item in package.test_imports(facts_list)
                    if item.rule not in language.disabled_rules)
    # 同目录互导、导入顺序与一行多个 import:要拿整批事实一起看
    findings.extend(item for item in package.import_structure(facts_list, language.reserved)
                    if item.rule not in language.disabled_rules)
    return findings, facts_list, covered, total


def main():
    """命令行入口。

    解析命令行参数,执行全局代码结构与注释验收,输出格式化文本或结构化 JSON,
    并根据是否存在需拦截的硬性违规设置进程退出码。
    """
    # 构造命令行参数解析器,定义所有支持的结构检查阈值与输出控制开关
    parser = argparse.ArgumentParser(description='代码结构闸')
    parser.add_argument('paths', nargs='+', type=Path)
    # 默认一律 None:None 表示「不动这门语言自己的值」,按语言给的阈值在 lang/registry.py
    parser.add_argument('--max-body', type=int, default=None)
    parser.add_argument('--max-kwargs', type=int, default=None)
    parser.add_argument('--max-keys', type=int, default=None)
    parser.add_argument('--max-depth', type=int, default=None)
    # 模块文档行数阈值与目录层级模块数上限
    parser.add_argument('--min-module-doc', type=int, default=None)
    parser.add_argument('--max-modules', type=int, default=None)
    parser.add_argument('--max-flat', type=int, default=None)
    parser.add_argument('--max-module-lines', type=int, default=None)
    parser.add_argument('--max-declarations', type=int, default=None)
    # 格式化输出选项:开启时以 JSON 结构输出原始违规列表
    parser.add_argument('--json', action='store_true')
    # 先用 ruff 自动排导入,再扫描;缺 ruff 时明确报错
    parser.add_argument('--fix', action='store_true')
    # 额外要跳过的目录名。可重复,判据与 _SKIP_DIRS 相同(整个目录名匹配)
    parser.add_argument('--exclude', action='append', default=[], metavar='目录名')
    # 命令行参数决定阈值覆写与输出模式,不合法入参由 argparse 内部拦截
    args = parser.parse_args()

    findings, file_count, skipped, covered, total, density, unknown = run(args.paths, args)
    # 空集不许冒充通过:一个目标都没扫到,说明路径写错了或语言不支持
    if not file_count:
        # 汇总前 5 个未知文件的扩展名,用于友好的未命中原因回显
        names = ', '.join(path.suffix or '(无扩展名)' for path in unknown[:5])
        sys.exit(f'没有匹配到任何目标文件,拒绝以「零违规」收场。'
                 f'未支持的扩展名:{names or "无"}')

    # 启发式后端的结构项易误报,仅阻断型硬指标决定非零退出码
    blocking = report.blocking(findings)
    # 指定 --json 选项时直接输出结构化结果,供自动化工具消费
    if args.json:
        print(json.dumps([item.__dict__ for item in findings], ensure_ascii=False, indent=2))
    else:
        print(report.render(findings, file_count, skipped, covered, total))
        print(f'说明密度 {density:.1f}%   (参照:20% 以下基本可判定「只有一行式文档,'
              f'没有解释为什么」)')
        # 显式点名但无法识别的文件逐条提示,避免读者误以为这些路径已通过审查
        for path in unknown:
            print(f'⚠ 不认得的文件类型,已跳过:{path}')
    sys.exit(1 if blocking else 0)


if __name__ == '__main__':
    main()
