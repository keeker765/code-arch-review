<#
.SYNOPSIS
把一批 PowerShell 文件解析成 AST 事实,以 Base64 包裹的 JSON 写到 stdout。

.DESCRIPTION
由 `lang/powershell/__init__.py` 起进程调用,**只读源码、不执行它**
(`ParseInput` 只做词法与语法分析),行号一律取 AST 的 `Extent`。

输出走 Base64 而不是裸 JSON:Windows 控制台的代码页会把非 ASCII 字符
(注释里的中文)换成问号,而这份结果要原样回到 Python 侧。Base64 是 ASCII,
经过任何代码页都不变。

🔴 **为什么绝不数大括号** —— 四条硬坑,踩过才写在这里:

1. `{}` 在 PowerShell 里同时是 scriptblock 定界符、哈希表字面量、`Where-Object {}`
   这类参数块 —— 一个 `@{ a = 1 }` 就让括号深度算错;
2. 字符串与 here-string(`@" ... "@`)里 `{}` 和 `#` 什么都能出现;
3. `$( ... )` 子表达式、`@( ... )` 数组、`${ var }` 变量定界都会改变深度;
4. 行尾反引号是续行:`if ($a -and \`` 换行后的 `$b)` 是**同一个条件**,
   按物理行数会数成两个 —— 方向正好相反。

本文件只放常量、入口与主循环;节点判定在 `nodes.ps1`,逐个函数量事实在
`owners.ps1`,逐个文件抽事实在 `file_facts.ps1`。拆开是 `long-module` 逼出来的:
原先把这些全放在一个文件里已经越过 500 行,而补注释只会让它更长。
#>

# 用 $args 而不是 param([string[]]$Path):-File 调用里数组形参只吃得下第一个位置参数,
# 第二个参数会以「找不到接受该参数的位置参数」直接失败。
param()

$ErrorActionPreference = 'Stop'

# 算控制流嵌套层数时算数的语句类型 —— 函数与类定义**不算**,否则嵌套函数会被重复计入
$ControlKinds = @(
    'IfStatementAst', 'ForEachStatementAst', 'ForStatementAst', 'WhileStatementAst',
    'DoWhileStatementAst', 'DoUntilStatementAst', 'TryStatementAst'
)

# 五种循环到报告里标签的映射;键是 AST 类型名
$LoopLabels = @{
    'ForEachStatementAst' = 'foreach'
    'ForStatementAst'     = 'for'
    'WhileStatementAst'   = 'while'
    'DoWhileStatementAst' = 'do-while'
    'DoUntilStatementAst' = 'do-until'
}

# 赋值右侧算「算出来的」的节点类型 —— 与 Python 侧的 BinOp/Call/IfExp/Compare 对应
$ComputedKinds = @(
    'BinaryExpressionAst', 'InvokeMemberExpressionAst', 'InvokeExpressionAst',
    'CommandAst', 'SubExpressionAst'
)

# 谓词里逐节点跑的类型判断用 HashSet:数组 -contains 是线性表,热路径上会被放大
$ControlNames = [System.Collections.Generic.HashSet[string]]::new([string[]]$ControlKinds)
# 循环节点 AST 类型集合同样放入 HashSet,加速高频循环类型判定
$LoopNames = [System.Collections.Generic.HashSet[string]]::new([string[]]$LoopLabels.Keys)

# 块注释的 token 类型,拿出来避免在热循环里反复取枚举
$CommentKind = [System.Management.Automation.Language.TokenKind]::Comment

# 分段计时:由 CODE_ARCH_PS_TIMING 打开,只写 stderr,不污染 stdout 上的 JSON。
# 一个上万行的模块要跑好几秒,只报总耗时等于没报 —— 分不出「解析慢」「抽取慢」
# 还是「序列化慢」,而这三件事的优化方向完全不同。
$Script:Timing = [bool]$env:CODE_ARCH_PS_TIMING

function Write-Segment([string]$Label, $Watch) {
    <#
    .SYNOPSIS
    把上一段耗时打到 stderr 并重启秒表。

    .DESCRIPTION
    计时是运行日志不是报告:走 stderr,`CODE_ARCH_PS_TIMING` 没开时整个函数直接返回,
    一个字符都不输出。

    .PARAMETER Label
    段名,固定宽度对齐便于纵向比较。

    .PARAMETER Watch
    正在计时的秒表,本函数负责 Restart。
    #>
    # 没开计时开关就什么都不做,连格式化都省掉
    if (-not $Script:Timing) { return }
    # -f 的右操作数要显式括起来:逗号比 -f 松,不括会被拆成两个语句的参数
    [Console]::Error.WriteLine('    {0,-10} {1,8:N0} ms' -f ($Label, $Watch.ElapsedMilliseconds))
    $Watch.Restart()
}

# token 层先于其余各层:注释行号是所有规则共用的判据
. "$PSScriptRoot/tokens.ps1"
. "$PSScriptRoot/nodes.ps1"
. "$PSScriptRoot/owners.ps1"
. "$PSScriptRoot/file_facts.ps1"

$Targets = @($args)
# 一个目标都没有时直接失败:空集冒充「零违规」是最坏的失败方式
if ($Targets.Count -eq 0) { throw 'no target paths given' }

$Results = @()
# 整批共用一次进程:PowerShell 起进程约 0.3 秒,逐文件起一次会把扫描拖成分钟级
foreach ($Target in $Targets) {
    try {
        # 目标文件经 AST 解析与结构事实抽取产出标准化 Entry 字典
        $Entry = Get-FileFacts $Target
        $Entry.path = $Target
        $Results += $Entry
    }
    catch {
        # 单个文件读不动不能拖垮整批,但错误随结果一起回去,调用方按文件数差额察觉
        $Results += [ordered]@{ path = $Target; parse_errors = @("$($_.Exception.Message)") }
    }
}

# 启动序列化与输出耗时分段秒表
$OutWatch = [System.Diagnostics.Stopwatch]::StartNew()
$Json = @{ results = @($Results) } | ConvertTo-Json -Depth 8 -Compress
Write-Segment 'json' $OutWatch
# Base64 是纯 ASCII,不会被 Windows 控制台代码页改写,中文注释才能原样回到 Python 侧
[Console]::Out.Write([Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($Json)))
Write-Segment 'emit' $OutWatch
