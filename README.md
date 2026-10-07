# BetterPlayList

网易云音乐智能随机播放工具 —— 打破官方"伪随机"的局限，让歌单真正随机起来。

## 为什么做这个工具？

网易云 PC 客户端的"随机播放"存在以下问题：

- **随机不彻底**：经常连续播放同一歌手、同一专辑的歌曲
- **热门歌循环**：冷门歌曲几乎不会被随机到
- **无记忆功能**：每次随机结果雷同，近期听过的歌反复出现

BetterPlayList 通过**自定义随机算法 + 静默队列插入**解决这些问题，让你听到真正"随机"的歌单。

## 功能特性

### 🎲 两种随机算法

| 算法 | 说明 |
|------|------|
| **SuperShuffle 强力洗牌** | Fisher-Yates 公平洗牌 + 近期播放去重，近期听过的歌自动后置 |
| **Configurable 可配置分散随机** | 在公平洗牌基础上，额外确保相邻歌曲在**热度 / 歌手 / 年代**三个维度上分散，避免连续播放相似歌曲 |

### 🔇 静默队列插入（核心亮点）

- **AwooMusicBot 管道通信**：通过命名管道直接向网易云进程发送指令，**完全静默，不唤起窗口**
- **智能回退**：Awoo 不可用时自动降级到 `orpheus://` 协议，仍保持最小干扰
- **逐首插入 + 失败重试**：每首歌独立检测通道状态，失败自动重试，确保插入成功率

### 🎵 歌单管理

- 本地 Cookie 自动登录（无需手动输入账号密码）
- 歌单列表搜索、预览
- 歌单 JSON 缓存，二次加载秒开
- 支持手动输入分享链接 / 歌单 ID

### 👁️ 实时预览

- 选中歌单后实时展示随机处理结果
- 切换算法、调整参数时**实时重新排列**
- 预览列：歌名、热度、歌手、年代、听过次数
- 双击歌曲直接添加到"下一首播放"

### 📝 播放历史

- 记录每次插入的歌曲 ID
- 近期去重窗口可调（0-100 首），避免短时间内重复听到同一首歌

## 技术栈

| 技术 | 用途 |
|------|------|
| **Python 3.12** | 主语言 |
| **Tkinter** | GUI 界面（暗色主题） |
| **PyInstaller** | 单文件打包，无需 Python 环境 |
| **requests** | 网易云 API 请求 |
| **cryptography** | DPAPI 解密 + AES-GCM 解密本地 Cookie |
| **Windows Named Pipe** | 与 AwooMusicBot 注入 DLL 通信 |
| **ShellExecuteW + SW_HIDE** | 静默调用 `orpheus://` 协议 |
| **Fisher-Yates Shuffle** | 公平随机洗牌算法 |

## 核心技术实现

### 1. 本地 Cookie 自动登录

网易云 PC 客户端将登录 Cookie 加密存储在本地 SQLite 数据库中。本项目通过以下步骤自动读取：

```
Chrome DPAPI 解密 → AES-GCM 解密 → 提取 MUSIC_U 等关键 Cookie
```

无需用户手动输入账号密码，实现"已骇入本地账户"的无感登录体验。

### 2. AwooMusicBot 管道静默通信（重点借鉴）

