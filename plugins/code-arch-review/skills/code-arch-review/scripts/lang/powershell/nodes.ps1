<#
.SYNOPSIS
AST 节点的判定与剥离工具 —— 后端所有「这颗节点是什么、它里面包着什么」的问题都问这里。

.DESCRIPTION
PowerShell 的 AST 没有统一的 kind 枚举,类型信息只存在于 .NET 的
`$Node.GetType().Name` 字符串里。本文件把那些字符串判断收在一处,好处是
**口径只有一份**:`Unwrap-Pipeline` 剥到哪一层算「剥干净」、`Get-ConditionOperands`
把哪些包装算透明,分散在几个文件里迟早会出现两处答案。

🔴 所有函数都按**类型名字符串**判定而不按 .NET 类型 `-is` 判定:同样的 AST 在
PowerShell 5.1 与 7.x 上来自不同的程序集,`-is` 会因程序集版本而失败,
类型名不会。
#>

function Test-Kind($Node, [string]$Name) {
    <#
    .SYNOPSIS
    这颗节点的类型名是不是给定的那一个。

    .DESCRIPTION
    每次调用都先判 `$null`:AST 里到处是「可能没有这个子节点」的位置
    (`$node.Parent` 到根就是 $null),让调用方逐个判空会把判空散到几十处。

    .PARAMETER Node
    要判的节点;传 $null 时返回 $false 而不是抛错。

    .PARAMETER Name
    .NET 类型名,如 `IfStatementAst`。

    .OUTPUTS
    布尔值。
    #>
    # 空节点不算任何一种类型 —— 调用方据此免写判空
    if ($null -eq $Node) { return $false }
    # 比的是 .NET 类型名字符串:同样的 AST 在 5.1 与 7.x 上来自不同程序集,-is 会因版本失败
    return ($Node.GetType().Name -eq $Name)
}

function Test-AnyKind($Node, $Names) {
    <#
    .SYNOPSIS
    这颗节点的类型名在给定的集合里吗。

    .DESCRIPTION
    与 `Test-Kind` 同一条判据,只是接受多个类型名 —— 调用点要判三个以上类型时,
    写成 `-or` 连缀会把一行撑到看不清,而且每个分支都要重写一遍判空。

    .PARAMETER Node
    要判的节点;传 $null 时返回 $false。

    .PARAMETER Names
    类型名数组。

    .OUTPUTS
    布尔值。
    #>
    # 与 Test-Kind 同一条口径:空节点不算命中
    if ($null -eq $Node) { return $false }
    # 线性扫集合:调用点给的类型名通常只有两三个,建索引反而更慢
    return ($Names -contains $Node.GetType().Name)
}

function Get-LineText([int]$Row) {
    <#
    .SYNOPSIS
    取源码里第 $Row 行的原文(1 基)。

    .DESCRIPTION
    行文本缓存在 `$Script:LineTexts` 里,由 `Get-TokenFacts` 在进入 token 循环前
    一次性填好 —— 逐 token 去读文件会把同一次扫描变成几百次磁盘访问。

    越界一律返回空串而不是抛错:注释块跨到文件末尾之外是合法输入
    (块注释收尾那一行可能恰好是最后一行),抛错会让整个文件被记成解析失败。

    .PARAMETER Row
    1 基行号。

    .OUTPUTS
    该行原文;越界时是空串。
    #>
    # 行号 0 或负数来自 AST 的边界情形,不是真实行
    if ($Row -lt 1) { return '' }
    # 超过总行数说明这一行不存在,按空行处理
    if ($Row -gt $Script:LineTexts.Count) { return '' }
    # 缓存是 0 基数组、行号是 1 基,取第 $Row 行要减一
    return $Script:LineTexts[$Row - 1]
}

