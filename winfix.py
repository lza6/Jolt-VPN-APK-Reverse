#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 控制台默认 GBK，把 stdout/stderr 强制切到 UTF-8，避免 emoji/中文抛 UnicodeEncodeError。

被 harvest.py / probe.py / stress.py 在文件顶部 import，副作用式生效。
"""
from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
