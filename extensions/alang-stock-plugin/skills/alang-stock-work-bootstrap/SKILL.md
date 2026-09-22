---
name: alang-stock-work-bootstrap
description: 在ChatGPT Work中执行阿狼×Big-A-chovy时，先可靠取得GitHub仓库；遇到net::ERR_HTTP2_PROTOCOL_ERROR或仓库未挂载时，不走浏览器HTTP/2，改用Git HTTP/1.1或GitHub codeload ZIP，再执行runner并输出真实执行回执。
---

# 阿狼 × Big-A-chovy · Work 启动 Skill

## 目标

解决 Work/云电脑在“执行指定仓库”时可能出现的：

```text
net::ERR_HTTP2_PROTOCOL_ERROR
```

该错误属于浏览器/HTTP2传输路径失败，不应被解释成仓库不存在，也不应在失败后跳过程序直接生成股票结论。

## 硬规则

1. 不使用浏览器页面打开 GitHub 仓库作为执行前提。
2. 如果工作目录已经存在 `Big-A-chovy/extensions/alang-stock-plugin/work/runner.py`，直接复用。
3. 如果仓库不存在，优先用 Git HTTP/1.1 clone。
4. Git clone 失败时，用 `curl --http1.1` 下载 GitHub codeload ZIP。
5. 只有检测到 `runner.py` 后，才允许声称仓库准备完成。
6. 只有实际运行 runner 并看到 JSON 输出，才允许声称执行了市场/板块/筛选/单股入口。
7. 浏览器 HTTP2 报错后不得自行改用网页行情假装完成 Big-A 扫描。

## 仓库准备

在 Work 云电脑执行：

```bash
if [ -f Big-A-chovy/extensions/alang-stock-plugin/work/runner.py ]; then
  echo '{"alang_bootstrap":true,"event":"reuse_existing"}'
else
  rm -rf Big-A-chovy
  git -c http.version=HTTP/1.1 clone --depth 1 --single-branch \
    --branch feature/alang-cloud-plugin-v2 \
    https://github.com/GeorgeCao1987/Big-A-chovy.git Big-A-chovy \
  || true
fi
```

若上一步没有得到 `runner.py`，执行 HTTP/1.1 ZIP fallback：

```bash
rm -rf Big-A-chovy /tmp/alang-repo.zip /tmp/alang-repo-unpack
curl --http1.1 -fL --retry 5 --retry-all-errors --retry-delay 2 \
  --connect-timeout 20 --max-time 180 \
  https://codeload.github.com/GeorgeCao1987/Big-A-chovy/zip/refs/heads/feature/alang-cloud-plugin-v2 \
  -o /tmp/alang-repo.zip
mkdir -p /tmp/alang-repo-unpack
python - <<'PY'
import shutil, zipfile
from pathlib import Path
z=Path('/tmp/alang-repo.zip')
out=Path('/tmp/alang-repo-unpack')
with zipfile.ZipFile(z) as f:
    f.extractall(out)
roots=[p for p in out.iterdir() if p.is_dir()]
assert len(roots)==1, roots
src=roots[0]
assert (src/'extensions/alang-stock-plugin/work/runner.py').is_file()
shutil.move(str(src), 'Big-A-chovy')
print('{"alang_bootstrap":true,"event":"ready_codeload_http1"}')
PY
```

随后必须验证：

```bash
test -f Big-A-chovy/extensions/alang-stock-plugin/work/runner.py
cd Big-A-chovy
python -m pip install -r requirements.txt
```

## 执行回执

仓库准备完成后，先输出并核对：

```bash
pwd
git rev-parse --short HEAD 2>/dev/null || true
python --version
ls -l extensions/alang-stock-plugin/work/runner.py
```

然后才执行四个数据入口。

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

## 成功判定

必须同时满足：

- 仓库目录真实存在。
- `runner.py`真实存在。
- 至少一个 runner 命令退出码为 0。
- 标准输出能解析为 JSON。
- JSON 中有真实时间戳/数据源/结果字段。

缺任一项，只能报告“执行尚未完成”，不得生成假装来自 Big-A 的扫描结果。

## 后续分析

仓库成功执行后，再读取同分支：

```text
extensions/alang-stock-plugin/skills/alang-stock-work/SKILL.md
```

按其中规则完成：

大盘 → 板块 → 候选 → 单股 → 阿狼趋势阶段 → 量价 → 条件策略。
