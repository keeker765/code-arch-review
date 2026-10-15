<#
.SYNOPSIS
把 token 流翻译成注释事实 —— 哪些行有注释、哪些是独立整行、模块文档写了什么。

.DESCRIPTION
「哪些行算有注释」是违规与覆盖率**共用的唯一判据**:闸的 `_explained()` 只看两样
东西 —— 构造上一行是不是独立整行注释,以及本行有没有行尾注释。这两份行号集合
必须由同一次 token 遍历算出,分两处判迟早会出现两个答案(原闸就是这么坏掉的)。

🔴 判「独立整行」不能只看这一行是不是以 `#` 开头:`#` 可能出现在字符串里,而块注释的
中间行本身不带 `#`。这里按 token 的 **StartColumnNumber / EndColumnNumber** 切出注释
覆盖的列区间,再看区间两侧是不是只剩空白 —— 只有位置信息才能同时判对这两种。

输入是 token 数组而不是源码文本:字符串与 here-string 里的 `#` 和 `{}` 只有 tokenizer
认得出来,自己扫文本一定会把它们当注释或当括号。
#>

function Get-CommentBody([string]$Text) {
    <#
    .SYNOPSIS
    去掉一块注释的定界符,只留正文。

    .DESCRIPTION
    块注释去掉两端的定界符,行注释去掉开头的井号与紧随的一个空格。
    模块文档要的是正文而不是标记 —— 标记混进去,「写了三行还是一行」就不可判了。

    .PARAMETER Text
    一个注释 token 的原文。

    .OUTPUTS
    去掉定界符后的正文(可能为空串)。
    #>
    # 块注释:两端各有两字符的定界符
    if ($Text.StartsWith('<#')) {
        # 砍掉开头的两字符定界符,剩下的才是正文
        $body = $Text.Substring(2)
        # 收尾的 #> 也要脱掉,否则最后一行会多出两个字符
        if ($body.EndsWith('#>')) { $body = $body.Substring(0, $body.Length - 2) }
        # 块注释正文以裁剪后的内容为准,首尾空行不算
        return $body.Trim()
    }
    # 行注释:去掉开头的 # 与紧随的一个空格
    $body = $Text.Substring(1)
    # 只吃一个空格,`#   缩进内容` 里多出来的空格属于正文排版
    if ($body.StartsWith(' ')) { $body = $body.Substring(1) }
    return $body
}

function Get-ModuleDocText($TokenList) {
    <#
    .SYNOPSIS
    取文件开头的注释块作为模块文档正文;之前出现过代码就返回 `$null`。

    .DESCRIPTION
    判据是「它之前没有任何代码」:从第一个 token 起,途中的块注释与连续的
    `#` 行都算模块文档的一部分,**行与行之间允许空行** —— 空行只是分段,不是代码。
    `#Requires` 是编译指令不是说明,跳过它但**不算进正文**,它也不终结文档。

    真代码一出现就收摊 —— 后面即使还有注释,那也是代码区里的注释。正文按行拼,
    `thin-module-doc` 数的是行数,所以分段空行不该在这里丢掉。

    🔴 这条口径与 Python 侧**故意不同**:Python 只认模块第一个字符串字面量。
    别来「统一」—— `#` 注释在 Python 里语法上就当不了 docstring,而 PowerShell
    根本没有 docstring 节点,文件开头的注释块是它唯一的模块说明位置。
    完整理由与它修掉的那个真实误报见 `references/languages.md` 的 PowerShell 一节。

    🔴 **为什么这里认 `#` 行注释,而 Python 后端只认 docstring** —— 这不是两边
    判据分叉,是语言各写各的。规则本身是「模块要有说明」,而「什么算说明」由语言的
    语法决定:Python 里 `#` 注释**在语法上就当不了 docstring**(`ast.get_docstring`
    取的是模块第一个字符串字面量),PowerShell 里则根本没有 docstring 这种节点,
    文件开头的注释块就是它唯一的模块说明位置。照搬 Python 的取法等于把一个语言的
    语法强加给另一个语言,结果是 PowerShell 的 `#` 风格模块说明永远不被承认。

    这条口径修掉过一个真实误报:`脚本工具/claude-privacy-audit.ps1`(948 行)开头是
    `#Requires` 加一个完整帮助块,旧口径因为「第一个有意义的 token 不是块注释」
    直接判成没写模块文档。看到两门口径不同时,**先看这段再决定要不要「统一」**。

    .PARAMETER TokenList
    `Parser::ParseInput` 吐出的 token 数组。

    .OUTPUTS
    注释正文(多行用换行拼);文件开头没有注释时返回 `$null`。
    #>
    $lines = @()
    # 只看文件最前面这一段:撞上真代码就停
    foreach ($token in $TokenList) {
        # 非注释 token 里,空行与缩进都不是代码,继续往后找
        if ($token.Kind -ne $CommentKind) {
            # 换行、空白、行尾反引号都不构成「代码已经开始」
            if ($token.Kind -in 'NewLine', 'Whitespace', 'LineContinuation') { continue }
            break
        }
        # #Requires 是给引擎看的指令,不进文档正文
        if ($token.Extent.Text -match '^#\s*[Rr]equires\b') { continue }
        # 正文按行累加:块注释与井号行都拆成一行正文
        $lines += Get-CommentBody $token.Extent.Text
    }
    # 一行注释都没有就等于没写模块文档
    if ($lines.Count -eq 0) { return $null }
    # 多行用换行拼成一份正文:行数就是 thin-module-doc 要数的那一行
    return ($lines -join "`n")
}


