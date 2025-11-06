"""Command-line tool to monitor Polymarket markets and display a live order book.

The script queries Polymarket's public HTTP API to fetch information about a
market, prints the current probability (price) for the selected outcome, and
refreshes the order book in real time.

Usage example
-------------
$ python polymarket_monitor.py --slug will-trump-win-2024 --outcome yes

"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

API_BASE = "https://clob.polymarket.com"
MARKETS_ENDPOINT = f"{API_BASE}/markets"
MARKET_SEARCH_ENDPOINT = f"{MARKETS_ENDPOINT}/search"
ORDERBOOK_ENDPOINT_TEMPLATE = f"{MARKETS_ENDPOINT}/{{market_id}}/orderbook"
DEFAULT_LIMIT = 30
USER_AGENT = "polymarket-monitor/1.0"


class PolymarketAPIError(RuntimeError):
    """Raised when the Polymarket API returns an error."""


def _http_get(url: str, **params: Any) -> Any:
    """Perform a GET request and return the decoded JSON body."""

    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise PolymarketAPIError(
                    f"Polymarket 接口返回错误 {response.status}: {response.reason}"
                )
            data = response.read()
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore")
        raise PolymarketAPIError(
            f"Polymarket 接口返回错误 {exc.code}: {message.strip()}"
        ) from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network failure
        raise PolymarketAPIError(f"无法连接到 {url}: {exc}") from exc

    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise PolymarketAPIError("接口返回内容不是有效的 JSON") from exc


def _extract_markets(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return data["data"]
        if "data" in data and isinstance(data["data"], dict):
            inner = data["data"]
            if isinstance(inner.get("markets"), list):
                return inner["markets"]
        if isinstance(data.get("markets"), list):
            return data["markets"]
    raise PolymarketAPIError("无法解析市场列表数据")


def search_markets(query: str, active_only: bool = True, limit: int = 50) -> List[Dict[str, Any]]:
    """Search markets by keyword using the official search endpoint."""

    params: Dict[str, Any] = {"text": query, "limit": limit}
    if active_only:
        params["active"] = "true"

    data = _http_get(MARKET_SEARCH_ENDPOINT, **params)
    return _extract_markets(data)


def fetch_market_by_slug(slug: str) -> Dict[str, Any]:
    """Fetch a single market using its slug via official API endpoints."""

    possible_endpoints = [
        f"{MARKETS_ENDPOINT}/{urllib.parse.quote(slug)}",
        f"{MARKETS_ENDPOINT}/slug/{urllib.parse.quote(slug)}",
    ]

    for endpoint in possible_endpoints:
        try:
            data = _http_get(endpoint)
        except PolymarketAPIError:
            continue

        if isinstance(data, dict) and data.get("slug") == slug:
            return data
        if isinstance(data, dict) and data.get("data"):
            payload = data["data"]
            if isinstance(payload, dict) and payload.get("slug") == slug:
                return payload

        # Some endpoints may return a list with one element.
        try:
            markets = _extract_markets(data)
        except PolymarketAPIError:
            markets = []
        for market in markets:
            if market.get("slug") == slug:
                return market

    # Fall back to keyword search to catch renamed endpoints.
    markets = search_markets(slug, active_only=False, limit=10)
    for market in markets:
        if market.get("slug") == slug:
            return market

    raise PolymarketAPIError(f"找不到 slug 为 {slug!r} 的市场")


def find_market(
    slug: Optional[str],
    question: Optional[str],
) -> Dict[str, Any]:
    """Locate a market using official lookup endpoints."""

    if slug:
        return fetch_market_by_slug(slug)

    if not question:
        raise PolymarketAPIError("必须提供 slug 或关键词用于检索市场")

    markets = search_markets(question, active_only=True, limit=20)
    matches = [market for market in markets if question.lower() in (market.get("question", "").lower())]

    if not matches:
        raise PolymarketAPIError("根据关键词无法找到对应的市场，请尝试更精确的描述")

    if len(matches) == 1:
        return matches[0]

    formatted = "\n".join(
        f"- {item.get('question')} (slug: {item.get('slug')}, id: {item.get('market_id')})"
        for item in matches
    )
    raise PolymarketAPIError(
        "匹配到多个市场，请使用 --slug 或更具体的关键词:\n" + formatted
    )


def _normalize_outcome_name(name: str) -> str:
    return name.strip().lower()


def pick_outcome(market: Dict[str, Any], outcome_name: str) -> Dict[str, Any]:
    outcomes = market.get("outcomes") or []
    normalized = _normalize_outcome_name(outcome_name)

    for outcome in outcomes:
        if _normalize_outcome_name(outcome.get("name", "")) == normalized:
            return outcome
    raise PolymarketAPIError(
        f"在市场 {market.get('question')} 中找不到名为 {outcome_name!r} 的结果，"
        "可用结果包括: " + ", ".join(outcome.get("name", "?") for outcome in outcomes)
    )


def fetch_orderbook(
    market_id: str,
    token_id: Optional[str],
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": limit}
    if token_id:
        params["token_id"] = token_id
    endpoint = ORDERBOOK_ENDPOINT_TEMPLATE.format(market_id=market_id)
    return _http_get(endpoint, **params)


def format_price(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def summarize_orderbook(
    book: Dict[str, Any]
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    best_bid = format_price(bids[0]["price"]) if bids else None
    best_ask = format_price(asks[0]["price"]) if asks else None

    if best_bid is not None and best_ask is not None:
        midpoint = (best_bid + best_ask) / 2
    else:
        midpoint = None

    return best_bid, best_ask, midpoint


def clear_screen() -> None:
    if sys.stdout.isatty():
        os.system("cls" if os.name == "nt" else "clear")


def render_header(market: Dict[str, Any], outcome: Dict[str, Any]) -> str:
    lines = [
        market.get("question", "未知问题"),
        f"市场 ID: {market.get('market_id')}",
        f"结果: {outcome.get('name')} (token {outcome.get('token_id', 'N/A')})",
        "",
    ]
    return "\n".join(lines)


def render_orderbook(book: Dict[str, Any], depth: int = 10) -> str:
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    depth = min(depth, max(len(bids), len(asks)))
    lines = ["价格(买)/价格(卖)    数量(买)    |    价格(卖)    数量(卖)"]
    for i in range(depth):
        bid = bids[i] if i < len(bids) else {}
        ask = asks[i] if i < len(asks) else {}

        bid_price = bid.get("price")
        bid_size = bid.get("size") or bid.get("quantity")
        ask_price = ask.get("price")
        ask_size = ask.get("size") or ask.get("quantity")

        lines.append(
            f"{bid_price!s:>10} {bid_size!s:>10}    |    {ask_price!s:>10} {ask_size!s:>10}"
        )

    return "\n".join(lines)


def render_summary(
    best_bid: Optional[float],
    best_ask: Optional[float],
    midpoint: Optional[float],
) -> str:
    def format_value(value: Optional[float]) -> str:
        return f"{value:.4f}" if isinstance(value, float) else "--"

    return textwrap.dedent(
        f"""
        最优买价: {format_value(best_bid)}
        最优卖价: {format_value(best_ask)}
        中间价(概率): {format_value(midpoint)}
        更新时间: {dt.datetime.utcnow().isoformat()}Z
        """
    ).strip()


def monitor_market(
    slug: Optional[str],
    keyword: Optional[str],
    outcome_name: str,
    depth: int,
    interval: float,
) -> None:
    market = find_market(slug=slug, question=keyword)
    outcome = pick_outcome(market, outcome_name)
    market_id = market.get("market_id") or market.get("id")

    if not market_id:
        raise PolymarketAPIError("市场信息缺少 market_id")

    while True:
        book = fetch_orderbook(
            market_id,
            outcome.get("token_id"),
            limit=max(depth, DEFAULT_LIMIT),
        )
        best_bid, best_ask, midpoint = summarize_orderbook(book)

        clear_screen()
        print(render_header(market, outcome))
        print(render_summary(best_bid, best_ask, midpoint))
        print()
        print(render_orderbook(book, depth=depth))

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n用户中断，退出监控。")
            return


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="监控 Polymarket 事件概率与订单簿")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--slug", help="市场的 slug，例如 will-trump-win-2024")
    group.add_argument("--keyword", help="在问题文本中搜索的关键词")
    parser.add_argument("--outcome", default="yes", help="要监控的结果名称，例如 yes 或 no")
    parser.add_argument("--depth", type=int, default=10, help="显示订单簿深度")
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="刷新频率（秒）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        monitor_market(
            slug=args.slug,
            keyword=args.keyword,
            outcome_name=args.outcome,
            depth=args.depth,
            interval=args.interval,
        )
    except PolymarketAPIError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
