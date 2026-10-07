"""应用层：随机播放流程编排"""
import logging
import time
from .dto import ShuffleRequest, ShuffleResult
from ..domain.shuffle.factory import ShuffleStrategyFactory
from ..domain.models import Song, Playlist
from ..infrastructure.ncm_api_client import PlaylistFetcher
from ..infrastructure.orpheus_inserter import QueueInserter
from ..infrastructure.history_store import HistoryStore

logger = logging.getLogger(__name__)


class ShuffleAppService:
    """
    随机播放应用服务
    编排：抓取歌单 → 获取历史 → 随机打乱 → 插入队列 → 记录历史
    """

    def __init__(
        self,
        fetcher: PlaylistFetcher,
        inserter: QueueInserter,
        history: HistoryStore,
    ):
        self.fetcher = fetcher
        self.inserter = inserter
        self.history = history

    def run(self, request: ShuffleRequest) -> ShuffleResult:
        """执行完整随机播放流程"""
        try:
            # 1. 抓取歌单（支持缓存刷新）
            logger.info(f"开始获取歌单: {request.playlist_id}"
                        f"{'（强制刷新）' if request.force_refresh else ''}")
            if request.force_refresh and hasattr(self.fetcher, 'refresh'):
                playlist = self.fetcher.refresh(request.playlist_id)
                logger.info(f"已刷新歌单缓存")
            else:
                playlist = self.fetcher.fetch(request.playlist_id)
            logger.info(f"获取到 {playlist.total} 首歌: {playlist.name}")

            if playlist.total == 0:
                return ShuffleResult(
                    playlist_name=playlist.name,
                    total=0,
                    shuffled_songs=[],
                    strategy=request.strategy,
                    inserted=False,
                    message="歌单为空",
                    error=None
                )

            # 2. 获取近期播放历史（始终开启去重）
            recent_ids = self.history.get_recent(request.dedupe_window)
            logger.info(f"获取到 {len(recent_ids)} 条近期播放记录")

            # 3. 随机打乱
            options = None
            if request.strategy == "configurable":
                options = {
                    "spread_popularity": request.spread_popularity,
                    "spread_artist": request.spread_artist,
                    "spread_era": request.spread_era,
                }
            shuffler = ShuffleStrategyFactory.create(request.strategy, options)
            shuffled = shuffler.shuffle(playlist.songs, recent_ids)
            logger.info(f"随机打乱完成，策略: {request.strategy}")

            # 4. 可选：清空播放队列
            if request.clear_queue:
                logger.info("清空播放队列")
                self.inserter.clear_queue()
                time.sleep(1)  # 等待清空生效

            # 5. 插入播放队列
            #    若勾选清空队列，则插入第一首后立即播放，其余歌曲继续静默插入
            song_ids = [s.id for s in shuffled]
            song_names = {s.id: f"{s.name} - {s.artist}" for s in shuffled}
            logger.info(f"开始插入播放队列，共 {len(song_ids)} 首")
            insert_success = self.inserter.insert(
                song_ids,
                song_names=song_names,
                progress_callback=request.progress_callback,
                current_song_callback=request.current_song_callback,
                stop_event=request.stop_event,
                play_first=request.clear_queue,
            )

            if not insert_success:
                logger.warning("插入被用户停止")
                return ShuffleResult(
                    playlist_name=playlist.name,
                    total=len(shuffled),
                    shuffled_songs=shuffled,
                    strategy=request.strategy,
                    inserted=False,
                    stopped=True,
                    message="已停止插入",
                )

            # 6. 验证插入结果
            verified, expected = self.inserter.verify_inserted(song_ids)
            logger.info(f"插入验证: {verified}/{expected} 首已在播放队列中")

            # 7. 只有插入成功才记录历史
            self.history.append(song_ids)
            logger.info("已记录播放历史")

            return ShuffleResult(
                playlist_name=playlist.name,
                total=len(shuffled),
                shuffled_songs=shuffled,
                strategy=request.strategy,
                inserted=True,
                message=f"成功：已将 {len(shuffled)} 首歌随机插入播放队列（验证 {verified}/{expected} 首生效）",
                verified_count=verified,
            )

        except Exception as e:
            logger.error(f"执行失败: {e}", exc_info=True)
            return ShuffleResult(
                playlist_name="",
                total=0,
                shuffled_songs=[],
                strategy=request.strategy,
                inserted=False,
                message="执行失败",
                error=str(e)
            )
