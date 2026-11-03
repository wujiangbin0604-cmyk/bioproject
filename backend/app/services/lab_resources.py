"""同时考虑主机和Docker cgroup可用内存；不靠降低机器限制冒充资源隔离。"""
from pathlib import Path

import psutil


def available_memory_bytes(cgroup_root: Path = Path("/sys/fs/cgroup")) -> int:
    available = int(psutil.virtual_memory().available)
    # Ubuntu22.04默认cgroup v2；兼容v1。未知平台保留主机保护。
    for maximum, used in (("memory.max", "memory.current"),
                          ("memory/memory.limit_in_bytes", "memory/memory.usage_in_bytes")):
        try:
            raw = (cgroup_root / maximum).read_text().strip()
            if raw != "max":
                capacity = int(raw)
                usage = int((cgroup_root / used).read_text().strip())
                available = min(available, max(0, capacity - usage))
            break
        except (OSError, ValueError):
            continue
    return available
