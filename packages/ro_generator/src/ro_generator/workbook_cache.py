"""WorkbookCacheManager：本地进程级 base 文件内存缓存。

缓存按 base 文件路径建立，通过文件签名（mtime_ns + size）检测变化。
生命周期独立于 session：多个 session 共享同一缓存，session 过期不清理缓存。

线程安全：使用 RLock + per-file build lock + 双重检查。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ro_generator.workbook_snapshot import (
    FileSignature,
    WorkbookSnapshot,
    build_workbook_snapshot,
)

DEFAULT_TTL_SECONDS: Final = 1800  # 30 分钟未访问自动清理


# —————————————————————————————————————
# 内部缓存条目
# —————————————————————————————————————

@dataclass
class _CachedEntry:
    snapshot: WorkbookSnapshot
    signature: FileSignature
    last_access: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_access = time.time()


# —————————————————————————————————————
# 缓存管理器
# —————————————————————————————————————

class WorkbookCacheManager:
    """按 base 文件路径管理 WorkbookSnapshot 缓存。"""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
        self._cache: dict[str, _CachedEntry] = {}
        self._build_locks: dict[str, threading.RLock] = {}

    # ——— 公开 API ———

    def get_snapshot(self, base_file: str) -> WorkbookSnapshot:
        """获取 base 文件的缓存快照。签名不匹配时自动重建。"""
        key = _normalize_path(base_file)
        signature = FileSignature.from_file(key)

        # 快速路径：缓存命中
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached.signature == signature:
                cached.touch()
                return cached.snapshot
            build_lock = self._build_locks.setdefault(key, threading.RLock())

        # 慢路径：需要构建
        with build_lock:
            # 双重检查
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None and cached.signature == signature:
                    cached.touch()
                    return cached.snapshot

            snapshot = build_workbook_snapshot(key)

            with self._lock:
                self._cache[key] = _CachedEntry(
                    snapshot=snapshot,
                    signature=signature,
                )
                return snapshot

    def invalidate(self, base_file: str) -> None:
        """显式失效指定 base 文件的缓存。"""
        key = _normalize_path(base_file)
        with self._lock:
            self._cache.pop(key, None)
            self._build_locks.pop(key, None)

    def get_info(self) -> dict[str, object]:
        """返回缓存状态信息，用于调试。不修改任何状态。"""
        with self._lock:
            entries = []
            for key, entry in self._cache.items():
                entries.append({
                    "base_file": key,
                    "file_size": entry.signature.size,
                    "po_count": len(entry.snapshot.po_index),
                    "row_count": len(entry.snapshot.po_rows),
                    "age_seconds": round(time.time() - entry.snapshot.created_at, 1),
                    "last_access_seconds_ago": round(time.time() - entry.last_access, 1),
                })
            return {
                "entry_count": len(self._cache),
                "build_lock_count": len(self._build_locks),
                "ttl_seconds": self._ttl,
                "entries": entries,
            }

    def clear_expired(self) -> int:
        """清理超过 TTL 未访问的缓存条目。返回清理数量。"""
        now = time.time()
        removed = 0
        with self._lock:
            expired = [
                k for k, v in self._cache.items()
                if now - v.last_access > self._ttl
            ]
            for k in expired:
                self._cache.pop(k, None)
                self._build_locks.pop(k, None)
                removed += 1
        return removed


# —————————————————————————————————————
# 模块级单例
# —————————————————————————————————————

_cache_manager: WorkbookCacheManager | None = None
_lock_singleton = threading.Lock()


def get_cache_manager() -> WorkbookCacheManager:
    """获取模块级 WorkbookCacheManager 单例。"""
    global _cache_manager
    if _cache_manager is None:
        with _lock_singleton:
            if _cache_manager is None:
                _cache_manager = WorkbookCacheManager()
    return _cache_manager


# —————————————————————————————————————
# 辅助
# —————————————————————————————————————

def _normalize_path(path: str) -> str:
    return str(Path(path).resolve())


__all__ = [
    "WorkbookCacheManager",
    "get_cache_manager",
]
