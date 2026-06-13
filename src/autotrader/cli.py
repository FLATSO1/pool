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

    sub.add_parser("backtest", help="過去データで戦略を検証")

    p_run = sub.add_parser("run", help="評価して発注（1サイクル）")
    p_run.add_argument(
        "--dry-run", action="store_true", help="発注せず判断のみ表示"
    )

    sub.add_parser("account", help="ペーパー口座状態を表示")

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)

    if args.command == "screen":
        return _cmd_screen(cfg)
    if args.command == "analyze":
        return _cmd_analyze(cfg, args.ticker)
    if args.command == "backtest":
        return _cmd_backtest(cfg)
    if args.command == "run":
        return _cmd_run(cfg, dry_run=args.dry_run)
    if args.command == "account":
        return _cmd_account(cfg)
    return 1


# --- サブコマンド実装 ----------------------------------------------------

def _cmd_screen(cfg: Config) -> int:
    from .analysis.fundamental import score_fundamentals
    from .data.fundamentals import fetch_fundamentals

    if not cfg.universe:
        print("ユニバースが空です。config.yaml の universe を設定してください。")
        return 1

    print(f"ファンダメンタル選定（{len(cfg.universe)}銘柄）...\n")
    rows = []
    for t in cfg.universe:
        f = fetch_fundamentals(t)
        s = score_fundamentals(f, cfg.fundamental)
        rows.append(s)

    rows.sort(key=lambda r: r.score, reverse=True)
    print(f"{'銘柄':<10}{'スコア':>8}{'判定':>8}  根拠")
    print("-" * 70)
    for r in rows:
        mark = "通過" if r.passed else "除外"
        print(f"{r.ticker:<10}{r.score:>8.2f}{mark:>8}  {', '.join(r.reasons)}")
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


def _cmd_backtest(cfg: Config) -> int:
    from .analysis.fundamental import score_fundamentals
    from .backtest.backtester import Backtester
    from .data.fundamentals import fetch_fundamentals
    from .data.market_data import fetch_ohlcv

    if not cfg.universe:
        print("ユニバースが空です。")
        return 1

    print(
        f"バックテスト {cfg.backtest.start} 〜 {cfg.backtest.end} "
        f"（{len(cfg.universe)}銘柄）...\n"
    )
    ohlcv: dict = {}
    passed: set[str] = set()
    for t in cfg.universe:
        df = fetch_ohlcv(t, start=cfg.backtest.start, end=cfg.backtest.end)
        if not df.empty:
            ohlcv[t] = df
        # 現時点のファンダで足切り（簡易: 静的適用）
        if score_fundamentals(fetch_fundamentals(t), cfg.fundamental).passed:
            passed.add(t)

    if not ohlcv:
        print("価格データを取得できませんでした。")
        return 1

    result = Backtester(cfg).run(ohlcv, passed_tickers=passed or None)
    print(result.summary())
    return 0


def _cmd_run(cfg: Config, dry_run: bool) -> int:
    from .broker.paper import PaperBroker
    from .data.fundamentals import fetch_fundamentals
    from .data.market_data import fetch_ohlcv, latest_price
    from .data.news import fetch_headlines
    from .portfolio import can_open_new, check_risk_exits
    from .strategy.engine import StrategyEngine

    live = cfg.live_enabled()
    if cfg.trading.mode == "live" and not live:
        print(
            "⚠️ trading.mode=live ですが、環境変数 AUTOTRADER_ENABLE_LIVE が "
            "true ではありません。安全のためペーパーで実行します。"
        )

    broker = _build_broker(cfg, live)
    label = "ライブ" if live else "ペーパー"
    print(f"=== 売買サイクル開始（{label}{' / DRY-RUN' if dry_run else ''}）===\n")

    # 価格を集める
    ohlcv_map: dict = {}
    prices: dict[str, float] = {}
    for t in cfg.universe:
        df = fetch_ohlcv(t, period="1y")
        if df.empty:
            continue
        ohlcv_map[t] = df
        px = latest_price(df)
        if px is not None:
            prices[t] = px

    # 1) リスク決済
    exits = check_risk_exits(broker.positions(), prices, cfg.trading)
    for ex in exits:
        print(
            f"[決済] {ex.ticker} {ex.quantity}株 理由={ex.reason} "
            f"損益={ex.pnl_pct * 100:+.1f}%"
        )
        if not dry_run:
            _submit(broker, ex.ticker, "SELL", ex.quantity, prices.get(ex.ticker))

    # 2) 新規/継続評価
    engine = StrategyEngine(cfg)
    equity = broker.snapshot().equity(prices)
    for t in ohlcv_map:
        headlines = (
            fetch_headlines(
                t, cfg.sentiment.lookback_days, cfg.sentiment.max_headlines
            )
            if cfg.sentiment.enabled
            else []
        )
        decision = engine.evaluate(
            t, ohlcv_map[t], fetch_fundamentals(t), headlines, equity
        )
        if decision.action == "HOLD":
            continue
        if decision.action == "BUY" and not can_open_new(broker.positions(), cfg.trading):
            print(f"[スキップ] {t} 買いシグナルだが保有上限に到達")
            continue

        print(
            f"[{decision.action}] {t} スコア={decision.combined_score:+.2f} "
            f"数量={decision.quantity} 価格={decision.price}"
        )
        if not dry_run:
            qty = decision.quantity if decision.action == "BUY" else _held_qty(
                broker, t
            )
            if qty > 0:
                _submit(broker, t, decision.action, qty, decision.price)

    print("\n=== サイクル完了 ===")
    _print_account(broker, prices)
    return 0


def _cmd_account(cfg: Config) -> int:
    from .broker.paper import PaperBroker

    broker = PaperBroker(cash=cfg.trading.cash)
    _print_account(broker, {})
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


def _submit(broker, ticker: str, side: str, qty: int, price: float | None) -> None:
    from .broker.base import Order, Side

    result = broker.submit(
        Order(ticker=ticker, side=Side(side), quantity=qty, limit_price=price)
    )
    status = "OK" if result.ok else "NG"
    print(f"    -> 発注{status}: {result.message}")


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
