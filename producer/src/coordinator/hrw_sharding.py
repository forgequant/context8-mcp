"""Highest Random Weight (HRW) consistent hashing with hysteresis."""
import hashlib
from typing import List, Optional


def hrw_hash(node_id: str, symbol: str) -> int:
    """Compute HRW hash using blake2b (64-bit digest).

    Args:
        node_id: Unique node identifier
        symbol: Symbol to hash

    Returns:
        64-bit integer hash value
    """
    h = hashlib.blake2b(digest_size=8)  # 64-bit hash
    h.update(f"{node_id}:{symbol}".encode('utf-8'))
    return int.from_bytes(h.digest(), byteorder='big')


def select_node(
    symbol: str,
    nodes: List[str],
    current_owner: Optional[str] = None,
    sticky_pct: float = 0.02
) -> Optional[str]:
    """Select node for symbol using HRW with hysteresis.

    Hysteresis mechanism: current owner receives sticky bonus to reduce
    unnecessary rebalancing when nodes join/leave.

    Args:
        symbol: Symbol to assign
        nodes: List of active node IDs
        current_owner: Current owner (receives sticky bonus)
        sticky_pct: Sticky bonus percentage (default 2%)

    Returns:
        Node ID with highest weight, or None if no nodes available
    """
    if not nodes:
        return None

    if len(nodes) == 1:
        return nodes[0]

    weights = {}
    for node in nodes:
        weight = hrw_hash(node, symbol)

        # Apply sticky bonus if this is the current owner
        if current_owner and node == current_owner:
            weight = int(weight * (1 + sticky_pct))

        weights[node] = weight

    # Return node with maximum weight
    return max(weights, key=weights.get)


def calculate_symbol_distribution(
    symbols: List[str],
    nodes: List[str],
    sticky_pct: float = 0.02
) -> dict[str, str]:
    """Calculate complete symbol-to-node assignment.

    Args:
        symbols: List of symbols to assign
        nodes: List of active node IDs
        sticky_pct: Sticky bonus percentage

    Returns:
        Dictionary mapping symbol -> node_id
    """
    assignments = {}
    for symbol in symbols:
        node = select_node(symbol, nodes, sticky_pct=sticky_pct)
        if node:
            assignments[symbol] = node
    return assignments
