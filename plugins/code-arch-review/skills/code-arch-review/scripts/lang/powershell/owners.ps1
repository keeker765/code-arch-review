<#
.SYNOPSIS
逐个函数/类量事实 —— 参数表、体长、嵌套深度、字符串键数、有没有返回值、帮助块在哪。

.DESCRIPTION
这一组函数的共同点是**输入都是一个可调用体的节点**:函数定义、类定义或类方法。
它们只回答「这个体有多大、有多深、用了几个字段名」,不作任何阈值判断 ——
判多少算多是 `core/rules.py` 的事,阈值随语言给,不随语法给。

帮助块的查找(`Get-HelpText`)也在这里而不在入口:它要按**源码偏移**在候选区间里挑,
与 AST 无关,但它的输入仍然是「一个可调用体」,和上面几个同源。
#>

function Get-ParameterNames($Owner) {
    <#
    .SYNOPSIS
    这个可调用体声明的形参名。

    .DESCRIPTION
    形参有两处来源,缺一不可:

    * `$Owner.Parameters` —— 函数名后面括号里的内联形参;
    * `$Owner.Body.ParamBlock` —— 函数体开头的 `param( ... )` 块。

    真实脚本里两种写法混用很常见,只看一处会把一半函数的参数数报成 0,
    于是 `many-kwargs` 整条规则静默失效。

    🔴 与 Python 侧不同,这里**不剔除任何东西**:PowerShell 没有隐式 `self`,
    所有形参都是调用方真的会传的。

    .PARAMETER Owner
    函数定义或类方法节点。

    .OUTPUTS
    参数名数组;没有形参时是空数组。
    #>
    $names = @()
    # 没有内联形参时 Parameters 是 $null 而不是空集合,@($null) 会变成一个元素
    if ($null -ne $Owner.Parameters) {
        # 提取形参 UserPath 剥去 $ 前缀,统一成不带作用域修饰的纯标识符
        foreach ($parameter in @($Owner.Parameters)) {
            $names += $parameter.Name.VariablePath.UserPath
        }
    }
    # param() 块与内联形参是并列的两种写法,要把两边都收进来
    if (
        # 排除无函数体节点(如接口纯声明)
        $null -ne $Owner.Body -and
        # 函数体显式声明了 param 块时从中提取参数
        $null -ne $Owner.Body.ParamBlock
    ) {
        # param 块可能与内联形参并存,此处累加确保高级函数的形参不被漏计
        foreach ($parameter in @($Owner.Body.ParamBlock.Parameters)) {
            $names += $parameter.Name.VariablePath.UserPath
        }
    }
    return $names
}

function Get-BodyLines($Owner) {
    <#
    .SYNOPSIS
    函数体占多少物理行。

    .DESCRIPTION
    口径与 Python 侧 `body_lines` 一致:**首尾之间的闭区间行数**,不是语句条数。
    这里刻意不直接拿 `$Owner.Extent` 首尾相减 —— 那会把 `function f` 这一行和
    函数签名上方的东西也算进去,导致同样一个体在有注解时凭空变长。

    因此本函数先分别取 `param()` 块与 `begin` / `process` / `end` 三个块的起止行,
    再取「最早起点」与「最晚终点」。三块里只有非空的才算 —— 空的 `process {}`
    不该把体长撑到函数末尾。

    .PARAMETER Owner
    函数定义或类方法节点。

    .OUTPUTS
    行数;没有体或体是空的时返回 0。
    #>
    $body = $Owner.Body
    # 没有体(理论上不该出现)按 0 行算,不让调用方判空
    if ($null -eq $body) { return 0 }
    $starts = @()
    $ends = @()
    # param() 块属于函数体的一部分,它占据的行要算进去
    if ($null -ne $body.ParamBlock) {
        $starts += $body.ParamBlock.Extent.StartLineNumber
        $ends += $body.ParamBlock.Extent.EndLineNumber
    }
    # 逐块扫描以获取有效执行块的起止行号
    foreach ($block in @($body.BeginBlock, $body.ProcessBlock, $body.EndBlock)) {
        # 三个块里没写的那些是 $null
        if ($null -eq $block) { continue }
        # 写了但里面是空的块不占体长,不该把终点撑到函数末尾
        if ($block.Statements.Count -eq 0) { continue }
        $starts += $block.Extent.StartLineNumber
        $ends += $block.Extent.EndLineNumber
    }
    # 一块都没写(空函数)按 0 行算
    if ($starts.Count -eq 0) { return 0 }
    $first = ($starts | Measure-Object -Minimum).Minimum
    $last = ($ends | Measure-Object -Maximum).Maximum
    # PS 7 的 Measure-Object 在单元素上给 double,统一成整数免得 JSON 里出 18.0
    return [int]($last - $first + 1)
}

