#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L5 Freeze Manager（冷冻管理层）

职责：读取执行记录，更新冷冻表。不主动选股，不在分析热路径上。

冷冻规则：
- 10天冷冻：初筛失败1次
- 3个月冷冻：10天到期重跑仍失败，或3条件同时触发

3条件同时触发（直接3个月冷冻）：
1. 主力近5日净流出 > 1亿
2. 均线空头排列（MA5 < MA10 < MA20）
3. 外内盘比 < 0.75
"""

import json
import os
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Set
from pathlib import Path

logger = logging.getLogger("freeze_manager")

# ======================== 路径配置 ========================

PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))

FREEZE_TABLE_PATHS = {
    "CN": PROJECT_ROOT / "main" / "freeze_table.json",
    "HK": PROJECT_ROOT / "main" / "freeze_table_hk.json",
    "US": PROJECT_ROOT / "main" / "freeze_table_us.json",
}

# ======================== 冷冻规则常量 ========================

FREEZE_10_DAYS = timedelta(days=10)
FREEZE_3_MONTHS = timedelta(days=90)

# 3个月冷冻触发条件阈值
THRESH_MAIN_NET_FLOW = -100_000_000  # -1亿
THRESH_OUTER_INNER_RATIO = 0.75


class FreezeManager:
    """冷冻状态管理器（支持 CN/HK/US 市场）"""

    def __init__(self, market: str = "CN"):
        self.market = market.upper()
        self.freeze_table_path = FREEZE_TABLE_PATHS.get(self.market, FREEZE_TABLE_PATHS["CN"])
        self.freeze_table = self._load_freeze_table()

    def _load_freeze_table(self) -> dict:
        """加载冷冻表"""
        if not self.freeze_table_path.exists():
            return {"freeze_records": [], "observing_list": [], "buy_signals": []}
        try:
            with open(self.freeze_table_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"冷冻表加载失败: {e}，返回空表")
            return {"freeze_records": [], "observing_list": [], "buy_signals": []}

    def _save_freeze_table(self) -> bool:
        """保存冷冻表"""
        try:
            self.freeze_table_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.freeze_table_path, "w", encoding="utf-8") as f:
                json.dump(self.freeze_table, f, ensure_ascii=False, indent=2)
            logger.info(f"冷冻表已保存: {self.freeze_table_path}")
            return True
        except IOError as e:
            logger.error(f"冷冻表保存失败: {e}")
            return False

    def get_frozen_codes(self) -> Set[str]:
        """获取当前冷冻股票代码集合"""
        today = date.today().strftime("%Y-%m-%d")
        frozen = set()
        for record in self.freeze_table.get("freeze_records", []):
            if record.get("status") == "frozen" and record.get("frozen_until", "") > today:
                frozen.add(record["stock_code"])
        return frozen

    def get_observing_list(self) -> List[dict]:
        """获取观察池列表"""
        return self.freeze_table.get("observing_list", [])

    def get_buy_signals(self) -> List[dict]:
        """获取待推送买入信号"""
        return self.freeze_table.get("buy_signals", [])

    def check_and_update_freeze(self, market: str = None) -> Dict[str, List]:
        """
        每日收盘后调用：检查冷冻到期，更新状态

        Args:
            market: 市场标识 CN/HK/US。若不指定则使用初始化时指定的市场。

        Returns:
            {"expired": [], "upgraded": [], "unfrozen": []}
        """
        # Delegate to market-specific instance if needed
        if market and market.upper() != self.market:
            other = FreezeManager(market=market)
            return other.check_and_update_freeze()

        today = date.today()
        today_str = today.strftime("%Y-%m-%d")
        results = {"expired": [], "upgraded": [], "unfrozen": []}

        for record in self.freeze_table.get("freeze_records", []):
            if record.get("status") != "frozen":
                continue

            frozen_until_str = record.get("frozen_until", "")
            if not frozen_until_str:
                continue

            frozen_until = datetime.strptime(frozen_until_str, "%Y-%m-%d").date()

            if frozen_until <= today:
                # 到期，需要重跑验证
                verification_result = self._verify_and_update(record)
                action = verification_result.get("action")

                if action == "upgrade":
                    results["upgraded"].append(record["stock_code"])
                elif action == "unfreeze":
                    results["unfrozen"].append(record["stock_code"])

                results["expired"].append(record["stock_code"])

        self._save_freeze_table()
        self._update_state_pool(results)
        return results

    def _get_data_for_verification(self, stock_code: str, stock_name: str) -> tuple:
        """
        根据市场获取数据，用于冻结验证。

        Returns:
            (moneyflow_data, technical_data) or ({}, {}) on failure

        使用 L2 统一入口 fetch_market_data，避免跨层引用 L4_judge.utils
        """
        try:
            if self.market == "CN":
                import sys
                PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))
                sys.path.insert(0, str(PROJECT_ROOT))
                from L2_data_enrich.data_fetcher import fetch_all
                data = fetch_all(stock_code, stock_name)
                return data.get("moneyflow_data", {}), data.get("technical_data", {})

            elif self.market in ("HK", "US"):
                # 使用 L2 统一入口，避免跨层引用 L4
                import sys
                PROJECT_ROOT = Path(os.path.expanduser("~/.hermes/investment"))
                sys.path.insert(0, str(PROJECT_ROOT))
                from L2_data_enrich.core.market_fetcher import fetch_market_data

                data = fetch_market_data(stock_code, self.market)
                return data.get("moneyflow_data", {}), data.get("technical_data", {})

        except Exception as e:
            logger.warning(f"[{self.market}] 获取{stock_code}数据失败: {e}")
        return {}, {}

    def _verify_and_update(self, record: dict) -> dict:
        """
        重跑验证逻辑：读取最新资金流、均线、外内盘数据，判断是否解冻/升级

        3条件同时触发 → 升级3个月冷冻
        任意1条触发 → 续期10天
        0条触发 → 解冻

        HK/US市场：仅使用MA空头排列条件（其他数据不可直接对比）
        """
        stock_code = record["stock_code"]
        stock_name = record.get("stock_name", stock_code)
        check_count = record.get("check_count", 0) + 1

        # 1. 获取最新数据
        mf, tc = self._get_data_for_verification(stock_code, stock_name)
        if not mf and not tc:
            logger.warning(f"获取{stock_code}数据失败，使用续期")
            record["frozen_until"] = (date.today() + FREEZE_10_DAYS).strftime("%Y-%m-%d")
            record["last_checked"] = date.today().strftime("%Y-%m-%d")
            record["check_count"] = check_count
            return {"action": "extend", "record": record}

        # 2. 判断冻结条件
        main_net_flow_5d = mf.get("main_net_flow_5d", 0)
        outer_inner_ratio = mf.get("outer_inner_ratio", 1.0)
        ma5 = tc.get("ma5")
        ma10 = tc.get("ma10")
        ma20 = tc.get("ma20")

        cond1_main_outflow = (main_net_flow_5d is not None) and (main_net_flow_5d < THRESH_MAIN_NET_FLOW)
        cond2_bearish_ma = all(v is not None for v in [ma5, ma10, ma20]) and (ma5 < ma10 < ma20)
        cond3_outer_inner = (outer_inner_ratio is not None) and (outer_inner_ratio < THRESH_OUTER_INNER_RATIO)

        # HK/US市场：外内盘比不可用，跳过该条件
        if self.market in ("HK", "US"):
            triggered_count = int(cond1_main_outflow) + int(cond2_bearish_ma)
            logger.info(f"  冻结验证 [{self.market}] {stock_code}: 主力={main_net_flow_5d/1e6:.1f}万({'❌流出' if cond1_main_outflow else '✅'}), "
                        f"MA空头={'❌' if cond2_bearish_ma else '✅'} (外内盘比: N/A)")
        else:
            triggered_count = sum([cond1_main_outflow, cond2_bearish_ma, cond3_outer_inner])
            logger.info(f"  冻结验证 {stock_code}: 主力={main_net_flow_5d/1e6:.1f}万({'❌流出' if cond1_main_outflow else '✅'}), "
                        f"MA空头={'❌' if cond2_bearish_ma else '✅'}, 外内盘比={outer_inner_ratio:.2f}({'❌低' if cond3_outer_inner else '✅'})")

        # 3. 决策
        if triggered_count == 3 or (triggered_count >= 1 and record.get("freeze_level") == "3months"):
            # 升级3个月（3条件全触发，或3个月股再次触发1条以上）
            record["freeze_level"] = "3months"
            record["frozen_until"] = (date.today() + FREEZE_3_MONTHS).strftime("%Y-%m-%d")
            record["last_checked"] = date.today().strftime("%Y-%m-%d")
            record["check_count"] = check_count
            return {"action": "upgrade", "record": record}
        elif triggered_count >= 1:
            # 续期10天（任意1条触发）
            record["frozen_until"] = (date.today() + FREEZE_10_DAYS).strftime("%Y-%m-%d")
            record["last_checked"] = date.today().strftime("%Y-%m-%d")
            record["check_count"] = check_count
            return {"action": "extend", "record": record}
        else:
            # 解冻（0条触发）
            record["status"] = "unfrozen"
            record["unfrozen_date"] = date.today().strftime("%Y-%m-%d")
            record["last_checked"] = date.today().strftime("%Y-%m-%d")
            record["check_count"] = check_count
            return {"action": "unfreeze", "record": record}

    def add_freeze(self, stock_code: str, stock_name: str,
                   level: str, reason: List[str]) -> bool:
        """
        添加冷冻记录

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            level: "10days" | "3months"
            reason: 失败原因列表
        """
        if level == "10days":
            frozen_until = date.today() + FREEZE_10_DAYS
        elif level == "3months":
            frozen_until = date.today() + FREEZE_3_MONTHS
        else:
            logger.error(f"无效冷冻级别: {level}")
            return False

        # 检查是否已存在
        for record in self.freeze_table.get("freeze_records", []):
            if record["stock_code"] == stock_code:
                logger.warning(f"{stock_code} 已在冷冻表中")
                return False

        new_record = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "freeze_level": level,
            "frozen_until": frozen_until.strftime("%Y-%m-%d"),
            "fail_reasons": reason,
            "last_checked": date.today().strftime("%Y-%m-%d"),
            "check_count": 0,
            "status": "frozen"
        }

        self.freeze_table["freeze_records"].append(new_record)
        self._save_freeze_table()
        self._create_frozen_markdown(new_record)
        logger.info(f"添加冷冻记录: {stock_code} {stock_name} {level}")
        return True

    def unfreeze(self, stock_code: str) -> bool:
        """解冻股票"""
        for record in self.freeze_table.get("freeze_records", []):
            if record["stock_code"] == stock_code:
                record["status"] = "unfrozen"
                record["unfrozen_date"] = date.today().strftime("%Y-%m-%d")
                self._save_freeze_table()
                self._move_to_observing(record)
                logger.info(f"解冻股票: {stock_code}")
                return True
        logger.warning(f"股票不在冷冻表中: {stock_code}")
        return False

    def record_buy_signal(self, stock_code: str, stock_name: str,
                          judge_score: float, price: float,
                          stop_loss: float, take_profit: float,
                          kelly_fraction: float, reason: str = "") -> bool:
        """
        记录买入信号（BUY决策时调用）

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            judge_score: 裁判评分
            price: 当前价格
            stop_loss: 止损价
            take_profit: 止盈价
            kelly_fraction: 凯利仓位
            reason: 买入理由
        """
        signal = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "judge_score": round(judge_score, 3),
            "price": round(price, 2) if price else 0,
            "stop_loss": round(stop_loss, 2) if stop_loss else 0,
            "take_profit": round(take_profit, 2) if take_profit else 0,
            "kelly_fraction": round(kelly_fraction, 4) if kelly_fraction else 0,
            "signal_date": date.today().strftime("%Y-%m-%d"),
            "reason": reason,
            "status": "pending",  # pending / executed / expired
        }
        self.freeze_table.setdefault("buy_signals", []).append(signal)
        self._save_freeze_table()
        logger.info(f"记录买入信号: {stock_code} {stock_name} judge={judge_score:.3f} @ {price}")
        return True

    def _create_frozen_markdown(self, record: dict) -> None:
        """创建冷冻状态Markdown文件（已迁移到DB，此处为空）"""
        pass

    def _move_to_observing(self, record: dict) -> None:
        """移动到观察池（已迁移到DB，此处为空）"""
        pass

    def _update_state_pool(self, results: dict) -> None:
        """更新状态池"""
        for code in results.get("upgraded", []):
            logger.info(f"升级冷冻: {code}")

        for code in results.get("unfrozen", []):
            logger.info(f"解冻: {code}")

    def get_summary(self) -> dict:
        """获取冷冻状态摘要"""
        frozen = [r for r in self.freeze_table.get("freeze_records", [])
                  if r.get("status") == "frozen"]
        observing = self.freeze_table.get("observing_list", [])
        buy_signals = self.freeze_table.get("buy_signals", [])

        return {
            "frozen_count": len(frozen),
            "observing_count": len(observing),
            "buy_signals_count": len(buy_signals),
            "frozen_codes": [r["stock_code"] for r in frozen],
            "next_check": min([r["frozen_until"] for r in frozen], default=None)
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="L5 Freeze Manager")
    parser.add_argument("--market", "-m", default="CN",
                        choices=["CN", "HK", "US"],
                        help="市场标识 (默认: CN)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    fm = FreezeManager(market=args.market)

    print(f"\n[{args.market}] 冷冻状态摘要:")
    summary = fm.get_summary()
    print(f"  冷冻中: {summary['frozen_count']} 只")
    print(f"  观察池: {summary['observing_count']} 只")
    print(f"  买入信号: {summary['buy_signals_count']} 只")
    if summary.get("frozen_codes"):
        print(f"  冷冻股票: {', '.join(summary['frozen_codes'])}")
    if summary.get("next_check"):
        print(f"  下次检查: {summary['next_check']}")
