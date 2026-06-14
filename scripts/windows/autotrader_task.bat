@echo off
REM ============================================================
REM autotrader を「取引日だけ」実行する Windows タスク用スクリプト
REM
REM 使い方（タスクスケジューラの「操作」に設定）:
REM   プログラム: C:\path\to\pool\scripts\windows\autotrader_task.bat
REM   引数:       run        （または report / propose など）
REM
REM 非取引日（土日・祝日・年末年始）は何もせず終了します。
REM ============================================================

setlocal

REM --- リポジトリのルートへ移動（このスクリプトは scripts\windows\ にある想定）---
cd /d "%~dp0..\.."

REM --- 仮想環境があれば有効化 ---
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

REM --- 実行するサブコマンド（未指定なら report）---
set CMD=%1
if "%CMD%"=="" set CMD=report

REM --- 取引日ゲート（非取引日ならスキップ）---
autotrader is-trading-day
if errorlevel 1 (
    echo [autotrader] 非取引日のためスキップします。
    endlocal
    exit /b 0
)

REM --- ログ付きで実行 ---
if not exist "logs" mkdir "logs"
echo [autotrader] %DATE% %TIME% : autotrader %CMD%
autotrader %CMD% >> "logs\autotrader.log" 2>&1

endlocal
exit /b %ERRORLEVEL%
