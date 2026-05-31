# 神农系统 — 运维手册

> 详细使用说明见 **[USER.md](./USER.md)**（完整参数说明、命令示例、验证结果）

本文档只记录运维相关的快速参考，不重复 USER.md 中的技术细节。

---

## 快速启动

```bash
cd ~/.hermes/investment
python3 main/shennong.py --mode full --market CN
```

##常用运维命令

```bash
# 查看冻结状态
python3 -c "import json; f=open('main/freeze_table.json'); d=json.load(f); print(f'冻结:{len(d[\"freeze_records\"])} 观察:{len(d[\"observing_list\"])} 买入信号:{len(d[\"buy_signals\"])}')"

# 实时日志
tail -f ~/.hermes/investment/logs/hermes.log

# 按数据源查日志
grep "[source=akshare]" ~/.hermes/investment/logs/hermes.log
grep "[ERROR]" ~/.hermes/investment/logs/hermes.log
```

## Cron 配置

`~/.hermes/cron/jobs.json`：

```json
{
  "script": "cd /Users/guchuang/.hermes/investment && python3 main/shennong.py --mode full --market CN",
  "prompt": null,
  "deliver": "local"
}
```

## 关键路径

| 路径 | 说明 |
|---|---|
| `~/.hermes/investment/main/shennong.py` | 统一入口 |
| `~/.hermes/investment/main/freeze_table.json` | 冷冻股表 |
| `~/.hermes/investment/platform/backend/platform.db` | SQLite 数据库 |
| `~/.hermes/investment/logs/hermes.log` | 日志 |
| `~/.hermes/investment/docs/USER.md` | **完整使用手册（以此为准）** |