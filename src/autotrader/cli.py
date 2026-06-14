"""autotrader コマンドラインインターフェース。

サブコマンド:
  screen    ファンダメンタルでユニバースを選定
  analyze   1銘柄を解析（ファンダ+テクニカル+センチメント）
  backtest  過去データで戦略を検証
  run       ユニバースを評価し、ペーパー/ライブで発注（1サイクル）
  account   現在の口座状態を表示（ペーパー）
"""

from __future__ import annotations

import argparse
import sys

from .config import Config
from .logging_setup import get_logger, setup_logging

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(
        prog="autotrader", description="日本株 自動売買アプリ"
    )
    parser.add_argument("-c", "--config", help="設定ファイル(YAML)のパス")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("screen", help="ファンダメンタルで銘柄選定")

    p_an = sub.add_parser("analyze", help="1銘柄を解析")
    p_an.add_argument("ticker", help='例: "7203.T"')

    p_bt = sub.add_parser("backtest", help="過去データで戦略を検証")
    p_bt.add_argument("--start", help="開始日 YYYY-MM-DD（config上書き）")
    p_bt.add_argument("--end", help="終了日 YYYY-MM-DD（config上書き）")
    sub.add_parser(
        "eval-signals", help="シグナル別にバックテストし有効性を比較"
    )

    p_run = sub.add_parser("run", help="評価して発注（1サイクル）")
    p_run.add_argument(
        "--dry-run", action="store_true", help="発注せず判断のみ表示"
    )

    sub.add_parser(
        "propose", help="売買候補を根拠つきで提示（Claudeレビュー＋地合い）。発注はしない"
    )
    p_exec = sub.add_parser(
        "execute", help="propose の提案を承認して発注"
    )
    p_exec.add_argument("--yes", action="store_true", help="全提案を確認なしで発注")
    p_exec.add_argument(
        "--only", help="この銘柄だけ対象（カンマ区切り。例: 7203.T,6758.T）"
    )

    sub.add_parser("account", help="ペーパー口座状態を表示")
    sub.add_parser("report", help="ポートフォリオ状況を通知（スケジュール実行向け）")
    sub.add_parser(
        "is-trading-day", help="東証の取引日か判定（取引日=終了コード0/非取引日=1）"
    )

    p_kc = sub.add_parser(
        "kabus-check", help="kabuステーションAPIへの接続を確認（発注しない）"
    )
    p_kc.add_argument(
        "ticker", nargs="?", help='現在値を取得する銘柄（省略時はユニバース先頭）'
    )

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)

    if args.command == "screen":
        return _cmd_screen(cfg)
    if args.command == "analyze":
        return _cmd_analyze(cfg, args.ticker)
    if args.command == "backtest":
        if getattr(args, "start", None):
            cfg.backtest.start = args.start
        if getattr(args, "end", None):
            cfg.backtest.end = args.end
        return _cmd_backtest(cfg)
    if args.command == "eval-signals":
        return _cmd_eval_signals(cfg)
    if args.command == "run":
        return _cmd_run(cfg, dry_run=args.dry_run)
    if args.command == "propose":
        return _cmd_propose(cfg)
    if args.command == "execute":
        only = (
            {t.strip() for t in args.only.split(",")} if args.only else None
        )
        return _cmd_execute(cfg, approve_all=args.yes, only=only)
    if args.command == "account":
        return _cmd_account(cfg)
    if args.command == "report":
        return _cmd_report(cfg)
    if args.command == "is-trading-day":
        return _cmd_is_trading_day()
    if args.command == "kabus-check":
        return _cmd_kabus_check(cfg, args.ticker)
    return 1


# --- サブコマンド実装 ----------------------------------------------------

