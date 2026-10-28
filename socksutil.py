#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 SOCKS5 客户端（支持域名，供 probe/stress/demo 复用）。"""
from __future__ import annotations

import socket
import struct


class SocksError(RuntimeError):
    pass


REP = {
    1: "general failure",
    2: "connection not allowed",
    3: "network unreachable",
    4: "host unreachable",
    5: "connection refused",
    6: "TTL expired",
    7: "command not supported",
    8: "address type not supported",
}


def connect(proxy_host: str, proxy_port: int, host: str, port: int, timeout: float = 8.0) -> socket.socket:
    """经 SOCKS5 建立到 host:port 的 TCP 连接（域名交给代理侧解析）。"""
    s = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    s.settimeout(timeout)
    try:
        s.sendall(b"\x05\x01\x00")
        if s.recv(2) != b"\x05\x00":
            raise SocksError("服务端拒绝无认证方式")
        try:
            socket.inet_aton(host)
            addr = b"\x01" + socket.inet_aton(host)
        except OSError:
            hb = host.encode("idna")
            addr = b"\x03" + bytes([len(hb)]) + hb
        s.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))
        head = s.recv(4)
        if len(head) < 4:
            raise SocksError("响应截断")
        rep, atyp = head[1], head[3]
        if rep != 0:
            raise SocksError(f"CONNECT 失败: rep={rep} ({REP.get(rep, '?')})")
        if atyp == 1:
            s.recv(4)
        elif atyp == 3:
            s.recv(s.recv(1)[0])
        elif atyp == 4:
            s.recv(16)
        s.recv(2)
        return s
    except Exception:
        s.close()
        raise


def http_get(proxy_host: str, proxy_port: int, url: str, timeout: float = 10.0, max_bytes: int = 65536) -> tuple[bytes, float]:
    """经 SOCKS5 发一个最小 HTTP/1.1 GET，返回 (body, 耗时秒)。仅 http://。"""
    import time

    assert url.startswith("http://"), "仅支持 http://"
    rest = url[7:]
    host, _, path = rest.partition("/")
    path = "/" + path
    port = 80
    if ":" in host:
        host, _, ps = host.partition(":")
        port = int(ps)
    t0 = time.time()
    s = connect(proxy_host, proxy_port, host, port, timeout)
    try:
        s.sendall(
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: jolt-probe/1.0\r\n"
            f"Accept: */*\r\nConnection: close\r\n\r\n".encode()
        )
        buf = b""
        while len(buf) < max_bytes:
            d = s.recv(16384)
            if not d:
                break
            buf += d
        return buf, time.time() - t0
    finally:
        s.close()


def http_body(raw: bytes) -> bytes:
    return raw.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in raw else raw
