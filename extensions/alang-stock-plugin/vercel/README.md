# Vercel Hobby 托管方案

这套部署用于替代 ChatGPT Work 云电脑直接联网。Work 环境如果无法解析 GitHub、东财、腾讯等域名，就不要再让 Work 负责数据采集；改为让 ChatGPT Skill 调用 Vercel 上的只读 MCP。

## 部署目标

仓库：`GeorgeCao1987/Big-A-chovy`

分支：`feature/alang-cloud-plugin-v2`

Vercel 直接导入整个仓库，Root Directory 保持仓库根目录，不需要 Docker。

本分支新增：

- `api/alang_mcp.py`：无状态 MCP 入口。
- `api/health.py`：DNS/HTTPS 连通性检查。
- `vercel.json`：把 `/mcp` 和 `/health` 映射到上述函数。

根目录原有 `requirements.txt` 已包含数据采集所需的 `requests` 与 `PyYAML`，此 Vercel 入口自身只使用 Python 标准库，因此不需要修改原依赖文件。

## Vercel 操作

1. 在 Vercel 选择 **Add New → Project**。
2. 导入 `GeorgeCao1987/Big-A-chovy`。
3. Branch 选择 `feature/alang-cloud-plugin-v2`（合并后可改 main）。
4. Framework Preset 选择 `Other` 或保持自动识别。
5. Root Directory 保持 `./`。
6. 不需要填写 Build Command、Start Command、环境变量或数据库。
7. Deploy。

## 部署后先测试

假设 Vercel 给出的域名是：

`https://your-project.vercel.app`

先访问：

`https://your-project.vercel.app/health`

正常应返回 JSON，并逐项显示：

- `push2delay.eastmoney.com`
- `qt.gtimg.cn`
- `money.finance.sina.com.cn`
- `github.com`

每个项目会显示 `dns` 和 `https` 状态。

只要东财/腾讯/新浪至少一个行情源 HTTPS 可用，就可以继续联调；如果某个源被海外出口限制，后续工具应按数据源降级处理，而不是伪造数据。

然后访问：

`https://your-project.vercel.app/mcp`

GET 只用于探活，应看到 `service=alang-stock-data`。正式 MCP 调用使用 POST。

## ChatGPT 连接地址

最终远程 MCP 地址就是：

`https://your-project.vercel.app/mcp`

连接成功后先调用 `health_check`，再调用：

- `market_snapshot`
- `sector_rank`
- `scan_candidates`
- `stock_detail`

## 设计边界

Vercel 只负责实时数据与 Big-A 候选发现；最终判断仍由 `skills/alang-stock/SKILL.md` 执行。

Big-A 的 A/B/C、dual pool、intersection 等标签不能直接解释为买点。

本方案仍遵守：不自动下单、数据缺失要明确标注、不得用旧数据冒充实时数据。