def _cmd_screen(cfg: Config) -> int:
    from .analysis.fundamental import score_fundamentals
    from .data.fundamentals import fetch_fundamentals
    from .data.universe import load_universe

    universe = load_universe(cfg)
    if not universe:
        print(
            "ユニバースが空です。config.yaml の universe か universe_file を設定してください。"
        )
        return 1

    print(f"ファンダメンタル選定（{len(universe)}銘柄をスキャン）...\n")
    rows = []
    for t in universe:
        f = fetch_fundamentals(t)
        s = score_fundamentals(f, cfg.fundamental)
        rows.append(s)

    rows.sort(key=lambda r: r.score, reverse=True)
    print(f"{'銘柄':<10}{'スコア':>8}{'判定':>8}  根拠")
    print("-" * 70)
    for r in rows:
        mark = "通過" if r.passed else "除外"
        print(f"{r.ticker:<10}{r.score:>8.2f}{mark:>8}  {', '.join(r.reasons)}")

    passed = [r for r in rows if r.passed]
    print("-" * 70)
    print(f"通過: {len(passed)} / {len(rows)} 銘柄")
    if passed:
        top = ", ".join(r.ticker for r in passed[:10])
        print(f"上位通過銘柄: {top}")
    return 0


def _cmd_analyze(cfg: Config, ticker: str) -> int:
    from .data.fundamentals import fetch_fundamentals
    from .data.market_data import fetch_ohlcv
    from .data.news import fetch_headlines
    from .strategy.engine import StrategyEngine

    print(f"=== {ticker} の解析 ===\n")
    ohlcv = fetch_ohlcv(ticker, period="1y")
    if ohlcv.empty:
        print("株価データを取得できませんでした。")
        return 1

    fundamentals = fetch_fundamentals(ticker)
    headlines = (
        fetch_headlines(
            ticker, cfg.sentiment.lookback_days, cfg.sentiment.max_headlines
        )
        if cfg.sentiment.enabled
        else []
    )

    engine = StrategyEngine(cfg)
    decision = engine.evaluate(
        ticker, ohlcv, fundamentals, headlines, equity=cfg.trading.cash
    )
    _print_decision(decision)
    return 0


def _load_backtest_data(cfg: Config):
    """バックテスト用の価格データとファンダ通過銘柄を集める。"""
    from .analysis.fundamental import score_fundamentals
    from .data.fundamentals import fetch_fundamentals
    from .data.market_data import fetch_ohlcv
    from .data.universe import load_universe

    universe = load_universe(cfg)
    ohlcv: dict = {}
    passed: set[str] = set()
    for t in universe:
        df = fetch_ohlcv(t, start=cfg.backtest.start, end=cfg.backtest.end)
        if not df.empty:
            ohlcv[t] = df
        if score_fundamentals(fetch_fundamentals(t), cfg.fundamental).passed:
            passed.add(t)
    return universe, ohlcv, passed


def _cmd_backtest(cfg: Config) -> int:
    from .backtest.backtester import Backtester

    universe, ohlcv, passed = _load_backtest_data(cfg)
    if not universe:
        print("ユニバースが空です。")
        return 1
    print(
        f"バックテスト {cfg.backtest.start} 〜 {cfg.backtest.end} "
        f"（{len(universe)}銘柄）...\n"
    )
    if not ohlcv:
        print("価格データを取得できませんでした。")
        return 1

    result = Backtester(cfg).run(ohlcv, passed_tickers=passed or None)
    print(result.summary())
    return 0


