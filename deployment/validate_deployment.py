# -*- coding: utf-8 -*-
"""向后兼容入口：执行不依赖研究项目的便携验证。"""
from __future__ import annotations

try:
    from .validate_portable import main
except ImportError:  # 直接执行脚本时
    from validate_portable import main


if __name__ == "__main__":
    raise SystemExit(main())
