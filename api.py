from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams

# 配置参数
host = "https://clob.polymarket.com"
key = "0xeb91494a09eb4003aad210c6f28ad2f9997354ac10520140729586818aa98f7e"  # 您的私钥
chain_id = 137
POLYMARKET_PROXY_ADDRESS = '0xa1a4BE50ab5361F643AcC74D5E78e48474D34F46'  # 您的代理地址

# 初始化客户端（根据登录方式选择）
# Email/Magic 登录：
client = ClobClient(host, key=key, chain_id=chain_id, signature_type=1, funder=POLYMARKET_PROXY_ADDRESS)

# 或浏览器钱包登录：
# client = ClobClient(host, key=key, chain_id=chain_id, signature_type=2, funder=POLYMARKET_PROXY_ADDRESS)

# 创建或派生 API 凭证（自动处理 L2 认证）
client.set_api_creds(client.create_or_derive_api_creds())

# 查询余额（客户端自动添加 L2 认证头）
# 端点：GET /balance-allowance
# L2 认证头包括：POLY_ADDRESS, POLY_SIGNATURE, POLY_TIMESTAMP, POLY_API_KEY, POLY_PASSPHRASE
params = BalanceAllowanceParams()  # ensures signature_type is set when SDK inspects params
balance = client.get_balance_allowance(params)
print(balance)