def _cmd_eval_signals(cfg: Config) -> int:
    from .backtest.signal_eval import evaluate_signals

    universe, ohlcv, passed = _load_backtest_data(cfg)
    if not universe:
        print("ユニバースが空です。")
        return 1
    if not ohlcv:
        print("価格データを取得できませんでした。")
        return 1

    print(
        f"シグナル別バックテスト {cfg.backtest.start} 〜 {cfg.backtest.end} "
        f"（{len(ohlcv)}銘柄）...\n"
    )
    evals = evaluate_signals(cfg, ohlcv, passed_tickers=passed or None)

    # ALL以外をリターン降順で並べ、ALLは先頭に固定
    baseline = [e for e in evals if e.name.startswith("ALL")]
    singles = sorted(
        [e for e in evals if not e.name.startswith("ALL")],
        key=lambda e: e.total_return,
        reverse=True,
    )
    ordered = baseline + singles

    print(f"{'シグナル':<18}{'リターン':>10}{'最大DD':>10}{'ｼｬｰﾌﾟ':>8}{'勝率':>7}{'回数':>6}")
    print("-" * 64)
    for e in ordered:
        r = e.result
        print(
            f"{e.name:<18}{r.total_return * 100:>9.1f}%"
            f"{r.max_drawdown() * 100:>9.1f}%{r.sharpe():>8.2f}"
            f"{e.win_rate() * 100:>6.0f}%{e.n_trades:>6}"
        )
    print("-" * 64)
    print("※ リターン上位＝単独で効いたシグナル。config.yaml の technical.weights で")
    print("  効くシグナルを重く、効かないものを軽く（0で無効化）して再検証できます。")
    return 0


def _cmd_run(cfg: Config, dry_run: bool) -> int:
    from .data.fundamentals import fetch_fundamentals
    from .data.market_data import fetch_ohlcv, latest_price
    from .data.news import fetch_headlines
    from .data.universe import load_universe
    from .notify import build_notifier
    from .portfolio import can_open_new, check_risk_exits, update_peaks
    from .safety import SafetyGuard
    from .strategy.engine import StrategyEngine

    live = cfg.live_enabled()
    if cfg.trading.mode == "live" and not live:
        print(
            "⚠️ trading.mode=live ですが、環境変数 AUTOTRADER_ENABLE_LIVE が "
            "true ではありません。安全のためペーパーで実行します。"
        )

    broker = _build_broker(cfg, live)
    notifier = build_notifier(cfg)
    guard = SafetyGuard(cfg.safety)
    label = "ライブ" if live else "ペーパー"
    print(f"=== 売買サイクル開始（{label}{' / DRY-RUN' if dry_run else ''}）===\n")

    def notify(text: str) -> None:
        print(text)
        if not dry_run:
            notifier.send(text)

    # 価格を集める
    ohlcv_map: dict = {}
    prices: dict[str, float] = {}
    for t in load_universe(cfg):
        df = fetch_ohlcv(t, period="1y")
        if df.empty:
            continue
        ohlcv_map[t] = df
        px = latest_price(df)
        if px is not None:
            prices[t] = px

    equity = broker.snapshot().equity(prices)
    guard.begin_day(equity)
    actions: list[str] = []

    # トレイリングストップ用の高値を読み込み・更新
    peaks = _load_peaks()
    peaks = update_peaks(peaks, broker.positions(), prices)

    # 1) リスク決済（安全ガードに関係なく常に実行）
    for ex in check_risk_exits(broker.positions(), prices, cfg.trading, peaks):
        msg = (
            f"💰決済 {ex.ticker} {ex.quantity}株 "
            f"理由={ex.reason} 損益={ex.pnl_pct * 100:+.1f}%"
        )
        notify(msg)
        if not dry_run:
            r = _submit(broker, ex.ticker, "SELL", ex.quantity, prices.get(ex.ticker))
            if r:
                guard.record_trade(is_new_position=False)
        actions.append(msg)

    # 2) 新規/継続評価
    blocked, reason = guard.new_buy_blocked(equity)
    if blocked:
        notify(f"⛔ 新規買い停止: {reason}")

    engine = StrategyEngine(cfg)
    for t in ohlcv_map:
        headlines = (
            fetch_headlines(t, cfg.sentiment.lookback_days, cfg.sentiment.max_headlines)
            if cfg.sentiment.enabled
            else []
        )
        decision = engine.evaluate(
            t, ohlcv_map[t], fetch_fundamentals(t), headlines, equity
        )
        if decision.action == "HOLD":
            continue

        if decision.action == "BUY":
            if blocked:
                continue
            if not can_open_new(broker.positions(), cfg.trading):
                print(f"[スキップ] {t} 買いシグナルだが保有上限に到達")
                continue
            # 1サイクル内でも上限を再チェック
            again, why = guard.new_buy_blocked(equity)
            if again:
                notify(f"⛔ 新規買い停止: {why}")
                blocked = True
                continue
            msg = (
                f"🟢買い {t} {decision.quantity}株 @ {decision.price} "
                f"スコア{decision.combined_score:+.2f}"
            )
            notify(msg)
            if not dry_run and decision.quantity > 0:
                if _submit(broker, t, "BUY", decision.quantity, decision.price):
                    guard.record_trade(is_new_position=True)
            actions.append(msg)
        else:  # SELL
            qty = _held_qty(broker, t)
            if qty <= 0:
                continue
            msg = f"🔴売り {t} {qty}株 @ {decision.price} スコア{decision.combined_score:+.2f}"
            notify(msg)
            if not dry_run:
                if _submit(broker, t, "SELL", qty, decision.price):
                    guard.record_trade(is_new_position=False)
            actions.append(msg)

    # トレイリングストップ用の高値を保存（売却済みは除去）
    if not dry_run:
        _save_peaks(update_peaks(peaks, broker.positions(), prices))

    print("\n=== サイクル完了 ===")
    _print_account(broker, prices)

    # サイクルにアクションがあればサマリ通知（無風の日は通知しない）
    if actions and not dry_run:
        final_equity = broker.snapshot().equity(prices)
        day_pnl = final_equity - guard.state.start_equity
        summary = (
            f"📊 {label}サイクル完了: {len(actions)}件\n"
            + "\n".join(actions)
            + f"\n評価額 {final_equity:,.0f}円 / 当日損益 {day_pnl:+,.0f}円 "
            + f"(取引{guard.state.trades}件)"
        )
        notifier.send(summary)
    return 0


