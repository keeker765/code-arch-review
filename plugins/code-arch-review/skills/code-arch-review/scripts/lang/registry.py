"""语言注册表:扩展名 → 后端,以及**各语言的阈值与档位**。

阈值按语言给,但**规则本身只有一套** —— 这是刻意的:同一条规则在不同语言里可判性不同
(见 `SKILL.md` 的档位表与 `references/languages.md`),但一旦可判,判据就该一样。
所以这里只有「这门语言用哪个数」和「这门语言哪几条不查」,没有第二份规则实现。

`disabled_rules` 是把 `SKILL.md` 档位表里写 `—` 的那些格子**变成可执行的配置**。
写在文档里而没人执行,下次改动就会有人把规则加回去。
"""

import importlib

from core.rules import Thresholds

# Bash 只查纯文件级三条。注释四条**已实现**,默认不拦 ——
# 理由见 references/languages.md:bash 的 `if [ -f "$f" ]` 这类存在性检查密度极高,
# 逐条要求注释会让人直接把闸关掉。要开只需从这里删掉对应规则名,不必改代码。
_SHELL_DISABLED = frozenset({
    'no-docstring', 'thin-docstring', 'docstring-sections', 'thin-module-doc',
    'long-function', 'many-kwargs', 'deep-nesting', 'dict-as-type',
    'duplicate-toplevel', 'silent-except',
    'uncommented-condition', 'uncommented-loop',
    'uncommented-flat', 'uncommented-field', 'uncommented-assign',
})

# PowerShell 关掉 `dict-as-type`:这条规则判的是「同一个对象上按多个字符串键取值」,
# 而 PowerShell 里 `$obj.A` / `$obj.B` 既可能是哈希表也可能是**强类型对象的属性访问** ——
# 没有类型信息就分不开。实测 20k 行里命中 21 次,量级说明它是噪声不是信号。
_PS_DISABLED = frozenset({'dict-as-type'})

# CSS 不查逐块注释:一个 200 个规则块的文件要求 200 条注释,没有人会写,
# 结果是闸被关掉。改成查「文件级 + 块形状 + 同块头重定义 + 胖块」这些低噪声的。
# `thin-module-doc` 也在名单里:CSS 没有「模块文档」这个概念,后端按约定把 `module_doc`
# 留成 None,于是任何超过 80 行的 .css 都会报一条**永远修不掉**的违规 ——
# 那不是缺陷,是规则套错了对象。CSS 文件的用途由文件名与首行注释交代,凑 3 行只会催生废话。
_CSS_DISABLED = frozenset({
    'no-docstring', 'thin-docstring', 'docstring-sections', 'thin-module-doc',
    'many-kwargs', 'dict-as-type', 'silent-except', 'long-function',
    'uncommented-condition', 'uncommented-loop',
    'uncommented-flat', 'uncommented-field', 'uncommented-assign',
})


class Language:
    """一门语言的配置:扩展名、后端模块名、阈值、不查的规则、保留文件名。

    这里存的是**配置**不是**实现**。同一个规则名在四种语言上的判据完全一样(在
    `core/rules.py`),各不相同的是三个数(阈值)、一份禁用名单、一份保留文件名。
    新增一门语言要写的是「怎么把语法翻译成事实」(一个后端模块),不是「怎么判规则」。

    Attributes:
        name: 语言名,报告里显示。
        exts: 认得的扩展名。
        module_name: 后端模块的完整名字,延迟导入 —— 某个后端缺依赖不该让整条闸起不来。
        thresholds: 这门语言的阈值。
        disabled_rules: 这门语言**明确不查**的规则名(档位表里写 `—` 的格子)。
        reserved: 语言规定的保留文件名,`flat-package` 与 `duplicate-basename` 都豁免它们。
    """

    def __init__(self, name, exts, module_name, thresholds, disabled_rules, reserved=()):
        self.name = name
        self.exts = exts
        self.module_name = module_name
        self.thresholds = thresholds
        self.disabled_rules = disabled_rules
        # 保留文件名要先归一成不可变集合:它会被 `core.package` 反复查询
        self.reserved = frozenset(reserved)
        # 后端模块缓存与失败原因:两者都为空表示还没试过导入
        self._backend = None
        self._error = None

    @property
    def backend(self):
        """后端模块;第一次访问时才导入,结果(成功或失败)都缓存下来。

        延迟导入不是风格问题:`javascript` 后端需要 `node`、`powershell` 后端需要
        `pwsh`,而一台机器上完全可能两者都缺。在模块顶层 import 会让「缺一个后端」
        升级成「闸根本起不来」—— 那是把可降级的依赖做成了硬依赖。

        Returns:
            后端模块;导入失败或接口不全时返回 None(原因存在 `load_error` 里)。
        """
        # 已经导入过、或已经失败过都直接返回缓存 —— 失败结果也要缓存,否则每次访问都重试一遍
        if (
            # 还没尝试过导入
            self._backend is None
            # 也还没有失败记录
            and self._error is None
        ):
            try:
                # 真正导入后端模块:缺 node / 缺 pwsh 会在这里以 ImportError 暴露
                module = importlib.import_module(self.module_name)
            except ImportError as exc:
                self._error = f'后端 {self.module_name} 无法导入:{exc}'
                return None
            # 接口也要对:后端写了一半(只有 parse 没有 parse_many)时整条闸不该跟着崩,
            # 应该像缺 node / 缺 pwsh 一样被跳过并说明原因
            if not hasattr(module, 'parse_many'):
                self._error = f'后端 {self.module_name} 没有实现 parse_many'
                return None
            self._backend = module
        return self._backend

    @property
    def load_error(self):
        """后端导入失败的原因;成功时为 None。"""
        return self._error


