"""orpheus:// 协议客户端：向网易云 PC 客户端发送命令"""
import base64
import json
import sys
import ctypes
import time

# Windows ShellExecute 显示方式常量
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_SHOWNOACTIVATE = 4  # 显示但不激活（不抢焦点）
SW_SHOW = 5

# 用户32 API
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def _restore_focus(target_hwnd):
    """
    将焦点归还到指定窗口
    使用 AttachThreadInput 技巧绕过 Windows 焦点保护机制
    """
    if not target_hwnd:
        return
    try:
        foreground_hwnd = user32.GetForegroundWindow()
        if foreground_hwnd == target_hwnd:
            return
        # 获取前台窗口的线程ID和当前线程ID
        foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        if foreground_thread and current_thread and foreground_thread != current_thread:
            user32.AttachThreadInput(current_thread, foreground_thread, True)
        user32.SetForegroundWindow(target_hwnd)
        if foreground_thread and current_thread and foreground_thread != current_thread:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
    except Exception:
        pass


class OrpheusClient:
    """
    封装 orpheus:// 协议调用
    网易云 PC 客户端注册了 orpheus:// URL Scheme，可通过系统协议唤起并发送指令
    """

    # 发送命令后需要归还焦点的窗口句柄（设置为 BPL 主窗口的 hwnd）
    restore_hwnd = None

    @staticmethod
    def send(payload: dict) -> bool:
        """
        发送 orpheus 命令（静默模式，发送后把焦点还给 restore_hwnd）
        :param payload: 命令对象，如 {"cmd": "play", "type": "song", "id": "123"}
        :return: 是否成功发送
        """
        try:
            json_str = json.dumps(payload, separators=(',', ':'))
            encoded = base64.b64encode(json_str.encode('utf-8')).decode('ascii')
            url = f"orpheus://{encoded}"

            if sys.platform.startswith('win'):
                # 使用 ShellExecuteW + SW_HIDE，完全隐藏窗口
                ctypes.windll.shell32.ShellExecuteW(
                    None, "open", url, None, None, SW_HIDE
                )
                # 网易云处理命令时可能自己抢焦点，这里把焦点抢回来
                if OrpheusClient.restore_hwnd:
                    # 稍等一下让网易云处理完命令再抢焦点
                    time.sleep(0.02)
                    _restore_focus(OrpheusClient.restore_hwnd)
            else:
                import subprocess
                subprocess.run(["xdg-open", url], check=False)
            return True
        except Exception:
            return False

    @staticmethod
    def play_song(song_id: str) -> bool:
        """播放指定歌曲"""
        return OrpheusClient.send({"cmd": "play", "type": "song", "id": song_id})

    @staticmethod
    def play_playlist(playlist_id: str) -> bool:
        """播放指定歌单"""
        return OrpheusClient.send({"cmd": "play", "type": "playlist", "id": playlist_id})

    @staticmethod
    def clear_playlist() -> bool:
        """清空播放队列（命令格式待验证）"""
        # 尝试多种可能的清空命令
        for cmd in [
            {"cmd": "playingList", "type": "clear"},
            {"cmd": "playingList", "type": "removeAll"},
            {"cmd": "clear"},
        ]:
            if OrpheusClient.send(cmd):
                return True
        return False