def _cmd_report(cfg: Config) -> int:
    """現在のポートフォリオ状態を通知（場の開始/引け後のスケジュール実行向け）。"""
    from .data.market_data import fetch_ohlcv, latest_price
    from .data.universe import load_universe
    from .notify import build_notifier

    broker = _build_broker(cfg, cfg.live_enabled())
    notifier = build_notifier(cfg)
    snap = broker.snapshot()

    prices: dict[str, float] = {}
    for t in list(snap.positions):
        df = fetch_ohlcv(t, period="5d")
        px = latest_price(df)
        if px is not None:
            prices[t] = px

    lines = [f"📊 ポートフォリオ状況", f"現金: {snap.cash:,.0f}円"]
    if snap.positions:
        for t, pos in snap.positions.items():
            px = prices.get(t)
            pnl = f"{pos.unrealized_pnl(px):+,.0f}円" if px else "—"
            lines.append(f"  {t}: {pos.quantity}株 @ {pos.avg_price:,.0f} (含み {pnl})")
        lines.append(f"評価額合計: {snap.equity(prices):,.0f}円")
    else:
        lines.append("保有銘柄: なし")

    text = "\n".join(lines)
    print(text)
    notifier.send(text)
    return 0


def _cmd_propose(cfg: Config) -> int:
    """売買候補を根拠つきで提示し、proposals.json に保存（発注はしない）。"""
    from .analysis.advisor import review_candidate
    from .analysis.market_regime import assess_market
    from .data.fundamentals import fetch_fundamentals
    from .data.market_data import fetch_ohlcv, latest_price
    from .data.news import fetch_headlines
    from .data.universe import load_universe
    from .portfolio import can_open_new, check_risk_exits
    from .strategy.engine import StrategyEngine
    from .strategy.proposal import Proposal, save_proposals

    live = cfg.live_enabled()
    broker = _build_broker(cfg, live)
    api_key = cfg.secrets.anthropic_api_key

    # 地合い判定（Claude）
    regime = assess_market(cfg.advisor, api_key)
    print("=== 売買提案 ===")
    print(
        f"地合い: {regime.regime} (bias {regime.bias:+.2f}) — {regime.summary}\n"
    )
    block_buys = (
        cfg.advisor.enabled
        and cfg.advisor.regime_enabled
        and cfg.advisor.risk_off_block_buys
        and regime.blocks_new_buys()
    )
    if block_buys:
        print("⚠️ 地合いが risk_off のため、新規買いは見送り（売り/決済のみ提示）\n")

    # 価格収集
    ohlcv_map: dict = {}
    prices: dict[str, float] = {}
    for t in load_universe(cfg):
        df = fetch_ohlcv(t, period="1y")
        if df.empty:
            continue
        ohlcv_map[t] = df
        px = latest_price(df)
        if px is not None:
            prices[t] = px

    proposals: list[Proposal] = []

    # 1) リスク決済（損切り/利確）
    for ex in check_risk_exits(broker.positions(), prices, cfg.trading):
        proposals.append(
            Proposal(
                ticker=ex.ticker, action="SELL", quantity=ex.quantity,
                price=prices.get(ex.ticker), combined_score=0.0,
                reason=f"{ex.reason}（損益 {ex.pnl_pct * 100:+.1f}%）",
            )
        )

    # 2) シグナル評価
    engine = StrategyEngine(cfg)
    equity = broker.snapshot().equity(prices)
    for t, df in ohlcv_map.items():
        headlines = (
            fetch_headlines(t, cfg.sentiment.lookback_days, cfg.sentiment.max_headlines)
            if cfg.sentiment.enabled
            else []
        )
        d = engine.evaluate(t, df, fetch_fundamentals(t), headlines, equity)
        if d.action == "HOLD":
            continue
        if d.action == "BUY":
            if block_buys or not can_open_new(broker.positions(), cfg.trading):
                continue
            opinion = review_candidate(
                t, d.action, d.combined_score,
                d.fundamental.reasons if d.fundamental else [],
                d.technical.reasons if d.technical else [],
                d.sentiment.summary if d.sentiment else "",
                headlines, cfg.advisor, api_key,
            )
            proposals.append(
                Proposal(
                    ticker=t, action="BUY", quantity=d.quantity, price=d.price,
                    combined_score=d.combined_score,
                    fundamental_reasons=d.fundamental.reasons if d.fundamental else [],
                    technical_reasons=d.technical.reasons if d.technical else [],
                    sentiment_summary=d.sentiment.summary if d.sentiment else "",
                    advisor=opinion.to_dict(),
                )
            )
        else:  # SELL（シグナル）
            held = _held_qty(broker, t)
            if held > 0:
                proposals.append(
                    Proposal(
                        ticker=t, action="SELL", quantity=held,
                        price=d.price, combined_score=d.combined_score,
                        reason="売りシグナル",
                        technical_reasons=d.technical.reasons if d.technical else [],
                    )
                )

    if not proposals:
        print("提案なし（条件を満たす売買候補がありませんでした）。")
        return 0

    for p in proposals:
        _print_proposal(p)

    path = save_proposals(proposals, cfg.trading.mode, regime.to_dict())
    print(f"\n提案を保存しました: {path}")
    print("内容を確認のうえ、`autotrader execute` で承認・発注してください。")
    return 0


