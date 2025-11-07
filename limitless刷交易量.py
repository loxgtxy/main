import http.client
import json
import time
import random
from typing import Dict, List, Optional
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from web3 import Web3

class VolumeTradingBot:
    def __init__(self, private_keys: List[str]):
        """初始化刷量交易机器人"""
        self.private_keys = private_keys
        self.bots = []
        self.account_names = ["甲", "乙", "丙"]
        self.current_market = None
        self.market_slug = None
        
        # 初始化三个账号
        for i, private_key in enumerate(private_keys):
            bot = SingleAccountBot(private_key, self.account_names[i])
            self.bots.append(bot)
    
    def authenticate_all(self):
        """认证所有账号"""
        print("🔐 正在认证三个账号...")
        for bot in self.bots:
            if bot.authenticate():
                print(f"✅ {bot.account_name} 认证成功")
            else:
                raise Exception(f"❌ {bot.account_name} 认证失败")
    
    def get_points_for_all(self):
        """获取三个账号的积分"""
        points = {}
        print("\n📊 获取账号积分...")
        for bot in self.bots:
            points_data = bot.get_points()
            if points_data:
                points[bot.account_name] = {
                    'points': points_data.get('points', '0'),
                    'accumulativePoints': points_data.get('accumulativePoints', '0')
                }
                print(f"   {bot.account_name}: 当前积分 {points_data.get('points', '0')}, 累计积分 {points_data.get('accumulativePoints', '0')}")
            else:
                points[bot.account_name] = {'points': '0', 'accumulativePoints': '0'}
                print(f"   {bot.account_name}: 获取积分失败")
        
        return points
    
    def find_aapl_market(self):
        """寻找包含AAPL的市场"""
        print("\n🔍 正在寻找AAPL市场...")
        
        # 使用第一个账号搜索市场
        markets = self.bots[0].search_active_markets(市场id)
        if not markets:
            print("❌ 未找到活跃市场")
            return False
        
        # 筛选包含AAPL的市场
        aapl_markets = []
        for market in markets:
            slug = market.get("slug", "").lower()
            title = market.get("title", "").lower()
            
            if 'aapl' in slug or 'aapl定位市场' in title:
                aapl_markets.append(market)
                print(f"✅ 找到AAPL市场: {market.get('title')}")
        
        if not aapl_markets:
            print("❌ 未找到包含AAPL的市场")
            return False
        
        # 选择第一个AAPL市场
        self.current_market = aapl_markets[0]
        self.market_slug = self.current_market.get("slug")
        print(f"🎯 选定市场: {self.current_market.get('title')}")
        print(f"   Slug: {self.market_slug}")
        
        return True
    
    def get_positions_for_all(self):
        """获取三个账号在当前市场的仓位"""
        positions = {}
        print(f"\n📊 获取账号在 {self.market_slug} 的仓位...")
        
        for bot in self.bots:
            balances = bot.get_token_balances(self.market_slug)
            positions[bot.account_name] = {
                'yes': balances.get('yes', 0),
                'no': balances.get('no', 0)
            }
            print(f"   {bot.account_name}: YES={balances.get('yes', 0)}, NO={balances.get('no', 0)}")
        
        return positions
    
    def get_orderbook_prices(self):
        """获取订单簿价格"""
        print(f"\n💰 获取订单簿价格...")
        orderbook = self.bots[0].get_orderbook(self.market_slug)
        if not orderbook:
            print("❌ 无法获取订单簿")
            return None
        
        asks = orderbook.get("asks", [])
        bids = orderbook.get("bids", [])
        
        if not asks or not bids:
            print("❌ 订单簿数据不完整")
            return None
        
        # 获取最低卖价
        best_ask_yes = asks[0]['price']  # YES最低卖价
        best_ask_no = 1 - bids[0]['price']  # NO最低卖价（1 - YES最高买价）
        
        print(f"   YES最低卖价: {best_ask_yes:.4f}")
        print(f"   NO最低卖价: {best_ask_no:.4f}")
        
        # 选择交易方向：选择价格较高的进行交易
        if best_ask_yes > best_ask_no:
            trade_direction = "yes"
            reference_price = best_ask_yes
            print(f"   🎯 选择交易YES (价格较高)")
        else:
            trade_direction = "no" 
            reference_price = best_ask_no
            print(f"   🎯 选择交易NO (价格较高)")
        
        return {
            'direction': trade_direction,
            'reference_price': reference_price,
            'best_ask_yes': best_ask_yes,
            'best_ask_no': best_ask_no
        }
    
    def find_seller(self, positions: Dict, trade_direction: str):
        """寻找有仓位的卖家"""
        print(f"\n🔎 寻找{trade_direction.upper()}仓位...")
        
        seller = None
        max_position = 0
        
        for account_name, position in positions.items():
            position_amount = position.get(trade_direction, 0)
            if position_amount > max_position:
                max_position = position_amount
                seller = account_name
        
        if seller and max_position > 0:
            print(f"   ✅ 找到卖家: {seller}, {trade_direction.upper()}仓位: {max_position}")
            return seller, max_position
        else:
            print("   ❌ 没有找到有仓位的卖家")
            return None, 0
    
    def execute_trade_round(self):
        """执行一轮交易"""
        print("\n" + "="*50)
        print("🔄 开始新一轮交易")
        print("="*50)
        
        # 标记处开始
        # 1. 获取积分
        points = self.get_points_for_all()
        
        # 2. 获取仓位
        positions = self.get_positions_for_all()
        
        # 3. 获取订单簿价格并选择交易方向
        price_info = self.get_orderbook_prices()
        if not price_info:
            return False
        
        trade_direction = price_info['direction']
        reference_price = price_info['reference_price']
        
        # 4. 寻找卖家
        seller_name, position_amount = self.find_seller(positions, trade_direction)
        if not seller_name:
            print("❌ 没有找到合适的卖家，跳过本轮")
            return False
        
        # 获取卖家bot对象
        seller_bot = next((bot for bot in self.bots if bot.account_name == seller_name), None)
        if not seller_bot:
            print(f"❌ 找不到卖家 {seller_name} 的bot对象")
            return False
        
        # 5. 卖家挂卖单
        sell_price = round(reference_price - 0.0001, 4)  # 比最低卖价低0.0001
        quantity = int(position_amount)  # 整数数量
        
        print(f"\n🔄 {seller_name} 挂卖单:")
        print(f"   方向: {trade_direction.upper()}")
        print(f"   价格: {sell_price}")
        print(f"   数量: {quantity}")
        
        sell_success = seller_bot.place_sell_order(self.market_slug, trade_direction, sell_price, quantity)
        if not sell_success:
            print("❌ 卖单挂单失败")
            return False
        
        # 6. 随机选择买家
        buyer_candidates = [bot for bot in self.bots if bot.account_name != seller_name]
        if not buyer_candidates:
            print("❌ 没有可用的买家")
            return False
        
        buyer_bot = random.choice(buyer_candidates)
        print(f"\n🔄 {buyer_bot.account_name} 挂买单:")
        print(f"   方向: {trade_direction.upper()}")
        print(f"   价格: {sell_price}")  # 相同价格
        print(f"   数量: {quantity}")    # 相同数量
        
        buy_success = buyer_bot.place_buy_order(self.market_slug, trade_direction, sell_price, quantity)
        if not buy_success:
            print("❌ 买单挂单失败")
            # 取消卖单
            seller_bot.cancel_all_orders(self.market_slug)
            return False
        
        # 7. 等待2秒让订单可能成交
        print("\n⏳ 等待2秒...")
        time.sleep(2)
        
        # 8. 取消全部订单
        print("\n🗑️ 取消全部订单...")
        for bot in self.bots:
            bot.cancel_all_orders(self.market_slug)
        
        print("✅ 本轮交易完成")
        return True
    
    def run(self, max_cycles: int = 100):
        """运行刷量策略"""
        print("="*60)
        print("🚀 三账号刷量交易策略启动")
        print("="*60)
        print("📋 策略流程:")
        print("   1. 获取三个账号积分")
        print("   2. 寻找AAPL市场")
        print("   3. 获取各账号仓位")
        print("   4. 选择交易方向(高价方向)")
        print("   5. 有仓位账号挂卖单(价格-0.0001)")
        print("   6. 随机另一账号挂买单(相同价格数量)")
        print("   7. 等待2秒后取消全部订单")
        print("   8. 循环执行")
        print("="*60)
        
        # 认证所有账号
        self.authenticate_all()
        
        # 寻找AAPL市场
        if not self.find_aapl_market():
            print("❌ 市场寻找失败，程序退出")
            return
        
        cycle_count = 0
        successful_trades = 0
        
        while cycle_count < max_cycles:
            cycle_count += 1
            print(f"\n🎯 第 {cycle_count}/{max_cycles} 轮")
            
            try:
                if self.execute_trade_round():
                    successful_trades += 1
                else:
                    print("❌ 本轮交易失败")
                
                # 等待后继续下一轮
                wait_time = 3
                print(f"\n⏳ 等待{wait_time}秒后继续下一轮...")
                time.sleep(wait_time)
                
            except KeyboardInterrupt:
                print("\n⏹️ 用户中断执行")
                break
            except Exception as e:
                print(f"❌ 执行异常: {e}")
                # 异常后等待稍长时间
                time.sleep(5)
        
        print(f"\n🎉 刷量策略执行完成!")
        print(f"📊 统计: 共执行 {cycle_count} 轮, 成功 {successful_trades} 轮")
        print("="*60)


