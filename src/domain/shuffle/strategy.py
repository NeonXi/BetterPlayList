"""随机算法策略接口"""
from abc import ABC, abstractmethod
from ..models import Song


class ShuffleStrategy(ABC):
    """随机策略接口"""

    @abstractmethod
    def shuffle(self, songs: list[Song], recent_ids: list[str]) -> list[Song]:
        """
        打乱歌曲顺序
        :param songs: 原始歌曲列表
        :param recent_ids: 最近播放过的歌曲ID列表（按时间倒序）
        :return: 打乱后的歌曲列表
        """
        ...
