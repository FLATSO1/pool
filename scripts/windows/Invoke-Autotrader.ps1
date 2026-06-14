<#
.SYNOPSIS
  autotrader を「取引日だけ」実行する PowerShell スクリプト（.bat の代替）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File Invoke-Autotrader.ps1 -Command run

.NOTES
  タスクスケジューラの「操作」:
    プログラム: powershell.exe
    引数: -ExecutionPolicy Bypass -File "C:\path\to\pool\scripts\windows\Invoke-Autotrader.ps1" -Command run
#>

param(
    [string]$Command = "report"
)

$ErrorActionPreference = "Stop"

# リポジトリのルートへ移動（このスクリプトは scripts\windows\ にある想定）
Set-Location -Path (Join-Path $PSScriptRoot "..\..")

# 仮想環境があれば有効化
$venv = ".venv\Scripts\Activate.ps1"
if (Test-Path $venv) { . $venv }

# 取引日ゲート
autotrader is-trading-day | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[autotrader] 非取引日のためスキップします。"
    exit 0
}

# ログ付きで実行
if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Path "logs" | Out-Null }
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "[autotrader] $stamp : autotrader $Command"
autotrader $Command *>> "logs\autotrader.log"
exit $LASTEXITCODE