def _cmd_execute(cfg: Config, approve_all: bool, only: set | None) -> int:
    """propose の提案を読み込み、承認した分だけ発注する。"""
    from .strategy.proposal import load_proposals

    ps = load_proposals()
    if ps is None or not ps.proposals:
        print("提案がありません。先に `autotrader propose` を実行してください。")
        return 1

    live = cfg.live_enabled()
    broker = _build_broker(cfg, live)
    label = "ライブ" if live else "ペーパー"
    print(f"=== 提案の実行（{label}）===")
    print(f"提案作成: {ps.created_at}\n")

    executed = 0
    for p in ps.proposals:
        if only and p.ticker not in only:
            continue
        _print_proposal(p)
        if approve_all:
            approved = True
        else:
            try:
                ans = input(f"  → {p.ticker} {p.action} {p.quantity}株を発注？ [y/N]: ")
            except EOFError:
                ans = "n"
            approved = ans.strip().lower() in ("y", "yes")
        if approved:
            _submit(broker, p.ticker, p.action, p.quantity, p.price)
            executed += 1
        else:
            print("    → 見送り")

    print(f"\n発注した提案: {executed}件")
    return 0


def _cmd_account(cfg: Config) -> int:
    from .broker.paper import PaperBroker

    broker = PaperBroker(cash=cfg.trading.cash)
    _print_account(broker, {})
    return 0


