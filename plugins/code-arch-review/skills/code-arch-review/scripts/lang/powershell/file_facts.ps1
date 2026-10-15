<#
.SYNOPSIS
逐个文件抽事实 —— 从 token 与 AST 里数出报告要用的每一项。

.DESCRIPTION
`Get-FileFacts` 是编排:读源码、解析、再依次叫四组抽取器。四组各自独立,
因为它们问的是四个不同的问题,失败方式也各不相同:

* `Get-TokenFacts`  —— 注释分布与模块文档(看 token 流)
* `Get-OwnerFacts`  —— 函数与类的形状(看 AST 的定义节点)
* `Get-ControlFacts` —— 条件/循环/抛异常/算式 return(看 AST 的语句节点)
* `Get-BindingFacts` —— 字段/赋值/行尾静默异常/顶层绑定(看 AST 的赋值与非定义语句)

拆开不只是为了行数:一次改动只会落在其中一组上,而混在一起时
改「字段怎么算」要在一百多行里翻找。

🔴 一个文件读不动或语法坏掉时,错误**随结果一起回去**给调用方,不在这里静默吞掉 ——
静默少扫一个文件,报告里的「零违规」就成了谎话。
#>

function Get-OwnerFacts($Ast, $ClassNodes) {
    <#
    .SYNOPSIS
    产出所有函数与类的形状事实。

    .DESCRIPTION
    类与函数分两条路走,因为能问的问题不同:类没有参数表、没有嵌套层数、没有字符串键,
    这四项在类上一律留空;**类方法**则按函数处理。

    🔴 类方法在 AST 里是**嵌套的两个节点**:`FunctionMemberAst`(类成员)里面还套着一个
    同名的 `FunctionDefinitionAst`。两个都收会把同一个方法数两次,于是
    `long-function` 的计数翻倍。所以函数那条路显式跳过 `Parent` 是 `FunctionMemberAst`
    的节点,方法统一走类成员那条路。

    .PARAMETER Ast
    整个文件的 AST。

    .PARAMETER ClassNodes
    已经筛成「类」的 `TypeDefinitionAst`(枚举与 DSC 配置不算)。

    .OUTPUTS
    pscustomobject 数组,字段与 `core.model.FunctionFact` 对齐。
    #>
    $FunctionFacts = @()
    # 类先收:类没有体长以外的形状,四项形状值一律留空
    foreach ($class in $ClassNodes) {
        $startLine = $class.Extent.StartLineNumber
        $endLine = $class.Extent.EndLineNumber
        $bodyLines = 0
        # 类的体长按成员算:首尾成员之间才是它的体
        if ($class.Members.Count -gt 0) {
            # 体长口径按首末成员跨越的行数闭区间统计,空行与内联注释均计入
            $bodyLines = $class.Members[-1].Extent.EndLineNumber - $class.Members[0].Extent.StartLineNumber + 1
        }
        $FunctionFacts += [pscustomobject]@{
            name             = $class.Name
            line             = $startLine
            end_line         = $endLine
            body_lines       = $bodyLines
            params           = @()
            is_class         = $true
            doc              = Get-HelpText $class
            has_return       = $false
            string_key_count = 0
            nesting_depth    = 0
        }
    }
    $Owners = @()
    # 收集脚本级函数定义
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'FunctionDefinitionAst' }, $true))) {
        # 类方法里嵌着一个同名的 FunctionDefinitionAst(Parent 是 FunctionMemberAst),
        # 拿着它会让同一个方法被数两次;方法统一走下面的 Members 分支
        if (Test-Kind $node.Parent 'FunctionMemberAst') { continue }
        $Owners += $node
    }
    # 再收类方法:它们不是脚本级的 FunctionDefinitionAst,只能从类成员里取
    foreach ($class in $ClassNodes) {
        # 类体包含属性与方法两种成员,此处仅提取方法节点与顶层函数合流度量形状
        foreach ($member in $class.Members) {
            # 类成员里只有方法需要量形状,属性走字段那条路
            if (Test-Kind $member 'FunctionMemberAst') { $Owners += $member }
        }
    }
    # 脚本级函数与类方法到这里合流,后面一视同仁
    foreach ($owner in $Owners) {
        $FunctionFacts += [pscustomobject]@{
            name             = $owner.Name
            line             = $owner.Extent.StartLineNumber
            end_line         = $owner.Extent.EndLineNumber
            body_lines       = Get-BodyLines $owner
            params           = @(Get-ParameterNames $owner)
            is_class         = $false
            doc              = Get-HelpText $owner
            has_return       = Get-HasReturn $owner.Body
            string_key_count = Get-StringKeyCount $owner.Body
            nesting_depth    = Get-NestingDepth $owner.Body
        }
    }
    return $FunctionFacts
}

