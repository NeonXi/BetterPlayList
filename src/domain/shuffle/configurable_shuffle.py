"""可配置分散随机算法：用户自定义热度/歌手/年代三个维度的分散开关"""
import random
from .strategy import ShuffleStrategy
from ..models import Song


class ConfigurableShuffle(ShuffleStrategy):
    """
    可配置分散随机算法

    在 Fisher-Yates 公平洗牌 + 近期去重的基础上，
    通过"冲突最小化贪心"对启用的维度做相邻分散：

    - 热度分散：按 pop 分三桶（冷门 <40 / 中等 40-70 / 热门 >=70）
    - 歌手分散：同名歌手视为同组
    - 年代分散：按发行年份分四桶（2000前 / 2000s / 2010s / 2020s）

    分散为软约束：扫描相邻对，统计冲突维度数，
    在后续窗口内搜索交换候选使冲突最小化。
    小歌单或分布不均时允许存在冲突，保证必然终止。
    """

    # 交换搜索窗口大小
    SWAP_WINDOW = 50

    def __init__(
        self,
        dedupe_window: int = 20,
        spread_popularity: bool = True,
        spread_artist: bool = True,
        spread_era: bool = True,
    ):
        self.dedupe_window = dedupe_window
        self.spread_popularity = spread_popularity
        self.spread_artist = spread_artist
        self.spread_era = spread_era

    def shuffle(self, songs: list[Song], recent_ids: list[str]) -> list[Song]:
        if not songs:
            return []

        # 1. Fisher-Yates 公平洗牌
        arr = self._fisher_yates(songs)

        # 2. 近期去重（窗口为0则跳过）
        if recent_ids and self.dedupe_window > 0:
            arr = self._deweight_recent(arr, recent_ids)

        # 3. 冲突最小化贪心分散（按启用的维度）
        group_keys = self._build_group_keys()
        if group_keys:
            arr = self._spread_by_conflict(arr, group_keys)

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

    def _build_group_keys(self) -> list:
        """根据开关构建启用的分组键函数列表"""
        keys = []
        if self.spread_popularity:
            keys.append(lambda s: s.popularity_bucket)
        if self.spread_artist:
            keys.append(lambda s: s.artist)
        if self.spread_era:
            keys.append(lambda s: s.era_bucket)
        return keys

    @staticmethod
    def _conflict_count(a: Song, b: Song, group_keys: list) -> int:
        """计算两首歌在启用维度上的冲突数"""
        return sum(1 for key in group_keys if key(a) == key(b))

    def _spread_by_conflict(self, songs: list[Song], group_keys: list) -> list[Song]:
        """
        冲突最小化贪心分散
        扫描相邻对，冲突>0 时在后续窗口内搜索使冲突最低的交换候选
        """
        arr = songs[:]
        n = len(arr)

        for i in range(n - 1):
            conflict = self._conflict_count(arr[i], arr[i + 1], group_keys)
            if conflict == 0:
                continue

            # 在窗口内搜索最佳交换候选
            best_j = None
            best_conflict = conflict
            window_end = min(i + 2 + self.SWAP_WINDOW, n)

            for j in range(i + 2, window_end):
                # 交换后 arr[j] 会来到 i+1 位置，检查它与 arr[i] 的冲突
                new_conflict = self._conflict_count(arr[i], arr[j], group_keys)
                # 同时尽量不给 j 位置引入新冲突：检查被换走的 arr[i+1] 与 arr[j] 前后邻居
                if new_conflict < best_conflict:
                    # 预估交换后 j 位置的冲突变化
                    old_j_conflict = 0
                    new_j_conflict = 0
                    if j - 1 > i:  # j 的前邻居（不是正在处理的 i+1）
                        old_j_conflict += self._conflict_count(arr[j - 1], arr[j], group_keys)
                        new_j_conflict += self._conflict_count(arr[j - 1], arr[i + 1], group_keys)
                    if j + 1 < n:
                        old_j_conflict += self._conflict_count(arr[j], arr[j + 1], group_keys)
                        new_j_conflict += self._conflict_count(arr[i + 1], arr[j + 1], group_keys)

                    # 总冲突降低才交换
                    if new_conflict + new_j_conflict < conflict + old_j_conflict:
                        best_j = j
                        best_conflict = new_conflict
                        if new_conflict == 0 and new_j_conflict <= old_j_conflict:
                            break

            if best_j is not None:
                arr[i + 1], arr[best_j] = arr[best_j], arr[i + 1]

        return arr
