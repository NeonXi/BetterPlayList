r"""Awoo bridge 命名管道客户端。

bridge DLL（AwooNcmCefBridge.dll）注入网易云后，会创建命令命名管道
``\\.\pipe\AwooNcmCefBridge-v1-{pid}``。本模块负责：
- probe: 发送 ``HELLO 1``，收到 ``OK READY`` 表示 bridge 已就绪
- add_next / play：文本命令 + ``\n``，读取一行响应

成功响应以 ``OK`` 开头（如 ``OK POSTED``），失败以 ``ERR`` 开头。
整个过程不唤起网易云窗口，完全静默。
"""
import threading
import logging

logger = logging.getLogger(__name__)


class AwooClient:
    """通过 bridge 命名管道向网易云发送命令（完全静默）。"""

    PIPE_PREFIX = r"\\.\pipe\AwooNcmCefBridge-v1"

    # ------------------------------------------------------------------
    # 底层调用
    # ------------------------------------------------------------------
    @staticmethod
    def _call(pid: int, command: str, timeout: float = 5.0) -> str | None:
        """
        向 bridge 发送一条命令并读取一行响应。
        :return: 响应文本；连接失败或超时返回 None
        """
        result: dict = {"resp": None}

        def _worker():
            pipe_name = f"{AwooClient.PIPE_PREFIX}-{pid}"
            try:
                # buffering=0：无缓冲二进制；readline 会读到行尾
                handle = open(pipe_name, "r+b", buffering=0)
                try:
                    handle.write((command + "\n").encode("utf-8"))
                    line = handle.readline()
                    result["resp"] = line.decode("utf-8", errors="replace").strip()
                finally:
                    handle.close()
            except Exception as exc:  # 管道不存在 / 拒绝访问等
                result["err"] = str(exc)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            logger.warning(f"[PIPE] 命令超时({timeout}s): {command}")
            return None
        if "err" in result:
            logger.debug(f"[PIPE] 命令失败 {command}: {result['err']}")
            return None
        return result["resp"]

    # ------------------------------------------------------------------
    # 高层接口（均接受显式 pid）
    # ------------------------------------------------------------------
    @staticmethod
    def probe(pid: int, timeout: float = 2.0) -> tuple[bool, str]:
        """
        探测 bridge 是否就绪。
        :return: (是否连接, 原始响应)
        """
        resp = AwooClient._call(pid, "HELLO 1", timeout=timeout)
        if resp is None:
            return False, ""
        return resp.startswith("OK"), resp

    @staticmethod
    def add_next(pid: int, song_id: str) -> bool:
        """添加歌曲到「下一首播放」。"""
        resp = AwooClient._call(pid, f"ADD_NEXT {song_id}")
        ok = bool(resp) and resp.startswith("OK")
        if not ok:
            logger.warning(f"[PIPE] ADD_NEXT 失败 id={song_id} resp={resp}")
        return ok

    @staticmethod
    def play(pid: int, song_id: str) -> bool:
        """立即播放指定歌曲。"""
        resp = AwooClient._call(pid, f"PLAY {song_id}")
        ok = bool(resp) and resp.startswith("OK")
        if not ok:
            logger.warning(f"[PIPE] PLAY 失败 id={song_id} resp={resp}")
        return ok