function Get-TokenFacts($TokenList, $Text) {
    <#
    .SYNOPSIS
    扫一遍 token 流,产出注释行、独立整行注释行,并填好后续要用的三份脚本级缓存。

    .DESCRIPTION
    这一步同时干三件事,因为它们共用同一次 token 遍历:

    1. **注释行** —— 块注释跨几行就记几行,行尾 `#` 也记;
    2. **独立整行注释行** —— 注释两侧除空白外什么都没有的那种。条件/循环/抛异常
       只认这一种,行尾注释不算;
    3. **模块文档与块注释缓存** —— 第一个有意义的 token 若是块注释,它就是模块文档;
       每块注释的「结束行 → 文本」映射留给 `Get-HelpText` 判「紧贴上方」用。

    🔴 判「独立整行」不能只看这一行是不是以 `#` 开头:`#` 可能出现在字符串里,
    而块注释的中间行本身就不带 `#`。这里按 token 的 **StartColumnNumber / EndColumnNumber**
    切出注释覆盖的列区间,再看区间两侧是不是只剩空白 —— 只有位置信息才能同时判对这两种。

    副作用(调用方依赖):填 `$Script:LineTexts`、`$Script:BlockTokens`、
    `$Script:CommentEnding`、`$Script:ModuleDoc`。

    .PARAMETER TokenList
    `Parser::ParseInput` 吐出的 token 数组。

    .PARAMETER Text
    该文件的完整源码。行文本缓存由它切出,不另读一次磁盘。

    .OUTPUTS
    带 `comment_rows` 与 `whole_line_rows` 两个哈希集的 pscustomobject。
    #>
    $Script:LineTexts = $Text -split "`n"
    # 每一行是否出现过注释(含行尾注释):字段与算出来的赋值接受行尾注释
    $CommentRows = New-Object 'System.Collections.Generic.HashSet[int]'
    # 其中「独立整行」的那些:条件 / 循环 / 抛异常只认这一种
    $WholeRows = New-Object 'System.Collections.Generic.HashSet[int]'
    # <# #> 块注释表,留给 Get-HelpText 判「帮助块紧贴函数上方」
    $Script:BlockTokens = @()
    # 注释的「结束行 → 文本」映射,同样给「紧贴上方」那种写法用
    $Script:CommentEnding = @{}
    # 文件开头的注释块正文;真代码之前没有注释时为 $null
    $Script:ModuleDoc = Get-ModuleDocText $TokenList
    # 一次遍历同时收三种信息,分三遍扫是白花两倍时间
    foreach ($token in $TokenList) {
        # 这一遍只关心注释 token,别的直接跳过
        if ($token.Kind -ne $CommentKind) { continue }
        # 块注释要留给 Get-HelpText,行注释不用 —— 帮助块只能是 <# #>
        if ($token.Extent.Text.StartsWith('<#')) {
            # 记住这一块与它的结束行:「紧贴函数上方」那种写法靠这张表 O(1) 查到
            $Script:BlockTokens += $token
            $Script:CommentEnding[$token.Extent.EndLineNumber] = $token.Extent.Text
        }
        $startRow = $token.Extent.StartLineNumber
        $endRow = $token.Extent.EndLineNumber
        # 块注释跨几行就记几行,行号是 1 基的物理行
        for ($row = $startRow; $row -le $endRow; $row++) {
            [void]$CommentRows.Add($row)
            # 取本行原文,下面按列区间切出注释前、注释后那两段
            $line = Get-LineText $row
            # 注释在本行覆盖的区间:首行从 token 起点算,其余行从行首算
            $from = 1
            # 首行才要跳过 token 起点之前的缩进
            if ($row -eq $startRow) { $from = $token.Extent.StartColumnNumber }
            # 默认管到行尾:中间行两侧都是注释,后面没有代码
            $to = $line.Length + 1
            # 末行才截到 token 终点
            if ($row -eq $endRow) { $to = $token.Extent.EndColumnNumber }
            $before = ''
            # 列号是 1 基的,换成 0 基的切片长度要减一;再夹到行长以内防越界
            if ($from -gt 1) { $before = $line.Substring(0, [Math]::Min($from - 1, $line.Length)) }
            # 注释之后那一段的起点,同样要夹到行长以内
            $tail = [Math]::Min($to - 1, $line.Length)
            $after = ''
            # 注释之后还有内容就取出来,它就是「行尾有没有别的东西」的证据
            if ($tail -lt $line.Length) { $after = $line.Substring($tail) }
            # 两侧都只剩空白,这一行才是独立整行注释
            if (($before -match '^\s*$') -and
                # 注释之后那一段也只许是空白
                ($after -match '^\s*$')) { [void]$WholeRows.Add($row) }
        }
    }
    # 两个行号集合由同一次遍历产出,调用方可以当同一份判据的两面用
    return [pscustomobject]@{ comment_rows = $CommentRows; whole_line_rows = $WholeRows }
}