function Get-ControlFacts($Ast) {
    <#
    .SYNOPSIS
    产出条件、循环、抛异常、算式 return 四组事实。

    .DESCRIPTION
    四组都「只需要一个行号」,但判据各不相同:

    * **条件** —— 每个 if 的每个 clause(`elseif` 在 AST 里是同级的 clause 不是嵌套 if),
      记下摊平后的每个子判据所在行,「多个条件挤一行」靠这个重复;
    * **循环** —— 五种循环各有自己的类型名,标签由 `$LoopLabels` 给出;
    * **抛异常** —— 只认 `throw`,`trap` 不在此列(它更像 catch);
    * **算式 return** —— 剥掉包装后是裸变量或字面量的一律不算:没有口径可写,
      与 Python 侧 `return x` / `return None` 一个口径。

    .PARAMETER Ast
    整个文件的 AST。

    .OUTPUTS
    带 `conditions` / `loops` / `raises` / `returns` 四个数组的 pscustomobject。
    #>
    $Conditions = @()
    # if 与 elseif 在语法树中归并在 IfStatementAst 的 Clauses 中,在此统一收集条件分支
    foreach ($ifNode in @($Ast.FindAll({ $args[0].GetType().Name -eq 'IfStatementAst' }, $true))) {
        $index = 0
        # elseif 在 AST 里是与 if 同级的 clause,逐个收就是全部条件
        foreach ($clause in $ifNode.Clauses) {
            $condition = $clause.Item1
            $rows = @()
            # 每个子判据记一次它所在的行:同一行出现两个就说明条件被挤在了一行
            foreach ($operand in @(Get-ConditionOperands $condition)) {
                $rows += $operand.Extent.StartLineNumber
            }
            # 首个 clause 报 if 关键字所在行,elseif 报条件自己所在行(常见写法里两者同行)
            $line = $condition.Extent.StartLineNumber
            # 首个子句对齐 if 关键字所在行号,后续子句保留 elseif 自身起始行号
            if ($index -eq 0) { $line = $ifNode.Extent.StartLineNumber }
            $Conditions += [pscustomobject]@{ line = $line; operand_lines = @($rows) }
            $index++
        }
    }
    $Loops = @()
    # 五种循环共用一个类型名集合,标签由哈希表给出
    foreach ($node in @($Ast.FindAll({ $Script:LoopNames.Contains($args[0].GetType().Name) }, $true))) {
        $Loops += [pscustomobject]@{ line = $node.Extent.StartLineNumber; label = $LoopLabels[$node.GetType().Name] }
    }
    $Raises = @()
    # 只认 throw;trap 更像 catch,不在此列
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'ThrowStatementAst' }, $true))) {
        $Raises += [pscustomobject]@{ line = $node.Extent.StartLineNumber; label = 'throw' }
    }
    $Returns = @()
    # 仅带算式的 return 才需在上方注明返回值口径,需逐个检查其 Pipeline 承载的表达式类型
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'ReturnStatementAst' }, $true))) {
        # 裸 return 没有返回值,谈不上口径
        if ($null -eq $node.Pipeline) { continue }
        # 解包外层管道节点,获取实际被返回的内部单语句或底层表达式
        $inner = Unwrap-Pipeline $node.Pipeline
        # 剥不动说明整条管道本身就是一个算式,那也要报
        if ($null -eq $inner) { continue }
        $innerKind = $inner.GetType().Name
        # 裸变量与字面量都不是算式:没有口径可写,与 Python 侧 `return x` / `return None` 一个口径
        if ($innerKind -eq 'VariableExpressionAst') { continue }
        # 排除各类字面量常量(数值/布尔/字符串等),常量返回无需解释计算依据
        if ($innerKind -like '*ConstantExpressionAst') { continue }
        # 字符串插值、哈希表、数组字面量同理:读者一眼看得出得到的是什么
        if ($innerKind -in 'ExpandableStringExpressionAst', 'HashtableAst', 'ArrayLiteralAst') { continue }
        $Returns += [pscustomobject]@{ line = $node.Extent.StartLineNumber; label = 'return' }
    }
    # 返回控制流结构事实,供 rules.py 统一比对上方独立注释行与行号边界
    return [pscustomobject]@{
        conditions = $Conditions; loops = $Loops; raises = $Raises; returns = $Returns
    }
}

