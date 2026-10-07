"""强力随机算法：Fisher-Yates 公平洗牌 + 近期去重 + 同歌手不相邻"""
import random
from .strategy import ShuffleStrategy
from ..models import Song


class SuperShuffle(ShuffleStrategy):
    """
    强力打乱算法
    1. Fisher-Yates 公平洗牌：保证每种排列等概率
    2. 近期去重：把近期播过的歌挪到列表后部
    3. 同歌手不相邻：贪心扫描交换，避免同一歌手连续播放
    """

    def __init__(self, dedupe_window: int = 20):
        self.dedupe_window = dedupe_window

    def shuffle(self, songs: list[Song], recent_ids: list[str]) -> list[Song]:
        if not songs:
            return []

        # 1. Fisher-Yates 公平洗牌
        arr = self._fisher_yates(songs)

        # 2. 近期去重（窗口为0则跳过）
        if recent_ids and self.dedupe_window > 0:
            arr = self._deweight_recent(arr, recent_ids)

        # 3. 同歌手去相邻
        arr = self._separate_same_artist(arr)

        return arr

    @staticmethod
    def _fisher_yates(items: list) -> list:
        """Fisher-Yates 洗牌"""
        arr = items[:]
        for i in range(len(arr) - 1, 0, -1):
            j = random.randint(0, i)
            arr[i], arr[j] = arr[j], arr[i]
        return arr

    def _deweight_recent(self, songs: list[Song], recent_ids: list[str]) -> list[Song]:
        """把近期播过的歌曲挪到列表后部"""
        recent_set = set(recent_ids[-self.dedupe_window:])
        front = [s for s in songs if s.id not in recent_set]
        back = [s for s in songs if s.id in recent_set]
        return front + back

    @staticmethod
    def _separate_same_artist(songs: list[Song]) -> list[Song]:
        """贪心扫描：相邻同歌手则往后找不同歌手交换"""
        arr = songs[:]
        for i in range(len(arr) - 1):
            if arr[i].artist == arr[i + 1].artist:
                for j in range(i + 2, len(arr)):
                    if arr[j].artist != arr[i].artist:
                        arr[i + 1], arr[j] = arr[j], arr[i + 1]
                        break
        return arr
