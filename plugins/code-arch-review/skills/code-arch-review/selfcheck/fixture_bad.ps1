<#
.SYNOPSIS
  闸的 PowerShell 阴性对照:每类该报的构造各留一个,故意不写注释。

.DESCRIPTION
  这份样本用来证明闸在 PowerShell 档位上**真的会报**,不是恒绿。它故意包含:
  一行里挤两个子条件的 if、行尾反引号续行的条件、无注释的循环与 throw、
  行尾注释可接受但没写的赋值与 return、无注释的字段、空 catch、
  以及同名函数的重复顶层定义(后者静默胜出,没有任何别的东西会说)。
  当前期望值:15 处违规、覆盖率 57.9%(其中 `duplicate-toplevel` 与 `silent-except`
  各 1 处必须命中)。改动 PowerShell 后端之后请重新核对这三个数。
#>

#>

# 顶层常量:模块根目录
$script:RootPath = $PSScriptRoot

# 带类型的顶层字段:重试次数上限
[int]$MaxRetry = 3

function Get-Documented {
    <#
    .SYNOPSIS
      Do one thing.
    .DESCRIPTION
      Explains why this exists and what the caller must guarantee,
      so a reader can call it without reading the body.
    .PARAMETER Name
      The target name.
    .OUTPUTS
      System.String
    #>
    param([string]$Name, [int]$Count)

    # 拼出来的是给日志用的短标签,不带路径
    $label = "$Name/$Count"
    # 转成小写再比,配置里大小写不统一
    $normalized = $Name.ToLower()

    # 名字为空就没得比,直接返回空标签
    if ([string]::IsNullOrEmpty($Name)) {
        return ''
    }

    # 两个条件都要成立才算命中
    if (
        # 名字必须非空
        $Name -and
        # 次数必须为正
        $Count -gt 0
    ) {
        return $label + $normalized
    }

    # 逐条累加:顺序有语义,不能并行
    foreach ($item in 1..$Count) {
        $total = $total + $item
    }

    # 缩进注释里同时有 {} 和 #{ 也不能影响解析
    $here = @"
    { not a block } # not a comment
"@

    # 哈希表字面量里的 # 也不是注释
    $map = @{ key = '#value'; other = 'a { b }' }

    # 行尾注释在这一条上被接受
    $head = $Name.Substring(0, 1)   # 首字母,给短标签用

    return $label
}

function Get-Bare([string]$Name) {
    $value = Get-Item $Name
    if ($Name) {
        throw "missing: $Name"
    }
    try {
        Remove-Item $Name
    }
    catch { }

    # 反引号续行:这是同一个条件,不是两个
    if ($Name -and `
        $value) {
        Write-Host $Name
    }
    return $value
}

class Widget {
    # 显示名,给日志用
    [string]$Bar
    [int]$Count

    [void] Run([int]$Times) {
        for ($i = 0; $i -lt $Times; $i++) {
            Write-Host $i
        }
    }
}

# 第一份实现
function Duplicate {
    return 1
}

# 第二份实现:同名,后定义的静默胜出
function Duplicate {
    return 2
}

# 累加式重绑:不算覆盖
$script:RootPath = $script:RootPath + '/sub'
