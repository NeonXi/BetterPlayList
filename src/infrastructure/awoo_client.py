"""AwooMusicBot 管道客户端：通过命名管道向网易云注入的 DLL 发送命令（完全静默）"""
import os
import subprocess
import time

# Windows 隐藏控制台窗口标志
CREATE_NO_WINDOW = 0x08000000


class AwooClient:
    """
    通过 AwooMusicBot 注入到网易云进程的 DLL 通信
    完全静默，不唤起网易云窗口

    支持的命令：
    - ADD_NEXT {songId}  添加到下一首播放
    - PLAY {songId}      播放指定歌曲
    - PAUSE              暂停
    - RESUME             恢复播放
    """

    PIPE_PREFIX = r"\\.\pipe\AwooNcmCefBridge-v1"

    @staticmethod
    def _get_cloudmusic_pid() -> int | None:
        """获取网易云进程ID（隐藏控制台窗口）"""
        try:
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq cloudmusic.exe', '/FO', 'CSV'],
                capture_output=True, timeout=5,
                creationflags=CREATE_NO_WINDOW
            )
            # Windows tasklist 输出为 GBK 编码
            output = result.stdout.decode('gbk', errors='replace')
            for line in output.split('\n')[1:]:
                if line.strip():
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        return int(parts[1])
        except Exception:
            pass
        return None

    @staticmethod
    def is_available() -> bool:
        """检查 AwooMusicBot 是否可用（直接尝试打开管道，比 os.path.exists 更可靠）"""
        pid = AwooClient._get_cloudmusic_pid()
        if pid is None:
            return False
        pipe_name = rf"{AwooClient.PIPE_PREFIX}-{pid}"
        try:
            handle = os.open(pipe_name, os.O_RDWR)
            os.close(handle)
            return True
        except OSError:
            return False

    @staticmethod
    def _send_command(cmd: str, timeout: float = 2.0) -> str:
        """
        发送命令到 AwooMusicBot 管道
        :return: 响应字符串，如果失败返回空字符串
        """
        pid = AwooClient._get_cloudmusic_pid()
        if pid is None:
            return ""
        pipe_name = rf"{AwooClient.PIPE_PREFIX}-{pid}"
        try:
            handle = os.open(pipe_name, os.O_RDWR)
            try:
                os.write(handle, (cmd + '\n').encode())
                # 等待响应
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        resp = os.read(handle, 4096).decode('utf-8', errors='replace').strip()
                        if resp:
                            return resp
                    except OSError:
                        break
                    time.sleep(0.05)
            finally:
                os.close(handle)
        except Exception:
            pass
        return ""

    @staticmethod
    def add_next(song_id: str) -> bool:
        """添加歌曲到下一首播放"""
        resp = AwooClient._send_command(f"ADD_NEXT {song_id}")
        return resp.startswith("OK")

    @staticmethod
    def play(song_id: str) -> bool:
        """播放指定歌曲"""
        resp = AwooClient._send_command(f"PLAY {song_id}")
        return resp.startswith("OK")

    @staticmethod
    def pause() -> bool:
        """暂停播放"""
        resp = AwooClient._send_command("PAUSE")
        return resp.startswith("OK")

    @staticmethod
    def resume() -> bool:
        """恢复播放"""
        resp = AwooClient._send_command("RESUME")
        return resp.startswith("OK")
