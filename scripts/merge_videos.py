#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站离线缓存合并工具（Python 核心）。

设计要点：全量递归遍历 + 智能配对，不假设任何固定目录层级。

原理：
  1) 用 os.walk 递归收集整棵目录树中的
       - 所有 *.m4s（按所在目录分组 -> 每个含 m4s 的目录即一个候选条目）
       - 所有元数据 entry.json（手机版）/ videoInfo.json（电脑版）
  2) 对每个「媒体目录」独立判定：
       - 音视频识别：固定命名 video.m4s/audio.m4s -> index.json 的 size 精确匹配 -> 大小启发式
       - 标题解析：从媒体目录向上父目录链找元数据；找不到则按 cid 匹配；再回退目录名
  3) 按视频流路径去重。

这样既兼容平铺的电脑版结构，也兼容元数据与媒体流分离的嵌套手机版结构。

用法:
    python merge_videos.py [根目录] [输出目录]
    python merge_videos.py            # 无参数则弹窗选择文件夹
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# Windows 文件名非法字符（常规字符串，\x00 是真正的 NUL）
_ILLEGAL_CHARS = '<>:"/\\|?*\x00'
assert _ILLEGAL_CHARS == '<>:"/\\|?*' + '\x00', "非法字符表定义错误"

# Windows 保留设备名（不可用作文件名）
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# 元数据文件名
_ENTRY_JSON = "entry.json"
_VIDEO_INFO_JSON = "videoInfo.json"
_INDEX_JSON = "index.json"

# cid 提取：目录名中的长数字（>=6 位），排除清晰度 id（通常 2-5 位）
_CID_RE = re.compile(r"(\d{6,})")


def app_dir() -> str:
    """返回脚本实际所在目录。"""
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
    p = shutil.which("ffmpeg")
    return os.path.abspath(p) if p else None