本项目最核心的静默插入功能，**深受 [AwooMusicBot](https://github.com/MikkoAbudo/AwooMusicBot)（嗷呜点歌机）项目的启发**。

AwooMusicBot 通过 DLL 注入技术，将 `AwooNcmCefBridge.dll` 注入到网易云进程内部，然后通过 **Windows 命名管道（Named Pipe）** 与外部程序通信：

```
\\.\pipe\AwooNcmCefBridge-v1-{网易云进程PID}
```

**从 AwooMusicBot 学到的关键经验**：

| 经验 | 说明 |
|------|------|
| **管道命名规范** | `AwooNcmCefBridge-v1-{pid}`，包含进程 PID 确保唯一性 |
| **单命令单连接** | 每次连接只能发送一个命令，发送后管道关闭，需要重新连接 |
| **命令格式** | `COMMAND arg1 arg2\n`，如 `ADD_NEXT 123456` |
| **响应格式** | `OK ...` 表示成功，`ERR ...` 表示失败 |
| **静默原理** | DLL 在网易云进程内部直接调用 CEF 的 `Runtime.evaluate`，无需唤起窗口 |

**我们的改进**：

- **逐首检测**：每首歌插入前重新检测管道可用性，避免网易云状态变化导致失败
- **失败重试**：Awoo 插入失败后等待 150ms 自动重试一次
- **静默兜底**：Awoo 可用但插入失败时**静默跳过**，绝不回退到会唤起窗口的方案
- **动态间隔**：Awoo 模式下 50ms/首，orpheus 回退时 1000ms/首

### 3. orpheus:// 协议静默调用

当 AwooMusicBot 不可用时，回退到网易云官方的 `orpheus://` URL Scheme：

```python
ShellExecuteW(None, "open", url, None, None, SW_HIDE)
```

配合 `SW_HIDE` 参数和焦点归还机制，最大程度减少窗口干扰。

### 4. 可配置分散随机算法

在 Fisher-Yates 公平洗牌基础上，引入**冲突最小化贪心算法**：

```
对于每首歌，从候选池中选取与已选序列冲突最少的一首：
- 热度冲突：冷门(<40) / 中等(40-70) / 热门(>=70)
- 歌手冲突：同一歌手不连续出现
- 年代冲突：2000前 / 2000s / 2010s / 2020s
```

实测 100 首歌，纯随机产生 81 对相邻冲突，开启三个分散开关后仅 1 对冲突。

## 项目结构

```
BetterPlayList/
├── main.py                          # 程序入口
├── build.py                         # PyInstaller 打包脚本
├── requirements.txt                 # Python 依赖
├── src/
│   ├── application/                 # 应用层
│   │   ├── dto.py                   # 数据传输对象
│   │   └── shuffle_service.py       # 随机播放编排服务
│   ├── domain/                      # 领域层
│   │   ├── models.py                # 核心模型（Song, Playlist）
│   │   └── shuffle/                 # 随机算法
│   │       ├── strategy.py          # 策略接口
│   │       ├── factory.py           # 策略工厂
│   │       ├── super_shuffle.py     # 强力洗牌
│   │       └── configurable_shuffle.py  # 可配置分散随机
│   ├── infrastructure/              # 基础设施层
│   │   ├── ncm_api_client.py        # 网易云 API 客户端
│   │   ├── ncm_local_cookie.py      # 本地 Cookie 读取
│   │   ├── cached_playlist_fetcher.py  # 歌单缓存
│   │   ├── awoo_client.py           # AwooMusicBot 管道客户端
│   │   ├── orpheus_client.py        # orpheus:// 协议客户端
│   │   ├── orpheus_inserter.py      # 队列插入器
│   │   ├── playing_list_reader.py   # 播放队列读取
│   │   └── history_store.py         # 播放历史存储
│   └── presentation/                # 表现层
│       └── main_window.py           # 主窗口 GUI
├── docs/
│   └── deprecated_dll_injection.md  # 已弃用的 DLL 注入方案
└── data/                            # 运行时数据（不上传 Git）
    ├── history.json                 # 播放历史
    └── playlists/                   # 歌单缓存
```

## 使用说明

### 环境要求

- Windows 10 / 11
- 网易云音乐 PC 客户端（已登录）
- （推荐）安装 [AwooMusicBot](https://github.com/MikkoAbudo/AwooMusicBot) 以获得完全静默体验

### 运行方式

**方式一：直接运行 exe（推荐）**

下载 Release 中的 `BetterPlayList_v2.0.exe`，双击运行。

**方式二：Python 源码运行**

```bash
pip install -r requirements.txt
python main.py
```

**方式三：自行打包**

```bash
python build.py
# 生成 dist/BetterPlayList_v2.0.exe
```

### 操作步骤

1. 启动程序，自动读取本地 Cookie 登录
2. 点击"加载我的歌单"或输入分享链接
3. 选择随机算法和参数
4. 点击"写入播放列表"
5. 回到网易云客户端，队列已更新

## 致谢

- **[AwooMusicBot](https://github.com/MikkoAbudo/AwooMusicBot)**（嗷呜点歌机）— 本项目最核心的静默插入功能深受其启发，感谢作者开源了如此优雅的 DLL 注入 + 命名管道通信方案
- **网易云音乐** — 提供了 `orpheus://` URL Scheme 和本地数据存储

## 免责声明

- 本项目仅供学习和技术研究使用
- 请遵守网易云音乐用户协议，勿用于商业用途
- 使用本项目产生的任何后果由使用者自行承担

## License

MIT License
