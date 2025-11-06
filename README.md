# Polymarket Monitor

`polymarket_monitor.py` 是一个简单的命令行脚本，用于监控 Polymarket 上指定事件的概率价格，并实时刷新订单簿。

## 功能特点
- 使用 Polymarket 官方文档中的 `GET /markets/{slug}` 与 `GET /markets/search` 端点检索市场
- 选择关注的结果（如 `yes` / `no`）
- 定期刷新并展示买卖盘以及中间价
- 无需额外第三方依赖，使用 Python 标准库发起 HTTP 请求

## 使用方法
直接运行脚本后，会提示输入用于搜索市场的关键词：
```bash
python polymarket_monitor.py
# 请输入用于搜索市场的关键词: Trump
```
脚本同样保留了命令行参数，便于直接使用 slug 或预设好的关键词：
```bash
python polymarket_monitor.py --slug will-trump-win-2024 --outcome yes --depth 12 --interval 2
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

## 快速同步网页端内容到本地的小贴士
如果先在网页端（例如浏览器中的 Git 托管服务或在线 IDE）创建/修改了本仓库的文件，通常可以通过 Git 的远程同步能力把改动快速拉到本地：

1. **确认网页端已提交并推送**：在网页界面完成改动后执行提交（commit），并确保它已经推送到远程仓库的目标分支。
2. **在本地拉取最新变更**：打开本地终端，进入仓库目录后运行：
   ```bash
   git fetch origin
   git pull origin <分支名>
   ```
   这样就能把网页端的最新提交合并到本地分支。
3. **需要单文件时的快速方式**：如果只是想临时同步单个文件，可以在网页端获取该文件的原始（raw）地址，然后在本地使用 `curl` 或 `wget` 下载覆盖：
   ```bash
   curl -o polymarket_monitor.py https://raw.githubusercontent.com/<用户名>/<仓库名>/<分支>/polymarket_monitor.py
   ```
   下载后仍建议执行一次 `git status` 确认工作区状态，并在需要时进行合并或提交。

> 提示：若仓库启用了多重身份验证，记得在本地为 `git` 配置好相应的访问令牌或 SSH Key，以免拉取时遇到权限问题。