def _cmd_is_trading_day() -> int:
    """東証の取引日なら0、非取引日なら1を返す（スケジューラのゲート用）。"""
    import datetime as dt

    from .market_calendar import describe_non_trading, is_trading_day

    today = dt.date.today()
    if is_trading_day(today):
        print(f"{today} は取引日です")
        return 0
    print(f"{today} は非取引日（{describe_non_trading(today)}）")
    return 1


def _cmd_kabus_check(cfg: Config, ticker: str | None) -> int:
    """kabuステーションAPIへの接続を確認する（認証・現在値・余力。発注はしない）。"""
    import os

    from .broker.kabus import KabusBroker

    pw = cfg.secrets.kabus_api_password
    if not pw:
        print("✗ KABUS_API_PASSWORD が未設定です。.env を確認してください。")
        return 1

    print(f"kabuステーションAPI 接続チェック: {cfg.secrets.kabus_base_url}\n")
    broker = KabusBroker(
        api_password=pw,
        base_url=cfg.secrets.kabus_base_url,
        trade_password=os.getenv("KABUS_TRADE_PASSWORD"),
        exchange=cfg.trading.exchange,
    )

    # 1) 認証
    try:
        broker.connect()
        print("✓ 認証成功（トークン取得）")
    except Exception as exc:  # noqa: BLE001 - 接続診断のため広く捕捉
        print(f"✗ 認証失敗: {exc}")
        print("  → kabuステーションが起動中か、APIパスワードが正しいか確認してください。")
        return 1

    # 2) 現在値
    symbol = ticker or (cfg.universe[0] if cfg.universe else "7203.T")
    px = broker.quote(symbol)
    if px is not None:
        print(f"✓ 現在値取得: {symbol} = {px:,}円")
    else:
        print(f"△ 現在値を取得できませんでした: {symbol}（板情報の購読登録が必要な場合あり）")

    # 3) 余力・ポジション
    cash = broker.cash()
    print(f"✓ 買付余力: {cash:,.0f}円")
    positions = broker.positions()
    print(f"✓ 保有銘柄: {len(positions)}件")
    for t, pos in positions.items():
        print(f"    {t}: {pos.quantity}株 @ {pos.avg_price:,.0f}")

    # 取引パスワードの有無（発注に必須）
    if os.getenv("KABUS_TRADE_PASSWORD"):
        print("✓ 取引パスワード(KABUS_TRADE_PASSWORD): 設定済み")
    else:
        print("△ 取引パスワード(KABUS_TRADE_PASSWORD)が未設定です（発注時に必要）")

    print("\n接続チェック完了。発注は行っていません。")
    return 0


# --- ヘルパ --------------------------------------------------------------

