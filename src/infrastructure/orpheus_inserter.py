"""播放队列插入器：通过注入的 bridge 命名管道静默插入。

工作流程：
1. find_endpoint：定位网易云主播放窗口所在进程
2. probe：HELLO 探测 bridge 是否已就绪
3. 未就绪则自动注入 AwooNcmCefBridge.dll，并轮询等待 READY
4. 通过命名管道逐首 ADD_NEXT / PLAY

ADD_NEXT 的「下一首播放」队列按 FIFO（先进先出）排列：连续插入
[A, B, C] 后播放顺序即为 A→B→C，因此按正序插入即可。

完全静默，不抢焦点、不弹窗。
"""
import time
import json
import base64
import ctypes
import threading
import logging
from abc import ABC, abstractmethod
from typing import Callable

from .dll_injector import DllInjector, NeteaseEndpoint
from .awoo_client import AwooClient
from .playing_list_reader import PlayingListReader

logger = logging.getLogger(__name__)

# ShellExecuteW：用 SW_HIDE 方式打开 orpheus:// 协议，避免显示窗口
_shell32 = ctypes.windll.shell32
_shell32.ShellExecuteW.argtypes = [
    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
    ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
_shell32.ShellExecuteW.restype = ctypes.c_void_p
SW_HIDE = 0


class QueueInserter(ABC):
    """播放队列插入策略接口"""

    @abstractmethod
    def insert(self, song_ids: list[str],
               song_names: dict[str, str] = None,
               progress_callback: Callable[[int, int], None] = None,
               current_song_callback: Callable[[str], None] = None,
               stop_event: threading.Event = None,
               play_first: bool = False) -> bool:
        ...


class OrpheusInserter(QueueInserter):
    """通过 bridge 管道按正序逐首 ADD_NEXT。"""

    pipe_interval = 0.05

    def __init__(self):
        self._reader = PlayingListReader()
        # 最近一次错误信息（供上层区分「失败」与「被停止」）
        self.last_error: str = ""

    # ------------------------------------------------------------------
    # bridge 就绪保障
    # ------------------------------------------------------------------
    def ensure_bridge(self) -> tuple[NeteaseEndpoint | None, str]:
        """
        确保目标网易云进程内的 bridge 已就绪。
        :return: (端点, 错误信息)；成功时错误信息为空
        """
        endpoint = DllInjector.find_endpoint()
        if endpoint is None:
            return None, "没有发现正在运行的网易云音乐，请先启动网易云。"

        connected, _ = AwooClient.probe(endpoint.pid)
        if connected:
            return endpoint, ""

        # 需要注入
        dll_path = DllInjector.find_dll()
        if not dll_path:
            return None, "未找到 AwooNcmCefBridge.dll，无法建立连接。"

        # 检测是否已有 bridge 残留（但 probe 失败）
        existing = DllInjector.find_existing_bridge(endpoint.pid)
        if existing:
            return None, (
                "检测到网易云中已加载一个 bridge 但未就绪。"
                "请完全关闭并重新打开网易云后再试。")

        logger.info(f"[BRIDGE] 开始注入 bridge 到 PID {endpoint.pid}: {dll_path}")
        ok, msg = DllInjector.inject(endpoint.pid, dll_path)
        if not ok:
            return None, f"注入失败：{msg}"

        # 轮询等待 bridge READY（最长约 12 秒）
        deadline = time.time() + 12
        while time.time() < deadline:
            time.sleep(0.3)
            connected, raw = AwooClient.probe(endpoint.pid)
            if connected:
                logger.info(f"[BRIDGE] 已就绪: {raw}")
                return endpoint, ""

        return None, "bridge DLL 已加载，但在 12 秒内未就绪；请确认网易云主界面已完整加载。"

    # ------------------------------------------------------------------
    # 批量插入（正序，FIFO）
    # ------------------------------------------------------------------
    def insert(self, song_ids: list[str],
               song_names: dict[str, str] = None,
               progress_callback: Callable[[int, int], None] = None,
               current_song_callback: Callable[[str], None] = None,
               stop_event: threading.Event = None,
               play_first: bool = False) -> bool:
        """
        按正序批量插入播放队列。
        :param play_first: 第一首立即播放（PLAY），其余正序 ADD_NEXT
        :return: True=全部插入完成, False=被中途停止或 bridge 不可用
        """
        total = len(song_ids)
        if total == 0:
            return True

        song_names = song_names or {}
        stop_event = stop_event or threading.Event()
        self.last_error = ""

        endpoint, err = self.ensure_bridge()
        if endpoint is None:
            self.last_error = err
            logger.error(f"[INSERT] {err}")
            return False
        pid = endpoint.pid

        for index, song_id in enumerate(song_ids):  # 始终正序
            if stop_event.is_set():
                return False

            if play_first and index == 0:
                # 立即播放第一首成为「当前歌曲」
                if not self.play_song(pid, song_id):
                    # 回退：先加入再播放
                    self.add_next(pid, song_id)
                    self.play_song(pid, song_id)
                # 等待播放真正开始，确保后续 ADD_NEXT 排在它之后
                time.sleep(0.8)
            else:
                inserted = self.add_next(pid, song_id)
                if not inserted:
                    logger.warning(f"[INSERT] 插入失败，跳过: {song_id}")

            if current_song_callback:
                current_song_callback(
                    song_names.get(song_id, f"歌曲 {song_id}"))

            if progress_callback:
                progress_callback(index + 1, total)

            if index < total - 1 and self.pipe_interval > 0:
                end_time = time.time() + self.pipe_interval
                while time.time() < end_time:
                    if stop_event.is_set():
                        return False
                    time.sleep(min(0.1, end_time - time.time()))

        return True

    # ------------------------------------------------------------------
    def clear_queue(self) -> bool:
        """
        真正清空播放队列（不依赖 DLL 注入）。

        通过 ShellExecuteW 以 SW_HIDE 方式打开 orpheus:// 协议 URL，
        命令为 {"cmd":"playingList","type":"clear"} 的 base64 编码，
        网易云收到后清空队列。已在网易云 3.1.41 上实测生效。
        """
        payload = {"cmd": "playingList", "type": "clear"}
        js = json.dumps(payload, separators=(",", ":"))
        url = "orpheus://" + base64.b64encode(js.encode("utf-8")).decode("ascii")

        # 返回值 >32 表示协议成功唤起，<=32 为失败
        rc = _shell32.ShellExecuteW(None, "open", url, None, None, SW_HIDE)
        if not rc or rc <= 32:
            logger.error(f"[CLEAR] ShellExecuteW 失败，返回 {rc}")
            return False

        # 轮询确认队列真的清空（最长约 3 秒）
        for _ in range(10):
            time.sleep(0.3)
            if len(self._reader.read()) == 0:
                logger.info("[CLEAR] 播放队列已清空")
                return True

        cleared = len(self._reader.read()) == 0
        if not cleared:
            logger.warning("[CLEAR] 命令已发送但队列未清空")
        return cleared

    def verify_inserted(self, song_ids: list[str]) -> tuple[int, int]:
        """读取本地播放队列，统计成功插入数量。"""
        queue_ids = self._reader.get_song_ids()
        expected = set(song_ids)
        inserted = expected & queue_ids
        return len(inserted), len(expected)

    def add_next(self, pid: int, song_id: str) -> bool:
        """添加单曲到下一首播放（带一次重试）。"""
        if AwooClient.add_next(pid, song_id):
            return True
        time.sleep(0.15)
        return AwooClient.add_next(pid, song_id)

    def play_song(self, pid: int, song_id: str) -> bool:
        """立即播放指定歌曲（带一次重试）。"""
        if AwooClient.play(pid, song_id):
            logger.info(f"[PLAY] 播放成功: {song_id}")
            return True
        time.sleep(0.15)
        if AwooClient.play(pid, song_id):
            logger.info(f"[PLAY] 播放成功（重试）: {song_id}")
            return True
        logger.warning(f"[PLAY] 播放失败: {song_id}")
        return False
