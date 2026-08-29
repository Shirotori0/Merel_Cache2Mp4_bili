#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站离线缓存合并工具（Python 核心）。

同时支持两种缓存目录结构：
  1) 手机版:  <根>/<任意顶层>/c_<cid>/entry.json + 递归 video.m4s/audio.m4s
  2) 电脑版:  <根>/<cid>/videoInfo.json + <cid>-<p>-<qn>.m4s

将每个视频条目的视频流(+音频流)无损封装为带声音的 <title>.mp4 并输出到根目录。

用法:
    python merge_videos.py [根目录] [输出目录]
    (由 scripts/run.bat 调用)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# Windows 文件名非法字符（用真实控制字符 + 显式字符集合，避免旧版 raw 串误伤 x/0）
_ILLEGAL_CHARS = '<>:"/\\|?*\x00'  # 注意：这是常规字符串，\x00 是真正的 NUL

# 非 raw 字符串，确保 \x00 是 NUL 而非字面 x/0
assert _ILLEGAL_CHARS == '<>:"/\\|?*' + '\x00', "非法字符表定义错误"


def app_dir() -> str:
    """返回脚本实际所在目录（用于定位 bin/ffmpeg.exe）。"""
    return os.path.dirname(os.path.abspath(__file__))


def locate_ffmpeg() -> str | None:
    """定位 ffmpeg：优先项目 bin/，其次脚本同级 bin/，再回退系统 PATH。"""
    candidates = [
        os.path.join(app_dir(), "..", "bin", "ffmpeg.exe"),
        os.path.join(app_dir(), "bin", "ffmpeg.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    # 回退 PATH
    p = shutil.which("ffmpeg")
    return os.path.abspath(p) if p else None


# ---------------------------------------------------------------------------
# JSON 读取（编码自适应：UTF-8 → GBK → latin1）
# ---------------------------------------------------------------------------
def read_json(path: str) -> dict:
    """读取 JSON，自动处理 UTF-8 BOM；失败则回退 GBK/latin1。"""
    # utf-8-sig 会剥离 BOM
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
    return {}


# ---------------------------------------------------------------------------
# 扫描器
# ---------------------------------------------------------------------------
class Entry:
    """一个视频条目。"""
    __slots__ = ("title", "video", "audio", "dir_path", "entry_json")

    def __init__(self, title, video, audio, dir_path, entry_json):
        self.title = title          # 最终标题
        self.video = video          # 视频流路径
        self.audio = audio          # 音频流路径（可能 None）
        self.dir_path = dir_path    # 条目所在目录
        self.entry_json = entry_json


def scan_mobile(root: str) -> list[Entry]:
    """扫描手机版结构：<根>/<顶层>/c_<cid>/entry.json + video/audio.m4s。"""
    entries: list[Entry] = []
    for name in sorted(os.listdir(root)):
        top = os.path.join(root, name)
        if not os.path.isdir(top):
            continue
        for c_name in sorted(os.listdir(top)):
            c_dir = os.path.join(top, c_name)
            if not os.path.isdir(c_dir):
                continue
            entry_json = os.path.join(c_dir, "entry.json")
            if not os.path.isfile(entry_json):
                continue
            video = audio = None
            for dirpath, _dirs, files in os.walk(c_dir):
                if "video.m4s" in files:
                    video = os.path.join(dirpath, "video.m4s")
                if "audio.m4s" in files:
                    audio = os.path.join(dirpath, "audio.m4s")
            if video is None:
                continue
            data = read_json(entry_json)
            title = (
                data.get("title")
                or data.get("page_data", {}).get("part")
                or name
            )
            # 多 P：若 page_data.part 存在且不等于 title，则拼接合集名-分P名
            part = data.get("page_data", {}).get("part")
            if part and data.get("title") and part != data.get("title"):
                title = f"{data.get('title')} - {part}"
            entries.append(Entry(str(title), video, audio, c_dir, entry_json))
    return entries


def _pc_entry_from_dir(d: str, fallback_name: str) -> Entry | None:
    """解析单个电脑版条目目录，返回 Entry 或 None。"""
    video_info = os.path.join(d, "videoInfo.json")
    if not os.path.isfile(video_info):
        return None
    m4s = [f for f in os.listdir(d) if f.lower().endswith(".m4s")]
    if not m4s:
        return None
    # 按文件大小排序：最大者为视频，次大者为音频（启发式）
    m4s.sort(key=lambda f: os.path.getsize(os.path.join(d, f)), reverse=True)
    video_path = os.path.join(d, m4s[0])
    audio_path = os.path.join(d, m4s[1]) if len(m4s) > 1 else None
    data = read_json(video_info)
    title = data.get("title") or fallback_name
    return Entry(str(title), video_path, audio_path, d, video_info)


def scan_pc(root: str) -> list[Entry]:
    """扫描电脑版结构：<根>/<cid>/videoInfo.json + <cid>-<p>-<qn>.m4s。

    同时兼容两种传入方式：
      1) root 本身即单个条目目录（内含 videoInfo.json + *.m4s）
      2) root 是含多个条目子目录的父目录
    """
    entries: list[Entry] = []
    # 情形1：root 自身就是一个条目目录
    direct = _pc_entry_from_dir(root, os.path.basename(os.path.normpath(root)))
    if direct is not None:
        entries.append(direct)
        return entries
    # 情形2：遍历 root 下各子目录
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d) or name.startswith("."):
            continue
        ent = _pc_entry_from_dir(d, name)
        if ent is not None:
            entries.append(ent)
    return entries


def find_all_entries(root: str) -> list[Entry]:
    """合并扫描手机版与电脑版，返回所有条目。"""
    return scan_mobile(root) + scan_pc(root)


# ---------------------------------------------------------------------------
# 文件名处理
# ---------------------------------------------------------------------------
def sanitize_filename(title: str, max_len: int = 180) -> str:
    """清洗为安全的文件名：替换非法字符、压缩空白、去首尾空白/点号。"""
    title = title.strip()
    for ch in _ILLEGAL_CHARS:
        title = title.replace(ch, "_")
    # 压缩连续空白（含全角空格）
    title = re.sub(r"\s+", " ", title).strip()
    # 去掉尾部点号/空白
    title = title.rstrip(". ")
    if not title:
        title = "untitled"
    # 截断过长（单段文件名 Windows 上限 255，留出扩展名与序号余量）
    if len(title) > max_len:
        title = title[:max_len].rstrip(". ")
    return title


def unique_path(root: str, basename: str) -> str:
    """在 root 下生成不冲突的路径，同名追加 (2)、(3)…"""
    base, ext = os.path.splitext(basename)
    dest = os.path.join(root, basename)
    counter = 2
    while os.path.exists(dest):
        dest = os.path.join(root, f"{base}({counter}){ext}")
        counter += 1
    return dest


# ---------------------------------------------------------------------------
# FFmpeg 封装
# ---------------------------------------------------------------------------
# B 站电脑版缓存的 m4s 文件开头带有 9 字节前缀 "000000000"，
# 标准 MP4 应从 ftyp 开始。ffmpeg 无法直接识别，需先剥离前缀。
def strip_bili_prefix(src: str, dst: str) -> str:
    """剥离 m4s 中 ftyp 之前的非标准前缀，返回清洗后文件路径。

    若文件不含前缀（已是标准 MP4），直接返回原路径，不产生临时文件。
    """
    try:
        with open(src, "rb") as f:
            head = f.read(4096)
        idx = head.find(b"ftyp")
        # ftyp 前的 4 字节是 box size；标准 MP4 中 ftyp 出现在偏移 4
        if idx > 0:
            # 保留 ftyp 前 4 字节的 box size，使从 box 头开始
            start = idx - 4
            if start < 0:
                start = 0
            with open(src, "rb") as fin, open(dst, "wb") as fout:
                fin.seek(start)
                shutil.copyfileobj(fin, fout)
            return dst
    except OSError:
        pass
    return src


def merge_with_ffmpeg(video: str, audio: str | None, output: str, ffmpeg: str) -> tuple[bool, str]:
    """用 ffmpeg 无损封装为 mp4（-c copy）。返回 (成功?, 错误信息)。"""
    # 预处理：剥离 B 站前缀（生成临时清洗文件）
    tmp_clean = []
    v_clean = strip_bili_prefix(video, video + ".clean")
    if v_clean != video:
        tmp_clean.append(v_clean)
    a_clean = None
    if audio:
        a_clean = strip_bili_prefix(audio, audio + ".clean")
        if a_clean != audio:
            tmp_clean.append(a_clean)

    cmd = [ffmpeg, "-y", "-i", v_clean]
    if a_clean:
        cmd += ["-i", a_clean]
    # 显式指定流映射，避免多轨误选
    cmd += ["-map", "0:v:0"]
    if a_clean:
        cmd += ["-map", "1:a:0", "-c:a", "copy"]
    cmd += ["-c:v", "copy", output]
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        # 清理临时文件
        for t in tmp_clean:
            try:
                os.remove(t)
            except OSError:
                pass
        if res.returncode == 0:
            return True, ""
        err = res.stderr.decode("utf-8", "ignore")
        return False, (err[-300:] if err else f"退出码 {res.returncode}")
    except OSError as e:
        for t in tmp_clean:
            try:
                os.remove(t)
            except OSError:
                pass
        return False, str(e)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="B 站离线缓存合并工具")
    parser.add_argument("root", nargs="?", default=None, help="缓存根目录（默认脚本所在目录）")
    parser.add_argument("output", nargs="?", default=None, help="输出目录（默认根目录）")
    args = parser.parse_args()

    root = os.path.abspath(args.root) if args.root else app_dir()
    out_dir = os.path.abspath(args.output) if args.output else root

    # 标准输出 UTF-8，避免中文标题在 cp936 下报错
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    print(f"根目录: {root}")
    print(f"输出目录: {out_dir}")
    print()

    ffmpeg = locate_ffmpeg()
    if ffmpeg is None:
        print("未检测到 ffmpeg。请将 ffmpeg.exe 放在 bin/ 目录或安装到 PATH。")
        print("下载: https://ffmpeg.org/download.html")
        return 1
    print(f"使用 ffmpeg: {ffmpeg}")
    print()

    if not os.path.isdir(root):
        print(f"[错误] 根目录不存在或不可访问: {root}")
        return 1
    if not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            print(f"[错误] 输出目录不可创建: {e}")
            return 1

    entries = find_all_entries(root)
    if not entries:
        print("未找到任何视频条目（手机版需 entry.json+video.m4s，电脑版需 videoInfo.json+*.m4s）。")
        return 0

    print(f"共发现 {len(entries)} 个视频条目。")
    print()

    ok = fail = 0
    for ent in entries:
        safe = sanitize_filename(ent.title)
        print(f"[处理] {ent.title}")
        out_mp4 = unique_path(out_dir, safe + ".mp4")
        # 直接输出到目标目录，不在缓存内生成临时文件
        success, err = merge_with_ffmpeg(ent.video, ent.audio, out_mp4, ffmpeg)
        if success:
            print(f"    [完成] -> {out_mp4}")
            ok += 1
            continue
        # 失败：若因音频问题且存在音频，尝试仅封装视频
        if ent.audio is not None:
            print(f"    [警告] 带音频合并失败（{err}），尝试仅封装视频。")
            success2, err2 = merge_with_ffmpeg(ent.video, None, out_mp4, ffmpeg)
            if success2:
                print(f"    [完成(仅视频)] -> {out_mp4}")
                ok += 1
                continue
            err = err2
        print(f"    [跳过] {ent.title}（{err}）")
        # 清理失败产生的半成品
        if os.path.exists(out_mp4):
            try:
                os.remove(out_mp4)
            except OSError:
                pass
        fail += 1

    print(f"\n==== 汇总 ====\n成功: {ok}  失败: {fail}  总计: {len(entries)}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