def _build_broker(cfg: Config, live: bool):
    from .broker.paper import PaperBroker

    if live:
        from .broker.kabus import KabusBroker
        import os

        return KabusBroker(
            api_password=cfg.secrets.kabus_api_password or "",
            base_url=cfg.secrets.kabus_base_url,
            trade_password=os.getenv("KABUS_TRADE_PASSWORD"),
            exchange=cfg.trading.exchange,
        )
    return PaperBroker(cash=cfg.trading.cash)


_PEAKS_PATH = "data/state/peaks.json"


def _load_peaks() -> dict[str, float]:
    import json
    from pathlib import Path

    p = Path(_PEAKS_PATH)
    if not p.exists():
        return {}
    try:
        return {k: float(v) for k, v in json.loads(p.read_text("utf-8")).items()}
    except (ValueError, OSError):
        return {}


def _save_peaks(peaks: dict[str, float]) -> None:
    import json
    from pathlib import Path

    p = Path(_PEAKS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(peaks, ensure_ascii=False, indent=2), encoding="utf-8")


def _submit(broker, ticker: str, side: str, qty: int, price: float | None) -> bool:
    from .broker.base import Order, Side

    result = broker.submit(
        Order(ticker=ticker, side=Side(side), quantity=qty, limit_price=price)
    )
    status = "OK" if result.ok else "NG"
    print(f"    -> 発注{status}: {result.message}")
    return result.ok


def _held_qty(broker, ticker: str) -> int:
    pos = broker.positions().get(ticker)
    return pos.quantity if pos else 0


def _print_decision(d) -> None:
    print(f"アクション: {d.action}")
    print(f"総合スコア: {d.combined_score:+.2f}")
    print(f"参考価格: {d.price}")
    if d.action == "BUY":
        print(f"推奨株数: {d.quantity}")
    print("\n--- 内訳 ---")
    for r in d.reasons:
        print(f"  • {r}")
    if d.technical and d.technical.reasons:
        print("\n--- テクニカル根拠 ---")
        for r in d.technical.reasons:
            print(f"  • {r}")
    if d.sentiment:
        print(f"\n--- センチメント要約 ---\n  {d.sentiment.summary}")


def _print_proposal(p) -> None:
    mark = "🟢買い" if p.action == "BUY" else "🔴売り"
    price = f"{p.price:,.0f}円" if p.price else "—"
    print(f"\n[{mark}] {p.ticker}  {p.quantity}株  参考{price}  スコア{p.combined_score:+.2f}")
    if p.reason:
        print(f"  理由: {p.reason}")
    if p.fundamental_reasons:
        print(f"  ファンダ: {', '.join(p.fundamental_reasons)}")
    if p.technical_reasons:
        print(f"  テクニカル: {', '.join(p.technical_reasons[:5])}")
    if p.sentiment_summary:
        print(f"  ニュース: {p.sentiment_summary}")
    if p.advisor:
        a = p.advisor
        rec = {"go": "実行推奨", "caution": "注意", "skip": "見送り推奨"}.get(
            a.get("recommendation", ""), a.get("recommendation", "")
        )
        print(
            f"  🤖アドバイザー: {rec}（確信度 {a.get('confidence', 0) * 100:.0f}% / "
            f"{a.get('source', '')}）"
        )
        if a.get("rationale"):
            print(f"     {a['rationale']}")
        for risk in a.get("risks", [])[:3]:
            print(f"     ⚠ {risk}")


def _print_account(broker, prices: dict[str, float]) -> None:
    snap = broker.snapshot()
    print(f"\n現金: {snap.cash:,.0f}円")
    if snap.positions:
        print("保有銘柄:")
        for t, pos in snap.positions.items():
            px = prices.get(t)
            pnl = f"{pos.unrealized_pnl(px):+,.0f}円" if px else "—"
            print(f"  {t}: {pos.quantity}株 @ {pos.avg_price:,.0f} (含み損益 {pnl})")
    else:
        print("保有銘柄: なし")
    if prices:
        print(f"評価額合計: {snap.equity(prices):,.0f}円")


if __name__ == "__main__":
    sys.exit(main())
