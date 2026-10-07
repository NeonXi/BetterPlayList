"""播放历史记录存储（本地 JSON）"""
import json
import os
from collections import deque


class HistoryStore:
    """
    本地 JSON 持久化的播放历史
    用于跨次去重：记录已播放的歌曲ID，下次随机时把它们排到后面
    """

    def __init__(self, file_path: str, max_size: int = 500):
        """
        :param file_path: 历史记录文件路径
        :param max_size: 最多保留的歌曲ID数量
        """
        self.file_path = file_path
        self.max_size = max_size
        self._ids = deque(maxlen=max_size)
        self._load()

    def get_recent(self, window: int) -> list[str]:
        """获取最近播放的 window 首歌曲ID"""
        return list(self._ids)[-window:]

    def append(self, song_ids: list[str]) -> None:
        """追加播放记录"""
        for sid in song_ids:
            self._ids.append(sid)
        self._save()

    def clear(self) -> None:
        """清空历史记录"""
        self._ids.clear()
        self._save()

    def _load(self) -> None:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._ids = deque(data, maxlen=self.max_size)
            except (json.JSONDecodeError, IOError):
                self._ids = deque(maxlen=self.max_size)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(list(self._ids), f, ensure_ascii=False)