class SingleAccountBot:
    """单个账号的交易机器人"""
    
    def __init__(self, private_key: str, account_name: str):
        self.conn = http.client.HTTPSConnection("api.limitless.exchange")
        self.private_key = private_key
        self.session_cookie = None
        self.eth_address = None
        self.user_id = None
        self.fee_rate_bps = 0
        self.account_name = account_name

    def setup_crypto(self):
        """设置加密相关功能"""
        try:
            account = Account.from_key(self.private_key)
            self.eth_address = Web3.to_checksum_address(account.address)
            return True
        except Exception as e:
            print(f"❌ {self.account_name} 私钥无效: {e}")
            return False

    def get_signing_message(self):
        """获取签名消息"""
        try:
            self.conn.request("GET", "/auth/signing-message")
            res = self.conn.getresponse()
            if res.status == 200:
                return res.read().decode('utf-8')
            else:
                return None
        except Exception as e:
            raise

    def sign_message_eip191(self, message: str) -> str:
        """使用EIP-191标准签名消息"""
        try:
            account = Account.from_key(self.private_key)
            message = message.rstrip()
            message_hash = encode_defunct(text=message)
            signed_message = account.sign_message(message_hash)
            signature = signed_message.signature.hex()
            if not signature.startswith('0x'):
                signature = '0x' + signature
            return signature
        except Exception as e:
            return ""

    def string_to_hex(self, text: str) -> str:
        """将字符串转换为十六进制格式"""
        return "0x" + text.encode('utf-8').hex()

    def authenticate(self):
        """完整的Web3认证流程"""
        if not self.setup_crypto():
            return False
            
        try:
            signing_message = self.get_signing_message()
            if not signing_message:
                return False
            
            signing_message = signing_message.rstrip()
            signature = self.sign_message_eip191(signing_message)
            if not signature:
                return False
            
            hex_message = self.string_to_hex(signing_message)
            
            headers = {
                'x-account': self.eth_address,
                'x-signing-message': hex_message,
                'x-signature': signature,
                'Content-Type': 'application/json'
            }
            
            login_data = {"client": "eoa"}
            self.conn.request("POST", "/auth/login", 
                             body=json.dumps(login_data), 
                             headers=headers)
            
            res = self.conn.getresponse()
            data = res.read().decode("utf-8")
            
            if res.status == 200:
                cookies = res.getheader('Set-Cookie', '')
                if 'limitless_session=' in cookies:
                    self.session_cookie = cookies.split('limitless_session=')[1].split(';')[0]
                    user_info = json.loads(data)
                    self.user_id = user_info.get('id')
                    
                    # 从用户信息中获取费率
                    rank_info = user_info.get('rank', {})
                    self.fee_rate_bps = rank_info.get('feeRateBps', 0)
                    return True
                else:
                    return False
            else:
                return False
                
        except Exception as e:
            return False

    def get_points(self):
        """获取积分明细"""
        try:
            if not self.session_cookie:
                return None
                
            headers = {
                'Cookie': f'limitless_session={self.session_cookie}'
            }
            
            self.conn.request("GET", "/portfolio/points", headers=headers)
            res = self.conn.getresponse()
            
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return data
            else:
                return None
                
        except Exception as e:
            return None

    def search_active_markets(self, category_id: int = 31):
        """搜索活跃市场"""
        try:
            self.conn.request("GET", f"/markets/active/{category_id}")
            res = self.conn.getresponse()
            
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return data.get("data", [])
            else:
                return []
                
        except Exception as e:
            return []

    def get_token_balances(self, market_slug: str):
        """查询YES和NO Token余额"""
        try:
            if not self.session_cookie:
                return {"yes": 0, "no": 0}
                
            headers = {
                'Cookie': f'limitless_session={self.session_cookie}'
            }
            
            self.conn.request("GET", "/portfolio/positions", headers=headers)
            res = self.conn.getresponse()
            
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return self._parse_token_balances(data, market_slug)
            else:
                return {"yes": 0, "no": 0}
                
        except Exception as e:
            return {"yes": 0, "no": 0}

    def _parse_token_balances(self, portfolio_data: Dict, market_slug: str):
        """从持仓数据中解析YES和NO Token余额"""
        scaling_factor = 1000000
        yes_balance = 0
        no_balance = 0
        
        try:
            # 检查CLOB持仓
            if 'clob' in portfolio_data:
                for position in portfolio_data['clob']:
                    market = position.get('market', {})
                    if market.get('slug') == market_slug:
                        tokens_balance = position.get('tokensBalance', {})
                        yes_balance = float(tokens_balance.get('yes', '0')) / scaling_factor
                        no_balance = float(tokens_balance.get('no', '0')) / scaling_factor
                        break
            
            # 检查AMM持仓
            if 'amm' in portfolio_data and (yes_balance == 0 or no_balance == 0):
                for position in portfolio_data['amm']:
                    market = position.get('market', {})
                    if market.get('slug') == market_slug:
                        outcome_token_amount = position.get('outcomeTokenAmount', '0')
                        outcome_index = position.get('outcomeIndex', -1)
                        
                        if outcome_index == 0:  # YES Token
                            yes_balance = float(outcome_token_amount) / scaling_factor
                        elif outcome_index == 1:  # NO Token
                            no_balance = float(outcome_token_amount) / scaling_factor
        
        except Exception as e:
            pass
        
        return {"yes": yes_balance, "no": no_balance}

    def get_orderbook(self, market_slug: str):
        """获取订单簿数据"""
        try:
            self.conn.request("GET", f"/markets/{market_slug}/orderbook")
            res = self.conn.getresponse()
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                return data
            else:
                return None
        except Exception as e:
            return None

    def get_market_tokens(self, market_slug: str):
        """获取市场的YES/NO Token ID"""
        try:
            self.conn.request("GET", f"/markets/{market_slug}")
            res = self.conn.getresponse()
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                
                tokens = {}
                if 'positionIds' in data:
                    tokens['yes'] = data['positionIds'][0]
                    tokens['no'] = data['positionIds'][1]
                elif 'tokens' in data:
                    tokens['yes'] = data['tokens']['yes']
                    tokens['no'] = data['tokens']['no']
                elif 'position_ids' in data:
                    tokens['yes'] = data['position_ids'][0]
                    tokens['no'] = data['position_ids'][1]
                
                return tokens
            else:
                return {}
                
        except Exception as e:
            return {}

    def create_eip712_signature(self, order_data: Dict) -> str:
        """创建EIP-712订单签名"""
        try:
            account = Account.from_key(self.private_key)
            
            domain_data = {
                "name": "Limitless CTF Exchange",
                "version": "1", 
                "chainId": 8453,
                "verifyingContract": Web3.to_checksum_address("0xa4409D988CA2218d956BeEFD3874100F444f0DC3")
            }
            
            types = {
                "Order": [
                    {"name": "salt", "type": "uint256"},
                    {"name": "maker", "type": "address"},
                    {"name": "signer", "type": "address"},
                    {"name": "taker", "type": "address"},
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "makerAmount", "type": "uint256"},
                    {"name": "takerAmount", "type": "uint256"},
                    {"name": "expiration", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "feeRateBps", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "signatureType", "type": "uint8"}
                ]
            }
            
            zero_address = Web3.to_checksum_address("0x0000000000000000000000000000000000000000")
            maker_address = Web3.to_checksum_address(order_data["maker"])
            signer_address = Web3.to_checksum_address(order_data["signer"])
            
            message = {
                "salt": order_data["salt"],
                "maker": maker_address,
                "signer": signer_address,
                "taker": zero_address,
                "tokenId": int(order_data["tokenId"]),
                "makerAmount": order_data["makerAmount"],
                "takerAmount": order_data["takerAmount"],
                "expiration": int(order_data["expiration"]),
                "nonce": order_data["nonce"],
                "feeRateBps": order_data["feeRateBps"],
                "side": order_data["side"],
                "signatureType": order_data["signatureType"]
            }
            
            encoded_data = encode_typed_data(domain_data, types, message)
            signed_message = account.sign_message(encoded_data)
            
            signature = signed_message.signature.hex()
            if not signature.startswith('0x'):
                signature = '0x' + signature
                
            return signature
            
        except Exception as e:
            return ""

    def place_sell_order(self, market_slug: str, token_type: str, price: float, size: int) -> bool:
        """挂卖单"""
        try:
            tokens = self.get_market_tokens(market_slug)
            if not tokens:
                return False
                
            token_id = tokens[token_type.lower()]
            salt = int(time.time() * 1000)
            scaling_factor = 1000000
            
            # 卖单逻辑：支付Token，获取USDC
            maker_amount = size * scaling_factor  # 支付的Token数量
            taker_amount = int(price * size * scaling_factor)  # 获取的USDC数量
            
            zero_address = "0x0000000000000000000000000000000000000000"
            
            order_data = {
                "salt": salt,
                "maker": self.eth_address,
                "signer": self.eth_address,
                "taker": zero_address,
                "tokenId": str(token_id),
                "makerAmount": maker_amount,
                "takerAmount": taker_amount,
                "expiration": "0",
                "nonce": 0,
                "feeRateBps": self.fee_rate_bps,
                "side": 1,  # 卖单
                "signatureType": 0
            }
            
            signature = self.create_eip712_signature(order_data)
            if not signature:
                return False
            
            rounded_price = round(price, 4)  # 4位小数
            
            order_payload = {
                "order": {
                    **order_data,
                    "signature": signature,
                    "price": rounded_price
                },
                "ownerId": self.user_id,
                "orderType": "GTC",
                "marketSlug": market_slug
            }
            
            headers = {
                'Cookie': f'limitless_session={self.session_cookie}',
                'Content-Type': 'application/json'
            }
            
            self.conn.request("POST", "/orders", 
                            body=json.dumps(order_payload), 
                            headers=headers)
            res = self.conn.getresponse()
            data = res.read().decode("utf-8")
            
            if res.status == 201:
                print(f"   ✅ {self.account_name} {token_type.upper()}卖单成功: {size}份 @ {rounded_price}")
                return True
            else:
                print(f"   ❌ {self.account_name} {token_type.upper()}卖单失败: {res.status}")
                return False
                
        except Exception as e:
            print(f"   ❌ {self.account_name} 卖单异常: {e}")
            return False

    def place_buy_order(self, market_slug: str, token_type: str, price: float, size: int) -> bool:
        """挂买单"""
        try:
            tokens = self.get_market_tokens(market_slug)
            if not tokens:
                return False
                
            token_id = tokens[token_type.lower()]
            salt = int(time.time() * 1000)
            scaling_factor = 1000000
            
            # 买单逻辑：支付USDC，获取Token
            maker_amount = int(price * size * scaling_factor)  # 支付的USDC数量
            taker_amount = size * scaling_factor  # 获取的Token数量
            
            zero_address = "0x0000000000000000000000000000000000000000"
            
            order_data = {
                "salt": salt,
                "maker": self.eth_address,
                "signer": self.eth_address,
                "taker": zero_address,
                "tokenId": str(token_id),
                "makerAmount": maker_amount,
                "takerAmount": taker_amount,
                "expiration": "0",
                "nonce": 0,
                "feeRateBps": self.fee_rate_bps,
                "side": 0,  # 买单
                "signatureType": 0
            }
            
            signature = self.create_eip712_signature(order_data)
            if not signature:
                return False
            
            rounded_price = round(price, 4)  # 4位小数
            
            order_payload = {
                "order": {
                    **order_data,
                    "signature": signature,
                    "price": rounded_price
                },
                "ownerId": self.user_id,
                "orderType": "GTC",
                "marketSlug": market_slug
            }
            
            headers = {
                'Cookie': f'limitless_session={self.session_cookie}',
                'Content-Type': 'application/json'
            }
            
            self.conn.request("POST", "/orders", 
                            body=json.dumps(order_payload), 
                            headers=headers)
            res = self.conn.getresponse()
            data = res.read().decode("utf-8")
            
            if res.status == 201:
                print(f"   ✅ {self.account_name} {token_type.upper()}买单成功: {size}份 @ {rounded_price}")
                return True
            else:
                print(f"   ❌ {self.account_name} {token_type.upper()}买单失败: {res.status}")
                return False
                
        except Exception as e:
            print(f"   ❌ {self.account_name} 买单异常: {e}")
            return False

    def cancel_all_orders(self, market_slug: str) -> bool:
        """取消指定市场的全部订单"""
        try:
            if not self.session_cookie:
                return False
                
            headers = {
                'Cookie': f'limitless_session={self.session_cookie}'
            }
            
            self.conn.request("DELETE", f"/orders/all/{market_slug}", headers=headers)
            res = self.conn.getresponse()
            data = res.read().decode("utf-8")
            
            if res.status == 200:
                print(f"   ✅ {self.account_name} 取消订单成功")
                return True
            else:
                print(f"   ❌ {self.account_name} 取消订单失败: {res.status}")
                return False
                
        except Exception as e:
            print(f"   ❌ {self.account_name} 取消订单异常: {e}")
            return False


if __name__ == "__main__":
    # 三个账号的私钥
    private_keys = [
        "0x306要刷的账号35d0f62f3fe2fb03fb",  # 甲
        "0xcb78e431d7ed5c7446d0",  # 乙
        "0xab9fa21243a69b953b3"   # 丙
    ]
    
    # 替换为你的实际私钥
    if private_keys[1].startswith("0xANOTHER"):
        print("❌ 请替换为实际的私钥")
        exit(1)
    
    bot = VolumeTradingBot(private_keys)
    bot.run(max_cycles=50)  # 运行50轮