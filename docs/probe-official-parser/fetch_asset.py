#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并行分段下载 GitHub Release 大文件（仅标准库）。

为什么需要它：本机到 release-assets.githubusercontent.com 的单连接被限速到
约 40 KB/s，126 MB 的 kernel zip 要下 50 分钟；8 路 Range 并行可到约 600 KB/s。
下载结果仍逐段校验长度，任何一段短了都会重试，不会悄悄写出半个文件。

用法：
    python3 fetch_asset.py <url> <输出文件> [--chunk-mb 2] [--threads 8]

本脚本是 spike 证据的一部分（docs/probe-official-parser/EVIDENCE.txt 有完整命令）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = {"User-Agent": "sysml-modeling-agent-probe/1.0"}


def _resolve(url: str) -> tuple[str, int]:
    """跟随重定向，返回 (最终 URL, 总字节数)。"""
    request = urllib.request.Request(url, headers=dict(UA))
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.geturl(), int(response.headers["Content-Length"])


def _fetch_range(
    url: str, start: int, end: int, target: Path, attempts: int = 6
) -> None:
    """下载 [start, end] 闭区间到 target，长度不符就重试。"""
    want = end - start + 1
    for attempt in range(1, attempts + 1):
        try:
            headers = dict(UA)
            headers["Range"] = "bytes=%d-%d" % (start, end)
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
            if len(payload) != want:
                raise IOError("短读：期望 %d 字节，实得 %d" % (want, len(payload)))
            target.write_bytes(payload)
            return
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts:
                raise
            print("  段 %d 第 %d 次失败：%s，重试" % (start, attempt, exc), flush=True)
            time.sleep(2 * attempt)


def download(url: str, out: Path, chunk_mb: int = 2, threads: int = 8) -> None:
    final_url, size = _resolve(url)
    chunk = chunk_mb * 1024 * 1024
    parts_dir = out.with_suffix(out.suffix + ".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)
    ranges = []
    for start in range(0, size, chunk):
        end = min(start + chunk - 1, size - 1)
        ranges.append((start, end))
    print("总大小 %d 字节，分 %d 段，%d 线程" % (size, len(ranges), threads), flush=True)

    def job(index_range):
        index, (start, end) = index_range
        target = parts_dir / ("%06d.part" % index)
        if target.exists() and target.stat().st_size == end - start + 1:
            return
        _fetch_range(final_url, start, end, target)

    started = time.time()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(job, enumerate(ranges)))
    elapsed = time.time() - started

    with out.open("wb") as handle:
        for index in range(len(ranges)):
            handle.write((parts_dir / ("%06d.part" % index)).read_bytes())
    got = out.stat().st_size
    if got != size:
        raise SystemExit("拼装后大小不符：%d != %d" % (got, size))
    for part in parts_dir.iterdir():
        part.unlink()
    parts_dir.rmdir()
    print(
        "完成 %s（%d 字节，%.1f 秒，%.0f KB/s）"
        % (out, got, elapsed, got / max(elapsed, 0.001) / 1024),
        flush=True,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="并行分段下载 GitHub Release 资产")
    parser.add_argument("url")
    parser.add_argument("out")
    parser.add_argument("--chunk-mb", type=int, default=2)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args(argv)
    download(args.url, Path(args.out).expanduser(), args.chunk_mb, args.threads)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
