<#
.SYNOPSIS
  闸的 PowerShell 合规样本:每类该解释的构造各一个,且全部解释到位。

.DESCRIPTION
  这份文件是自检夹具,不参与任何生产逻辑。它钉住的是两件事 —— 「零违规」与
  「覆盖率 100%」在 PowerShell 档位上必须同时成立;这两个数各由一套谓词算出,
  分叉时两个数都不报错,读者无法判断哪个是真的。改过 PowerShell 后端就跑一次
  `selfcheck/run.py`。

  覆盖到的构造:模块文档、$script: 与带类型的顶层字段、公开函数(含帮助块)、
  类与类属性、条件(含多行条件与摊平后的子条件)、循环、throw、空值返回、
  算式返回、算出来的赋值、try/catch。
#>

# 模块级常量:夹具要遍历的根目录
$script:Root = $PSScriptRoot

# 顶层字段:单个标签允许的最大长度(字符数,闭端)
[int]$MaxLength = 8

function Get-Label {
    <#
    .SYNOPSIS
      把名字与次序拼成一个给日志看的短标签。

    .DESCRIPTION
      短标签只给人看,不进任何索引,所以这里不做大小写归一 —— 调用方要比较时
      请用返回的归一化结果。名字为空时返回空串而不是抛异常:空名字在扫描过程里
      是常态(清单文件没有 Name 字段),为此中断整批不值得。

    .PARAMETER Name
      目标名字;允许空串,此时返回空标签。

    .PARAMETER Order
      次序编号,从 1 开始。

    .OUTPUTS
      System.String,形如 `<名字>/<次序>`,名字部分已转小写。
    #>
    param([string]$Name, [int]$Order)

    # 拼出来的是日志用短标签,不带路径、不带时间戳
    $label = "$Name/$Order"
    # 转小写再参与比较:配置里的名字大小写不统一
    $normalized = $Name.ToLower()

    # 名字为空就没得拼,给空标签而不是抛异常
    if ([string]::IsNullOrEmpty($Name)) {
        # 空串是「没有名字」的约定值,调用方按需回退到路径
        return ''
    }

    # 两个条件都成立才算一个合法标签
    if (
        # 名字得有实际内容
        $Name.Length -gt 0 -and
        # 次序得是正数
        $Order -gt 0
    ) {
        # 返回拼接结果:单位是字符,分隔符已包含在内
        return $label + $normalized
    }

    # 逐条累加次序:累加有前后依赖,顺序是语义,不能并行
    foreach ($index in 1..$Order) {
        # 累加值只用于长度校验,不参与标签本身
        $total = $total + $index
    }

    # 走到这里说明次序非法,仍然给出标签让人看到原始值
    return $label
}

function Remove-Cached {
    <#
    .SYNOPSIS
      删掉缓存文件,失败时报错而不是吞掉。

    .DESCRIPTION
      缓存文件被别的进程占着时删不掉,这时候要么重试要么报错 —— 静默返回会让
      调用方以为删干净了,下次读到的还是旧数据。

    .PARAMETER Path
      缓存文件路径。

    .OUTPUTS
      无。
    #>
    param([string]$Path)

    # 缓存不存在就是已经删干净了,不必当作异常
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    try {
        # -Force 才能删掉只读的缓存文件
        Remove-Item -LiteralPath $Path -Force
    }
    catch {
        # 删不掉必须让调用方看见:继续跑会读到旧数据
        throw "cache is locked: $Path"
    }
}

class Widget {
    <#
    .SYNOPSIS
      夹具用的最小类:一个可读属性加一个方法。

    .DESCRIPTION
      类只判文档,不判参数表与函数体 —— 类的形状由它的成员决定,
      套函数的那几条阈值只会误报。
    #>

    # 显示名,给日志用;可以为空
    [string]$Name

    [void] Report([int]$Times) {
        <#
        .SYNOPSIS
          把显示名打印若干次。

        .DESCRIPTION
          次数完全由调用方给,这里不做上限校验 —— 夹具只验证文档口径,
          不承担防呆职责;真要限流应该在上层按日志配额做。

        .PARAMETER Times
          打印次数,0 表示一次都不打。
        #>
        # 逐次打印:次数由调用方给,顺序不重要但必须都打出来
        for ($index = 0; $index -lt $Times; $index++) {
            Write-Host $this.Name
        }
    }
}
