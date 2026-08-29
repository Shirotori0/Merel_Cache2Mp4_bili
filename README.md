# B 站离线缓存合并工具（BAT 入口 + Python 核心）

一个 Windows 绿色小工具：扫描 B 站客户端离线缓存目录，将分散的 `video.m4s` + `audio.m4s` 无损封装为带声音的 `.mp4`。

- **轻量**：核心逻辑为 Python 脚本（纯标准库，零第三方依赖），入口为 BAT，不依赖 PyInstaller 打包的 exe。
- **双结构**：同时支持 B 站「手机版」与「电脑版」两种缓存目录结构。
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
├── archive/                  # 历史遗留备份（旧 Python/exe/压缩包）
└── .codebuddy/               # IDE 本地工作文件
```

---

## 使用方法

### 方式一：命令行（推荐）

```bat
rem 处理默认根目录（项目根）
run.bat

rem 处理指定缓存根目录
run.bat C:\Users\you\Videos\bilibili

rem 指定根目录与输出目录
run.bat C:\Users\you\Videos\bilibili D:\merged_output
```

### 方式二：双击

将 `bin\ffmpeg.exe` 与 `scripts\` 放置好后，双击 `scripts\run.bat`，默认处理项目根目录下的视频条目。

> 核心脚本也可直接运行：`python scripts\merge_videos.py [根目录] [输出目录]`

---

## 支持的缓存结构

### 手机版

```
<根目录>/
└── <任意顶层目录>/
    └── c_<cid>/
        ├── entry.json          ← 标题来源（title / page_data.part）
        └── 80/  (递归查找)
            ├── video.m4s
            └── audio.m4s
```

### 电脑版

```
<根目录>/
└── <cid>/
    ├── videoInfo.json          ← 标题来源（title 字段，UTF-8）
    ├── <cid>-1-30080.m4s       ← 视频流（较大）
    └── <cid>-1-30280.m4s       ← 音频流（较小）
```

- 电脑版按「文件大小」启发式区分音视频：同一目录下最大的 m4s 视为视频轨，次大的视为音频轨；只有一个 m4s 时视为仅视频。
- 电脑版 m4s 文件开头带有 B 站客户端的 9 字节前缀（`000000000`），工具会自动剥离后再封装。
- 支持把「单个条目目录」直接作为根目录传入（自动识别）。

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

- 电脑版仅能解析 UTF-8 的 `videoInfo.json`；若只有二进制 GBK 的 `.videoInfo` 文件，无法提取中文标题，将回退使用目录名。
- 电脑版多 P 合集若各分集 `title` 相同，输出文件会追加序号（`(2)`、`(3)`…）避免覆盖。
- 同名输出文件自动追加序号，不会覆盖已有文件。
- 若本机未安装 Python，或未放置 ffmpeg，BAT 会给出提示。

---

## 已知修复（相对旧 Python 版）

- 修正文件名清洗中 `\x00` 误将 `x`、`0` 替换为 `_` 的缺陷。
- 手机版多 P 标题改为「合集名 - 分P名」拼接，避免全部同名。
- 音频合并失败时真正降级为「仅视频」。
- 输出直接写入目标目录，不再在缓存内生成临时副本。
- 电脑版 m4s 前缀自动剥离。
