"""Fixed-size ring buffer for windowed data storage."""
from collections import deque
from datetime import datetime
from typing import Generic, TypeVar, List

T = TypeVar('T')


class RingBuffer(Generic[T]):
    """Fixed-size circular buffer that automatically discards oldest items.

    Used for storing recent events in fixed-size windows for calculations
    (e.g., trades in last 10s, 30s, 30min).
    """

    def __init__(self, max_size: int):
        """Initialize ring buffer with maximum size.

        Args:
            max_size: Maximum number of items to store
        """
        if max_size <= 0:
            raise ValueError(f"max_size must be positive, got {max_size}")

        self.buffer = deque(maxlen=max_size)
        self.max_size = max_size

    def append(self, item: T) -> None:
        """Append item to buffer (oldest item auto-discarded if full).

        Args:
            item: Item to append
        """
        self.buffer.append(item)

    def filter_by_time(self, cutoff: datetime) -> List[T]:
        """Return items newer than cutoff timestamp.

        Assumes items have a 'timestamp' attribute.

        Args:
            cutoff: Minimum timestamp (items older than this are filtered out)

        Returns:
            List of items with timestamp > cutoff
        """
        return [item for item in self.buffer if hasattr(item, 'timestamp') and item.timestamp > cutoff]

    def get_all(self) -> List[T]:
        """Return all items in buffer as list.

        Returns:
            List of all items (oldest to newest)
        """
        return list(self.buffer)

    def clear(self) -> None:
        """Remove all items from buffer."""
        self.buffer.clear()

    def __len__(self) -> int:
        """Return number of items currently in buffer."""
        return len(self.buffer)

    def __repr__(self) -> str:
        return f"RingBuffer(size={len(self)}/{self.max_size})"
