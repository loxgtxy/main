import os
import sys

from web3 import Web3


DEFAULT_RPC_URL = "https://polygon-rpc.com"
TARGET_ADDRESS = "0xa1a4BE50ab5361F643AcC74D5E78e48474D34F46"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Polygon PoS USDC


def main() -> None:
    """Fetch Polygon MATIC + USDC 余额."""
    rpc_url = os.environ.get("POLYGON_RPC_URL", DEFAULT_RPC_URL)
    web3 = Web3(Web3.HTTPProvider(rpc_url))

    if not web3.is_connected():
        print(f"Unable to connect to Polygon RPC endpoint at {rpc_url}", file=sys.stderr)
        sys.exit(1)

    checksum_address = Web3.to_checksum_address(TARGET_ADDRESS)
    # 查询原生 MATIC
    balance_wei = web3.eth.get_balance(checksum_address)
    balance_matic = Web3.from_wei(balance_wei, "ether")
    # 查询 USDC（ERC20）
    usdc_contract = web3.eth.contract(
        address=Web3.to_checksum_address(USDC_ADDRESS),
        abi=[
            {
                "constant": True,
                "inputs": [{"name": "account", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function",
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function",
            },
        ],
    )
    usdc_decimals = usdc_contract.functions.decimals().call()
    usdc_raw = usdc_contract.functions.balanceOf(checksum_address).call()
    usdc_human = usdc_raw / (10 ** usdc_decimals)

    print(f"Address: {checksum_address}")
    print(f"Balance: {balance_wei} wei")
    print(f"         {balance_matic} MATIC")
    print(f"USDC 余额: {usdc_raw} (raw)")
    print(f"          {usdc_human} USDC")


if __name__ == "__main__":
    main()