# 各语言的阈值。表里没有的项取 Thresholds 的默认值 —— 默认值就是 Python 那一套。
LANGUAGES = (
    # Python:基准。单文件 500 / 函数体 60 / 参数 5 / 嵌套 4
    Language('python', ('.py',), 'lang.python', Thresholds(trivial_body=10),
             frozenset(), reserved=('__init__.py', '__main__.py')),
    # PowerShell:惯例是动词-名词长函数名 + 显式 param() 块,参数多、函数长是常态;
    # 按 Python 的 60/5 会大面积误报,而只报噪声的闸会被关掉。
    Language('powershell', ('.ps1', '.psm1', '.psd1'), 'lang.powershell',
             Thresholds(max_body=80, max_kwargs=8), _PS_DISABLED),
    # JS/TS:回调、闭包、promise 链让函数极易膨胀,收到 50;模块上限保持 500 —— 组件文件天然偏长
    Language('javascript', ('.js', '.mjs', '.cjs', '.jsx', '.ts', '.mts', '.cts', '.tsx'),
             'lang.javascript', Thresholds(max_body=50), frozenset(),
             reserved=('index.js', 'index.jsx', 'index.mjs', 'index.cjs',
                       'index.ts', 'index.tsx', 'index.mts', 'index.cts')),
    # Bash:200 行以上就该换语言了,500 这条线对它失去意义;函数体不查(边界判不准,见 languages.md)
    Language('shell', ('.sh', '.bash', '.zsh', '.ksh'), 'lang.shell_backend',
             Thresholds(max_module_lines=300), _SHELL_DISABLED),
    # CSS:700 行的 CSS 很正常,套 500 会天天报警;选择器嵌套超过 3 层已经很难读
    Language('css', ('.css',), 'lang.css_backend',
             Thresholds(max_module_lines=800, max_depth=3, max_declarations=30),
             _CSS_DISABLED),
)


def all_languages():
    """全部已注册的语言,含后端暂时起不来的那些。

    与 `available()` 的区别就是这一点:「有哪些语言」是固定配置,「现在能用哪些」看机器。
    调用方要筛可用后端时用 `available()`,要展示完整档位表时用这里。

    Returns:
        `Language` 元组。
    """
    return LANGUAGES


def detect(path):
    """按扩展名判断文件属于哪门语言;完全没有扩展名时按 shebang 兜底。

    🔴 兜底不是锦上添花:无扩展名的可执行脚本(`bin/deploy`、`/etc/init.d/foo`)是 Unix 的
    常规形态,只按扩展名分发会把它们**整片静默漏掉** —— 而漏掉在报告里看不出来,
    读者会以为那些文件查过了。

    Args:
        path: 文件路径。

    Returns:
        对应的 `Language`;认不出来的返回 None。
    """
    # 一律小写再比:Windows 上 `Foo.PS1` 与 `foo.ps1` 是同一个文件
    suffix = path.suffix.lower()
    # 逐门语言比扩展名:表格只有 5 行,线性扫比建索引更省事也更好读
    for language in LANGUAGES:
        # 一门语言可以有多个扩展名,所以是遍历而不是字典查表
        if suffix in language.exts:
            return language
    # 只在**完全没有扩展名**时才去读文件头:整棵树逐个读首行会把扫描拖慢,
    # 而 `deploy.sh` 这种已有扩展名的文件本来就走上面的分支了
    if suffix:
        return None
    return _by_shebang(path)


def _by_shebang(path):
    """读文件头判断是不是 shell 脚本,给无扩展名的文件用。

    判据在 shell 后端里(`looks_like_shell`),因为「什么算 shell 脚本」是那门语言的知识,
    不是注册表的知识 —— 注册表只负责在扩展名这条路走不通时去问它。

    Args:
        path: 文件路径。

    Returns:
        shell 的 `Language`;判断不出来或后端不可用时返回 None。
    """
    # 从注册表里取 shell 那一项,而不是 import 后端模块:后端起不来时这里要安静地认不出来
    shell = next((item for item in LANGUAGES if item.name == 'shell'), None)
    # 没有 shell 这项配置,或它的后端起不来(缺依赖 / 还没写完),都不该让调用方崩
    if (
        # 注册表里根本没有 shell 这一项
        shell is None
        # 或者它的后端现在不可用
        or shell.backend is None
    ):
        return None
    # 后端没实现这个探测(或还没写完)时安静地认不出来,不要让整条闸跟着崩
    probe = getattr(shell.backend, 'looks_like_shell', None)
    # 老版本后端没有这个函数,当作「认不出来」而不是报错
    if probe is None:
        return None
    try:
        # 探测本身要读文件,可能碰上读不动的路径 —— 那种情况按认不出来处理
        return shell if probe(path) else None
    except OSError:
        return None


def available():
    """后端能正常导入的配置。

    失败的那几门**不从这里剔除后就消失** —— 名字与原因一并返回,由调用方打进报告。
    「跳过了什么」和「查过什么」一样重要:一份没提自己少扫了两种语言的报告,
    读起来和一份真的全扫过的报告一模一样。

    Returns:
        `(可用的 Language 列表, [(语言名, 失败原因)])`。
    """
    ready = []
    failed = []
    # 逐门语言触发一次延迟导入:成功进 ready,失败进 failed 并带上原因
    for language in LANGUAGES:
        # 访问 backend 属性会触发导入,失败原因落在 load_error 上
        module = language.backend
        # 起不来的记下原因:报告里要显式打出「跳过了什么、为什么」,不能静默少扫几种语言
        if module is None:
            failed.append((language.name, language.load_error))
        else:
            ready.append(language)
    return ready, failed