function Get-FieldFacts($Ast, $ClassNodes) {
    <#
    .SYNOPSIS
    产出类属性与顶层声明两类字段,以及它们的源码偏移。

    .DESCRIPTION
    字段是「这个数是什么、什么单位」的唯一落点,所以两种形态都要收:类里显式声明的
    属性,以及 **`$script:` 作用域或顶层带类型标注**的赋值 —— 后者表达的是模块级状态,
    不是临时变量;函数里的普通局部变量不算。

    偏移集合要一起返回:赋值那条路按偏移跳过同一个节点,否则一个构造会进两次分母,
    覆盖率的分母就虚高了。

    .PARAMETER Ast
    整个文件的 AST。

    .PARAMETER ClassNodes
    已经筛成「类」的 `TypeDefinitionAst`。

    .OUTPUTS
    带 `fields`(事实数组)与 `offsets`(哈希集)的 pscustomobject。
    #>
    $Fields = @()
    # 初始化字段节点源码偏移哈希表,用于在赋值统计中剔除声明类字段
    $FieldOffsets = New-Object 'System.Collections.Generic.HashSet[int]'
    # 类里显式声明的属性算字段,不管有没有带类型标注
    foreach ($class in $ClassNodes) {
        # 逐个成员筛:只有属性成员是字段,方法走函数那条路
        foreach ($member in $class.Members) {
            # 方法成员不是字段
            if (-not (Test-Kind $member 'PropertyMemberAst')) { continue }
            $Fields += [pscustomobject]@{ line = $member.Extent.StartLineNumber; label = $member.Name }
        }
    }
    # 再找「以赋值形式声明的字段」
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'AssignmentStatementAst' }, $true))) {
        # 排除属性修改与下标赋值等外部状态篡改,仅保留左侧为本作用域变量定义的节点
        $variable = Get-LeftVariable $node.Left
        # 左侧不是裸变量就不是声明,是改别人的属性或下标
        if ($null -eq $variable) { continue }
        # 有类型标注才谈得上「声明」;`$script:` 则连标注都不需要
        $typed = Test-TypeConstrained $node.Left
        # 两条都不满足就是函数里的临时变量,交给赋值那条路
        $isField = $variable.VariablePath.IsScript -or ($typed -and -not (Test-InsideCallable $node))
        # 不是字段就不记偏移 —— 偏移集合只用来排除字段
        if (-not $isField) { continue }
        $Fields += [pscustomobject]@{ line = $node.Extent.StartLineNumber; label = $variable.VariablePath.UserPath }
        # 记下偏移,赋值那条路据此跳过同一个节点
        [void]$FieldOffsets.Add($node.Extent.StartOffset)
    }
    # 字段偏移集合用于在赋值统计中跳过相同节点,避免同一个赋值构造进两次分母虚高基数
    return [pscustomobject]@{ fields = $Fields; offsets = $FieldOffsets }
}

function Get-AssignFacts($Ast, $FieldOffsets) {
    <#
    .SYNOPSIS
    产出「右侧是运算或调用」的赋值事实。

    .DESCRIPTION
    口径与 Python 侧只认 `BinOp` / `Call` / `IfExp` / `Compare` 完全一致:字面量赋值
    没什么可解释的,不要求注释,也就不进分母。已经算作字段的那些按偏移跳过。

    .PARAMETER Ast
    整个文件的 AST。

    .PARAMETER FieldOffsets
    `Get-FieldFacts` 给出的源码偏移集合。

    .OUTPUTS
    带 `line` / `label` 两个键的 pscustomobject 数组。
    #>
    $Assigns = @()
    # 逐个赋值看右侧是不是「算出来的」
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'AssignmentStatementAst' }, $true))) {
        # 字段声明只走 uncommented-field,不重复计入赋值(否则一个构造进两次分母)
        if ($FieldOffsets.Contains($node.Extent.StartOffset)) { continue }
        # 尝试剥离左侧裸变量以提取简明用户变量名
        $variable = Get-LeftVariable $node.Left
        # 默认拿左侧原文当标签:下标赋值与属性赋值剥不出变量名
        $label = $node.Left.Extent.Text
        # 能剥成裸变量就用变量名报,报告里读起来短
        if ($null -ne $variable) { $label = $variable.VariablePath.UserPath }
        # 解包右侧管道以判定其是否包含非平凡计算或调用表达式
        $inner = Unwrap-Pipeline $node.Right
        # 字面量与裸变量不算「算出来的」
        if (-not (Test-AnyKind $inner $ComputedKinds)) { continue }
        $Assigns += [pscustomobject]@{ line = $node.Extent.StartLineNumber; label = $label }
    }
    return $Assigns
}

