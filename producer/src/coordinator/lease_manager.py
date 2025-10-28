"""Writer lease management with fencing tokens."""
import os
from pathlib import Path
from typing import Optional
from redis import Redis
from redis.commands.core import Script
import structlog

logger = structlog.get_logger()


class LeaseManager:
    """Manages writer leases for symbols using Redis Lua scripts."""

    def __init__(self, redis_client: Redis, node_id: str, lua_dir: Optional[Path] = None):
        """Initialize lease manager.

        Args:
            redis_client: Redis client instance
            node_id: Unique node identifier
            lua_dir: Directory containing Lua scripts (default: producer/lua/)
        """
        self.redis = redis_client
        self.node_id = node_id

        # Find Lua script directory
        if lua_dir is None:
            # Assume we're in producer/src/coordinator/, scripts are in producer/lua/
            current_dir = Path(__file__).parent
            lua_dir = current_dir.parent.parent / "lua"

        self.lua_dir = lua_dir

        # Load Lua scripts
        self.acquire_script = self._load_script("acquire_lease.lua")
        self.renew_script = self._load_script("renew_lease.lua")
        self.release_script = self._load_script("release_lease.lua")

        logger.info("lease_manager_initialized", node_id=node_id, lua_dir=str(lua_dir))

    def _load_script(self, filename: str) -> Script:
        """Load Lua script from file.

        Args:
            filename: Script filename

        Returns:
            Loaded Script object

        Raises:
            FileNotFoundError: If script file not found
        """
        script_path = self.lua_dir / filename
        if not script_path.exists():
            raise FileNotFoundError(f"Lua script not found: {script_path}")

        with open(script_path, 'r') as f:
            script_content = f.read()

        return Script(self.redis, script_content)

    def acquire(self, symbol: str, ttl_ms: int) -> Optional[int]:
        """Acquire writer lease for symbol.

        Args:
            symbol: Symbol to acquire lease for
            ttl_ms: Lease TTL in milliseconds

        Returns:
            Fencing token (int) if acquired, None if already held by another node
        """
        lease_key = f"report:writer:{symbol}"
        token_key = f"report:writer:token:{symbol}"

        try:
            result = self.acquire_script(
                keys=[lease_key, token_key],
                args=[self.node_id, ttl_ms]
            )

            if result is not None:
                token = int(result)
                logger.info("lease_acquired", symbol=symbol, node_id=self.node_id, token=token)
                return token
            else:
                # Lease held by another node
                current_owner = self.redis.get(lease_key)
                # redis-py 5.x returns strings by default
                if isinstance(current_owner, bytes):
                    current_owner = current_owner.decode()
                logger.debug(
                    "lease_acquisition_failed",
                    symbol=symbol,
                    node_id=self.node_id,
                    current_owner=current_owner
                )
                return None

        except Exception as e:
            logger.error("lease_acquire_error", symbol=symbol, node_id=self.node_id, error=str(e))
            return None

    def renew(self, symbol: str, ttl_ms: int) -> bool:
        """Renew writer lease for symbol.

        Args:
            symbol: Symbol to renew lease for
            ttl_ms: New TTL in milliseconds

        Returns:
            True if renewed successfully, False if ownership lost
        """
        lease_key = f"report:writer:{symbol}"

        try:
            result = self.renew_script(
                keys=[lease_key],
                args=[self.node_id, ttl_ms]
            )

            renewed = int(result) == 1

            if renewed:
                logger.debug("lease_renewed", symbol=symbol, node_id=self.node_id)
            else:
                current_owner = self.redis.get(lease_key)
                # redis-py 5.x returns strings by default
                if isinstance(current_owner, bytes):
                    current_owner = current_owner.decode()
                logger.warning(
                    "lease_renewal_failed",
                    symbol=symbol,
                    node_id=self.node_id,
                    current_owner=current_owner
                )

            return renewed

        except Exception as e:
            logger.error("lease_renew_error", symbol=symbol, node_id=self.node_id, error=str(e))
            return False

    def release(self, symbol: str) -> bool:
        """Release writer lease for symbol.

        Args:
            symbol: Symbol to release lease for

        Returns:
            True if released successfully, False if not owner
        """
        lease_key = f"report:writer:{symbol}"

        try:
            result = self.release_script(
                keys=[lease_key],
                args=[self.node_id]
            )

            released = int(result) == 1

            if released:
                logger.info("lease_released", symbol=symbol, node_id=self.node_id)
            else:
                logger.warning("lease_release_failed", symbol=symbol, node_id=self.node_id)

            return released

        except Exception as e:
            logger.error("lease_release_error", symbol=symbol, node_id=self.node_id, error=str(e))
            return False

    def get_current_owner(self, symbol: str) -> Optional[str]:
        """Get current lease owner for symbol.

        Args:
            symbol: Symbol to check

        Returns:
            Node ID of current owner, or None if no lease
        """
        lease_key = f"report:writer:{symbol}"
        try:
            owner = self.redis.get(lease_key)
            # redis-py 5.x returns strings by default (not bytes)
            if isinstance(owner, bytes):
                return owner.decode()
            return owner if owner else None
        except Exception as e:
            logger.error("get_owner_error", symbol=symbol, error=str(e))
            return None

    def get_current_token(self, symbol: str) -> Optional[int]:
        """Get current fencing token for symbol.

        Args:
            symbol: Symbol to check

        Returns:
            Current fencing token, or None if not found
        """
        token_key = f"report:writer:token:{symbol}"
        try:
            token = self.redis.get(token_key)
            return int(token) if token else None
        except Exception as e:
            logger.error("get_token_error", symbol=symbol, error=str(e))
            return None

    def get_lease_info(self, symbol: str) -> dict[str, any]:
        """Get lease information (owner and token) for symbol.

        Args:
            symbol: Symbol to check

        Returns:
            Dictionary with 'owner' and 'token' keys, or empty dict if no lease
        """
        owner = self.get_current_owner(symbol)
        token = self.get_current_token(symbol)

        if owner is None and token is None:
            return {}

        return {
            "owner": owner,
            "token": token
        }

    def __repr__(self) -> str:
        return f"LeaseManager(node_id={self.node_id})"
