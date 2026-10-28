#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
凭据模板 —— 公开仓库只带这个文件。

真实值不在仓库里（也永远不该在）。要跑起来，自己从 APK 里把常量提出来填进去：

    cp jolt_secrets.example.py jolt_secrets.py

常量在哪、怎么提，见 docs/PROTOCOL.md 第 2–3 节（有逐步截图级的说明），一句话版：

    # 1) API Key 与两个 base URL
    jadx -d out app.apk
    rg -n -A3 "@Headers" out/sources/**/network_call/api/*.java

    # 2) AES Key / IV
    rg -n "SECRET_IV|AES/CBC|SecretKeySpec" out/sources/**/crypto/*.java

    再配合 dex 字符串表搜 "AES" 附近的 32 字节字面量即可。
"""

# 填空示例（把 *** 换成真值）。字段名不能改，harvest.py 按这个结构读。
SOURCES = [
    {
        "name": "primary",
        "base": "https://<主 API 域名>/",
        "api_key": "<请求头 key 的值>",
        "aes_key": "<32 字节 ASCII 密钥>",  # str 或 bytes 均可，harvest.py 会自动 encode
        "iv": "<16 字节 ASCII IV>",
    },
    {
        "name": "secondary",
        "base": "https://<备 API 域名>/",
        "api_key": "<另一个 key>",
        "aes_key": "<32 字节 ASCII 密钥>",  # str 或 bytes 均可，harvest.py 会自动 encode
        "iv": "<16 字节 ASCII IV>",
    },
]
