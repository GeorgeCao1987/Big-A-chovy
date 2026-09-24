# 阿狼 × Big-A-chovy Plugin

这是一个**完全新增、与上游代码隔离**的扩展目录。

目标：

- Big-A-chovy 继续负责实时行情、量化筛选和候选发现。
- ChatGPT 中的 `alang-stock` Skill 负责按阿狼体系做最终分析。
- 不修改根目录原有筛选器、`盘中` Skill、《选股框架.md》或上游文件，方便以后继续同步 upstream。
- 不自动下单。

## 目录

```text
extensions/alang-stock-plugin/
├── plugin.json
├── mcp.example.json
├── README.md
├── cloud/
│   ├── requirements.txt
│   └── server.py
└── skills/
    └── alang-stock/
        ├── SKILL.md
        └── references/
            └── fusion-rules.md
```

## 云端提供的 4 个工具

### `market_snapshot`

快速取得上证、深证成指、沪深300、科创50实时状态，以及 5/10/13/20/60/144 日均线。

### `sector_rank`

扫描行业板块，返回涨幅、成交额、主力净额、上涨/下跌家数，并提供一个透明的融合辅助分用于缩小研究范围。

### `scan_candidates`

直接调用仓库现有 `a_share_daily_screen.py`，保留 Big-A-chovy 原来的 strict / low / watchlist / dual pool / 资金 / 公告等筛选逻辑。

### `stock_detail`

取得单股实时行情、五档、分时、15分钟聚合、日K均线和公告风险。

## Render Free 部署

不需要本地 Python、Docker 或服务器。

在 Render 创建 **Web Service**，连接你的 GitHub 仓库，设置：

```text
Branch: 合并本扩展后的分支/main
Build Command:
pip install -r extensions/alang-stock-plugin/cloud/requirements.txt

Start Command:
python extensions/alang-stock-plugin/cloud/server.py
```

服务启动后，MCP 地址为：

```text
https://<你的Render服务名>.onrender.com/mcp
```

首版不需要数据库，也不需要任何密钥。

> Render 免费实例休眠后第一次调用会有冷启动延迟，这是免费方案的正常行为。

## 部署后生成可安装 Plugin

Render URL 确认后：

1. 将 `mcp.example.json` 复制为插件根目录下的 `mcp.json`。
2. 把其中的 `YOUR-RENDER-SERVICE` 替换为实际服务名。
3. 在 `plugin.json` 增加：

```json
"mcpServers": "./mcp.json"
```

这一步等真实 URL 出来后再做，避免仓库里长期保存一个无效 MCP 地址。

最终插件包就是整个：

```text
extensions/alang-stock-plugin/
```

## 数据与决策边界

云端只做**看见市场**：取数据、跑筛选、返回结构化证据。

Skill 负责**理解市场**：

```text
大盘
→ 板块
→ Big-A候选
→ 阿狼趋势阶段
→ 量价确认
→ 风险/基本面补证据
→ 条件策略
```

Big-A-chovy 的 A/B/C、dual pool、intersection 等标签不得直接解释成“可以买”。

## 首版有意保留的缺口

为了先把免费云端链路跑通，首版不会伪造或强行实现：

- 昨日同期成交额/成交量。
- 完整逐笔主动买卖。
- A50、期指、两融、GJD ETF 的组合判断。
- 完整公司基本面、CAPEX 和海外产业链数据。

这些后续可以继续以**新增文件/新增工具**方式扩展，不需要改动上游筛选器。
