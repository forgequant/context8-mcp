"""Node membership management for distributed coordination."""
import json
import time
import random
from datetime import datetime
from typing import List, Dict, Optional
from redis import Redis
import structlog

logger = structlog.get_logger()


class NodeMembership:
    """Manages node membership in Redis cluster."""

    def __init__(
        self,
        redis_client: Redis,
        node_id: str,
        hostname: str,
        pid: int,
        metrics_url: str,
        heartbeat_interval_sec: float = 1.0,
        ttl_sec: int = 5
    ):
        """Initialize node membership manager.

        Args:
            redis_client: Redis client instance
            node_id: Unique node identifier
            hostname: Server hostname
            pid: Process ID
            metrics_url: Prometheus metrics endpoint URL
            heartbeat_interval_sec: Heartbeat interval in seconds
            ttl_sec: Key TTL in seconds (should be > 2x heartbeat interval)
        """
        self.redis = redis_client
        self.node_id = node_id
        self.hostname = hostname
        self.pid = pid
        self.metrics_url = metrics_url
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.ttl_sec = ttl_sec
        self.started_at = datetime.utcnow()

        # Backup tracking ZSET
        self.nodes_seen_key = "nt:nodes_seen"

    def heartbeat(self) -> None:
        """Send heartbeat to Redis (SET with TTL + ZADD backup).

        Should be called every heartbeat_interval_sec with jitter.
        """
        key = f"nt:node:{self.node_id}"

        metadata = {
            "node_id": self.node_id,
            "hostname": self.hostname,
            "pid": self.pid,
            "started_at": self.started_at.isoformat(),
            "metrics_url": self.metrics_url,
            "last_heartbeat": datetime.utcnow().isoformat(),
        }

        try:
            # Primary: SET with TTL
            self.redis.set(key, json.dumps(metadata), ex=self.ttl_sec)

            # Backup: Add to ZSET with current timestamp
            current_ts = time.time()
            self.redis.zadd(self.nodes_seen_key, {self.node_id: current_ts})

            # Cleanup old entries from ZSET (older than 10 seconds)
            cutoff_ts = current_ts - 10
            self.redis.zremrangebyscore(self.nodes_seen_key, "-inf", cutoff_ts)

            logger.debug("heartbeat_sent", node_id=self.node_id)

        except Exception as e:
            logger.error("heartbeat_failed", node_id=self.node_id, error=str(e))

    def get_heartbeat_interval_with_jitter(self) -> float:
        """Calculate heartbeat interval with ±10% jitter.

        Jitter prevents thundering herd when multiple nodes start simultaneously.

        Returns:
            Interval in seconds with jitter applied
        """
        jitter = random.uniform(-0.1, 0.1)
        return self.heartbeat_interval_sec * (1 + jitter)

    def discover(self) -> List[Dict]:
        """Discover all active cluster members via SCAN.

        Returns:
            List of node metadata dicts for active nodes
        """
        active_nodes = []

        try:
            # Scan for all nt:node:* keys
            cursor = 0
            pattern = "nt:node:*"

            while True:
                cursor, keys = self.redis.scan(cursor, match=pattern, count=100)

                for key in keys:
                    try:
                        data = self.redis.get(key)
                        if data:
                            metadata = json.loads(data)

                            # Validate last_heartbeat within TTL window
                            last_hb = datetime.fromisoformat(metadata["last_heartbeat"])
                            age_sec = (datetime.utcnow() - last_hb).total_seconds()

                            if age_sec <= self.ttl_sec:
                                active_nodes.append(metadata)
                            else:
                                logger.warning(
                                    "discovered_stale_node",
                                    node_id=metadata.get("node_id"),
                                    age_sec=age_sec
                                )

                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning("discovery_parse_error", key=key, error=str(e))

                if cursor == 0:
                    break

            logger.debug("discovery_complete", active_count=len(active_nodes))
            return active_nodes

        except Exception as e:
            logger.error("discovery_failed", error=str(e))
            return []

    def get_active_node_ids(self) -> List[str]:
        """Get list of active node IDs.

        Returns:
            List of node_id strings for active nodes
        """
        nodes = self.discover()
        return [node["node_id"] for node in nodes]

    def cleanup(self) -> None:
        """Clean up membership on shutdown.

        Removes node from active membership and backup ZSET.
        """
        try:
            key = f"nt:node:{self.node_id}"
            self.redis.delete(key)
            self.redis.zrem(self.nodes_seen_key, self.node_id)
            logger.info("membership_cleanup_complete", node_id=self.node_id)
        except Exception as e:
            logger.error("membership_cleanup_failed", node_id=self.node_id, error=str(e))

    def __repr__(self) -> str:
        return f"NodeMembership(node_id={self.node_id}, hostname={self.hostname})"
