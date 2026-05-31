#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
神农批处理运行器 - 统一批处理入口

支持：
1. 任意时间手动触发（不只是早晨）
2. 批大小可配置
3. Run级别数据隔离
4. 故障恢复
5. 新鲜/缓存数据模式

使用方式：
  from main.batch_runner import ShennongBatchRunner

  runner = ShennongBatchRunner(batch_size=50, fresh_data=False)
  result = runner.run(stocks)

  # 查询状态
  status = runner.get_status()
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("batch_runner")


class BatchState(Enum):
    """批次状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # 部分完成


@dataclass
class BatchJob:
    """批次作业"""
    batch_run_id: str
    batch_index: int
    stocks: List[Dict[str, str]]  # [{"code": "600519", "name": "贵州茅台"}, ...]
    state: BatchState = BatchState.PENDING
    started_at: str = None
    completed_at: str = None
    l3_results: List[Dict] = field(default_factory=list)
    l4_decisions: List[Dict] = field(default_factory=list)
    error: str = None
    retry_count: int = 0
    total_count: int = 0
    success_count: int = 0
    fail_count: int = 0

    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now().isoformat()
        self.total_count = len(self.stocks)


@dataclass
class BatchCheckpoint:
    """批处理检查点"""
    batch_run_id: str
    batch_index: int
    processed_indices: List[int]  # 已处理的股票下标
    stock_states: Dict[str, str]  # code -> PENDING/PROCESSING/COMPLETED/FAILED
    results: Dict[str, Dict]  # code -> L3/L4结果
    started_at: str
    updated_at: str
    error: str = None


class ShennongBatchRunner:
    """
    统一批处理运行器

    支持：
    1. 任意时间手动触发（不只是早晨）
    2. 批大小可配置
    3. Run级别数据隔离
    4. 故障恢复
    5. 新鲜/缓存数据模式
    """

    def __init__(
        self,
        batch_size: int = 50,
        run_id: str = None,
        fresh_data: bool = False,
        cache_ttl: int = 1800,
        max_retries: int = 3,
        max_workers: int = 5,
        checkpoint_dir: str = None,
    ):
        """
        Args:
            batch_size: 每批处理的股票数量
            run_id: 批次唯一标识，不提供则自动生成
            fresh_data: True=强制刷新数据，不使用缓存
            cache_ttl: 缓存过期时间（秒）
            max_retries: 最大重试次数
            max_workers: 并行worker数
            checkpoint_dir: 检查点目录
        """
        self.batch_size = batch_size
        self.run_id = run_id or self._generate_run_id()
        self.fresh_data = fresh_data
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.max_workers = max_workers

        # 检查点目录
        if checkpoint_dir is None:
            checkpoint_dir = os.path.expanduser("~/.hermes/investment/main/checkpoints")
        self.checkpoint_dir = Path(checkpoint_dir) / self.run_id
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # 加载配置
        self._load_config()

        # 缓存管理器
        from main.cache_manager import CacheManager
        self.cache = CacheManager(
            run_id=self.run_id,
            ttl_seconds=cache_ttl,
            enabled=not fresh_data,
        )

        # 当前批次索引
        self.current_batch_index = 0

        # 统计
        self.stats = {
            "total_stocks": 0,
            "success_count": 0,
            "fail_count": 0,
            "start_time": None,
            "end_time": None,
            "elapsed_seconds": 0,
        }

        logger.info(
            f"ShennongBatchRunner初始化: run_id={self.run_id}, "
            f"batch_size={batch_size}, fresh_data={fresh_data}"
        )

    def _generate_run_id(self) -> str:
        """生成批次唯一ID"""
        return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _load_config(self):
        """加载批处理配置"""
        config_path = Path("~/.hermes/investment/main/config/l4_batch_config.json").expanduser()
        try:
            with open(config_path) as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.config = {}

    def run(
        self,
        stocks: List[Dict[str, str]],
        mode: str = "incremental",
    ) -> Dict[str, Any]:
        """
        运行批处理

        Args:
            stocks: 股票列表 [{"code": "600519", "name": "贵州茅台"}, ...]
            mode: 运行模式
                - "full": 从头开始处理所有股票
                - "incremental": 增量处理（跳过已完成的）
                - "resume": 从检查点恢复

        Returns:
            运行结果字典
        """
        self.stats["start_time"] = datetime.now().isoformat()
        self.stats["total_stocks"] = len(stocks)

        logger.info(f"开始批处理: mode={mode}, stocks={len(stocks)}")

        # 分批处理
        all_results = []
        all_decisions = []

        for i in range(0, len(stocks), self.batch_size):
            batch_stocks = stocks[i:i + self.batch_size]
            batch_index = i // self.batch_size

            logger.info(f"处理批次 {batch_index + 1}: {len(batch_stocks)} 只股票")

            job = BatchJob(
                batch_run_id=self.run_id,
                batch_index=batch_index,
                stocks=batch_stocks,
                state=BatchState.PROCESSING,
            )

            try:
                batch_result = self._execute_batch(job)

                all_results.extend(batch_result.get("l3_results", []))
                all_decisions.extend(batch_result.get("l4_decisions", []))

                self.stats["success_count"] += batch_result.get("success_count", 0)
                self.stats["fail_count"] += batch_result.get("fail_count", 0)

                # 保存检查点
                self._save_checkpoint(job, batch_result)

            except Exception as e:
                logger.error(f"批次 {batch_index} 执行失败: {e}")
                self.stats["fail_count"] += len(batch_stocks)
                job.state = BatchState.FAILED
                job.error = str(e)

        self.stats["end_time"] = datetime.now().isoformat()
        elapsed = (datetime.now() - datetime.fromisoformat(self.stats["start_time"])).total_seconds()
        self.stats["elapsed_seconds"] = elapsed

        result = {
            "status": "completed",
            "batch_run_id": self.run_id,
            "l3_results": all_results,
            "l4_decisions": all_decisions,
            "stats": self.stats,
            "cache_stats": self.cache.get_stats(),
        }

        logger.info(
            f"批处理完成: success={self.stats['success_count']}, "
            f"fail={self.stats['fail_count']}, elapsed={elapsed:.1f}s"
        )

        return result

    def _execute_batch(self, job: BatchJob) -> Dict[str, Any]:
        """
        执行单个批次

        Args:
            job: 批次作业

        Returns:
            批次执行结果
        """
        l3_results = []
        l4_decisions = []
        success_count = 0
        fail_count = 0

        # 设置路径
        project_root = Path("~/.hermes/investment").expanduser()
        sys.path.insert(0, str(project_root))

        for i, stock in enumerate(job.stocks):
            code = stock.get("code", "")
            name = stock.get("name", code)

            try:
                logger.debug(f"处理: {code} {name}")

                # 调用完整的pipeline处理单只股票
                # 这样确保L2→L3→L4全部正确执行
                from main.shennong import run_pipeline_for_stock

                stock_info = {"code": code, "name": name}
                pipeline_context = {
                    "run_date": datetime.now().strftime("%Y-%m-%d"),
                    "mode": "batch",
                    "market": "CN",
                }

                result = run_pipeline_for_stock(
                    stock_info=stock_info,
                    pipeline_context=pipeline_context,
                    skip_persona=True,  # 批处理跳过人格轨加速
                )

                # 提取L3结果
                l3 = result.get("L3", {})
                if l3.get("results"):
                    l3_results.extend(l3["results"])

                # 提取L4决策
                l4 = result.get("L4", {})
                if l4.get("decisions"):
                    l4_decisions.extend(l4["decisions"])

                success_count += 1

            except Exception as e:
                logger.error(f"处理失败: {code} {name}, error={e}")
                fail_count += 1

        return {
            "l3_results": l3_results,
            "l4_decisions": l4_decisions,
            "success_count": success_count,
            "fail_count": fail_count,
        }

    def _fetch_stock_data(self, code: str, name: str) -> Dict[str, Any]:
        """获取股票数据（支持缓存）"""
        cache_key = f"stock_data_{code}"

        # 尝试从缓存获取
        if not self.fresh_data:
            cached = self.cache.get(cache_key)
            if cached:
                logger.debug(f"缓存命中: {code}")
                return cached

        # 实际获取数据
        # 调用 L2 data fetcher
        try:
            from L2_data_enrich.data_fetcher import fetch_all
            data = fetch_all(code, name)
        except ImportError:
            # 简化版本：直接构造空数据
            logger.warning(f"L2 fetcher导入失败，使用空数据: {code}")
            data = {}

        # 写入缓存
        self.cache.set(cache_key, data)
        return data

    def _run_l3_score(self, code: str, name: str, l2_data: Dict) -> Dict[str, Any]:
        """运行L3评分"""
        try:
            from L3_quant_analysis.scoring.five_dimension_scorer import FiveDimensionScorer
            score_obj = FiveDimensionScorer().score_stock(code, name, l2_data)
            return score_obj.to_dict()
        except Exception as e:
            logger.error(f"L3评分失败: {code}, error={e}")
            return {"code": code, "name": name, "error": str(e)}

    def _run_l4_judge(self, code: str, name: str, l2_data: Dict, l3_result: Dict) -> Dict[str, Any]:
        """运行L4判决"""
        try:
            from L4_judge.risk.risk_manager import RiskManager

            rm = RiskManager()

            # 从l2_data提取价格
            price = 50.0
            if isinstance(l2_data, dict):
                price = float(l2_data.get("price", l2_data.get("technical_data", {}).get("price", 50.0)))

            # assess_stock_risk签名: (stock_code, stock_name, current_price, historical_volatility=0.0, score_result=None)
            assessment = rm.assess_stock_risk(
                stock_code=code,
                stock_name=name,
                current_price=price,
                score_result=l3_result,
            )

            return {
                "code": code,
                "name": name,
                "decision": "WATCH",
                "judge_score": 0.0,
                "risk_score": assessment.risk_score,
                "volatility": assessment.volatility,
                "kelly_fraction": assessment.kelly_fraction,
                "recommended_weight": assessment.recommended_weight,
                "stop_loss": assessment.stop_loss_price,
                "take_profit": assessment.take_profit_price,
            }
        except Exception as e:
            logger.error(f"L4判决失败: {code}, error={e}")
            return {
                "code": code,
                "name": name,
                "decision": "WATCH",
                "judge_score": 0,
                "error": str(e),
            }

    def _save_checkpoint(self, job: BatchJob, result: Dict):
        """保存检查点"""
        checkpoint = BatchCheckpoint(
            batch_run_id=self.run_id,
            batch_index=job.batch_index,
            processed_indices=[i for i in range(len(job.stocks))],
            stock_states={s["code"]: "COMPLETED" for s in job.stocks},
            results={s["code"]: r for s, r in zip(job.stocks, result.get("l4_decisions", []))},
            started_at=job.started_at,
            updated_at=datetime.now().isoformat(),
        )

        checkpoint_path = self.checkpoint_dir / f"batch_{job.batch_index}.json"
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(asdict(checkpoint), f, ensure_ascii=False, default=str)

        logger.debug(f"检查点已保存: {checkpoint_path}")

    def get_status(self, batch_run_id: str = None) -> Dict[str, Any]:
        """
        查询批次运行状态

        Args:
            batch_run_id: 可选，不提供则查询当前run

        Returns:
            状态信息
        """
        run_id = batch_run_id or self.run_id
        checkpoint_dir = Path(self.checkpoint_dir).parent / run_id

        if not checkpoint_dir.exists():
            return {"error": f"Run不存在: {run_id}"}

        checkpoints = list(checkpoint_dir.glob("batch_*.json"))
        total_processed = 0
        total_success = 0
        total_fail = 0

        for cp_path in checkpoints:
            with open(cp_path) as f:
                cp = json.load(f)
            total_processed += len(cp.get("processed_indices", []))
            total_success += sum(1 for s in cp.get("stock_states", {}).values() if s == "COMPLETED")
            total_fail += sum(1 for s in cp.get("stock_states", {}).values() if s == "FAILED")

        return {
            "batch_run_id": run_id,
            "checkpoint_count": len(checkpoints),
            "total_processed": total_processed,
            "success_count": total_success,
            "fail_count": total_fail,
            "stats": self.stats,
            "cache_stats": self.cache.get_stats(),
        }

    def resume(self, batch_run_id: str = None) -> Dict[str, Any]:
        """
        从检查点恢复批处理

        Args:
            batch_run_id: 要恢复的run_id

        Returns:
            恢复结果
        """
        run_id = batch_run_id or self.run_id
        checkpoint_dir = Path(self.checkpoint_dir).parent / run_id

        if not checkpoint_dir.exists():
            return {"error": f"检查点不存在: {run_id}"}

        # 加载所有检查点
        checkpoints = sorted(checkpoint_dir.glob("batch_*.json"))

        # 找出未完成的股票
        pending_stocks = []
        completed_codes = set()

        for cp_path in checkpoints:
            with open(cp_path) as f:
                cp = json.load(f)

            for code, state in cp.get("stock_states", {}).items():
                if state in ("PENDING", "FAILED"):
                    pending_stocks.append({"code": code})
                    completed_codes.add(code)
                else:
                    completed_codes.add(code)

        logger.info(f"从检查点恢复: run_id={run_id}, 待处理={len(pending_stocks)}, 已完成={len(completed_codes)}")

        if not pending_stocks:
            return {
                "status": "already_completed",
                "batch_run_id": run_id,
                "message": "所有股票已处理完成",
                "completed_count": len(completed_codes),
            }

        # 继续处理
        self.run_id = f"{run_id}_resume"
        return self.run(pending_stocks, mode="incremental")


def run_manual_batch(
    stocks: List[Dict[str, str]] = None,
    batch_size: int = 50,
    fresh_data: bool = False,
    run_id: str = None,
    fresh_start: bool = False,
) -> Dict[str, Any]:
    """
    手动触发批处理的便捷函数

    Args:
        stocks: 股票列表，不提供则从当日队列获取
        batch_size: 批大小
        fresh_data: 是否强制刷新数据
        run_id: 批次标识（不提供则自动生成）
        fresh_start: 是否从头开始（清除之前的处理状态）

    Returns:
        运行结果
    """
    # 如果指定了fresh_start，清除旧状态
    if fresh_start and run_id:
        _clear_run_state(run_id)

    runner = ShennongBatchRunner(
        batch_size=batch_size,
        fresh_data=fresh_data,
        run_id=run_id,
    )

    # 如果没有提供股票列表，从当日队列获取
    if stocks is None:
        stocks = _get_stocks_from_queue()
        if not stocks:
            return {"status": "queue_empty", "message": "当日队列为空"}

    return runner.run(stocks, mode="full")


def _clear_run_state(run_id: str):
    """清除指定run的状态（缓存、检查点）"""
    from main.cache_manager import CacheManager

    # 清除缓存
    cache = CacheManager(run_id=run_id, enabled=True)
    cache.force_refresh()

    # 清除检查点
    checkpoint_dir = Path("~/.hermes/investment/main/checkpoints").expanduser() / run_id
    if checkpoint_dir.exists():
        for f in checkpoint_dir.rglob("*.json"):
            f.unlink()
        checkpoint_dir.rmdir()

    logger.info(f"已清除run状态: {run_id}")


def _get_stocks_from_queue() -> List[Dict[str, str]]:
    """从当日队列获取股票列表"""
    queue_path = Path("~/.hermes/investment/main/daily_queue.json").expanduser()

    if not queue_path.exists():
        logger.warning("当日队列不存在")
        return []

    try:
        with open(queue_path) as f:
            data = json.load(f)

        candidates = data.get("candidates", [])
        return [{"code": c["code"], "name": c.get("name", c["code"])} for c in candidates]

    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"队列读取失败: {e}")
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    import argparse

    parser = argparse.ArgumentParser(description="神农批处理运行器")
    parser.add_argument("--batch-size", type=int, default=50, help="批大小")
    parser.add_argument("--run-id", type=str, help="批次标识")
    parser.add_argument("--fresh-data", action="store_true", help="强制刷新数据")
    parser.add_argument("--stocks", type=str, help="股票代码，逗号分隔")
    parser.add_argument("--status", action="store_true", help="查询状态")
    parser.add_argument("--resume", type=str, help="从检查点恢复")

    args = parser.parse_args()

    if args.status:
        runner = ShennongBatchRunner(run_id=args.run_id)
        print(json.dumps(runner.get_status(), indent=2, ensure_ascii=False))
    elif args.resume:
        runner = ShennongBatchRunner(run_id=args.resume)
        result = runner.resume(args.resume)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        stocks = None
        if args.stocks:
            stock_codes = args.stocks.split(",")
            stocks = [{"code": c.strip()} for c in stock_codes]

        result = run_manual_batch(
            stocks=stocks,
            batch_size=args.batch_size,
            fresh_data=args.fresh_data,
            run_id=args.run_id,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
