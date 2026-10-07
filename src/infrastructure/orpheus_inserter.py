"""播放队列插入器：优先使用 AwooMusicBot 管道（静默），回退到 orpheus:// 协议"""
import time
import threading
from abc import ABC, abstractmethod
from typing import Callable

from .orpheus_client import OrpheusClient
from .awoo_client import AwooClient
from .playing_list_reader import PlayingListReader


class QueueInserter(ABC):
    """播放队列插入策略接口"""

    @abstractmethod
    def insert(self, song_ids: list[str],
               song_names: dict[str, str] = None,
               progress_callback: Callable[[int, int], None] = None,
               current_song_callback: Callable[[str], None] = None,
               stop_event: threading.Event = None) -> bool:
        """
        按顺序将歌曲插入播放队列
        :param song_ids: 歌曲ID列表（按期望的播放顺序）
        :param song_names: 歌曲ID到名称的映射，用于显示当前插入歌曲
        :param progress_callback: 进度回调 callback(current, total)
        :param current_song_callback: 当前插入歌曲回调 callback(song_name)
        :param stop_event: 停止事件，用于中途取消
        :return: 是否完整插入成功（未被中途停止）
        """
        ...


class OrpheusInserter(QueueInserter):
    """
    通过 orpheus:// 协议逐首添加到下一首

    注意：addToNext 是插到"当前播放歌曲的下一首"，
    所以要按逆序插入才能保持最终顺序正确。
    例如要插入 [A, B, C]，实际发送顺序为 C, B, A，
    最终队列变为 [..., A, B, C]
    """

    # ⚠️ 此命令格式需通过 verify_orpheus.py 验证后确认
    ADD_TO_NEXT_TEMPLATE = {"cmd": "playingList", "type": "addToNext", "value": None}

    def __init__(self):
        self._reader = PlayingListReader()

    def insert(self, song_ids: list[str],
               song_names: dict[str, str] = None,
               progress_callback: Callable[[int, int], None] = None,
               current_song_callback: Callable[[str], None] = None,
               stop_event: threading.Event = None) -> bool:
        """
        逆序批量插入播放队列
        :return: True=全部插入完成, False=被中途停止
        """
        total = len(song_ids)
        if total == 0:
            return True

        # 检测是否可用 AwooMusicBot（静默模式，不抢焦点）
        # 注意：插入过程中可能因网易云状态变化导致 Awoo 失效，
        # 所以每首歌都重新检测，且失败时重试一次

        # AwooMusicBot 管道响应快，用短间隔；orpheus 协议需要较长间隔
        awoo_interval = 0.05
        orpheus_interval = 1.0

        song_names = song_names or {}
        stop_event = stop_event or threading.Event()

        # 逆序插入，保证最终顺序正确
        for index, song_id in enumerate(reversed(song_ids)):
            # 检查是否被停止
            if stop_event.is_set():
                return False

            # 每次插入前重新检测 Awoo 是否可用
            use_awoo = AwooClient.is_available()
            inserted = False

            if use_awoo:
                # 静默模式：通过 AwooMusicBot 管道直接执行，不唤起网易云窗口
                inserted = AwooClient.add_next(song_id)
                if not inserted:
                    # 失败后等一下重试一次
                    time.sleep(0.15)
                    inserted = AwooClient.add_next(song_id)

            if not inserted:
                if use_awoo:
                    # Awoo 可用但插入失败，静默跳过（不唤起窗口）
                    pass
                else:
                    # Awoo 不可用，回退到 orpheus:// 协议
                    cmd = dict(self.ADD_TO_NEXT_TEMPLATE)
                    cmd["value"] = song_id
                    OrpheusClient.send(cmd)

            # 汇报当前插入的歌曲
            if current_song_callback:
                name = song_names.get(song_id, f"歌曲 {song_id}")
                current_song_callback(name)

            # 汇报进度
            if progress_callback:
                progress_callback(index + 1, total)

            # 最后一首不需要等待
            if index < total - 1:
                actual_interval = awoo_interval if use_awoo else orpheus_interval
                if actual_interval > 0:
                    # 用小步长 sleep，以便及时响应停止
                    end_time = time.time() + actual_interval
                    while time.time() < end_time:
                        if stop_event.is_set():
                            return False
                        time.sleep(min(0.1, end_time - time.time()))

        return True

    def clear_queue(self) -> bool:
        """清空播放队列"""
        return OrpheusClient.clear_playlist()

    def verify_inserted(self, song_ids: list[str]) -> tuple[int, int]:
        """
        验证插入结果：读取本地播放队列，统计有多少首成功插入
        :return: (成功插入数, 期望插入数)
        """
        queue_ids = self._reader.get_song_ids()
        expected = set(song_ids)
        inserted = expected & queue_ids
        return len(inserted), len(expected)

    def add_next(self, song_id: str) -> bool:
        """
        添加单曲到下一首播放（静默优先，回退 orpheus）
        :param song_id: 歌曲 ID
        :return: 是否成功
        """
        if AwooClient.is_available():
            return AwooClient.add_next(song_id)
        # 回退 orpheus 协议
        cmd = dict(self.ADD_TO_NEXT_TEMPLATE)
        cmd["value"] = song_id
        return OrpheusClient.send(cmd)
