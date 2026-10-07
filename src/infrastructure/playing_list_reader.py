"""读取网易云本地播放队列文件，用于验证插入结果"""
import os
import json
import logging

logger = logging.getLogger(__name__)


def get_playing_list_path() -> str:
    """获取网易云本地播放队列文件路径"""
    return os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "NetEase", "CloudMusic", "webdata", "file", "playingList"
    )


class PlayingListReader:
    """读取并解析网易云本地播放队列文件"""

    def __init__(self, file_path: str = None):
        self.file_path = file_path or get_playing_list_path()

    def read(self) -> list[dict]:
        """
        读取播放队列，返回歌曲列表
        每项格式: {"id": str, "name": str, "artist": str, "duration": int}
        """
        if not os.path.exists(self.file_path):
            logger.warning(f"播放队列文件不存在: {self.file_path}")
            return []

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取播放队列失败: {e}")
            return []

        songs = []
        for item in data.get("list", []):
            track = item.get("track", {})
            artists = track.get("artists", [])
            artist = artists[0]["name"] if artists else ""
            songs.append({
                "id": str(track.get("id", "")),
                "name": track.get("name", ""),
                "artist": artist,
                "duration": track.get("duration", 0),
            })
        return songs

    def get_song_ids(self) -> set[str]:
        """获取播放队列中所有歌曲ID的集合（用于验证）"""
        return {s["id"] for s in self.read()}

    def contains(self, song_id: str) -> bool:
        """检查某首歌是否在播放队列中"""
        return str(song_id) in self.get_song_ids()

    def count(self) -> int:
        """获取播放队列歌曲总数"""
        return len(self.read())
