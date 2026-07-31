#Requires -Version 5.1
<#
  prune-runtime.ps1 - 删掉 venv 里运行时用不到的东西，为分发瘦身。

  默认只列清单不动手（dry-run）；确认无误后加 -Apply 才真删。
  删的是 .venv 本体，误删只能重跑 setup.ps1 重装，所以默认不动手。

  删除范围（实测 7.49 GB -> 约 4.55 GB）：
    *.lib            2.62 GB  静态链接库（dnnl.lib 2.2 GB 为首），纯编译期产物
    __pycache__       211 MB  字节码缓存，下次 import 会自动重建
    imageio_ffmpeg     84 MB  视频编解码器，预测路径只读图片用不到
    pip/setuptools     ~24 MB 装完就不再需要（要装新包时重跑 setup.ps1）

  刻意不碰 torch\lib 里的 CUDA DLL（cusparse 362 MB、cufft 263 MB 等）：
  torch 在 Windows 上 import 时会预加载它们，删了可能直接起不来。

  用法：
    powershell -ExecutionPolicy Bypass -File scripts\prune-runtime.ps1          # 看清单
    powershell -ExecutionPolicy Bypass -File scripts\prune-runtime.ps1 -Apply   # 真删
    删完务必跑一次：  .\.venv\Scripts\python.exe backend\smoke.py
#>
param(
    [switch]$Apply,
    [switch]$IncludePip,
    [string]$VenvPath
)
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $VenvPath) { $VenvPath = Join-Path $RepoRoot '.venv' }

# 安全闸：确认目标真的是个 venv，避免参数写错删到别处。
$PyExe = Join-Path $VenvPath 'Scripts\python.exe'
if (-not (Test-Path $PyExe)) { throw "目标不像是一个 venv（找不到 $PyExe）" }
$Site = Join-Path $VenvPath 'Lib\site-packages'
if (-not (Test-Path $Site)) { throw "找不到 site-packages: $Site" }

function Get-SizeGB([object[]]$Items) {
    if (-not $Items -or $Items.Count -eq 0) { return 0.0 }
    $sum = 0L
    foreach ($it in $Items) {
        if ($it -is [System.IO.DirectoryInfo]) {
            $sum += (Get-ChildItem $it.FullName -Recurse -File -ErrorAction SilentlyContinue |
                     Measure-Object Length -Sum).Sum
        } else {
            $sum += $it.Length
        }
    }
    return [double]$sum / 1GB
}

Write-Host "venv: $VenvPath" -ForegroundColor Cyan
$before = (Get-ChildItem $VenvPath -Recurse -File -ErrorAction SilentlyContinue |
           Measure-Object Length -Sum).Sum / 1GB
Write-Host ("当前体积: {0:N2} GB`n" -f $before) -ForegroundColor Cyan

# 逐类收集要删的东西。
$targets = [ordered]@{}

$targets['*.lib 静态链接库'] =
    @(Get-ChildItem $Site -Recurse -File -Filter *.lib -ErrorAction SilentlyContinue)

$targets['__pycache__ 字节码缓存'] =
    @(Get-ChildItem $Site -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue)

$targets['imageio_ffmpeg 视频编解码器'] =
    @(Get-ChildItem $Site -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -like 'imageio_ffmpeg*' })

# pip 只值 0.02 GB，删了这个 venv 就装不了新包了——只有做分发副本时才划算，故默认保留。
if ($IncludePip) {
    $targets['pip / setuptools / pytest'] =
        @(Get-ChildItem $Site -Directory -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -match '^(pip|setuptools|wheel|pytest|_pytest|pkg_resources)($|[-.])' })
}

$total = 0.0
foreach ($name in $targets.Keys) {
    $items = $targets[$name]
    $gb = Get-SizeGB $items
    $total += $gb
    Write-Host ("  {0,-30} {1,7:N2} GB  ({2} 项)" -f $name, $gb, $items.Count)
}
Write-Host ("  {0,-30} {1,7:N2} GB" -f '合计可释放', $total) -ForegroundColor Yellow

if (-not $Apply) {
    Write-Host "`n[DRY-RUN] 以上内容并未删除。确认无误后加 -Apply 执行：" -ForegroundColor Green
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\prune-runtime.ps1 -Apply" -ForegroundColor Green
    Write-Host ("预计删除后: {0:N2} GB" -f ($before - $total)) -ForegroundColor Green
    if (-not $IncludePip) {
        Write-Host "（默认保留 pip/setuptools，做分发副本时可加 -IncludePip 一并删除）" -ForegroundColor DarkGray
    }
    return
}

Write-Host "`n正在删除 ..." -ForegroundColor Yellow
$failed = 0
foreach ($name in $targets.Keys) {
    foreach ($it in $targets[$name]) {
        try {
            Remove-Item $it.FullName -Recurse -Force -ErrorAction Stop
        } catch {
            # 单个删不掉不该中断整轮（可能被别的进程占着）。
            $failed++
            Write-Host "  跳过（删除失败）: $($it.FullName)" -ForegroundColor DarkYellow
        }
    }
}

$after = (Get-ChildItem $VenvPath -Recurse -File -ErrorAction SilentlyContinue |
          Measure-Object Length -Sum).Sum / 1GB
Write-Host ("`n完成: {0:N2} GB -> {1:N2} GB (释放 {2:N2} GB)" -f $before, $after, ($before - $after)) -ForegroundColor Green
if ($failed -gt 0) { Write-Host "有 $failed 项删除失败（可能被占用），可关掉相关进程后重跑" -ForegroundColor DarkYellow }
Write-Host "`n务必立刻验证仍能推理：" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe backend\smoke.py" -ForegroundColor Cyan
