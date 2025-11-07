"""Resolution sniping bot for Polymarket CLOB.

This script monitors selected markets and sends aggressive limit orders when the
winning side experiences a sharp price spike near resolution.  It is designed as
an educational minimal example and **must** be audited before mainnet use.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from dotenv import load_dotenv
from web3 import Web3

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.order_builder import OrderBuilder
except ImportError as exc:  # pragma: no cover - library is optional at lint time
    raise SystemExit(
        "py-clob-client is required. Install it via `pip install py-clob-client`."
    ) from exc


CLOB_BASE_URL = "https://clob.polymarket.com"
POLYGON_CHAIN_ID = 137
FUNDER_ADDRESS = "0xa1a4BE50ab5361F643AcC74D5E78e48474D34F46"
GAS_PRIORITY_FEE_GWEI = 50
GAS_BASE_FEE_MULTIPLIER = 2
POLL_INTERVAL_SECONDS = 0.2
HISTORY_WINDOW_SECONDS = 10
HISTORY_BUFFER_SIZE = 50
DEFAULT_PRICE_THRESHOLD = Decimal("0.97")
DEFAULT_SPIKE_THRESHOLD = Decimal("0.15")
DEFAULT_MAX_SLIPPAGE = Decimal("0.01")
ORDER_EXPIRY_SECONDS = 600
MAX_RETRIES = 3


@dataclass
class Market:
    """Configuration for a single Polymarket market outcome pair."""

    condition_id: str
    yes_token: str
    no_token: str
    name: str
    price_history: List[Tuple[float, Decimal, Decimal]] = field(default_factory=list)
    last_snipe_ts: float = 0.0


@dataclass
class Settings:
    price_threshold: Decimal
    spike_threshold: Decimal
    max_slippage: Decimal
    snipe_amount_usdc: Decimal
    dry_run: bool


def setup_logging() -> None:
    """Configure the root logger with time, level and colored output."""

    class ColorFormatter(logging.Formatter):
        COLORS = {
            logging.DEBUG: "\033[36m",
            logging.INFO: "\033[32m",
            logging.WARNING: "\033[33m",
            logging.ERROR: "\033[31m",
            logging.CRITICAL: "\033[35m",
        }

        def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatters are runtime only
            color = self.COLORS.get(record.levelno, "")
            reset = "\033[0m" if color else ""
            return f"{color}{super().format(record)}{reset}"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        ColorFormatter("%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])


async def backoff_sleep(attempt: int) -> None:
    await asyncio.sleep(min(2 ** attempt, 5))


async def get_prices(
    session: aiohttp.ClientSession,
    market: Market,
) -> Optional[Dict[str, Decimal]]:
    """Fetch ask prices for the YES/NO tokens using the CLOB /prices endpoint.

    Returns a mapping of token_id -> price. Handles transient errors and rate
    limits. A `None` return indicates a non-recoverable error for this poll.
    """

    payload = [
        {"token_id": market.yes_token, "side": "BUY"},
        {"token_id": market.no_token, "side": "BUY"},
    ]
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(f"{CLOB_BASE_URL}/prices", json=payload, timeout=3) as resp:
                if resp.status == 429:
                    logging.warning("Rate limited by CLOB /prices, sleeping briefly…")
                    await asyncio.sleep(0.5)
                    continue
                resp.raise_for_status()
                raw = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            logging.warning(
                "Failed to fetch prices for %s (%s/%s): %s",
                market.name,
                market.yes_token,
                market.no_token,
                err,
            )
            await backoff_sleep(attempt)
            continue
        try:
            prices = {
                entry["token_id"]: Decimal(str(entry["price"]))
                for entry in raw
                if "token_id" in entry and "price" in entry
            }
            if market.yes_token not in prices or market.no_token not in prices:
                raise KeyError("Missing token IDs in response")
            return prices
        except (KeyError, ValueError) as err:
            logging.error("Malformed /prices response for %s: %s", market.name, err)
            return None
    return None


def detect_spike(
    history: List[Tuple[float, Decimal, Decimal]],
    now: float,
    winning_price: Decimal,
    winner_is_yes: bool,
    spike_threshold: Decimal,
) -> bool:
    """Check whether the winning outcome's price increased by >threshold in the last window."""

    recent = [point for point in history if now - point[0] <= HISTORY_WINDOW_SECONDS]
    if len(recent) < 2:
        return False
    baseline_price = recent[0][1] if winner_is_yes else recent[0][2]
    if baseline_price <= 0:
        return False
    increase = (winning_price - baseline_price) / baseline_price
    return increase >= spike_threshold