def pick_folder_dialog(initial_dir: str | None = None) -> str | None:
    """弹出文件夹选择窗口，返回所选路径；取消或不可用返回 None。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    try:
        root = tk.Tk()
        root.withdraw()                 # 隐藏根窗口
        root.attributes("-topmost", True)  # 弹窗置顶
        start = initial_dir if (initial_dir and os.path.isdir(initial_dir)) else None
        path = filedialog.askdirectory(
            title="请选择 B 站缓存文件夹",
            mustexist=True,
            initialdir=start,
        )
        root.destroy()
        return path or None
    except Exception:
        return None


def prompt_folder() -> str | None:
    """获取缓存根目录：优先弹窗，不可用时回退到命令行输入。"""
    picked = pick_folder_dialog()
    if picked:
        return picked
    try:
        raw = input("请输入 B 站缓存文件夹路径（直接回车取消）: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return raw or None


# ---------------------------------------------------------------------------
# JSON 读取（编码自适应：UTF-8(BOM) -> GBK -> latin1）
# ---------------------------------------------------------------------------
def read_json(path: str) -> dict:
    """读取 JSON，自动处理 UTF-8 BOM；失败回退 GBK/latin1；彻底失败返回 {}。"""
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError):
            continue
    return {}


# ---------------------------------------------------------------------------
# 扫描：全量递归收集 + 智能配对
# ---------------------------------------------------------------------------
class Entry:
    """一个视频条目。"""

    __slots__ = ("title", "video", "audio", "dir_path", "meta_file")

    def __init__(self, title: str, video: str, audio: str | None,
                 dir_path: str, meta_file: str | None):
        self.title = title
        self.video = video
        self.audio = audio
        self.dir_path = dir_path
        self.meta_file = meta_file


def collect_tree(root: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """递归遍历整棵树。

    返回:
        media_dirs: {媒体目录: [该目录下的 m4s 绝对路径...]}
        meta_by_dir: {元数据所在目录: [entry.json/videoInfo.json 路径...]}
    """
    media_dirs: dict[str, list[str]] = {}
    meta_by_dir: dict[str, list[str]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        m4s = [os.path.join(dirpath, f)
               for f in filenames if f.lower().endswith(".m4s")]
        if m4s:
            media_dirs[dirpath] = m4s
        metas = [os.path.join(dirpath, f)
                 for f in filenames if f in (_ENTRY_JSON, _VIDEO_INFO_JSON)]
        if metas:
            meta_by_dir[dirpath] = metas
    return media_dirs, meta_by_dir


def classify_streams(dir_path: str, m4s_paths: list[str]) -> tuple[str | None, str | None]:
    """识别媒体目录内的视频流与音频流（三级策略）。"""
    by_name = {os.path.basename(p).lower(): p for p in m4s_paths}

    # 策略 1：固定命名（手机版标准结构 + 本项目分离式结构均适用）
    video = by_name.get("video.m4s")
    audio = by_name.get("audio.m4s")
    if video:
        return video, audio

    # 策略 2：同目录 index.json 的 size 精确匹配（最可靠）
    index_path = os.path.join(dir_path, _INDEX_JSON)
    if os.path.isfile(index_path):
        data = read_json(index_path)
        size_kind: dict[int, str] = {}
        for item in data.get("video") or []:
            if isinstance(item, dict) and item.get("size"):
                size_kind[int(item["size"])] = "v"
        for item in data.get("audio") or []:
            if isinstance(item, dict) and item.get("size"):
                size_kind[int(item["size"])] = "a"
        if size_kind:
            matched_v: str | None = None
            matched_a: str | None = None
            for p in m4s_paths:
                try:
                    kind = size_kind.get(os.path.getsize(p))
                except OSError:
                    kind = None
                if kind == "v" and matched_v is None:
                    matched_v = p
                elif kind == "a" and matched_a is None:
                    matched_a = p
            if matched_v:
                return matched_v, matched_a

    # 策略 3：大小启发式（最大=视频，次大=音频）
    ordered = sorted(m4s_paths, key=lambda p: os.path.getsize(p), reverse=True)
    return ordered[0], (ordered[1] if len(ordered) > 1 else None)


def parse_title(meta_file: str) -> str | None:
    """从 entry.json / videoInfo.json 解析标题；失败返回 None。"""
    data = read_json(meta_file)
    if not data:
        return None
    base = data.get("title")
    part = (data.get("page_data") or {}).get("part")
    if base and part and part != base:
        return f"{base} - {part}"
    return base or part or None


def extract_cids(path: str, root: str) -> set[str]:
    """从路径的各级目录名中提取候选 cid（长数字，排除清晰度 id）。"""
    cids: set[str] = set()
    rel = os.path.relpath(path, root)
    for part in rel.split(os.sep):
        for m in _CID_RE.findall(part):
            cids.add(m)
    return cids


def resolve_meta(dir_path: str, meta_by_dir: dict[str, list[str]], root: str) -> tuple[str | None, str | None]:
    """为媒体目录查找元数据文件。

    顺序：
      1) 媒体目录自身
      2) 沿父目录链向上（直到 root 之外）
      3) 全量元数据中按 cid 匹配（处理「元数据与媒体流分离」结构）
    返回 (title, meta_file)
    """
    # 1) 自身
    if dir_path in meta_by_dir:
        for mf in meta_by_dir[dir_path]:
            t = parse_title(mf)
            if t:
                return t, mf

    # 2) 向上父目录链
    cur = dir_path
    root_abs = os.path.abspath(root)
    while True:
        parent = os.path.dirname(cur)
        if parent == cur or len(parent) < len(root_abs):
            break
        cur = parent
        if cur in meta_by_dir:
            for mf in meta_by_dir[cur]:
                t = parse_title(mf)
                if t:
                    return t, mf

    # 3) 按 cid 匹配全局元数据（分离式结构的关键回退）
    cids = extract_cids(dir_path, root_abs)
    if cids:
        for meta_dir, files in meta_by_dir.items():
            meta_cids = extract_cids(meta_dir, root_abs)
            if cids & meta_cids:
                for mf in files:
                    t = parse_title(mf)
                    if t:
                        return t, mf
    return None, None


def scan_tree(root: str) -> list[Entry]:
    """全量遍历扫描，返回所有视频条目（已按视频流路径去重）。"""
    media_dirs, meta_by_dir = collect_tree(root)
    entries: list[Entry] = []
    seen: set[str] = set()
    for dir_path in sorted(media_dirs):
        video, audio = classify_streams(dir_path, media_dirs[dir_path])
        if not video or video in seen:
            continue
        seen.add(video)
        title, meta_file = resolve_meta(dir_path, meta_by_dir, root)
        if not title:
            title = os.path.basename(dir_path.rstrip("\\/")) or "untitled"
        entries.append(Entry(str(title), video, audio, dir_path, meta_file))
    return entries


# ---------------------------------------------------------------------------
# 文件名处理
# ---------------------------------------------------------------------------
def sanitize_filename(title: str, max_len: int = 180) -> str:
    """清洗为安全文件名：替换非法字符、压缩空白、去首尾空白/点号、处理保留设备名。"""
    title = title.strip()
    for ch in _ILLEGAL_CHARS:
        title = title.replace(ch, "_")
    title = re.sub(r"\s+", " ", title).strip()
    title = title.rstrip(". ")
    if not title:
        title = "untitled"
    if len(title) > max_len:
        title = title[:max_len].rstrip(". ")
    # Windows 保留设备名（如 CON.mp4 非法）
    stem = title.split(".")[0].upper()
    if stem in _RESERVED_NAMES:
        title = "_" + title
    return title


def unique_path(root: str, basename: str) -> str:
    """在 root 下生成不冲突路径，同名追加 (2)、(3)…"""
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
def strip_bili_prefix(src: str, dst: str) -> str:
    """剥离 B 站客户端 m4s 文件开头的非标准前缀（ftyp 之前的内容）。

    电脑版缓存的 m4s 开头带 9 字节 '000000000'，ffmpeg 无法识别，需剥离。
    已是标准 MP4 时直接返回原路径，不产生临时文件。
    """
    try:
        with open(src, "rb") as f:
            head = f.read(4096)
        idx = head.find(b"ftyp")
        if idx > 0:
            start = max(idx - 4, 0)
            with open(src, "rb") as fin, open(dst, "wb") as fout:
                fin.seek(start)
                shutil.copyfileobj(fin, fout)
            return dst
    except OSError:
        pass
    return src


def merge_with_ffmpeg(video: str, audio: str | None, output: str,
                      ffmpeg: str) -> tuple[bool, str]:
    """用 ffmpeg 无损封装为 mp4（-c copy）。返回 (成功?, 错误信息)。"""
    tmp_clean: list[str] = []
    try:
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
        cmd += ["-map", "0:v:0"]
        if a_clean:
            cmd += ["-map", "1:a:0", "-c:a", "copy"]
        cmd += ["-c:v", "copy", output]

        res = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, check=False)
        if res.returncode == 0:
            return True, ""
        err = res.stderr.decode("utf-8", "ignore")
        return False, (err[-300:] if err else f"退出码 {res.returncode}")
    except OSError as e:
        return False, str(e)
    finally:
        for t in tmp_clean:
            try:
                os.remove(t)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="B 站离线缓存合并工具")
    parser.add_argument("root", nargs="?", default=None,
                        help="缓存根目录（省略则弹窗选择文件夹）")
    parser.add_argument("output", nargs="?", default=None,
                        help="输出目录（默认：所选文件夹的父目录）")
    args = parser.parse_args()

    # 标准输出 UTF-8，避免中文标题在 cp936 下报错
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    # 1) 确定缓存根目录（命令行优先，否则弹窗）
    if args.root:
        root = os.path.abspath(args.root)
    else:
        picked = prompt_folder()
        if not picked:
            print("未选择文件夹，已取消。")
            return 0
        root = os.path.abspath(picked)

    # 2) 确定输出目录：默认「所选文件夹的父目录」（同级位置，避免污染缓存）
    if args.output:
        out_dir = os.path.abspath(args.output)
    else:
        parent = os.path.dirname(root.rstrip("\\/"))
        out_dir = parent if parent else root

    print(f"缓存目录: {root}")
    print(f"输出目录: {out_dir}")
    print()

    if not os.path.isdir(root):
        print(f"[错误] 缓存目录不存在或不可访问: {root}")
        return 1

    ffmpeg = locate_ffmpeg()
    if ffmpeg is None:
        print("未检测到 ffmpeg。请将 ffmpeg.exe 放在 bin/ 目录或安装到 PATH。")
        print("下载: https://ffmpeg.org/download.html")
        return 1
    print(f"使用 ffmpeg: {ffmpeg}")
    print()

    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as e:
        print(f"[错误] 输出目录不可创建: {e}")
        return 1

    entries = scan_tree(root)
    if not entries:
        print("未找到任何视频条目（需目录下存在 *.m4s 文件）。")
        return 0

    print(f"共发现 {len(entries)} 个视频条目。")
    print()

    ok = fail = 0
    for i, ent in enumerate(entries, 1):
        safe = sanitize_filename(ent.title)
        print(f"[{i}/{len(entries)}] {ent.title}")
        out_mp4 = unique_path(out_dir, safe + ".mp4")
        success, err = merge_with_ffmpeg(ent.video, ent.audio, out_mp4, ffmpeg)
        if success:
            print(f"    [完成] -> {out_mp4}")
            ok += 1
            continue
        if ent.audio is not None:
            print(f"    [警告] 带音频合并失败，尝试仅封装视频。")
            success2, err2 = merge_with_ffmpeg(ent.video, None, out_mp4, ffmpeg)
            if success2:
                print(f"    [完成(仅视频)] -> {out_mp4}")
                ok += 1
                continue
            err = err2
        print(f"    [跳过] {ent.title}（{err}）")
        if os.path.exists(out_mp4):
            try:
                os.remove(out_mp4)
            except OSError:
                pass
        fail += 1

    print(f"\n==== 汇总 ====\n成功: {ok}  失败: {fail}  总计: {len(entries)}")
    print(f"输出目录: {out_dir}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())