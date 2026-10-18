r"""PowerShell 后端:把 `.ps1` / `.psm1` / `.psd1` 翻译成语言无关的 `FileFacts`。

**为什么走外部进程**:PowerShell 的语法树只存在于 .NET 的
`System.Management.Automation.Language.Parser` 里,Python 侧没有等价物。
于是本模块只干三件事 —— 起进程、收 JSON、组装事实。**任何阈值判断都不在这里**,
那是 `core/rules.py` 的事:换语言只该换语法翻译,不该换阈值。

配套两件:同目录的 `dump.ps1` 负责按 Extent 吐 JSON(与规则无关,内部再拆成
`tokens.ps1` / `nodes.ps1` / `owners.ps1` / `file_facts.ps1`),`help.py` 负责读注释式帮助块。
分成文件是 `long-module` 逼出来的,顺带把「解析」「逐函数量」「判文档」分开了。
`parse_many` 把整批路径交给**同一个**子进程:PowerShell 起进程约 0.3 秒,
逐文件起一次会让扫描一个含几百个脚本的目录从一秒变成一分钟。

🔴 **为什么抽取脚本绝不数大括号**(四条硬坑,踩过才写在这里):
1. `{}` 在 PowerShell 里同时是 scriptblock 定界符、哈希表字面量、`Where-Object {}`
   这类参数块 —— 一个 `@{ a = 1 }` 就让括号深度算错;
2. 字符串与 here-string(`@" ... "@`)里 `{}` 和 `#` 什么都能出现;
3. `$( ... )` 子表达式、`@( ... )` 数组、`${ var }` 变量定界都会改变深度;
4. 行尾反引号是续行:`if ($a -and \`` 换行后的 `$b)` 是**同一个条件**,按物理行数
   会数成两个 —— 方向正好相反。一律取 AST 节点的 `Extent`。

**没实现的两项**(报告里要写明,不是漏做):`flat_runs`(连续平铺段)与
`layout_gaps`(定义间空行)。PowerShell 的语句流里混着 scriptblock 与哈希表,
空行口径也得另定一套,做不准比不做更坏(见 `references/languages.md` 的启发式纪律)。
"""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

from core.model import BindingFact, ConditionFact, FileFacts, FunctionFact, SimpleFact

from lang.powershell import help as powershell_help


# 本后端认的扩展名:脚本(.ps1)、模块(.psm1)、模块清单(.psd1)
EXTS = ('.ps1', '.psm1', '.psd1')

# 宿主探测顺序:优先 pwsh(PowerShell 7),回退 Windows PowerShell 5.1
_PS_HOSTS = ('pwsh', 'powershell')

# 抽取脚本的入口文件名,与后端同目录。真正的抽取逻辑按职责拆在 dump.ps1 与它
# dot-source 的 nodes.ps1 / owners.ps1 / file_facts.ps1 里。
_DUMP_SCRIPT = 'dump.ps1'

# 单批解析超时:正常解析在一秒内,跑到这个量级说明进程卡住,而不是文件多
_TIMEOUT_SECONDS = 120

# 宿主路径只探一次:每个文件都重新 which 一遍是白花的开销
_HOST_PATH = None


def _powershell_host():
    """找到可用的 PowerShell 宿主并缓存路径。

    宿主由 PATH 决定,不由调用方指定 —— 这扇闸要在任何 Windows 机器上直接跑起来,
    多一个配置项就多一处「本机没配所以跳过」的借口。

    Returns:
        可执行文件路径。

    Raises:
        RuntimeError: 两个宿主都不在 PATH 上。**不静默返回空事实** ——
            空事实上报会让报告以「零违规」收场,而实际上一行都没查。
    """
    global _HOST_PATH

    # 一个进程里只探一次:逐文件重新 which 是白花的开销
    if _HOST_PATH is None:
        # 先 pwsh 后 powershell:哪台在 PATH 上就用哪台
        for candidate in _PS_HOSTS:
            # 命中即定,剩下的候选不必再探
            found = shutil.which(candidate)
            # 找到了就记下来,循环到此为止
            if found:
                _HOST_PATH = found
                break
    # 两个都缺时必须炸:静默降级成空事实等于把闸关掉还报绿
    if _HOST_PATH is None:
        # 这里不返回空事实,直接抛给调用方
        raise RuntimeError('找不到 pwsh 也找不到 powershell,PowerShell 后端无法解析')
    return _HOST_PATH


def _command(paths):
    """拼出调用抽取脚本的命令行。

    走 `-File` 而不是 `-Command`:源码路径从 argv 传,绕开命令行的转义地狱。
    批量靠把多个路径一起放进 argv,而不是逐文件起进程 —— 数组形参在 `-File` 下
    只能接到第一个位置参数,所以抽取脚本用 `$args` 收路径。

    Args:
        paths: 待解析的源码路径序列。

    Returns:
        argv 列表,末尾依次是待解析的路径。
    """
    flags = ['-NoProfile', '-NonInteractive']
    # -ExecutionPolicy 只在 Windows 上存在,Linux 的 pwsh 不认这个参数
    if os.name == 'nt':
        flags += ['-ExecutionPolicy', 'Bypass']
    # 抽取脚本与本模块同目录:skill 被整个复制走时两者一起走
    script = Path(__file__).resolve().parent / _DUMP_SCRIPT
    return [_powershell_host(), *flags, '-File', str(script),
            *(str(path) for path in paths)]


