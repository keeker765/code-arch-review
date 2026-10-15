"""JavaScript / TypeScript 后端:把源码翻成 `core.model.FileFacts`。**半精确档。**

首选走 `node` 跑 TypeScript 编译器自带的 `ts.createSourceFile`(只 parse,不 typecheck):
`//` 会出现在字符串、模板串与正则里,只有真解析分得清;对象字面量、模板插值与解构
都会让括号深度失真;而 `function f(){} function f(){}` 这种**静默后者胜出**只有 AST
看得见(见 `references/languages.md` 的 JS/TS 一节)。

拿不到 `node` 或拿不到 typescript 包时降级到 `js_fallback`(纯 Python 启发式)。
降级会往 stderr 写一行原因 —— 报告里的「(启发式)」标记只在有违规时才看得见,而
「整批文件根本没被精确解析」这件事必须说出来,否则「零违规」会被读成「代码没问题」。

🔴 一次 node 进程处理**整批**文件:进程启动本机 50~200 ms,逐文件起进程等于把扫描时间
全花在启动上。文件路径从 stdin 传而不走命令行 —— Windows 命令行有长度上限,几百个
绝对路径会把参数列表撑爆。

本文件只管「怎么跑 node、怎么把它的 JSON 翻成事实」;找 node 与 typescript 的位置在
`js_env`,启发式那一档在 `js_fallback`。
"""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from core.model import BindingFact, ConditionFact, FileFacts, FunctionFact, SimpleFact
from .js_fallback import facts_for as _fallback_facts
from .js_env import node_binary, note_once, typescript_dir

EXTS = ('.js', '.mjs', '.cjs', '.jsx', '.ts', '.mts', '.cts', '.tsx')
LANGUAGE = 'javascript'

# node 侧的解析脚本,与本文件同目录。
_PROBE = Path(__file__).with_name('js_probe.mjs')

# 一次 node 进程处理多少文件:够摊薄启动开销,又不至于把整份 JSON 结果堆在内存里。
_BATCH = 200

# node 的硬超时。卡死要变成一次可见的降级,不能让整条闸无声地挂着。
_TIMEOUT = 900


def parse(path: Path) -> FileFacts:
    """解析一个 JS / TS 文件,产出语言无关的事实。

    单文件调用也要起一次 node —— 精确档的代价就在这里;批量扫描请用 `parse_many`,
    它会把整批文件合并成一次进程调用。

    Args:
        path: 文件路径。

    Returns:
        该文件的事实;走 node 真解析时为 `heuristic=False`。

    Raises:
        OSError: 文件读不到 —— 不吞掉,让调用方决定怎么报。
    """
    target = Path(path)                                 # 统一成 Path,后端接口收的就是它
    data = _usable(parse_with_node([target]).get(0))       # 单个文件的解析结果
    # node 侧没解析成(读不动、或整台机器拿不到 typescript)就自己数一遍
    if not data:
        return _fallback_facts(target)
    return facts_from_json(target, data)


def parse_many(paths) -> list:
    """批量解析。整批文件只起一次 node 进程。

    单个文件读不动时跳过它而不是中断整批 —— 调用方按文件数差额察觉,不静默当作通过。

    Args:
        paths: 文件路径列表。

    Returns:
        `FileFacts` 列表,顺序与 `paths` 一致(读不动的除外)。
    """
    targets = [Path(item) for item in paths]
    parsed = parse_with_node(targets)                      # 整批的结果,按位置索引
    facts = []
    # 逐文件翻译:node 的结果直接拿来用,没有结果才回落到启发式
    for index, target in enumerate(targets):
        data = _usable(parsed.get(index))               # 这一条可用的事实,没有就是 None
        try:
            facts.append(facts_from_json(target, data) if data else _fallback_facts(target))
        except OSError:
            continue
    return facts


