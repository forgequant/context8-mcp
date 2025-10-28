"""Symbol assignment controller using HRW with lease management."""
import time
from typing import List, Set, Dict, Optional, Callable
from .hrw_sharding import select_node
from .lease_manager import LeaseManager
from .membership import NodeMembership
import structlog

logger = structlog.get_logger()


class SymbolAssignmentController:
    """Coordinates symbol assignment using HRW hashing and writer leases."""

    def __init__(
        self,
        membership: NodeMembership,
        lease_manager: LeaseManager,
        symbols: List[str],
        lease_ttl_ms: int,
        min_hold_ms: int = 2000,
        sticky_pct: float = 0.02
    ):
        """Initialize assignment controller.

        Args:
            membership: Node membership manager
            lease_manager: Lease manager
            symbols: List of symbols to manage
            lease_ttl_ms: Lease TTL in milliseconds
            min_hold_ms: Minimum hold time before allowing reassignment
            sticky_pct: Sticky percentage for hysteresis
        """
        self.membership = membership
        self.lease_manager = lease_manager
        self.configured_symbols = symbols
        self.lease_ttl_ms = lease_ttl_ms
        self.min_hold_ms = min_hold_ms
        self.sticky_pct = sticky_pct

        # Current assignments
        self.owned_symbols: Set[str] = set()
        self.symbol_tokens: Dict[str, int] = {}  # symbol -> fencing token
        self.symbol_acquisition_times: Dict[str, float] = {}  # symbol -> timestamp

        # Callbacks for symbol lifecycle
        self.on_acquired_callbacks: List[Callable[[str], None]] = []
        self.on_dropped_callbacks: List[Callable[[str], None]] = []

        logger.info(
            "assignment_controller_initialized",
            node_id=membership.node_id,
            symbols=len(symbols),
            lease_ttl_ms=lease_ttl_ms
        )

    def register_on_acquired(self, callback: Callable[[str], None]) -> None:
        """Register callback for symbol acquisition.

        Args:
            callback: Function called with symbol when acquired
        """
        self.on_acquired_callbacks.append(callback)

    def register_on_dropped(self, callback: Callable[[str], None]) -> None:
        """Register callback for symbol drop.

        Args:
            callback: Function called with symbol when dropped
        """
        self.on_dropped_callbacks.append(callback)

    def rebalance(self) -> Dict[str, List[str]]:
        """Execute rebalancing cycle: compute assignments and acquire/release as needed.

        Returns:
            Dictionary with "acquire" and "release" lists: {"acquire": [...], "release": [...]}
        """
        try:
            # Discover active cluster members
            active_node_ids = self.membership.get_active_node_ids()

            if not active_node_ids:
                logger.warning("rebalance_no_active_nodes")
                return {"acquire": [], "release": []}

            # Calculate desired assignments using HRW
            desired_assignments = {}
            current_time = time.time()

            for symbol in self.configured_symbols:
                # Determine current owner for hysteresis
                current_owner = None
                if symbol in self.owned_symbols:
                    current_owner = self.membership.node_id

                # Check min hold time
                if current_owner and symbol in self.symbol_acquisition_times:
                    acquisition_time = self.symbol_acquisition_times[symbol]
                    hold_duration_ms = (current_time - acquisition_time) * 1000

                    if hold_duration_ms < self.min_hold_ms:
                        # Still within minimum hold time, keep current owner
                        desired_assignments[symbol] = current_owner
                        continue

                # Select node using HRW with hysteresis
                assigned_node = select_node(
                    symbol=symbol,
                    nodes=active_node_ids,
                    current_owner=current_owner,
                    sticky_pct=self.sticky_pct
                )

                if assigned_node:
                    desired_assignments[symbol] = assigned_node

            # Determine symbols to acquire and release
            desired_owned = {sym for sym, node in desired_assignments.items() if node == self.membership.node_id}
            to_acquire = desired_owned - self.owned_symbols
            to_release = self.owned_symbols - desired_owned

            # Release symbols no longer assigned to us
            for symbol in to_release:
                self._release_symbol(symbol)

            # Acquire new symbols
            for symbol in to_acquire:
                self._acquire_symbol(symbol)

            logger.debug(
                "rebalance_complete",
                owned=len(self.owned_symbols),
                acquired=len(to_acquire),
                released=len(to_release)
            )

            return {"acquire": list(to_acquire), "release": list(to_release)}

        except Exception as e:
            logger.error("rebalance_failed", error=str(e), exc_info=True)
            return {"acquire": [], "release": []}

    def _acquire_symbol(self, symbol: str) -> bool:
        """Attempt to acquire lease for symbol.

        Args:
            symbol: Symbol to acquire

        Returns:
            True if acquired successfully
        """
        try:
            token = self.lease_manager.acquire(symbol, self.lease_ttl_ms)

            if token is not None:
                # Lease acquired successfully
                self.owned_symbols.add(symbol)
                self.symbol_tokens[symbol] = token
                self.symbol_acquisition_times[symbol] = time.time()

                logger.info(
                    "symbol_acquired",
                    symbol=symbol,
                    token=token,
                    node_id=self.membership.node_id
                )

                # Notify callbacks
                for callback in self.on_acquired_callbacks:
                    try:
                        callback(symbol)
                    except Exception as e:
                        logger.error("on_acquired_callback_error", symbol=symbol, error=str(e))

                return True
            else:
                logger.debug("symbol_acquisition_failed_lease", symbol=symbol)
                return False

        except Exception as e:
            logger.error("symbol_acquisition_error", symbol=symbol, error=str(e))
            return False

    def _release_symbol(self, symbol: str) -> None:
        """Release lease for symbol.

        Args:
            symbol: Symbol to release
        """
        try:
            # Notify callbacks BEFORE releasing lease
            for callback in self.on_dropped_callbacks:
                try:
                    callback(symbol)
                except Exception as e:
                    logger.error("on_dropped_callback_error", symbol=symbol, error=str(e))

            # Release lease
            self.lease_manager.release(symbol)

            # Update local state
            self.owned_symbols.discard(symbol)
            self.symbol_tokens.pop(symbol, None)
            self.symbol_acquisition_times.pop(symbol, None)

            logger.info("symbol_released", symbol=symbol, node_id=self.membership.node_id)

        except Exception as e:
            logger.error("symbol_release_error", symbol=symbol, error=str(e))

    def renew_leases(self) -> None:
        """Renew leases for all owned symbols.

        Should be called periodically at lease_ttl / 2 interval.
        """
        for symbol in list(self.owned_symbols):  # Copy to allow modification during iteration
            try:
                renewed = self.lease_manager.renew(symbol, self.lease_ttl_ms)

                if not renewed:
                    # Lost ownership - trigger drop
                    logger.warning("lease_renewal_failed_ownership_lost", symbol=symbol)
                    self._release_symbol(symbol)

            except Exception as e:
                logger.error("lease_renewal_error", symbol=symbol, error=str(e))

    def get_token_for_symbol(self, symbol: str) -> Optional[int]:
        """Get fencing token for owned symbol.

        Args:
            symbol: Symbol to check

        Returns:
            Fencing token if owned, None otherwise
        """
        return self.symbol_tokens.get(symbol)

    def cleanup(self) -> None:
        """Release all owned symbols on shutdown."""
        logger.info("assignment_controller_cleanup_start", owned=len(self.owned_symbols))

        for symbol in list(self.owned_symbols):
            self._release_symbol(symbol)

        logger.info("assignment_controller_cleanup_complete")

    def __repr__(self) -> str:
        return f"SymbolAssignmentController(node={self.membership.node_id}, owned={len(self.owned_symbols)})"