function Get-ControlDepth($Node, $Scope) {
    <#
    .SYNOPSIS
    这颗控制流节点在**给定函数体内部**嵌套了几层。

    .DESCRIPTION
    从节点往上走到 `$Scope` 为止,数路上撞到几个控制流节点。
    撞到更里层的函数/类定义就返回 0 —— 那说明这颗节点属于里层函数,
    对外层函数根本不算深度,数进去等于把「抽小函数」这个动作惩罚两次。

    .PARAMETER Node
    一个控制流节点。

    .PARAMETER Scope
    它的所属函数体;往上走到这里就停。

    .OUTPUTS
    层数。
    #>
    $depth = 0
    $parent = $Node.Parent
    # 一路往上走到本函数的边界为止
    while ($null -ne $parent) {
        # 走到自己函数的顶上就停,再往上不属于本函数
        if ([object]::ReferenceEquals($parent, $Scope)) { break }
        $kind = $parent.GetType().Name
        # 撞到别的函数/类的边界说明这个节点属于里层,对外层函数不算深度
        if (
            # 嵌套函数定义形成独立的新作用域
            $kind -eq 'FunctionDefinitionAst' -or
            # 类方法成员定义具有独立控制流边界
            $kind -eq 'FunctionMemberAst' -or
            # 类定义本体同样阻断外层深度统计
            $kind -eq 'TypeDefinitionAst'
        ) {
            return 0
        }
        # 控制流节点才加一层;别的节点只是路上经过
        if ($Script:ControlNames.Contains($kind)) { $depth++ }
        $parent = $parent.Parent
    }
    return $depth
}

function Get-NestingDepth($Scope) {
    <#
    .SYNOPSIS
    这个函数体里最深嵌套到几层。

    .DESCRIPTION
    取「各控制流节点深度的最大值」。与 Python 侧 `depth()` 同一条口径:
    **函数与类定义不加层**,理由见 `Get-ControlDepth`。

    .PARAMETER Scope
    函数体节点。

    .OUTPUTS
    最深层数;没有任何控制流时返回 0。
    #>
    $worst = 0
    # 先找出体内所有控制流节点,再逐个量它到本函数顶的距离
    foreach ($node in @($Scope.FindAll({ $Script:ControlNames.Contains($args[0].GetType().Name) }, $true))) {
        # 向上回溯父链统计经过的控制流节点数,遇内部嵌套函数则归零以防重复惩罚
        $depth = Get-ControlDepth $node $Scope
        # 保留最大者,小的那些不影响结论
        if ($depth -gt $worst) { $worst = $depth }
    }
    return $worst
}

function Get-StringKeyCount($Scope) {
    <#
    .SYNOPSIS
    体内在**同一个对象**上按字符串键取值,最多取了几种键。

    .DESCRIPTION
    对应 `dict-as-type`:一个对象上散着 `$cfg.A` / `$cfg.B` / `$cfg.C` …… 说明
    它其实是个类型,字段含义全靠键名口头约定。

    🔴 本后端**默认关掉这条规则**(见 `lang/registry.py` 的 `_PS_DISABLED`):
    `$obj.A` 在这个语言里既可能是哈希表取值,也可能是强类型对象的属性访问,
    没有类型信息分不开。实测两万行命中 21 次,量级说明它是噪声不是信号。
    函数留着是为了让口径可查、也为了将来有了类型信息能直接打开。

    两种取值形态都收:`$obj.A`(`MemberExpressionAst`)与 `$obj['A']`(`IndexExpressionAst`)。
    `$obj[0]` 这类数字下标不算 —— 那不是按字段名取值。

    .PARAMETER Scope
    函数体节点。

    .OUTPUTS
    最多的键数;一个字符串键都没用时返回 0。
    #>
    $seen = @{}
    # 一次遍历同时收属性访问与下标访问两种形态
    foreach ($node in @($Scope.FindAll({ $args[0].GetType().Name -in 'MemberExpressionAst', 'IndexExpressionAst' }, $true))) {
        $key = $null
        $target = $null
        # 属性访问:`$obj.A`,键在 .Member 上
        if (Test-Kind $node 'MemberExpressionAst') {
            $target = $node.Expression
            # 成员名是字面量时提取属性字符串键名
            if (Test-Kind $node.Member 'StringConstantExpressionAst') { $key = $node.Member.Value }
        }
        else {
            # 下标访问:`$obj['A']`,键在 .Index 上
            $target = $node.Target
            # 下标是字面量时提取字典字符串键名
            if (Test-Kind $node.Index 'StringConstantExpressionAst') { $key = $node.Index.Value }
        }
        # 数字下标或算出来的下标不是「按字段名取值」,跳过
        if (
            # 未提取到有效字符串键时无法作为类型字段统计
            $null -eq $key -or
            # 目标对象表达式为空时无法归纳对象标识
            $null -eq $target
        ) { continue }
        # 用取值目标的源码文本当对象标识:不建符号表也能把同一个对象的不同写法归到一起
        $owner = $target.Extent.Text
        # 该对象首次出现时初始化其属性键名集合字典
        if (-not $seen.ContainsKey($owner)) { $seen[$owner] = @{} }
        $seen[$owner][$key] = $true
    }
    $best = 0
    # 取「同一个对象上键最多」的那个数
    foreach ($keys in $seen.Values) {
        # 保留最大者即可,其余对象有多少键不影响结论
        if ($keys.Count -gt $best) { $best = $keys.Count }
    }
    return $best
}