def parse_with_node(targets):
    """把整批文件交给 node 侧的解析器,返回按位置索引的结果。

    node 或 typescript 拿不到、以及子进程层面的失败(启动不了、超时、输出不是 JSON)
    都返回空字典,由调用方把**整批**回落到启发式:这是解析器本身没跑成,不是
    「某个文件有问题」,所以回落而不是中断。

    Args:
        targets: 文件路径列表。

    Returns:
        `{位置: 该文件的结果}`;不可用时是空字典。
    """
    node = node_binary()                                # node 可执行文件的路径
    # node 都没有就没什么可谈的,整批走启发式
    if not node:
        note_once('PATH 里找不到 node')
        return {}
    typescript = typescript_dir(targets)                    # 编译器包的位置
    # typescript 包是解析器的本体,缺了同样只能走启发式
    if not typescript:
        note_once('找不到 typescript 包(可用环境变量指到包目录)')
        return {}
    parsed = {}
    offset = 0
    # 逐批交给 node:启动开销按批摊薄,不按文件重复付
    for batch in _batches(targets):
        try:
            results = _run_node(node, typescript, batch)    # 这一批的结果,顺序同输入
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
            note_once(f'node 解析失败({error})')
            return {}
        # 结果按位置对上文件:node 侧保证顺序与输入一致
        for item in results:
            parsed[offset] = item
            offset += 1
    return parsed


def _batches(targets):
    """把文件列表切成每批 `_BATCH` 个。

    分批是为了限制单次子进程的输入与输出规模:一次把上千个文件塞进去,
    光是拼出来的 JSON 就够占满内存,而失败也只能整批重来。

    Args:
        targets: 文件路径列表。

    Yields:
        每一批的路径切片。
    """
    # 步长就是批大小,最后一批可能不满
    for start in range(0, len(targets), _BATCH):
        yield targets[start:start + _BATCH]


def _run_node(node, typescript, targets):
    """跑一次 node 解析脚本。

    路径走 stdin:Windows 的命令行有长度上限,几百个绝对路径会把参数列表撑爆。

    Args:
        node: node 可执行文件路径。
        typescript: typescript 包目录。
        targets: 这一批的文件路径。

    Returns:
        node 侧的结果列表,顺序与 `targets` 一致。

    Raises:
        RuntimeError: node 退出码非零 —— 由调用方决定整批回落。
    """
    payload = json.dumps([str(item) for item in targets], ensure_ascii=False)   # 走 stdin 的输入
    done = subprocess.run(                              # 子进程一次拿全这批结果
        [node, str(_PROBE), typescript], input=payload,
        capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=_TIMEOUT)
    # 非零退出说明解析器自己没跑成,不是某个文件的问题
    if done.returncode:
        # 失败要带着 stderr 前一段抛出去:没有它,回落就变成了「不知道发生了什么」
        raise RuntimeError(f'退出码 {done.returncode}:{done.stderr.strip()[:200]}')
    return json.loads(done.stdout)['results']


def usable(result):
    """node 侧返回的一条结果能不能用。

    `{"path": ..., "error": ...}` 这种形状说明 node 侧连那个文件都没读成 ——
    它没有事实可用,只能回落。返回 None 而不是空字典,是为了让调用方
    一眼看出「这一条不可用」而不是「这个文件什么都没有」。

    Args:
        result: 该位置的解析结果;没有对应结果时为 None。

    Returns:
        可用的事实字典;该条解析失败或缺失时返回 None,由调用方回落到启发式。
    """
    # 没有这一条说明整批都没拿到结果
    if not result:
        return None
    # 单文件解析失败的那一条只有错误说明
    if 'error' in result:
        return None
    return result