function Get-LeftVariable($Left) {
    <#
    .SYNOPSIS
    赋值左侧如果最终落在裸变量上,返回那个变量节点;否则返回 $null。

    .DESCRIPTION
    赋值左侧在 AST 里常常不是 `VariableExpressionAst` 本身,而是被两层包装裹住:

    * `[int]$x = 1`  → `ConvertExpressionAst`(类型转换)
    * `[ValidateRange(0,9)][int]$x = 1` → `AttributedExpressionAst` 套上面那层

    本后端的 `uncommented-field` / `uncommented-assign` 都要求「左侧是裸变量」,
    不剥这两层会把带类型标注的声明整类漏掉。

    🔴 只剥这两层,不再往下走:属性赋值(`$obj.A = 1`)与下标赋值(`$h['k'] = 1`)
    改的是别人的东西,不是本模块定义了一个变量,它们必须返回 $null。

    .PARAMETER Left
    赋值语句的左侧节点。

    .OUTPUTS
    `VariableExpressionAst` 节点;左侧不是裸变量时是 $null。
    #>
    $node = $Left
    # 逐层剥类型转换与属性包装,直到撞上不是包装的东西
    while ($null -ne $node -and (Test-AnyKind $node @('ConvertExpressionAst', 'AttributedExpressionAst'))) {
        $node = $node.Child
    }
    # 剥完之后只有裸变量才算「给一个名字赋值」
    if (Test-Kind $node 'VariableExpressionAst') { return $node }
    return $null
}

function Test-TypeConstrained($Left) {
    <#
    .SYNOPSIS
    这个赋值的左侧带类型约束吗(`[int]$x` 或 `[pscustomobject]$x`)。

    .DESCRIPTION
    判「这是不是字段声明」要用到:PowerShell 没有类字段以外的声明语法,
    顶层 `[type]$x = ...` 是脚本作者表达「这不是临时变量」的唯一手段。

    两种形态都算:
    * `ConvertExpressionAst` —— `[int]$x = 1` 直接转换;
    * `AttributedExpressionAst` 里挂着 `TypeConstraintAst` —— `[ValidateRange()][int]$x`。

    只认类型约束,不认其它特性:`[Parameter()]$x` 是参数块里的写法,不表达类型。

    .PARAMETER Left
    赋值语句的左侧节点。

    .OUTPUTS
    布尔值。
    #>
    $node = $Left
    # 只有属性包装才需要继续往里找类型约束
    while ($null -ne $node -and (Test-Kind $node 'AttributedExpressionAst')) {
        # 属性挂在 .Attribute 上,是 TypeConstraintAst 就说明带了类型
        if (Test-Kind $node.Attribute 'TypeConstraintAst') { return $true }
        $node = $node.Child
    }
    # 剥掉属性包装后剩下的就是裸转换表达式,它本身就是类型约束
    return (Test-Kind $node 'ConvertExpressionAst')
}

function Test-InsideCallable($Node) {
    <#
    .SYNOPSIS
    这颗节点是不是被包在函数体里(而不是在模块顶层直接执行)。

    .DESCRIPTION
    判「顶层 `[type]$x = ...` 算字段」要用到:同样一句带类型标注的赋值,
    写在函数体里是局部变量,写在顶层才是模块级状态。函数体与类方法体都算「里层」。

    .PARAMETER Node
    任意节点。

    .OUTPUTS
    布尔值。
    #>
    $parent = $Node.Parent
    # 逐层往根走,撞到任何一个「可调用体」的边界就判定它在里层
    while ($null -ne $parent) {
        $kind = $parent.GetType().Name
        # 函数定义与类方法体是两种不同的「里层」节点
        if (
            # 脚本级函数
            $kind -eq 'FunctionDefinitionAst' -or
            # 类方法体
            $kind -eq 'FunctionMemberAst'
        ) { return $true }
        $parent = $parent.Parent
    }
    return $false
}

