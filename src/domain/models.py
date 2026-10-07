"""领域层：核心业务模型"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Song:
    """歌曲值对象（不可变）"""
    id: str
    name: str
    artist: str
    album: str
    duration_ms: int
    popularity: int  # 0-100
    publish_time: int = 0  # 发行时间毫秒时间戳，0=未知
    play_count: int = -1  # 本账号累计播放次数，-1=未上榜/未知

    @property
    def duration_str(self) -> str:
        """时长格式化为 mm:ss"""
        seconds = self.duration_ms // 1000
        return f"{seconds // 60}:{seconds % 60:02d}"

    @property
    def popularity_bucket(self) -> str:
        """热度桶：冷门/中等/热门"""
        if self.popularity < 40:
            return "cold"
        if self.popularity < 70:
            return "mid"
        return "hot"

    @property
    def era_bucket(self) -> str:
        """年代桶：2000前/2000s/2010s/2020s/未知"""
        if self.publish_time <= 0:
            return "unknown"
        year = datetime.fromtimestamp(self.publish_time / 1000).year
        if year < 2000:
            return "pre2000"
        if year < 2010:
            return "2000s"
        if year < 2020:
            return "2010s"
        return "2020s"

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "artist": self.artist,
            "album": self.album,
            "duration_ms": self.duration_ms,
            "popularity": self.popularity,
            "publish_time": self.publish_time,
            "play_count": self.play_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Song":
        """从字典反序列化"""
        return cls(
            id=str(data["id"]),
            name=data.get("name", ""),
            artist=data.get("artist", "未知歌手"),
            album=data.get("album", "未知专辑"),
            duration_ms=int(data.get("duration_ms", 0)),
            popularity=int(data.get("popularity", 0)),
            publish_time=int(data.get("publish_time", 0)),
            play_count=int(data.get("play_count", -1)),
        )


@dataclass
class Playlist:
    """歌单聚合根"""
    id: str
    name: str
    cover_url: str
    songs: list[Song]

    @property
    def total(self) -> int:
        return len(self.songs)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "cover_url": self.cover_url,
            "songs": [s.to_dict() for s in self.songs],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Playlist":
        """从字典反序列化"""
        return cls(
            id=str(data["id"]),
            name=data.get("name", ""),
            cover_url=data.get("cover_url", ""),
            songs=[Song.from_dict(s) for s in data.get("songs", [])],
        )
