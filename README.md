# Polymarket Monitor

`polymarket_monitor.py` 是一个简单的命令行脚本，用于监控 Polymarket 上指定事件的概率价格，并实时刷新订单簿。

## 功能特点
- 使用 Polymarket 官方文档中的 `GET /markets/{slug}` 与 `GET /markets/search` 端点检索市场
- 选择关注的结果（如 `yes` / `no`）
- 定期刷新并展示买卖盘以及中间价
- 无需额外第三方依赖，使用 Python 标准库发起 HTTP 请求

## 使用方法
```bash
python polymarket_monitor.py --slug will-trump-win-2024 --outcome yes --depth 12 --interval 2
```
或根据问题关键字搜索后选择结果：
```bash
python polymarket_monitor.py --keyword "Trump" --outcome yes
```

> 提示：脚本默认每 2 秒刷新一次。如果需要更高频率，可通过 `--interval` 参数调整，但请注意合理控制请求频率以避免触发 Polymarket 的限流。

## 输出示例
```
Will Donald Trump win the 2024 U.S. Presidential Election?
市场 ID: 12345678-aaaa-bbbb-cccc-1234567890ab
结果: Yes (token 0xabcdef...)

最优买价: 0.4350
最优卖价: 0.4450
中间价(概率): 0.4400
更新时间: 2024-08-01T12:34:56.789012Z

价格(买)/价格(卖)    数量(买)    |    价格(卖)    数量(卖)
     0.4350      500.0    |        0.4450      400.0
     0.4300      800.0    |        0.4500      600.0
...
```

## 限制说明
由于 Polymarket API 可能存在地理或网络限制，脚本在某些环境下可能无法建立连接。如果遇到相关错误，请检查本地网络、代理或重试其他时间。

## 参考资料
- [Polymarket API Reference](https://docs.polymarket.com/api-reference) —— 市场搜索、单一市场详情以及订单簿接口的官方说明