def compute_order_quantity(amount_usdc: Decimal, target_price: Decimal) -> Decimal:
    if target_price <= 0:
        raise ValueError("target_price must be positive")
    shares = amount_usdc / target_price
    return shares.quantize(Decimal("0.0001"))


def determine_winner(
    prices: Dict[str, Decimal], market: Market
) -> Tuple[str, Decimal, bool]:
    yes_price = prices[market.yes_token]
    no_price = prices[market.no_token]
    if yes_price >= no_price:
        return market.yes_token, yes_price, True
    return market.no_token, no_price, False


def update_history(market: Market, prices: Dict[str, Decimal]) -> None:
    now = time.time()
    yes_price = prices[market.yes_token]
    no_price = prices[market.no_token]
    market.price_history.append((now, yes_price, no_price))
    if len(market.price_history) > HISTORY_BUFFER_SIZE:
        market.price_history[:] = market.price_history[-HISTORY_BUFFER_SIZE:]


def build_signed_order(
    client: ClobClient,
    token_id: str,
    price: Decimal,
    size: Decimal,
    max_slippage: Decimal,
) -> Dict[str, Any]:
    """Create and sign a limit order payload ready for submission to the relayer."""

    builder = OrderBuilder(
        chain_id=POLYGON_CHAIN_ID,
        clob=client,
        token_id=token_id,
        side="BUY",
        price=float(price),
        size=float(size),
        time_in_force="GTC",
        expiration_ts=int(time.time()) + ORDER_EXPIRY_SECONDS,
        max_slippage=float(max_slippage),
        signature_type=2,
    )
    order = builder.build()
    return order


async def submit_order(
    session: aiohttp.ClientSession,
    order: Dict[str, Any],
) -> Dict[str, Any]:
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(f"{CLOB_BASE_URL}/orders", json=order, timeout=3) as resp:
                if resp.status == 429:
                    logging.warning("Rate limited when submitting order; retrying…")
                    await asyncio.sleep(0.3)
                    continue
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            logging.error("Order submission error: %s", err)
            await backoff_sleep(attempt)
    raise RuntimeError("Failed to submit order after retries")


async def snipe_buy(
    client: ClobClient,
    session: aiohttp.ClientSession,
    market: Market,
    token_id: str,
    winning_price: Decimal,
    settings: Settings,
) -> None:
    target_price = min(Decimal("0.9999"), winning_price + Decimal("0.001"))
    size = compute_order_quantity(settings.snipe_amount_usdc, target_price)
    logging.info(
        "Trigger hit for %s (%s). Target price %.4f, size %.4f shares.",
        market.name,
        token_id,
        target_price,
        size,
    )
    if settings.dry_run:
        logging.info("Dry-run enabled, skipping order submission.")
        return

    order = build_signed_order(client, token_id, target_price, size, settings.max_slippage)
    order["gasParameters"] = {
        "maxPriorityFeePerGas": int(GAS_PRIORITY_FEE_GWEI * 1e9),
        "maxFeePerGas": int(GAS_BASE_FEE_MULTIPLIER * GAS_PRIORITY_FEE_GWEI * 1e9),
    }
    response = await submit_order(session, order)
    tx_hash = response.get("transactionHash") or response.get("txHash")
    logging.info("Submitted order for %s -> tx %s", market.name, tx_hash)


async def ensure_balance(
    client: ClobClient,
    minimum: Decimal,
) -> None:
    try:
        balances = client.get_balances()
    except AttributeError as err:  # pragma: no cover - depends on library version
        raise RuntimeError(
            "ClobClient.get_balances is unavailable. Upgrade py-clob-client >=0.1.0."
        ) from err
    usdc_balance = Decimal(str(balances.get("USDC", {}).get("available", 0)))
    if usdc_balance < minimum:
        raise RuntimeError(
            f"Insufficient USDC balance. Available {usdc_balance}, required {minimum}."
        )
    logging.info("USDC available: %s", usdc_balance)


