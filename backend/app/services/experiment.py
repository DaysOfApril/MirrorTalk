# MirrorTalk - A/B 实验服务 (分流 + 指标追踪)
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

from app.services.database import get_db

logger = logging.getLogger(__name__)


# ---- 实验配置 ----

@dataclass
class ExperimentVariant:
    """"实验组变体定义"""
    name: str
    weight: float = 1.0           # 流量权重（相对比例）
    config: dict = field(default_factory=dict)  # 该组的配置覆盖
    description: str = ""


@dataclass
class Experiment:
    """"一次 A/B 实验定义"""
    id: str                       # 实验 ID
    name: str                     # 人类可读名称
    variants: list[ExperimentVariant]
    traffic_pct: float = 100.0    # 该实验覆盖的流量百分比
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    def get_total_weight(self) -> float:
        return sum(v.weight for v in self.variants)

    def assign_variant(self, user_id: str) -> ExperimentVariant:
        """"根据 user_id 确定性哈希分配到变体"""
        if not self.variants:
            raise ValueError("实验没有变体")

        # 一致性哈希：相同用户总是分到相同组
        hash_input = f"{self.id}:{user_id}"
        hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16) % 10000
        point = hash_val / 10000.0  # 0~1 之间

        # 按权重累积分配
        total = self.get_total_weight()
        cumulative = 0.0
        for variant in self.variants:
            cumulative += variant.weight / total
            if point <= cumulative:
                return variant

        return self.variants[-1]  # 兜底


# ---- 实验注册表 ----

_registry: dict[str, Experiment] = {}


def register_experiment(exp: Experiment) -> None:
    _registry[exp.id] = exp
    logger.info("注册实验: %s (%d 变体)", exp.name, len(exp.variants))


def get_experiment(exp_id: str) -> Optional[Experiment]:
    return _registry.get(exp_id)


def list_experiments() -> list[Experiment]:
    return list(_registry.values())

# ---- 指标记录 ----

@dataclass
class ExperimentEvent:
    """"单次实验曝光/转化事件"""
    experiment_id: str
    variant_name: str
    user_id: str
    event_type: str                # "impression" | "conversion" | "latency" | custom
    value: float = 0.0             # 指标值（转化=1.0, 延迟=毫秒数等）
    metadata: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


def record_event(event: ExperimentEvent) -> None:
    """"写入实验事件到 SQLite"""
    conn = get_db()
    conn.execute(
        """INSERT INTO experiment_events
           (experiment_id, variant_name, user_id, event_type, value, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            event.experiment_id,
            event.variant_name,
            event.user_id,
            event.event_type,
            event.value,
            json.dumps(event.metadata, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def get_experiment_stats(exp_id: str) -> dict:
    """"查询实验统计数据"""
    conn = get_db()
    rows = conn.execute(
        """SELECT variant_name, event_type, COUNT(*) as cnt, AVG(value) as avg_val
           FROM experiment_events
           WHERE experiment_id = ?
           GROUP BY variant_name, event_type""",
        (exp_id,),
    ).fetchall()
    conn.close()

    stats: dict[str, dict] = {}
    for r in rows:
        vn = r["variant_name"]
        if vn not in stats:
            stats[vn] = {"impressions": 0, "conversions": 0, "avg_latency": 0.0}
        if r["event_type"] == "impression":
            stats[vn]["impressions"] = r["cnt"]
        elif r["event_type"] == "conversion":
            stats[vn]["conversions"] = r["cnt"]
        elif r["event_type"] == "latency":
            stats[vn]["avg_latency"] = round(r["avg_val"], 2)

    # 计算转化率
    for vn, data in stats.items():
        if data["impressions"] > 0:
            data["conversion_rate"] = round(data["conversions"] / data["impressions"], 4)
        else:
            data["conversion_rate"] = 0.0

    return stats
