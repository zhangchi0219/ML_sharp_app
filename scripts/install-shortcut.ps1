#Requires -Version 5.1
<#
  install-shortcut.ps1 — 在桌面创建“SHARP 高斯泼溅”快捷方式（运行一次即可）。
    快捷方式直接指向 pythonw.exe desktop.py，全程无控制台窗口。
    前端产物缺失时 desktop.py 会自己弹窗提示，所以这里不需要经过 .bat 的前置检查。
#>
$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Pyw   = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
$Entry = Join-Path $RepoRoot 'desktop.py'
if (-not (Test-Path $Pyw))   { throw "未找到 venv，请先运行 scripts\setup.ps1" }
if (-not (Test-Path $Entry)) { throw "未找到入口：$Entry" }

$Desktop = [Environment]::GetFolderPath('Desktop')
$LnkPath = Join-Path $Desktop 'SHARP 高斯泼溅.lnk'

$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($LnkPath)
$lnk.TargetPath       = $Pyw
$lnk.Arguments        = "`"$Entry`""
$lnk.WorkingDirectory = $RepoRoot
$lnk.IconLocation     = "$env:SystemRoot\System32\shell32.dll,13"
$lnk.Description      = 'SHARP · 照片转高斯泼溅'
$lnk.Save()

Write-Host "已创建桌面快捷方式：$LnkPath" -ForegroundColor Green
Write-Host "双击即启动原生窗口；图标可在快捷方式属性里自行更换。" -ForegroundColor DarkGray