async def monitor_market(
    client: ClobClient,
    session: aiohttp.ClientSession,
    market: Market,
    settings: Settings,
) -> None:
    logging.info("Started monitoring %s", market.name)
    while True:
        prices = await get_prices(session, market)
        if prices is None:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        update_history(market, prices)
        winner_token, winner_price, winner_is_yes = determine_winner(prices, market)
        now = time.time()
        if now - market.last_snipe_ts < HISTORY_WINDOW_SECONDS:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        has_spike = detect_spike(
            market.price_history,
            now,
            winner_price,
            winner_is_yes,
            settings.spike_threshold,
        )
        if winner_price >= settings.price_threshold and has_spike:
            market.last_snipe_ts = now
            try:
                await snipe_buy(client, session, market, winner_token, winner_price, settings)
            except Exception as err:
                logging.exception("Failed to execute snipe for %s: %s", market.name, err)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def load_markets(raw: str) -> Dict[str, Market]:
    data = json.loads(raw)
    return {
        slug: Market(
            condition_id=entry["condition_id"],
            yes_token=entry["yes_token"],
            no_token=entry["no_token"],
            name=entry.get("name", slug),
        )
        for slug, entry in data.items()
    }


def build_client(
    private_key: str,
    api_key: str,
    api_secret: str,
    signer: str,
    rpc_url: str,
) -> ClobClient:
    kwargs: Dict[str, Any] = {
        "host": CLOB_BASE_URL,
        "api_key": api_key,
        "api_secret": api_secret,
        "signature_type": 2,
        "private_key": private_key,
        "wallet_address": signer,
        "funder": FUNDER_ADDRESS,
        "chain_id": POLYGON_CHAIN_ID,
        "rpc_url": rpc_url,
    }
    try:
        client = ClobClient(**kwargs)
    except TypeError:
        kwargs.pop("rpc_url")
        client = ClobClient(**kwargs)
        setattr(client, "rpc_url", rpc_url)
    return client


async def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket resolution sniping bot")
    parser.add_argument("--dry-run", action="store_true", help="Do not send signed orders")
    parser.add_argument(
        "--price-threshold",
        type=Decimal,
        default=DEFAULT_PRICE_THRESHOLD,
        help="Winning price threshold to trigger a snipe",
    )
    parser.add_argument(
        "--spike-threshold",
        type=Decimal,
        default=DEFAULT_SPIKE_THRESHOLD,
        help="Relative price increase over the last 10 seconds",
    )
    parser.add_argument(
        "--max-slippage",
        type=Decimal,
        default=DEFAULT_MAX_SLIPPAGE,
        help="Max slippage tolerance for limit orders",
    )
    args = parser.parse_args()

    setup_logging()
    load_dotenv()

    private_key = os.getenv("PK")
    rpc_url = os.getenv("RPC_URL")
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    signer = os.getenv("SIGNER")
    markets_raw = os.getenv("MARKETS")
    amount_usdc = os.getenv("SNIPE_AMOUNT_USDC", "0")

    if not all([private_key, rpc_url, api_key, api_secret, signer, markets_raw]):
        missing = [
            name
            for name, value in [
                ("PK", private_key),
                ("RPC_URL", rpc_url),
                ("API_KEY", api_key),
                ("API_SECRET", api_secret),
                ("SIGNER", signer),
                ("MARKETS", markets_raw),
            ]
            if not value
        ]
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    markets = load_markets(markets_raw)
    if not markets:
        raise SystemExit("No markets configured")

    web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 3}))
    if not web3.is_connected():  # pragma: no cover - network dependent
        logging.warning("Polygon RPC %s is unreachable; latency may suffer.", rpc_url)
    else:
        latest_block = web3.eth.block_number
        logging.info("Connected to Polygon RPC. Latest block: %s", latest_block)

    settings = Settings(
        price_threshold=args.price_threshold,
        spike_threshold=args.spike_threshold,
        max_slippage=args.max_slippage,
        snipe_amount_usdc=Decimal(amount_usdc),
        dry_run=args.dry_run,
    )

    client = build_client(private_key, api_key, api_secret, signer, rpc_url)
    await ensure_balance(client, settings.snipe_amount_usdc * Decimal("1.05"))

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=3, sock_read=3)
    headers = {"Authorization": f"Bearer {api_key}:{api_secret}"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [
            asyncio.create_task(monitor_market(client, session, market, settings))
            for market in markets.values()
        ]
        logging.info("Monitoring %d markets with %.1f s polling", len(tasks), POLL_INTERVAL_SECONDS)
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logging.info("Shutdown requested, cancelling tasks…")
        finally:
            for task in tasks:
                task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupted by user, exiting…")