function Get-BindingFacts($Ast, $ClassNodes) {
    <#
    .SYNOPSIS
    产出字段、赋值、静默吞异常、顶层绑定四组事实。

    .DESCRIPTION
    字段与赋值各自成函数(`Get-FieldFacts` / `Get-AssignFacts`),这里只做编排,
    外加两组只在语句块层面成立的事实:空 catch/trap,以及模块顶层的直接绑定。

    🔴 **字段与赋值互斥**:同一个赋值不可能既是字段又是普通赋值 —— 字段认领过的
    源码偏移会传进赋值那条路,那条路按偏移跳过它。

    静默吞异常只认**空的** catch/trap 体:`catch { }` 与 `trap { }`;写了语句的
    catch 是正常处理,不该报。顶层绑定只看脚本级的 begin/process/end 三块,
    函数体里的重名不算重名。

    .PARAMETER Ast
    整个文件的 AST。

    .PARAMETER ClassNodes
    已经筛成「类」的 `TypeDefinitionAst`,字段里的属性成员从它取。

    .OUTPUTS
    带 `fields` / `assigns` / `silent` / `bindings` 四个数组的 pscustomobject。
    #>
    $Field = Get-FieldFacts $Ast $ClassNodes
    # 提取所有右侧为计算或调用的赋值事实,传入字段偏移以跳过重复声明
    $Assigns = Get-AssignFacts $Ast $Field.offsets
    $Silent = @()
    # catch 体是空的,异常被吞掉且不留痕迹
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'TryStatementAst' }, $true))) {
        # 一个 try 可能有多个 catch,逐个看
        foreach ($clause in $node.CatchClauses) {
            # 只有「一条语句都没写」才算静默;写了语句的 catch 是正常处理
            if ($clause.Body.Statements.Count -eq 0) { $Silent += $clause.Extent.StartLineNumber }
        }
    }
    # trap 是 PowerShell 独有的吞异常形态,口径与空 catch 相同
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'TrapStatementAst' }, $true))) {
        # 同样只认空体
        if ($node.Body.Statements.Count -eq 0) { $Silent += $node.Extent.StartLineNumber }
    }
    # 顶层绑定只看脚本级的 begin/process/end 三块,函数体里的重名不算重名
    $ModuleStatements = @()
    # 三块里没写的那些是 $null
    foreach ($block in @($Ast.BeginBlock, $Ast.ProcessBlock, $Ast.EndBlock)) {
        # 没写的那块直接跳过
        if ($null -eq $block) { continue }
        $ModuleStatements += $block.Statements
    }
    $Bindings = @()
    # 逐个顶层语句看它绑定了什么名字
    foreach ($statement in $ModuleStatements) {
        # 函数与类定义是最常见的顶层绑定形态
        if (Test-AnyKind $statement @('FunctionDefinitionAst', 'TypeDefinitionAst')) {
            $Bindings += [pscustomobject]@{
                name = $statement.Name; kind = 'def'
                line = $statement.Extent.StartLineNumber; references_self = $false
            }
            continue
        }
        # 剩下的只有赋值可能构成绑定
        if (-not (Test-Kind $statement 'AssignmentStatementAst')) { continue }
        # 剥离赋值目标左侧的变量路径节点
        $variable = Get-LeftVariable $statement.Left
        # 左侧不是裸变量就不构成「定义了一次这个名字」
        if ($null -eq $variable) { continue }
        $name = $variable.VariablePath.UserPath
        $selfReference = $false
        # 右侧引用了自己说明是「就地扩展」而不是覆盖,不报重复
        foreach ($node in @($statement.Right.FindAll({ $args[0].GetType().Name -eq 'VariableExpressionAst' }, $true))) {
            # 任意深度出现同名变量都算引用自己
            if ($node.VariablePath.UserPath -eq $name) { $selfReference = $true }
        }
        $Bindings += [pscustomobject]@{
            name = $name; kind = 'assign'
            line = $statement.Extent.StartLineNumber; references_self = $selfReference
        }
    }
    # 汇总打包字段声明、非平凡赋值、吞异常行及顶层绑定记录对象
    return [pscustomobject]@{
        fields = $Field.fields; assigns = $Assigns; silent = $Silent; bindings = $Bindings
    }
}

