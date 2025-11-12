#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket high-probability buyer.

- Query available USDC balance on the CLOB account and split it into ten slices.
- Scan active markets and fetch the latest CLOB prices for all outcomes.
- Identify up to ten options whose probability is between 97% and 99.7%.
- Submit taker buy orders for each qualified option using the per-slice amount.
"""
import os
import time
import json
import math
from datetime import datetime, timezone
from typing import Dict, Optional, List
import requests
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client.exceptions import PolyApiException, PolyException

load_dotenv()

BUILDER_KEY = os.getenv("BUILDER_KEY")
BALANCE_PRIVATE_KEY = (
    os.getenv("BALANCE_PRIVATE_KEY")
    or os.getenv("BALANCE_PK")
    or os.getenv("PRIVATE_KEY")
    or os.getenv("PK")
)
SIGNING_SERVER_URL = os.getenv("SIGNING_SERVER_URL")
RELAYER_URL = os.getenv("RELAYER_URL")
ACCOUNT_ADDRESS = os.getenv("ACCOUNT_ADDRESS")
NETWORK_ID = int(os.getenv("NETWORK_ID", "137"))

CLOB_HOST = os.getenv("CLOB_HOST", "https://clob.polymarket.com").rstrip("/")
ORDERBOOK_URL = f"{CLOB_HOST}/book"  # GET ?token_id=...
PRICES_URL = f"{CLOB_HOST}/prices"
DEFAULT_LIMIT_PRICE = float(os.getenv("DEFAULT_LIMIT_PRICE", "1.00"))  # aggressive taker
TARGET_OPTION_COUNT = int(os.getenv("TARGET_OPTION_COUNT", "10"))
MIN_PRICE_THRESHOLD = float(os.getenv("MIN_PRICE_THRESHOLD", "0.97"))
MAX_PRICE_THRESHOLD = float(os.getenv("MAX_PRICE_THRESHOLD", "0.997"))
MARKET_SCAN_LIMIT = int(os.getenv("MARKET_SCAN_LIMIT", "200"))
PRICE_BATCH_SIZE = int(os.getenv("PRICE_BATCH_SIZE", "50"))
USER_AGENT = "ResolutionSniper/0.1 (+https://example.com)"

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
API_PASSPHRASE = os.getenv("API_PASSPHRASE")
SIGNATURE_TYPE = int(os.getenv("SIGNATURE_TYPE", "2"))
POLYMARKET_PROXY_ADDRESS = os.getenv("POLYMARKET_PROXY_ADDRESS") or os.getenv("FUNDER_ADDRESS")

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

BALANCE_CLIENT: Optional[ClobClient] = None

class OrderbookSnapshot(Dict):
    pass

class SniperError(Exception):
    pass


def _normalize_private_key(raw_key: Optional[str]) -> str:
    if not raw_key:
        raise SniperError(
            "缺少 BALANCE_PRIVATE_KEY/PRIVATE_KEY/PK 环境变量，无法查询余额。"
        )
    key = raw_key.strip()
    if key.startswith("0x") or key.startswith("0X"):
        hex_part = key[2:]
    else:
        hex_part = key
    if len(hex_part) != 64:
        raise SniperError("提供的私钥长度不是 64 个十六进制字符。")
    try:
        int(hex_part, 16)
    except ValueError as exc:
        raise SniperError("提供的私钥包含非十六进制字符。") from exc
    return key if key.startswith("0x") else f"0x{hex_part}"


def _manual_balance_override() -> Optional[float]:
    raw = os.getenv("MANUAL_BALANCE_USDC") or os.getenv("BALANCE_USDC_OVERRIDE")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise SniperError("MANUAL_BALANCE_USDC 不是有效的数字。") from exc
    if value <= 0:
        raise SniperError("MANUAL_BALANCE_USDC 必须大于 0。")
    return value


def _ensure_balance_client() -> ClobClient:
    global BALANCE_CLIENT
    if BALANCE_CLIENT:
        return BALANCE_CLIENT
    private_key = _normalize_private_key(BALANCE_PRIVATE_KEY or BUILDER_KEY)
    client = ClobClient(
        host=CLOB_HOST,
        key=private_key,
        chain_id=NETWORK_ID,
        signature_type=SIGNATURE_TYPE,
        funder=POLYMARKET_PROXY_ADDRESS,
    )
    if API_KEY and API_SECRET and API_PASSPHRASE:
        client.set_api_creds(ApiCreds(API_KEY, API_SECRET, API_PASSPHRASE))
    else:
        client.set_api_creds(client.create_or_derive_api_creds())
    BALANCE_CLIENT = client
    return client


def _probe_numeric(section: Optional[object]) -> Optional[float]:
    if isinstance(section, dict):
        for key in ("available", "free", "balance", "amount", "value"):
            if key in section:
                candidate = _coerce_price(section.get(key))
                if candidate is not None:
                    return candidate
    return None


def _extract_available_balance(payload: object) -> float:
    if isinstance(payload, dict):
        for key in ("balance", "balances", "collateral", "data", "result"):
            parsed = _probe_numeric(payload.get(key))
            if parsed is not None:
                return parsed
        parsed = _probe_numeric(payload)
        if parsed is not None:
            return parsed
    raise SniperError(f"无法解析余额响应: {payload}")


def fetch_available_usdc_balance() -> float:
    client = _ensure_balance_client()
    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SIGNATURE_TYPE)
    try:
        response = client.get_balance_allowance(params)
    except PolyApiException as exc:
        override = _manual_balance_override()
        if override is not None:
            print(
                f"余额接口错误 ({exc.status_code}), 使用 MANUAL_BALANCE_USDC={override:.2f} 作为可用余额。"
            )
            return override
        if exc.status_code == 401:
            raise SniperError(
                "CLOB 余额接口鉴权失败，请设置 API_KEY/API_SECRET/API_PASSPHRASE，或设置 MANUAL_BALANCE_USDC 作为备选值。"
            ) from exc
        raise SniperError(f"CLOB 余额接口错误: {exc}") from exc
    except PolyException as exc:
        override = _manual_balance_override()
        if override is not None:
            print(
                f"余额接口返回错误 ({exc}), 使用 MANUAL_BALANCE_USDC={override:.2f} 作为可用余额。"
            )
            return override
        raise
    available = _extract_available_balance(response)
    if available is None or available <= 0:
        raise SniperError("USDC 可用余额不足")
    return available


def _safe_float(value: Optional[object], default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def chunked(items: List[str], size: int):
    """Yield lists of up to `size` elements while preserving order."""

    if size <= 0:
        size = 50
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _coerce_price(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_price_value(entry: object) -> Optional[float]:
    if isinstance(entry, dict):
        for key in ("BUY", "buy", "price", "ask", "ASK", "Price"):
            if key not in entry:
                continue
            nested = entry[key]
            if isinstance(nested, dict):
                nested = nested.get("price") or nested.get("value")
            price = _coerce_price(nested)
            if price is not None:
                return price
        return None
    return _coerce_price(entry)


def _parse_prices_payload(raw: object) -> Dict[str, float]:
    parsed: Dict[str, float] = {}
    if isinstance(raw, dict):
        for token_id, payload in raw.items():
            price = _extract_price_value(payload)
            if price is None:
                continue
            parsed[str(token_id)] = price
    elif isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            token_id = entry.get("token_id") or entry.get("tokenId") or entry.get("id")
            if not token_id:
                continue
            price = _extract_price_value(entry)
            if price is None:
                continue
            parsed[str(token_id)] = price
    else:
        raise SniperError("Unexpected /prices payload type")
    if not parsed:
        raise SniperError("Empty /prices response")
    return parsed


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.5),
    retry=retry_if_exception_type((requests.RequestException, SniperError)),
)
def fetch_prices_chunk(payload: List[Dict[str, str]]) -> Dict[str, float]:
    if not payload:
        return {}
    resp = session.post(PRICES_URL, json=payload, timeout=3)
    if resp.status_code == 429:
        raise SniperError("Rate limited by /prices endpoint")
    if resp.status_code != 200:
        raise SniperError(f"/prices failed {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return _parse_prices_payload(data)


def fetch_prices_for_tokens(token_ids: List[str]) -> Dict[str, float]:
    if not token_ids:
        return {}

    seen = set()
    deduped = []
    for token_id in token_ids:
        if not token_id:
            continue
        token_id_str = str(token_id)
        if token_id_str in seen:
            continue
        seen.add(token_id_str)
        deduped.append(token_id_str)

    prices: Dict[str, float] = {}
    for chunk in chunked(deduped, PRICE_BATCH_SIZE):
        payload = [{"token_id": token_id, "side": "BUY"} for token_id in chunk]
        chunk_prices = fetch_prices_chunk(payload)
        prices.update(chunk_prices)
    return prices

@retry(stop=stop_after_attempt(3), wait=wait_fixed(0.5), retry=retry_if_exception_type((requests.RequestException, SniperError)))
def fetch_orderbook(token_id: str) -> OrderbookSnapshot:
    """Fetch CLOB order book summary for a token_id."""
    # GET /book?token_id=...
    resp = session.get(ORDERBOOK_URL, params={"token_id": token_id}, timeout=2.5)
    if resp.status_code != 200:
        raise SniperError(f"Bad status {resp.status_code}: {resp.text}")
    data = resp.json()
    # Basic shape validation
    for key in ("bids", "asks", "tick_size", "min_order_size"):
        if key not in data:
            raise SniperError(f"Orderbook missing key={key}")
    return data

def quantize(value: float, step: float, floor: bool = True) -> float:
    """Quantize value to step; floor to avoid exceeding limits."""
    if step <= 0:
        return value
    q = math.floor(value / step) * step if floor else round(value / step) * step
    return max(0.0, q)

def construct_order(token_id: str, side: str, limit_price: float, size: float, attribution: Optional[str] = None) -> Dict:
    """Build minimal order dict for signing & relaying."""
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    return {
        "token_id": token_id,
        "side": side,                 # BUY to acquire outcome shares
        "size": f"{size:.6f}",        # string per API conventions
        "price": f"{limit_price:.4f}",
        "account": ACCOUNT_ADDRESS,
        "network_id": NETWORK_ID,
        "attribution": attribution or BUILDER_KEY,
        # Optional: time-in-force, client_order_id
        "tif": "FOK",                 # Fill-or-Kill for speed; can change to IOC if supported
        "client_order_id": f"sniper-{int(time.time()*1000)}"
    }

@retry(stop=stop_after_attempt(3), wait=wait_fixed(0.5), retry=retry_if_exception_type((requests.RequestException, SniperError)))
def sign_order(order: Dict) -> Dict:
    """Send order to signing server and get signature."""
    resp = session.post(SIGNING_SERVER_URL, json=order, timeout=3)
    if resp.status_code != 200:
        raise SniperError(f"Signing failed {resp.status_code}: {resp.text}")
    signed = resp.json()
    if "signature" not in signed:
        raise SniperError("Signing server response missing 'signature'")
    return signed

@retry(stop=stop_after_attempt(3), wait=wait_fixed(0.5), retry=retry_if_exception_type((requests.RequestException, SniperError)))
def submit_order(signed_order: Dict) -> Dict:
    """Submit signed order to relayer."""
    resp = session.post(RELAYER_URL, json=signed_order, timeout=3)
    if resp.status_code != 200:
        raise SniperError(f"Relayer failed {resp.status_code}: {resp.text}")
    return resp.json()

MARKETS_API = "https://gamma-api.polymarket.com/markets"


def _parse_json_array(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _as_bool(value: Optional[object]) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _parse_end_datetime(record: Dict) -> Optional[datetime]:
    raw = (
        record.get("endDate")
        or record.get("end_date")
        or record.get("endDateIso")
        or record.get("end_time")
    )
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_market_active(record: Dict, *, now: Optional[datetime] = None) -> bool:
    closed = _as_bool(record.get("closed"))
    active = _as_bool(record.get("active"))
    enable_order_book = _as_bool(record.get("enableOrderBook"))
    accepting_orders = _as_bool(record.get("acceptingOrders"))

    if closed is True:
        return False
    if active is False:
        return False
    if enable_order_book is False:
        return False
    if accepting_orders is False:
        return False

    if now is None:
        now = datetime.now(timezone.utc)
    end_dt = _parse_end_datetime(record)
    if end_dt and end_dt < now:
        return False
    return True

def fetch_active_markets(limit: int = MARKET_SCAN_LIMIT, offset: int = 0) -> List[Dict]:
    """Return raw Gamma market records that are active and tradable."""

    limit = max(limit, TARGET_OPTION_COUNT * 5)
    limit = min(limit, 500)
    params = {
        "limit": limit,
        "offset": offset,
        "closed": "false",
        "archived": "false",
        "active": "true",
    }
    resp = requests.get(MARKETS_API, params=params, timeout=5)
    if resp.status_code != 200:
        raise SniperError(f"Gamma markets API error {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise SniperError(f"无法解析 Gamma markets 响应: {exc}") from exc

    records: List[Dict] = []
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = data.get("markets") or data.get("data") or []
    if not isinstance(records, list):
        raise SniperError("Gamma markets payload format unexpected")

    now = datetime.now(timezone.utc)
    active: List[Dict] = []
    for record in records:
        if not _is_market_active(record, now=now):
            continue
        token_ids = _parse_json_array(record.get("clobTokenIds") or record.get("tokenIds") or [])
        if not token_ids:
            continue
        active.append(record)
    return active


def collect_token_metadata(markets: List[Dict]) -> List[Dict]:
    """Extract outcome tokens from raw market payloads."""

    tokens: List[Dict] = []
    for market in markets:
        token_ids = _parse_json_array(market.get("clobTokenIds") or market.get("tokenIds") or [])
        if not token_ids:
            continue
        outcomes = _parse_json_array(market.get("outcomes"))
        label = market.get("question") or market.get("title") or market.get("slug") or "Unknown market"
        end_dt = _parse_end_datetime(market)
        for idx, token_id in enumerate(token_ids):
            if not token_id:
                continue
            outcome_name = str(outcomes[idx]) if idx < len(outcomes) else f"Outcome {idx + 1}"
            tokens.append(
                {
                    "label": label,
                    "token_id": str(token_id),
                    "outcome": outcome_name,
                    "end_dt": end_dt,
                }
            )
    return tokens


def find_high_probability_options(
    *,
    market_limit: int = MARKET_SCAN_LIMIT,
    max_options: int = TARGET_OPTION_COUNT,
) -> List[Dict]:
    markets = fetch_active_markets(limit=market_limit)
    if not markets:
        return []
    token_catalog = collect_token_metadata(markets)
    if not token_catalog:
        return []
    token_ids = [entry["token_id"] for entry in token_catalog]
    prices = fetch_prices_for_tokens(token_ids)

    candidates: List[Dict] = []
    for entry in token_catalog:
        price = prices.get(entry["token_id"])
        if price is None:
            continue
        if price < MIN_PRICE_THRESHOLD or price > MAX_PRICE_THRESHOLD:
            continue
        candidates.append(
            {
                "label": entry["label"],
                "token_id": entry["token_id"],
                "outcome": entry["outcome"],
                "price": price,
                "end_dt": entry["end_dt"],
            }
        )

    candidates.sort(key=lambda item: item["price"], reverse=True)
    return candidates[:max_options]


def format_end_time(dt_value: Optional[datetime]) -> str:
    if not dt_value:
        return "--"
    return dt_value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def print_candidates(candidates: List[Dict]) -> None:
    range_text = f"{MIN_PRICE_THRESHOLD * 100:.2f}% - {MAX_PRICE_THRESHOLD * 100:.2f}%"
    print(f"找到 {len(candidates)} 个概率位于 {range_text} 的选项:")
    for idx, candidate in enumerate(candidates, 1):
        end_time = format_end_time(candidate.get("end_dt"))
        label = candidate["label"]
        outcome = candidate["outcome"]
        price = candidate["price"]
        token_id = candidate["token_id"]
        print(
            f"{idx:02d}. {label} | {outcome} | 价格 {price:.4f} | 截止 {end_time} | Token {token_id}"
        )


def execute_buy_for_option(option: Dict, amount_usdc: float) -> None:
    label = option["label"]
    outcome = option["outcome"]
    token_id = option["token_id"]
    price = float(option["price"])
    if amount_usdc <= 0:
        raise SniperError("amount_usdc must be positive")

    orderbook = fetch_orderbook(token_id)
    tick_size = _safe_float(orderbook.get("tick_size"), 0.01) or 0.01
    min_order_size = _safe_float(orderbook.get("min_order_size"), 0.001)
    min_order_size = max(min_order_size, 0.0001)

    limit_price = max(DEFAULT_LIMIT_PRICE, price)
    limit_price_q = quantize(limit_price, step=tick_size, floor=False)
    if limit_price_q <= 0:
        raise SniperError("限价无效")
    raw_size = amount_usdc / limit_price_q
    size = quantize(raw_size, step=0.000001, floor=True)
    if size < min_order_size:
        print(
            f"[{label} | {outcome}] 资金 {amount_usdc:.2f} USDC 无法满足最小下单量 (>= {min_order_size:.6f}), 跳过"
        )
        return

    order = construct_order(
        token_id=token_id,
        side="BUY",
        limit_price=limit_price_q,
        size=size,
        attribution=BUILDER_KEY,
    )
    print(
        f"[{label} | {outcome}] 下单 price={limit_price_q:.4f} size={size:.6f} (~{size * limit_price_q:.2f} USDC)"
    )
    signed = sign_order(order)
    response = submit_order(signed)
    print(f"[{label} | {outcome}] 下单完成: {response}")


def buy_high_probability_options(candidates: List[Dict], amount_per_order: float) -> None:
    if not candidates:
        return
    total = len(candidates)
    for idx, candidate in enumerate(candidates, 1):
        label = candidate["label"]
        outcome = candidate["outcome"]
        price = candidate["price"]
        print(f"\n[{idx}/{total}] 处理 {label} | {outcome} (价格 {price:.4f})")
        try:
            execute_buy_for_option(candidate, amount_per_order)
        except Exception as exc:
            print(f"[{label}] 下单失败: {exc}")


def main():
    try:
        candidates = find_high_probability_options(max_options=TARGET_OPTION_COUNT * 2)
    except SniperError as exc:
        print(f"错误: {exc}")
        return 1

    if not candidates:
        print(
            f"没有找到概率位于 {MIN_PRICE_THRESHOLD * 100:.2f}% - {MAX_PRICE_THRESHOLD * 100:.2f}% 的选项。"
        )
        return 0

    selected = candidates[:TARGET_OPTION_COUNT]
    if len(selected) < TARGET_OPTION_COUNT:
        print(f"仅找到 {len(selected)} 个符合条件的选项，尝试全部买入。")

    try:
        available_balance = fetch_available_usdc_balance()
    except SniperError as exc:
        print(f"错误: {exc}")
        return 1

    per_order_amount = available_balance / TARGET_OPTION_COUNT
    if per_order_amount <= 0:
        print("USDC 余额不足，无法下单。")
        return 1

    print(
        f"USDC 可用余额: {available_balance:.2f} | 每单分配: {per_order_amount:.2f} (共 {TARGET_OPTION_COUNT} 份)"
    )
    print_candidates(selected)
    buy_high_probability_options(selected, per_order_amount)
    return 0


if __name__ == "__main__":
    main()