function Unwrap-Pipeline($Node) {
    <#
    .SYNOPSIS
    剥掉管道与括号包装,返回它们包着的那颗真正的表达式节点。

    .DESCRIPTION
    判「赋值右侧是不是算出来的」「return 的是不是算式」都要求先看到真正的表达式,
    否则 `$x = (Get-Date).Year` 会被当成「右侧是括号」而漏判。

    剥的四层都是**语法上的透明包装**,剥掉不改变语义:

    * `PipelineAst` 单元素 —— 包装而已;多元素(真的管道)停下来,那本身就是一个算式;
    * `CommandExpressionAst` —— `$x = 1 + 1` 里外侧那层;
    * `ParenExpressionAst` —— 括号;
    * `PipelineChainAst`(`&&` / `||`)停下来算一个判据,不再往里剥。

    .PARAMETER Node
    起始节点。

    .OUTPUTS
    剥到底的表达式节点;输入是 $null 时返回 $null。
    #>
    $current = $Node
    # 一层一层剥,直到撞上不可剥的节点或走空
    while ($null -ne $current) {
        $kind = $current.GetType().Name
        # 单元素管道是纯包装;多元素管道是真正的管道运算,它自己就是算式
        if ($kind -eq 'PipelineAst') {
            # 大于一个元素说明确实在做管道,不能剥
            if ($current.PipelineElements.Count -ne 1) { return $current }
            $current = $current.PipelineElements[0]
            continue
        }
        # 管道链(`a && b`)整体算一个算式,里面的每个命令不是独立判据
        if ($kind -eq 'PipelineChainAst') { return $current }
        # 命令表达式只是把表达式包起来,继续剥
        if ($kind -eq 'CommandExpressionAst') { $current = $current.Expression; continue }
        # 括号不改变语义,继续剥
        if ($kind -eq 'ParenExpressionAst') { $current = $current.Pipeline; continue }
        # 落到真实表达式上,剥干净了
        return $current
    }
    return $null
}

function Get-ConditionOperands($Node) {
    <#
    .SYNOPSIS
    把一个条件摊平成一个个独立判据。

    .DESCRIPTION
    `if ($a -and $b)` 是**两个**判据不是一个,与 Python 侧 `operands()` 同一条口径。
    `uncommented-condition` 要求每个子判据都能被指出来,摊平后才能知道
    「这个 if 上有几处分叉需要说明」,也才能判出「多个条件挤一行」。

    与 Python 侧的差异只有一处:`-not $x` / `!$x` **停下来算一个判据**,
    不往里剥 —— 取反是对同一个判据的修饰,不是新的分叉,与 Python 侧 `not` 一致。

    .PARAMETER Node
    条件的表达式节点。

    .OUTPUTS
    判据节点数组;输入是 $null 时是空数组。
    #>
    # 空条件(理论上不该出现)按零个判据处理,不让调用方判空
    if ($null -eq $Node) { return @() }
    $kind = $Node.GetType().Name
    # 二元表达式才可能藏着 and / or 组合
    if ($kind -eq 'BinaryExpressionAst') {
        # 运算符名只有 And / Or 两种是布尔组合,其余(加减、比较)都是最末端判据
        $operator = $Node.Operator.ToString()
        # 布尔组合递归摊平;`-and` 与 `-or` 一样处理,闸只关心有几个分叉
        if (
            # 逻辑与
            $operator -eq 'And' -or
            # 逻辑或
            $operator -eq 'Or'
        ) {
            # 两侧各自摊平后拼起来:顺序不影响计数,但保持原序便于对着源码看
            return @(Get-ConditionOperands $Node.Left) + @(Get-ConditionOperands $Node.Right)
        }
        # 比较运算本身就是最末端的判据
        return @($Node)
    }
    # 括号是透明的,拆掉后继续判里面的东西
    if ($kind -eq 'ParenExpressionAst') { return @(Get-ConditionOperands $Node.Pipeline) }
    # 命令表达式也是包装,剥掉后继续
    if ($kind -eq 'CommandExpressionAst') { return @(Get-ConditionOperands $Node.Expression) }
    # 单元素管道照样剥,多元素管道自己就是一个判据
    if ($kind -eq 'PipelineAst') {
        # 只有一个元素说明只是包装,继续往里剥
        if ($Node.PipelineElements.Count -eq 1) { return @(Get-ConditionOperands $Node.PipelineElements[0]) }
        # 多个元素是真的管道运算,整体算一个判据
        return @($Node)
    }
    # 落到叶子上,它自己就是一个判据
    return @($Node)
}