function Get-HasReturn($Scope) {
    <#
    .SYNOPSIS
    体内有没有 `return <算式>`。

    .DESCRIPTION
    只判「有没有」,决定**要不要写 `.OUTPUTS` 小节**。2026-10-18 起
    `return` 不再单独要求注释,返回口径统一归 `.OUTPUTS` 小节。
    裸 `return` 与 `return $x` 都算「没有返回值」（无口径可写)。

    .PARAMETER Scope
    函数体节点。

    .OUTPUTS
    布尔值。
    #>
    foreach ($node in @($Scope.FindAll({ $args[0].GetType().Name -eq 'ReturnStatementAst' }, $true))) {
        # 带管道的 return 才是有返回值的那种
        if ($null -ne $node.Pipeline) { return $true }
    }
    return $false
}

function Get-HelpText($Owner) {
    <#
    .SYNOPSIS
    找出这个可调用体的注释式帮助块,原样返回其文本。

    .DESCRIPTION
    `Get-Help` 认两种位置,两种都得找,少一种就会把写好的文档报成没写:

    1. **体内首**:帮助块写在函数体/类体的最前面,在第一条语句之前;
    2. **紧贴上方**:帮助块写在 `function` / `class` 关键字的上一行,中间不留空行。

    判「体内首」要一个上界,不能让帮助块属于下一个函数 —— 上界取
    「函数体首条语句的起点」,类则取「第一个成员的起点」。没有体(类)时走成员分支。

    输出范围而不是布尔值:后端还要用它判缺哪些小节、摘要有几行解释。

    .PARAMETER Owner
    函数定义、类定义或类方法节点。

    .OUTPUTS
    帮助块原文(含起止定界符);没有帮助块时返回 $null。
    #>
    $insideStart = $Owner.Extent.StartOffset
    $limit = $Owner.Extent.EndOffset
    # 有函数体时,上界收到第一条语句之前,免得把下一个函数的帮助块算进来
    if ($null -ne $Owner.Body) {
        $limit = $Owner.Body.Extent.EndOffset
        # 函数语句可能分散在 begin/process/end 任意一块中,需综合三者求出实际代码起始边界
        foreach ($block in @($Owner.Body.BeginBlock, $Owner.Body.ProcessBlock, $Owner.Body.EndBlock)) {
            # 三个块里没写的那些是 $null
            if ($null -eq $block) { continue }
            # 空块没有语句,给不出上界
            if ($block.Statements.Count -eq 0) { continue }
            $first = $block.Statements[0].Extent.StartOffset
            # 取所有块里最早的那条语句,它之前的内容才属于函数头
            if ($first -lt $limit) { $limit = $first }
        }
    }
    else {
        # 类没有 Body,上界收到第一个成员之前
        foreach ($member in @($Owner.Members)) {
            # 取最早的成员起点
            if ($member.Extent.StartOffset -lt $limit) { $limit = $member.Extent.StartOffset }
        }
    }
    # 形式一:帮助块在函数体/类体开头(Get-Help 认的第一种位置)
    $best = $null
    # AST 节点不包含注释文本,只能按源码字节偏移量在块注释缓存中匹配归属本函数的帮助块
    foreach ($token in $Script:BlockTokens) {
        $offset = $token.Extent.StartOffset
        # 在函数自己之前的不算
        if ($offset -le $insideStart) { continue }
        # 越过上界的属于后面的代码,不算本函数的
        if ($offset -ge $limit) { continue }
        # 取最靠前的那个:函数头里同时有两块注释时,只有第一块是 Get-Help 认的
        if (
            # 尚未记录首个帮助块标记时直接采纳当前块
            $null -eq $best -or
            # 遇到源码偏移量更靠前的块注释时更新为更优先的候选
            $offset -lt $best.Extent.StartOffset
        ) { $best = $token }
    }
    # 找到体内首那一块就直接返回,不必再看上方
    if ($null -ne $best) { return $best.Extent.Text }
    # 形式二:帮助块紧贴 function/class 关键字上方 —— Get-Help 同样认,不认就会把写好的文档报成没有
    $above = $Owner.Extent.StartLineNumber - 1
    # 定义在第一行时上方没有行可查
    if ($above -lt 1) { return $null }
    # 只有「结束于上一行」的块注释才算紧贴;中间隔了空行或代码就不是它的文档
    if ($Script:CommentEnding.ContainsKey($above)) { return $Script:CommentEnding[$above] }
    return $null
}
