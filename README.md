# B 站离线缓存合并工具（BAT 入口 + Python 核心）

一个 Windows 绿色小工具：扫描 B 站客户端离线缓存目录，将分散的 `video.m4s` + `audio.m4s` 无损封装为带声音的 `.mp4`。

- **轻量**：核心逻辑为 Python 脚本（纯标准库，零第三方依赖），入口为 BAT，不依赖 PyInstaller 打包的 exe。
- **全量遍历**：不假设固定目录层级，递归扫描整棵目录树并智能配对元数据与媒体流，兼容手机版/电脑版及各种混合结构。
- **零配置**：双击即弹出文件夹选择窗口，无需命令行输入路径。
- **无损**：使用 `ffmpeg -c copy` 直接封装，不重编码、无画质损失。

---

## 目录结构

**仓库（入库）内容：**

```
Merel_Cache2Mp4_bili/
├── README.md                 # 本说明
├── .gitignore
├── scripts/
│   ├── run.bat               # 入口脚本（双击或命令行调用）
│   └── merge_videos.py       # 核心逻辑（Python，纯标准库）
└── tools/
    └── build_release.bat     # 一键打包发布 ZIP
```

**本地运行时文件（已 gitignore，不入库，需自行放置/生成）：**

```
├── bin/                      # 精简版 FFmpeg（ffmpeg.exe 等），运行时依赖
├── release/                  # build_release.bat 生成的发布包
├── archive/                  # 历史遗留备份（含 v1_backup 旧版本备份）
└── .codebuddy/               # IDE 本地工作文件
```

---

## 使用方法

### 方式一：双击（推荐）

双击 `scripts\run.bat`，**弹出文件夹选择窗口**，选择你的 B 站缓存文件夹即可。

生成的 mp4 默认输出到**所选文件夹的父目录**（避免污染缓存目录）。

例如选择 `C:\Users\you\Videos\bilibili`，则 mp4 输出到 `C:\Users\you\Videos\`。

### 方式二：命令行

```bat
rem 弹窗选择文件夹（与双击等价）
run.bat

rem 指定缓存目录（输出到其父目录）
run.bat C:\Users\you\Videos\bilibili

rem 同时指定缓存目录与输出目录
run.bat C:\Users\you\Videos\bilibili D:\merged_output
```

> 核心脚本也可直接运行：`python scripts\merge_videos.py [缓存目录] [输出目录]`
> 若系统缺少 tkinter（无法弹窗），脚本会自动回退为命令行输入路径。

---

## 扫描原理（全量遍历 + 智能配对）

脚本不假设任何固定目录层级，工作流程：

1. **全量收集**：`os.walk` 递归遍历整棵树，收集
   - 所有 `*.m4s`（按所在目录分组，每个含 m4s 的目录即一个候选条目）
   - 所有元数据 `entry.json`（手机版）/ `videoInfo.json`（电脑版）
2. **音视频识别**（每个媒体目录内，三级策略逐级降级）：
   1. 固定命名：存在 `video.m4s` / `audio.m4s` 则直接使用；
   2. **精确匹配**：读同目录 `index.json`，用 `video[0].size` / `audio[0].size` 按文件大小精确匹配；
   3. 兜底启发式：按大小排序，最大者为视频、次大者为音频。
3. **标题解析**（媒体目录 → 元数据）：
   1. 媒体目录自身；
   2. 沿父目录链向上查找；
   3. **按 cid 匹配**全局元数据（应对元数据与媒体流分离的结构）；
   4. 仍无则回退使用目录名。
4. **去重**：按视频流路径去重，避免同一视频被重复处理。

### 支持的结构示例

**电脑版（平铺）：**

```
<缓存目录>/<cid>/
├── videoInfo.json          ← 标题来源（title 字段，UTF-8）
├── <cid>-1-30080.m4s       ← 视频流（较大）
└── <cid>-1-30280.m4s       ← 音频流（较小）
```

**手机版（分离式，元数据与媒体流分处不同分支，靠 cid 关联）：**

```
<缓存目录>/
├── c_<cid>/                ← 元数据分支
│   ├── cover.jpg
│   └── entry.json          ← 标题来源（title / page_data.part）
└── <avid>/                 ← 媒体流分支
    └── c_<cid>/
        └── 80/
            ├── video.m4s
            ├── audio.m4s
            └── index.json  ← 可精确按 size 识别音视频
```

> 由于采用全量遍历，脚本还兼容各类不规范命名（如带 `_nb3` 后缀的 m4s 文件）、多种清晰度 id、以及任意嵌套深度。

---

## 依赖与构建

### 运行时依赖

- **Python 3.9+**（任意，纯标准库）
- **FFmpeg**（优先 `bin\ffmpeg.exe`，其次系统 PATH）

### 获取精简版 FFmpeg

官方构建站（gyan.dev）提供精简（essentials）版，约 30–40MB，远小于完整版（222MB）：

```bat
# 下载 ffmpeg-release-essentials.7z 或 .zip 后，解压出 bin/ffmpeg.exe 放入项目 bin/ 目录
```

> `bin\` 已在 `.gitignore` 中忽略，ffmpeg.exe 不入库。

### 打包发布

```bat
tools\build_release.bat
```

会生成 `release\bili-cache2mp4-release.zip`，内含 `bin\`、`scripts\`、`README.md`。

---

## 限制说明

- 输出目录默认为所选文件夹的**父目录**；若所选目录为盘符根目录，则输出到该根目录本身。
- 同一合集多个分 P 若标题相同，输出文件会追加序号（`(2)`、`(3)`…）避免覆盖（不主动标注分 P 信息）。
- 电脑版仅能解析 UTF-8 的 `videoInfo.json`；若只有二进制 GBK 的 `.videoInfo` 文件，无法提取中文标题，将回退使用目录名。
- 同名输出文件自动追加序号，不会覆盖已有文件。
- 若本机未安装 Python 或未放置 ffmpeg，`run.bat` 会给出提示。

---

## 版本备份

改动前版本已备份：
- git tag：`v1.0-baseline`
- 文件副本：`archive/v1_backup/`

回滚方式：`git checkout v1.0-baseline -- scripts/` 或从 `archive/v1_backup/` 恢复。

---

## 已知修复（相对更早版本）

- 修正文件名清洗中 `\x00` 误将 `x`、`0` 替换为 `_` 的缺陷。
- 手机版多 P 标题改为「合集名 - 分P名」拼接，避免全部同名。
- 音频合并失败时真正降级为「仅视频」。
- 输出直接写入目标目录，不再在缓存内生成临时副本。
- 电脑版 m4s 前缀自动剥离（ftyp 前的 9 字节前缀）。
- 扫描逻辑从固定层级改为全量递归遍历 + cid 智能配对，兼容元数据与媒体流分离结构。
- 路径输入改为文件夹选择弹窗。
- 支持 Windows 保留设备名（CON/NUL/COM1 等）文件名防护。