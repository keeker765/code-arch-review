"""找 node 与 typescript 包 —— JS / TS 后端能不能走精确档,全看这两个探测。

分出来单独一个文件有两个理由。一是它跟「怎么解析」没关系,是「这台机器上有什么」;
二是探测要写不少注释(每一条候选路径为什么在这个优先级上),和解析代码挤在一起
会超过单文件 500 行的硬闸。

探测结果**整个进程只算一次**:一次扫描会问很多次「typescript 在哪」,每次都去 walk
一遍磁盘等于把扫描时间花在重复 stat 上。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# typescript 包的位置可以用环境变量直接指过去:项目里没装、又不想全局装时用它。
TS_ENV = 'CODE_ARCH_REVIEW_TS'

# node 的硬超时。卡死要变成一次可见的降级,不能让整条闸无声地挂着。
_TIMEOUT = 900

# 向上找 node_modules 的层数上限 —— 到盘根就停。
_WALK_LIMIT = 24

_NODE = None            # node 可执行文件路径;'' 表示确认这台机器上没有
_TYPESCRIPT = None      # typescript 包目录;'' 表示确认这台机器上没有
_NOTED = False          # 降级说明只往 stderr 写一次


def note_once(message):
    """把降级原因写一行到 stderr,只写一次。

    报告里的「(启发式)」标记只在有违规时才看得见,而「整批文件根本没被精确解析」
    这件事必须让人知道 —— 否则「零违规」会被读成「代码没问题」。

    Args:
        message: 降级原因。
    """
    global _NOTED
    # 一次扫描里 node 侧会失败很多次(每个文件都问一遍),原因却是同一个
    if _NOTED:
        return
    _NOTED = True
    print(f'⚠ JS/TS 后端降级为启发式:{message}', file=sys.stderr)


def node_binary():
    """node 可执行文件的路径,探测一次后缓存。

    `shutil.which` 在 Windows 上认 `PATHEXT`,所以 `node.cmd` 这类包装也能找到,
    比自己拼路径靠谱。

    Returns:
        路径字符串;PATH 里没有 node 时返回空串。
    """
    global _NODE
    # 只在第一次问的时候真的去 PATH 里找
    if _NODE is None:
        _NODE = shutil.which('node') or ''
    return _NODE


def typescript_dir(targets):
    """typescript 包目录,探测一次后缓存。

    缓存的是「找不到」这个结论也一样:一次扫描里问上百遍,每遍都去 walk 磁盘
    会把扫描时间全花在重复 stat 上,而磁盘内容在一次扫描里不会变。

    Args:
        targets: 本次要解析的文件 —— 就近找项目自己装的那一份。

    Returns:
        包目录字符串;这台机器上找不到时返回空串。
    """
    global _TYPESCRIPT
    # 第一次调用时探一次,之后连「没有」这个结论一起记住
    if _TYPESCRIPT is None:
        # 磁盘内容在一次扫描里不会变,重复 walk 只是白花时间
        _TYPESCRIPT = _search(targets)
    return _TYPESCRIPT


def _search(targets):
    """按「越靠近被扫的项目越优先」的顺序找 typescript 包。

    项目自带的版本最贴近它自己的语法,优先用它的;全局那份只是兜底。

    Args:
        targets: 本次要解析的文件。

    Returns:
        第一个可用的包目录;都没有时返回空串。
    """
    seen = set()                                    # 已经问过的位置,免得重复 stat
    # 逐个候选位置查:同一个位置会被多个文件、多条路径重复产出
    for candidate in _candidates(targets):
        key = str(candidate)                        # 去重按字符串比,Path 的相等判定更绕
        # 同一个目录被多个文件、多条路径各产出一次,只问第一遍
        if key in seen:
            continue
        seen.add(key)
        # 认得出编译器本体就定下来:后面的候选位不用再问了
        if is_typescript_package(candidate):
            return key
    return ''


def _candidates(targets):
    """typescript 包的候选位置,按优先级产出。

    顺序就是「谁更可能装着这门语言的正确版本」:环境变量是人指定的,
    项目自带的排第二,node 自己的搜索路径与全局安装排在最后。

    Args:
        targets: 本次要解析的文件。

    Yields:
        候选包目录,越靠前越优先。
    """
    override = os.environ.get(TS_ENV, '')           # 人工指定的位置,优先于一切自动探测
    # 环境变量是人工开关,优先级最高
    if override:
        yield Path(override)
    # 项目自带的 node_modules:被扫的项目自己装了 typescript 就用它那份
    for target in targets:
        yield from _walk_up(Path(target).parent)
    # 再退到 node 自己认的模块搜索路径
    for entry in os.environ.get('NODE_PATH', '').split(os.pathsep):
        # 空串是 NODE_PATH 里常见的分隔产物,不是一条路径
        if entry:
            yield Path(entry) / 'typescript'
    yield Path.cwd() / 'node_modules' / 'typescript'
    root = _npm_global_root()                       # 问不到全局目录时是空串
    # npm 自己也问不到全局目录时就没这一步
    if root:
        yield Path(root) / 'typescript'


def _walk_up(start):
    """从 start 逐级向上产出 `node_modules/typescript` 的位置。

    只探到 `_WALK_LIMIT` 层就停:被扫文件可能在很深的目录里,而 node 的解析规则
    也不会无限往上找。

    Args:
        start: 起始目录(通常是某个被扫文件的父目录)。

    Yields:
        每一级目录下的 `node_modules/typescript`。
    """
    current = start
    # 到盘根就停:再往上没有意义,而且 parent 会等于自己
    for _ in range(_WALK_LIMIT):
        yield current / 'node_modules' / 'typescript'
        parent = current.parent
        # 盘根的父亲是自己 —— 不挡住就是死循环
        if parent == current:
            return
        current = parent


def _npm_global_root():
    """`npm root -g` 给出的全局模块目录。

    npx 在没装 typescript 时不会帮忙,而全局装一份是这台机器上挺常见的形态,
    所以这条路值得一试;失败也只是多一次子进程。

    Returns:
        全局 node_modules 目录;没有 npm 或命令失败时返回空串。
    """
    npm = shutil.which('npm')                       # 没有 npm 就没什么可问的
    # 没有 npm 就没什么可问的
    if not npm:
        return ''
    try:
        # 子进程失败要么是没装要么是超时,两种都只是「问不到」,不该让整条闸崩
        done = subprocess.run([npm, 'root', '-g'], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ''
    # 命令自己报了错就当作没问到,不去猜它半截输出是什么意思
    if done.returncode:
        return ''
    return done.stdout.strip()


def is_typescript_package(path):
    """这个位置是不是一个能 require 的 typescript 包。

    `lib/typescript.js` 是编译器本体:认它等于认「这个目录能 require 出 createSourceFile」,
    比认 `package.json` 更贴近真正要用的东西。

    Args:
        path: 候选位置。

    Returns:
        是包目录(含 `lib/typescript.js`)或编译器本体文件时为 True。
    """
    # 环境变量可以指到编译器本体文件,那种写法也认
    if path.is_file():
        return True
    return (path / 'lib' / 'typescript.js').is_file()