function Get-FileFacts([string]$Target) {
    <#
    .SYNOPSIS
    读一个文件,产出报告需要的全部事实。

    .DESCRIPTION
    只做编排:读源码 → 解析 → 按四组抽取器各要一份结果 → 拼成有序字典。
    分段计时(由 `CODE_ARCH_PS_TIMING` 打开)打在这里,因为只有这里同时看得见
    「解析」「抽事实」「序列化」三段 —— 只看总耗时分不出该优化哪一段。

    🔴 `Parser::ParseInput` 只做词法与语法分析,**不执行被扫的源码**。这是本后端
    敢去解析任意脚本的前提。

    .PARAMETER Target
    要解析的文件路径。

    .OUTPUTS
    有序字典,字段名与 Python 侧后端的 JSON 约定对齐。
    #>
    $ItemWatch = [System.Diagnostics.Stopwatch]::StartNew()
    # 逐文件打一行路径,便于把慢的那个文件对上是哪一个
    if ($Script:Timing) { [Console]::Error.WriteLine("  $Target") }
    # 完整读取脚本源文件物理文本,供词法分析器分词及行号位置匹配
    $Text = [System.IO.File]::ReadAllText($Target)
    $TokenList = $null
    $ParseErrors = $null
    # 调用系统 Parser 提取 AST 树形结构与词法 Token 序列
    $Ast = [System.Management.Automation.Language.Parser]::ParseInput($Text, [ref]$TokenList, [ref]$ParseErrors)
    Write-Segment 'parse' $ItemWatch
    # 从 Token 流提取注释行号集合以及文件顶部帮助文档
    $Tokens = Get-TokenFacts $TokenList $Text
    Write-Segment 'comments' $ItemWatch
    # 枚举与 DSC 配置也是 TypeDefinitionAst,但它们没有「类的形状」,先筛掉
    $ClassNodes = @()
    # 遍历类型定义节点,过滤出 class 关键字声明的真实类定义
    foreach ($node in @($Ast.FindAll({ $args[0].GetType().Name -eq 'TypeDefinitionAst' }, $true))) {
        # 只有 class 关键字定义的才算类
        if ($node.IsClass) { $ClassNodes += $node }
    }
    # 抽取脚本中全部函数、类及类方法的定义与形状事实
    $FunctionFacts = Get-OwnerFacts $Ast $ClassNodes
    Write-Segment 'functions' $ItemWatch
    # 抽取分支条件、循环、抛出异常及非裸值返回等控制流事实
    $Control = Get-ControlFacts $Ast
    Write-Segment 'constructs' $ItemWatch
    # 抽取模块字段、右侧计算赋值、空体异常吞噬及顶层绑定事实
    $Binding = Get-BindingFacts $Ast $ClassNodes
    $ErrorMessages = @()
    # 语法错误不吞:随结果一起回去,调用方按文件数差额察觉
    foreach ($parseError in $ParseErrors) { $ErrorMessages += $parseError.Message }
    $Result = [ordered]@{
        parse_errors        = @($ErrorMessages)
        module_doc          = $Script:ModuleDoc
        comment_rows        = @($Tokens.comment_rows)
        whole_line_rows     = @($Tokens.whole_line_rows)
        functions           = @($FunctionFacts)
        conditions          = @($Control.conditions)
        loops               = @($Control.loops)
        raises              = @($Control.raises)
        fields              = @($Binding.fields)
        assigns             = @($Binding.assigns)
        returns             = @($Control.returns)
        silent_except_lines = @($Binding.silent)
        bindings            = @($Binding.bindings)
    }
    Write-Segment 'tail' $ItemWatch
    return $Result
}
