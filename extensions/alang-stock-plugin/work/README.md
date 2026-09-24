# ChatGPT Work 试运行方案

这个目录用于**不部署服务器、不使用本地环境**的试运行。

Work 云电脑临时取得仓库、安装依赖、运行 `runner.py`；ChatGPT 再按 `alang-stock-work` Skill 做最终分析。

## 试运行前提

仓库：

```text
GeorgeCao1987/Big-A-chovy
```

当前开发分支：

```text
feature/alang-cloud-plugin-v2
```

合并后可直接使用 `main`。

## Work 需要执行的准备

```bash
python -m pip install -r requirements.txt
```

不需要 Docker，不需要数据库，不需要启动实时看板。

## 四个入口

### 大盘

```bash
python extensions/alang-stock-plugin/work/runner.py market
```

### 板块

```bash
python extensions/alang-stock-plugin/work/runner.py sectors --top 30
```

### 全市场候选

```bash
python extensions/alang-stock-plugin/work/runner.py scan --mode all --top 15
```

### 单股

```bash
python extensions/alang-stock-plugin/work/runner.py stock 002916
```

所有命令标准输出都是 JSON，便于模型直接读取；错误应作为数据缺口处理，不允许模型自行补值。

## 最简单的测试提示词

在 ChatGPT Work 中给出：

> 使用仓库 `GeorgeCao1987/Big-A-chovy` 的 `feature/alang-cloud-plugin-v2` 分支，按 `extensions/alang-stock-plugin/skills/alang-stock-work/SKILL.md` 执行。先判断今天大盘，再扫描行业和全市场候选，最后按阿狼体系只留下少数值得研究的主板股票。不要自动下单。

单股测试：

> 按 `alang-stock-work` Skill 分析深南电路 002916。必须先看大盘和所属方向，再看15分钟、量价、资金和关键位置，最后给条件策略。

## 这版重点观察什么

第一轮主要验证：

1. Work 云电脑能否直接访问东财/腾讯行情。
2. Big-A 原筛选脚本能否在无本机代理环境完成全市场扫描。
3. 单次全市场扫描耗时是否能接受。
4. `market → sectors → scan → stock` 数据是否足够支持阿狼的二次判断。
5. 哪些缺口必须进入第二版，而不是一次性把系统做复杂。

## 已知缺口

首版主动不实现：

- 昨日同期成交额/成交量缓存。
- 黄白线。
- GJD ETF 组合迹象。
- 两融变化。
- A50 / 股指期货。
- 完整逐笔主动买卖。
- 完整基本面、CAPEX、海外产业链数据。

这些字段缺少时，Skill 必须明确写“尚未确认”，不能用其他指标代替。

## 与原仓库的关系

本试运行方案全部位于：

```text
extensions/alang-stock-plugin/
```

不要求修改上游已有文件。以后同步 `LuQTest/Big-A-chovy` 时，本目录可以独立保留。
