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


def _force_utf8_streams() -> None:
    """標準出力/標準エラーをUTF-8で出す。

    Windowsの既定コンソールはcp932のため、絵文字（🟢🔴💰等）を含む通知を
    print するとUnicodeEncodeErrorで落ち、日本語ログも文字化けする。
    UTF-8へ再構成し、万一エンコードできない文字があっても落ちないよう
    errors="replace" を付ける。reconfigure 非対応環境では何もしない。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
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

    p_rev = sub.add_parser(
        "review",
        help="Claude Codeレビュー用に候補を書き出す／記入済み意見を取り込む（API不要）",
    )
    p_rev.add_argument(
        "--apply", action="store_true",
        help="記入済み review.json を proposals.json に取り込む",
    )

    sub.add_parser("account", help="ペーパー口座状態を表示")
    sub.add_parser("report", help="ポートフォリオ状況を通知（スケジュール実行向け）")
    p_nt = sub.add_parser(
        "notify-test", help="通知チャネル（Discord/Telegram）へテスト送信して疎通確認"
    )
    p_nt.add_argument("message", nargs="?", help="送るテストメッセージ（省略時は既定文）")
    sub.add_parser(
        "is-trading-day", help="東証の取引日か判定（取引日=終了コード0/非取引日=1）"
    )

    p_kc = sub.add_parser(
        "kabus-check", help="kabuステーションAPIへの接続を確認（発注しない）"
    )
    p_kc.add_argument(
        "ticker", nargs="?", help='現在値を取得する銘柄（省略時はユニバース先頭）'
    )

    sub.add_parser("data", help="ローカルヒストリカルCSVの整備状況を表示")

    p_fd = sub.add_parser(
        "fetch-data", help="J-Quants APIから日足を取得しローカルCSVへ保存"
    )
    p_fd.add_argument("--from", dest="from_", help="取得開始日 YYYY-MM-DD")
    p_fd.add_argument("--to", dest="to", help="取得終了日 YYYY-MM-DD")
    p_fd.add_argument(
        "--force", action="store_true", help="既存CSVがあっても再取得する"
    )

    p_tw = sub.add_parser(
        "tune-weights", help="train/test分割で効くシグナルに重みを寄せる"
    )
    p_tw.add_argument("--split", help="train/test分割日 YYYY-MM-DD（省略時は7割地点）")
    p_tw.add_argument(
        "--fraction", type=float, default=0.7, help="分割日省略時のtrain比率（既定0.7）"
    )
    p_tw.add_argument(
        "--metric", default="excess", choices=["excess", "sharpe", "return"],
        help="最適化の目的（既定: excess=バイ&ホールド超過）",
    )

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    _configure_data_source(cfg)

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
    if args.command == "review":
        return _cmd_review(cfg, apply=args.apply)
    if args.command == "account":
        return _cmd_account(cfg)
    if args.command == "report":
        return _cmd_report(cfg)
    if args.command == "notify-test":
        return _cmd_notify_test(cfg, args.message)
    if args.command == "is-trading-day":
        return _cmd_is_trading_day()
    if args.command == "kabus-check":
        return _cmd_kabus_check(cfg, args.ticker)
    if args.command == "data":
        return _cmd_data(cfg)
    if args.command == "fetch-data":
        return _cmd_fetch_data(
            cfg, from_=args.from_, to=args.to, force=args.force
        )
    if args.command == "tune-weights":
        return _cmd_tune_weights(
            cfg, split=args.split, fraction=args.fraction, metric=args.metric
        )
    return 1


# --- サブコマンド実装 ----------------------------------------------------

def _configure_data_source(cfg: Config) -> None:
    """設定に応じてローカルCSVを株価ソースとして登録する。"""
    if cfg.data.source not in ("local", "auto"):
        return
    from .data.local_store import LocalStore
    from .data.market_data import configure_local_store

    store = LocalStore(
        cfg.data.local_dir,
        filename_template=cfg.data.filename_template,
        columns=cfg.data.columns,
        date_format=cfg.data.date_format,
    )
    configure_local_store(store, cfg.data.source)


def _cmd_tune_weights(
    cfg: Config, split: str | None, fraction: float, metric: str
) -> int:
    from .backtest.optimize import optimize_weights

    universe, ohlcv, passed = _load_backtest_data(cfg)
    if not ohlcv:
        print("価格データを取得できませんでした。data.source/期間/取得状況を確認してください。")
        return 1

    try:
        res = optimize_weights(
            cfg, ohlcv, passed_tickers=passed or None,
            split_date=split, fraction=fraction, metric=metric,
        )
    except ValueError as exc:
        print(f"チューニング不可: {exc}")
        return 1

    def _row(label: str, r) -> str:
        return (
            f"  {label:<16} リターン{r.total_return * 100:+7.2f}%  "
            f"超過{r.excess_return() * 100:+7.2f}%  "
            f"DD{r.max_drawdown() * 100:6.2f}%  "
            f"ｼｬｰﾌﾟ{r.sharpe():5.2f}  約定{len(r.trades)}"
        )

    print(f"=== 重みチューニング（metric={metric}）===")
    print(f"分割日: {res.split_date.date()}（未満=TRAIN / 以降=TEST・{len(ohlcv)}銘柄）\n")
    print("[TRAIN / in-sample]")
    print(_row("既定重み", res.train_baseline))
    print(_row("チューニング後", res.train_tuned))
    print("\n[TEST / out-of-sample] ← ここが本番の評価")
    print(_row("既定重み", res.test_baseline))
    print(_row("チューニング後", res.test_tuned))

    improved = res.test_tuned.excess_return() > res.test_baseline.excess_return()
    verdict = (
        "✅ アウトオブサンプルで既定重みを上回った → 採用候補"
        if improved
        else "⚠️ アウトオブサンプルで改善せず（過学習の疑い。採用は慎重に）"
    )
    print(f"\n{verdict}\n")
    print("--- config.yaml に貼れる提案重み ---")
    print(res.weights_yaml())
    return 0


def _cmd_fetch_data(
    cfg: Config, from_: str | None, to: str | None, force: bool
) -> int:
    from .data.jquants import JQuantsClient, JQuantsError
    from .data.local_store import LocalStore
    from .data.universe import load_universe

    s = cfg.secrets
    if not (s.jquants_refresh_token or (s.jquants_mailaddress and s.jquants_password)):
        print(
            "J-Quantsの認証情報が未設定です。.env に JQUANTS_REFRESH_TOKEN "
            "（または JQUANTS_MAILADDRESS / JQUANTS_PASSWORD）を設定してください。"
        )
        return 1

    client = JQuantsClient(
        refresh_token=s.jquants_refresh_token,
        mailaddress=s.jquants_mailaddress,
        password=s.jquants_password,
    )
    store = LocalStore(cfg.data.local_dir, filename_template=cfg.data.filename_template)
    universe = load_universe(cfg)
    print(f"=== J-Quantsから取得 → {cfg.data.local_dir} ({len(universe)}銘柄) ===")
    ok = skipped = failed = 0
    for t in universe:
        if not force and store.available(t):
            skipped += 1
            continue
        try:
            n = client.save_csv(t, cfg.data.local_dir, from_=from_, to=to)
            print(f"  ✅ {t}: {n}行")
            ok += 1
        except (JQuantsError, OSError) as exc:
            print(f"  ❌ {t}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001 - ネットワーク等は継続
            print(f"  ❌ {t}: {exc}")
            failed += 1
    print(f"\n取得{ok} / スキップ{skipped} / 失敗{failed}")
    return 0 if failed == 0 else 1


def _cmd_data(cfg: Config) -> int:
    from .data.local_store import LocalStore
    from .data.universe import load_universe

    store = LocalStore(
        cfg.data.local_dir,
        filename_template=cfg.data.filename_template,
        columns=cfg.data.columns,
        date_format=cfg.data.date_format,
    )
    universe = load_universe(cfg)
    print(f"=== ローカルデータ整備状況 ({cfg.data.local_dir}) ===")
    print(f"source={cfg.data.source} / 対象{len(universe)}銘柄\n")
    have = 0
    for t in universe:
        cov = store.coverage(t)
        if cov:
            have += 1
            rows, d0, d1 = cov
            print(f"  ✅ {t}: {rows}行 {d0}〜{d1}")
        else:
            print(f"  ❌ {t}: データなし")
    print(f"\n{have}/{len(universe)} 銘柄が利用可能")
    return 0

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
    from .portfolio import (
        can_open_new,
        check_risk_exits,
        update_peaks,
        within_leverage,
    )
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

    # ATRベース損切り用に、保有銘柄の直近ATRを用意
    atrs = _latest_atrs(broker.positions(), ohlcv_map, cfg)

    # 1) リスク決済（安全ガードに関係なく常に実行）
    for ex in check_risk_exits(broker.positions(), prices, cfg.trading, peaks, atrs):
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
            # レバレッジ上限（建玉合計 ≤ 余力×max_leverage）を超える買いは見送る
            new_cost = decision.quantity * (decision.price or 0.0)
            if not within_leverage(
                new_cost, broker.positions(), prices, equity, cfg.trading
            ):
                print(
                    f"[スキップ] {t} 買いシグナルだがレバレッジ上限"
                    f"（×{cfg.trading.max_leverage}）に到達"
                )
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


def _cmd_notify_test(cfg: Config, message: str | None) -> int:
    from datetime import datetime

    from .notify import ConsoleNotifier, build_notifier

    notifier = build_notifier(cfg)
    kind = type(notifier).__name__
    if isinstance(notifier, ConsoleNotifier):
        if not cfg.notify.enabled:
            print("⚠️ notify.enabled=false です。config.yaml で有効化してください。")
        else:
            print(
                f"⚠️ channel={cfg.notify.channel} の認証情報が未設定のため、"
                "コンソール出力にフォールバックしています。"
            )
            if cfg.notify.channel == "discord":
                print("   → .env の DISCORD_WEBHOOK_URL を確認してください。")
            elif cfg.notify.channel == "telegram":
                print("   → .env の TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID を確認してください。")

    text = message or (
        f"✅ autotrader 通知テスト（{datetime.now():%Y-%m-%d %H:%M}）— "
        "これが届けば連携OKです。"
    )
    ok = notifier.send(text)
    if ok and not isinstance(notifier, ConsoleNotifier):
        print(f"✅ {kind} へ送信しました。{cfg.notify.channel} を確認してください。")
        return 0
    if not ok:
        print(f"❌ {kind} 送信に失敗しました。URL/トークンとネットワークを確認してください。")
        return 1
    return 0


def _cmd_propose(cfg: Config) -> int:
    """売買候補を根拠つきで提示し、proposals.json に保存（発注はしない）。"""
    from .analysis.advisor import review_candidate
    from .analysis.market_regime import assess_market
    from .data.fundamentals import fetch_fundamentals
    from .data.market_data import fetch_ohlcv, latest_price
    from .analysis.correlation import too_correlated
    from .data.news import fetch_headlines
    from .data.universe import load_universe
    from .portfolio import can_open_new, check_risk_exits, within_leverage
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
            # レバレッジ上限（建玉合計 ≤ 余力×max_leverage）を超える買いは見送る
            new_cost = d.quantity * (d.price or 0.0)
            if not within_leverage(
                new_cost, broker.positions(), prices, equity, cfg.trading
            ):
                print(
                    f"[見送り] {t} レバレッジ上限（×{cfg.trading.max_leverage}）に到達"
                )
                continue
            # 相関分散: 既保有とよく似た値動きの銘柄は見送る
            if cfg.trading.max_correlation > 0:
                held_closes = {
                    p: ohlcv_map[p]["close"]
                    for p in broker.positions()
                    if p in ohlcv_map
                }
                skip, corr, who = too_correlated(
                    df["close"], held_closes,
                    cfg.trading.correlation_lookback, cfg.trading.max_correlation,
                )
                if skip:
                    print(f"[見送り] {t} 既保有 {who} と相関{corr:.2f}（高すぎ）")
                    continue
            # 発注直前の需給チェック（ライブ時のみ・板/1分足）
            pressure_str, buy_ratio = "", None
            if live and cfg.entry_filter.enabled:
                pressure_str, buy_ratio = _compute_entry_pressure(cfg, broker, t)
                if (
                    cfg.entry_filter.veto
                    and buy_ratio is not None
                    and buy_ratio < cfg.entry_filter.min_buy_ratio
                ):
                    print(f"[見送り] {t} 売り圧が強い（買い圧{buy_ratio:.0%}）")
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
                    entry_pressure=pressure_str,
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
        adv = p.advisor or {}
        # アドバイザーが skip と判断した買いは、設定により自動見送り。
        if (
            p.action == "BUY"
            and cfg.advisor.skip_blocks_buy
            and adv.get("recommendation") == "skip"
        ):
            print("    → 見送り（アドバイザーが skip と判断）")
            continue
        # Claude Code のレビュー未取り込み（pending）の買いは注意喚起。
        if p.action == "BUY" and adv.get("source") == "claude-code-pending":
            print(
                "    ⚠ 未レビュー（`autotrader review` でレビューを取り込めます）"
            )
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


def _cmd_review(cfg: Config, apply: bool) -> int:
    """Claude Codeレビューの書き出し／取り込み（API不要）。"""
    from .strategy.review import REVIEW_PATH, apply_review, export_review

    if apply:
        try:
            applied, warnings = apply_review()
        except FileNotFoundError as e:
            print(str(e))
            return 1
        for w in warnings:
            print(f"⚠ {w}")
        print(f"レビューを取り込みました: {applied}件")
        if applied:
            print("`autotrader execute` で承認・発注してください。")
        return 0

    try:
        path, n = export_review()
    except FileNotFoundError as e:
        print(str(e))
        return 1
    if n == 0:
        print("レビュー対象の買い候補がありません。")
        return 0
    print(f"レビュー候補 {n}件を書き出しました: {path}")
    print(
        "Claude Code に「このレビューを記入して」と頼むか、"
        f"{REVIEW_PATH} の各 opinion を埋めてください。"
    )
    print("記入後 `autotrader review --apply` で取り込みます。")
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

    print(f"kabuステーションAPI 接続チェック: {cfg.secrets.kabus_base_url}")
    if cfg.trading.trade_type == "margin":
        print(
            f"取引区分: 信用（{cfg.trading.margin_trade_type}） / "
            f"レバレッジ上限 ×{cfg.trading.max_leverage}\n"
        )
    else:
        print("取引区分: 現物\n")
    broker = KabusBroker(
        api_password=pw,
        base_url=cfg.secrets.kabus_base_url,
        trade_password=os.getenv("KABUS_TRADE_PASSWORD"),
        exchange=cfg.trading.exchange,
        trade_type=cfg.trading.trade_type,
        margin_trade_type=cfg.trading.margin_trade_type,
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
            trade_type=cfg.trading.trade_type,
            margin_trade_type=cfg.trading.margin_trade_type,
        )
    return PaperBroker(cash=cfg.trading.cash)


def _compute_entry_pressure(cfg: Config, broker, ticker: str):
    """発注直前の需給（板/1分足）を算出。(summary文字列, 総合買い圧比 or None) を返す。"""
    from .analysis.orderflow import board_imbalance, intraday_pressure
    from .data.market_data import fetch_ohlcv

    results = []
    if cfg.entry_filter.use_intraday:
        try:
            df1m = fetch_ohlcv(ticker, period="2d", interval="1m")
            r = intraday_pressure(df1m)
            if r:
                results.append(r)
        except Exception:  # noqa: BLE001 - データ取得失敗は無視
            pass
    if cfg.entry_filter.use_board and hasattr(broker, "board"):
        r = board_imbalance(broker.board(ticker))
        if r:
            results.append(r)

    if not results:
        return "", None
    ratio = sum(r.buy_ratio for r in results) / len(results)
    parts = [f"{r.source}:{r.buy_ratio:.0%}({r.label})" for r in results]
    return f"買い圧 {ratio:.0%} [{', '.join(parts)}]", ratio


def _latest_atrs(positions, ohlcv_map: dict, cfg: Config) -> dict[str, float]:
    """保有銘柄の直近ATRを返す（ATRベース損切り用）。"""
    from .analysis.technical import compute_indicators

    out: dict[str, float] = {}
    for t in positions:
        df = ohlcv_map.get(t)
        if df is None or df.empty:
            continue
        ind = compute_indicators(df, cfg.technical)
        if "atr" in ind.columns and len(ind):
            v = ind["atr"].iloc[-1]
            if v == v and v > 0:  # NaN除外
                out[t] = float(v)
    return out


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
    if getattr(p, "entry_pressure", ""):
        print(f"  📈板/需給: {p.entry_pressure}")
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