def facts_from_json(path, data):
    """把 node 侧的一条结果翻成 `FileFacts`。

    五类按行判定的构造(循环 / 抛异常 / 字段 / 赋值 / `return`)形状一样,合并成
    一次调用;文件级的四项走 `_head_facts`。

    Args:
        path: 文件路径。
        data: node 侧解析出来的一条事实。

    Returns:
        该文件的事实;走的是真解析,所以 `heuristic=False`。
    """
    head = _head_facts(data)                                # 总行数 / 注释行 / 模块文档
    return FileFacts(
        path=path,
        language=LANGUAGE,
        total_lines=head[0],
        comment_rows=head[1],
        whole_line_rows=head[2],
        module_doc=head[3],
        functions=_function_facts(data),
        conditions=_condition_facts(data),
        loops=_simple_facts(data, 'loops', False),
        raises=_simple_facts(data, 'raises', False),
        fields=_simple_facts(data, 'fields', True),
        assigns=_simple_facts(data, 'assigns', True),
        returns=_simple_facts(data, 'returns', True),
        silent_except_lines=[int(row) for row in data['silent_except_lines']],
        bindings=_binding_facts(data),
        flat_runs=[tuple(item) for item in data['flat_runs']],
        layout_gaps=[tuple(item) for item in data['layout_gaps']],
        heuristic=False,
    )


def _head_facts(data):
    """文件级的四项:总行数、注释行、独立整行注释行、模块文档。

    四样一起返回是因为它们都只由文件头一段算出来,分成四个函数会让读取同一份
    数据跑四遍;而拼成一个元组又比再造一个中间数据结构省事。

    Args:
        data: node 侧解析出来的一条事实。

    Returns:
        `(总行数, 注释行号集合, 整行注释行号集合, 模块文档)`。
    """
    return (int(data['total_lines']), set(data['comment_rows']),
            set(data['whole_line_rows']), data['module_doc'])


def _function_facts(data):
    """全部函数 / 类事实。

    JSON 里只有 list,而模型声明的是 tuple,在这里归一 —— 免得下游按 tuple 用
    (`fn.params + ('x',)`)时才发现拿到的是 list。

    Args:
        data: node 侧解析出来的一条事实。

    Returns:
        `FunctionFact` 列表。
    """
    facts = []
    # 逐条建事实:字段名与模型一一对应,改模型时这里会立刻炸出来
    for item in data['functions']:
        facts.append(replace(
            FunctionFact(**item),
            params=tuple(item['params']),
            required_sections=tuple(item['required_sections']),
            missing_sections=tuple(item['missing_sections']),
        ))
    return facts


def _condition_facts(data):
    """全部 `if` / `else if` 事实。

    行号是「子条件所在的行」,node 侧已经摊平算好,这里只做类型转换。

    Args:
        data: node 侧解析出来的一条事实。

    Returns:
        `ConditionFact` 列表。
    """
    return [ConditionFact(line=int(item['line']), operand_lines=tuple(item['operand_lines']))
            for item in data['conditions']]


def _simple_facts(data, key, inline):
    """按行判定的五类构造:循环 / 抛异常 / 字段 / 赋值 / `return`。

    它们形状完全一样(一行加一个标签),差别只在接不接受行尾注释,所以合成一条路径,
    取哪一类由调用方给键名 —— 五份几乎相同的代码只会让改一处要改五遍。

    Args:
        data: node 侧解析出来的一条事实。
        key: 取哪一类。
        inline: 这一类是否接受**行尾**注释(字段 / 赋值 / `return` 接受)。

    Returns:
        `SimpleFact` 列表。
    """
    return [SimpleFact(line=int(item['line']), label=item['label'], accepts_inline=inline)
            for item in data[key]]


def _binding_facts(data):
    """模块顶层的直接绑定,判 `duplicate-toplevel` 用。

    只有 `var` 与 `function` 会出现在这份清单里 —— `let` / `const` 的重复声明
    是语法错误,引擎自己会报,放进来的话只会制造假阳性。

    Args:
        data: node 侧解析出来的一条事实。

    Returns:
        `BindingFact` 列表。
    """
    return [BindingFact(name=item['name'], kind=item['kind'], line=int(item['line']),
                        references_self=bool(item['references_self']))
            for item in data['bindings']]