def _stderr_text(completed):
    """把子进程的 stderr 解成文本,供报错时带上。

    stderr 是唯一能说明「为什么起不来」的地方:卡在参数上、执行策略被拦、
    脚本自身语法错,都只写在那里,不带出来就只能看到一个退出码。
    """
    return (completed.stderr or b'').decode('utf-8', errors='replace')[:800]


def _as_list(value):
    """把后端 JSON 里的标量 / `null` 归一成列表。

    单元素数组在 JSON 里可能退化成标量(宿主版本不同行为不同),这里统一兜住。
    """
    # 缺字段与显式 null 同义:都当空集合
    if value is None:
        return []
    # 已经是列表就原样返回,免得把它再包一层
    if isinstance(value, list):
        return value
    return [value]


def _run_ast_dump(paths):
    """起一次子进程,批量解析若干文件。

    整批只起一个进程:单文件一次 spawn 约 0.3 秒,一个几百文件的目录逐文件起
    会把闸跑到一分钟。失败的文件在结果里带着 `parse_errors`,不拖垮整批。

    Args:
        paths: 源码路径序列。

    Returns:
        `{路径字符串: 该文件的原始字典}`。

    Raises:
        RuntimeError: 宿主缺失、超时、退出码非零,或返回值不是预期的 JSON。
    """
    try:
        # 输出一次收齐:整批结果都在这里,不再逐文件起进程
        completed = subprocess.run(_command(paths), capture_output=True,
                                   timeout=_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired as error:
        # 超时按失败处理:正常解析不该跑到这个量级
        raise RuntimeError(f'PowerShell 解析超时(>{_TIMEOUT_SECONDS}s):'
                           f'{len(paths)} 个文件') from error
    # 宿主把异常写在 stderr 上并用非零码退出,带上 stderr 才定位得出来
    if completed.returncode != 0:
        # 退出码非零说明整批都没跑起来,这时候不能假装扫过了
        raise RuntimeError(f'PowerShell 解析失败(退出码 {completed.returncode})\n'
                           f'{_stderr_text(completed)}')
    # 输出是 base64:宿主之间的 stdout 编码约定不一致,先编成 ASCII 才不会被改写字
    raw = json.loads(base64.b64decode(completed.stdout).decode('utf-8'))
    return {str(item.get('path')): item for item in _as_list(raw.get('results'))}


def _read_lines(path):
    """按 UTF-8 读源码并切成行。

    行数口径与 Python 后端一致(按行切、不含行尾换行),这样 `long-module`
    在两个语言上比较的是同一个东西。
    """
    return path.read_text(encoding='utf-8', errors='replace').splitlines()


def _function_fact(item):
    """把后端的一条函数记录变成 `FunctionFact`。

    参数表里没有 `self` / `cls` 这类绑定实参可剔 —— PowerShell 没有这种形参,
    管道传进来的值是运行时才有的,不在形参表里。
    """
    name = str(item.get('name') or '')  # 缺名字就退化成空串,报告里显示行号
    params = tuple(str(param) for param in _as_list(item.get('params')))  # 形参名已去掉 $
    doc = powershell_help.clean(item.get('doc'))  # 剥掉 <# #> 定界符
    # 没有帮助块就没什么可缺的:缺的是整块文档,由 no-docstring 去报
    required, missing = powershell_help.missing_sections(
        doc, params, bool(item.get('has_return'))) if doc else ((), ())
    return FunctionFact(
        name=name,
        line=int(item.get('line') or 0),
        end_line=int(item.get('end_line') or 0),
        body_lines=int(item.get('body_lines') or 0),
        params=params,
        is_public=not name.startswith('_'),
        is_class=bool(item.get('is_class')),
        doc=doc,
        required_sections=required,
        missing_sections=missing,
        string_key_count=int(item.get('string_key_count') or 0),
        nesting_depth=int(item.get('nesting_depth') or 0),
        doc_prose_lines=powershell_help.prose_lines(doc) if doc else 0,
    )


def _build_functions(raw):
    """组装全部函数 / 方法 / 类事实。

    类方法与普通函数走同一条路径:PowerShell 的方法也是 Verb-Noun 命名、
    也有 `param()` 块,判据没有区别。
    """
    return [_function_fact(item) for item in _as_list(raw.get('functions'))]


def _build_conditions(raw):
    """组装全部条件事实。

    子条件行号由抽取脚本按 `-and` / `-or` 摊平给出,保留在 `operand_lines` 里作诊断。
    2026-10-18 起注释规则只看条件起始行,不再逐个 operand 要求注释。
    """
    facts = []
    # 一个 clause 一条事实:if 与 elseif 各算一个
    for item in _as_list(raw.get('conditions')):
        rows = tuple(int(row) for row in _as_list(item.get('operand_lines')))  # 子条件行号
        facts.append(ConditionFact(line=int(item.get('line') or 0), operand_lines=rows))
    return facts


def _build_simple(raw, key, accepts_inline):
    """组装只按行号判定的构造(循环 / 抛异常 / 字段 / 赋值 / return)。

    这五种共用 `SimpleFact`,差别只在 `accepts_inline` 与所在的键:
    字段、赋值、return 接受行尾注释(一行放得下),循环与 throw 不接受。
    """
    return [SimpleFact(line=int(item.get('line') or 0),
                       label=str(item.get('label') or ''),
                       accepts_inline=accepts_inline)
            for item in _as_list(raw.get(key))]


def _build_bindings(raw):
    """组装模块顶层的直接绑定。

    只收模块体**直接**子节点:嵌在 `if` / `try` 里的同名定义是合法形态
    (按版本分支、回退定义),放进来会制造噪声。
    """
    return [BindingFact(name=str(item.get('name') or ''),
                        kind=str(item.get('kind') or ''),
                        line=int(item.get('line') or 0),
                        references_self=bool(item.get('references_self')))
            for item in _as_list(raw.get('bindings'))]


def _facts_from(path, raw):
    """把一份原始输出组装成 `FileFacts`。

    组装与取数分开:`parse` 与 `parse_many` 对「这份数据能不能用」判断不同,
    但对「怎么变成事实」必须完全一致,否则同一次扫描里两条路径会分叉。
    `flat_runs` 与 `layout_gaps` 留默认空,原因见本模块开头。
    """
    return FileFacts(
        path=path,
        language='PowerShell',
        total_lines=len(_read_lines(path)),
        comment_rows=set(_as_list(raw.get('comment_rows'))),
        whole_line_rows=set(_as_list(raw.get('whole_line_rows'))),
        module_doc=powershell_help.clean(raw.get('module_doc')),
        functions=_build_functions(raw),
        conditions=_build_conditions(raw),
        loops=_build_simple(raw, 'loops', False),
        raises=_build_simple(raw, 'raises', False),
        fields=_build_simple(raw, 'fields', True),
        assigns=_build_simple(raw, 'assigns', True),
        returns=_build_simple(raw, 'returns', True),
        silent_except_lines=[int(row) for row in _as_list(raw.get('silent_except_lines'))],
        bindings=_build_bindings(raw),
    )


def parse(path: Path) -> FileFacts:
    """把一份 PowerShell 源码翻译成语言无关的 `FileFacts`。

    单文件入口。语法错误在这里抛出去而不是咽掉 —— 把它当成「这个文件没有构造」
    会让闸静默放过一个坏文件;要批量扫目录时用 `parse_many`,由它按差额报告。

    Args:
        path: `.ps1` / `.psm1` / `.psd1` 路径。

    Returns:
        该文件的事实。阈值判断不在这里做:引擎只吃事实。

    Raises:
        RuntimeError: 宿主缺失、子进程超时或失败、文件读不到、源码有语法错误。
    """
    dumped = _run_ast_dump([path])  # 单文件也走批量入口,组装逻辑只有一条
    # 子进程没给出这个文件的结果,说明连路径都没送到
    raw = dumped.get(str(path))
    # 拿不到结果就没法组装事实,只能报错
    if raw is None:
        # 这里必须抛:返回空事实会让这个文件以「零违规」混过去
        raise RuntimeError(f'PowerShell 没有返回 {path} 的解析结果')
    # 语法错误由抽取脚本捕获后放在这里,不在脚本里抛 —— 一个坏文件不该拖垮整批
    errors = _as_list(raw.get('parse_errors'))
    # 有语法错就说明这份 AST 不可信,别拿它当事实
    if errors:
        # 抛出去让调用方看见,而不是当成「这个文件没有构造」
        raise RuntimeError(f'{path} 有 PowerShell 语法错误:{errors[0]}')
    return _facts_from(path, raw)


def parse_many(paths):
    """批量解析,整批只起一次子进程。

    失败的文件**跳过而不是中断整批**,但调用方会按文件数差额察觉 ——
    静默少扫几个文件等于把「零违规」变成谎话(见 `lang/registry.py`)。

    Args:
        paths: 文件路径列表。

    Returns:
        `FileFacts` 列表,顺序与入参一致;读不了或语法坏掉的文件不在里面。
    """
    dumped = _run_ast_dump(paths)  # 整批一次子进程
    facts = []
    # 按入参顺序回填,保证报告里的文件顺序稳定
    for path in paths:
        raw = dumped.get(str(path))  # 抽取脚本按入参原样回填路径
        # 子进程没回来结果,或回来的是读不了/语法坏 ⇒ 这个文件没有事实
        if raw is None or _as_list(raw.get('parse_errors')):
            continue
        facts.append(_facts_from(path, raw))
    return facts
