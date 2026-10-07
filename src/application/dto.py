"""应用层：数据传输对象（DTO）"""
import threading
from dataclasses import dataclass
from typing import Callable

from ..domain.models import Song


@dataclass
class ShuffleRequest:
    """随机播放请求"""
    playlist_id: str
    strategy: str = "super"
    dedupe_window: int = 20  # 近期去重窗口大小（始终开启）
    force_refresh: bool = False  # 是否强制刷新歌单缓存
    progress_callback: Callable[[int, int], None] = None  # 插入进度回调 callback(current, total)
    current_song_callback: Callable[[str], None] = None  # 当前插入歌曲回调 callback(song_name)
    stop_event: threading.Event = None  # 停止事件，用于中途取消
    clear_queue: bool = False  # 插入前是否清空播放队列
    # 可配置分散算法的三个维度开关（仅 strategy="configurable" 时生效）
    spread_popularity: bool = True  # 热度分散
    spread_artist: bool = True  # 歌手分散
    spread_era: bool = True  # 年代分散


@dataclass
class ShuffleResult:
    """随机播放结果"""
    playlist_name: str
    total: int
    shuffled_songs: list[Song]
    strategy: str
    inserted: bool
    message: str
    error: str | None = None
    stopped: bool = False  # 是否被用户中途停止
    verified_count: int = 0  # 验证成功插入的歌曲数
