"""目录说明约定 ``DIRS.md``:仓库根一份,每个放文件的目录一行 ``- `路径` — 一句话说明``。

新建文件夹就是新建模块(用户 2026-11-13 定):先想清它管什么,在 ``DIRS.md`` 补一行,
和新目录同一次提交;删目录时删那一行。只有平铺的文件树,读者只能靠猜目录名。
仓库根还没有 ``DIRS.md`` 的不查 —— 约定是在建第一个目录时一并建它,不追溯旧仓库。
"""

import os
from pathlib import Path
import re
import subprocess

# py-structure: allow-sibling-imports —— 同目录判据模块是这个 skill 的结构
from .model import Finding
from .rules import RULES

#: 约定的文件名
NAME = 'DIRS.md'
#: 合法的说明行:路径用反引号包住,长破折号后面跟非空说明
_LINE = re.compile(r'^- `([^`]+)` — \S')


def _root_of(path):
    """往上找最近一个放着 ``DIRS.md`` 的目录;找不到返回 None。"""
    for folder in [path, *path.parents]:
        if (folder / NAME).is_file():
            return folder
    return None


def _entries(root):
    """读 ``DIRS.md``:返回 {路径: 行号} 与格式不对的行号列表。"""
    entries, malformed = {}, []
    lines = (root / NAME).read_text(encoding='utf-8').splitlines()
    # 只看以 ``- ` `` 开头的条目行,标题和说明段落不管
    for number, line in enumerate(lines, 1):
        if not line.startswith('- `'):
            continue
        match = _LINE.match(line)
        if match:
            entries[match.group(1)] = number
        else:
            malformed.append(number)
    return entries, malformed


def _visible(root):
    """git 仓库里不被忽略的文件(相对路径集合);不是 git 仓库返回 None,表示全都算。"""
    proc = subprocess.run(['git', '-C', str(root), 'ls-files', '-co', '--exclude-standard'],
                          capture_output=True, text=True)
    return set(proc.stdout.splitlines()) if proc.returncode == 0 else None


def dirs_md(paths, skip_dirs):
    """查 ``DIRS.md``:放文件的目录缺说明、说明指向的目录已不存在、条目行格式不对。

    Args:
        paths: 命令行给的原始路径(文件或目录);目录会递归,文件只看它自己。
        skip_dirs: 递归时不进的目录名。

    Returns:
        违规列表,字段与单文件规则一致。缺说明按目录报一条,另两种报在 ``DIRS.md`` 的对应行。
    """
    files = []
    # 把命令行给的文件与目录摊平成文件清单:目录要递归,文件只取它自己
    for raw in paths:
        path = Path(raw).resolve()
        if path.is_dir():
            for here, dirs, names in os.walk(path):
                dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
                files.extend(Path(here) / name for name in names)
        elif path.is_file():
            files.append(path)

    roots, missing = {}, set()
    # 逐个文件定位所属仓库根,再逐级核对它所在的目录
    for item in files:
        root = _root_of(item.parent)
        # 仓库还没采用约定
        if root is None:
            continue
        if root not in roots:
            roots[root] = (_entries(root), _visible(root))
        (entries, _), visible = roots[root]
        rel = item.relative_to(root)
        # git 忽略的文件(日志、数据、产物)不是仓库内容
        if visible is not None and rel.as_posix() not in visible:
            continue
        missing.update((root, parent.as_posix()) for parent in rel.parents
                       if str(parent) != '.' and parent.as_posix() not in entries)

    found = [Finding(path=str(root / rel), line=1, rule='dirs-md',
                     detail=f'{NAME} 里没有 `{rel}` 的说明,补一行 ``- `{rel}` — 一句话说明``',
                     why=RULES['dirs-md'])
             for root, rel in sorted(missing)]
    # 每个仓库根再查一遍条目本身:目录还在不在、行格式对不对
    for root, ((entries, malformed), _) in sorted(roots.items()):
        found += [Finding(path=str(root / NAME), line=number, rule='dirs-md',
                          detail=f'`{rel}` 已不存在,删掉这一行', why=RULES['dirs-md'])
                  for rel, number in sorted(entries.items(), key=lambda kv: kv[1])
                  if not (root / rel).is_dir()]
        found += [Finding(path=str(root / NAME), line=number, rule='dirs-md',
                          detail='条目行格式应为 ``- `路径` — 一句话说明``', why=RULES['dirs-md'])
                  for number in malformed]
    return found
