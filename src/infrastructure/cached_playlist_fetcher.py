"""歌单本地缓存装饰器：永久缓存 + 手动刷新"""
import json
import os
from datetime import datetime

from ..domain.models import Playlist
from .ncm_api_client import PlaylistFetcher


class CachedPlaylistFetcher(PlaylistFetcher):
    """
    歌单缓存装饰器
    包装任意 PlaylistFetcher，增加本地 JSON 缓存能力。
    策略：永久缓存，通过 refresh() 手动刷新。
    """

    def __init__(self, fetcher: PlaylistFetcher, cache_dir: str):
        """
        :param fetcher: 实际的抓取实现（如 NcmApiClient）
        :param cache_dir: 缓存目录路径
        """
        self.fetcher = fetcher
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def fetch(self, playlist_id: str) -> Playlist:
        """
        获取歌单：优先读缓存，没有则抓取并缓存
        缓存命中时仍会补充最新的本账号播放次数（动态数据，不随缓存固化）
        """
        if self.has_cache(playlist_id):
            playlist = self._load_cache(playlist_id)
            return self._fill_play_counts(playlist)
        # 无缓存，抓取并保存
        playlist = self.fetcher.fetch(playlist_id)
        self._save_cache(playlist)
        return playlist

    def _fill_play_counts(self, playlist: Playlist) -> Playlist:
        """用最新的播放次数映射补充缓存歌单中的歌曲"""
        # 底层抓取器支持播放次数查询才补充
        fetch_counts = getattr(self.fetcher, "_fetch_play_counts", None)
        if not callable(fetch_counts):
            return playlist
        play_count_map = fetch_counts()
        if not play_count_map:
            return playlist

        from dataclasses import replace
        playlist.songs = [
            replace(s, play_count=play_count_map.get(s.id, -1))
            for s in playlist.songs
        ]
        return playlist

    def refresh(self, playlist_id: str) -> Playlist:
        """
        强制刷新：重新抓取并覆盖缓存
        """
        playlist = self.fetcher.fetch(playlist_id)
        self._save_cache(playlist)
        return playlist

    def has_cache(self, playlist_id: str) -> bool:
        """检查是否有该歌单的缓存"""
        return os.path.exists(self._cache_path(playlist_id))

    def cache_time(self, playlist_id: str) -> datetime | None:
        """获取缓存文件的修改时间"""
        path = self._cache_path(playlist_id)
        if os.path.exists(path):
            return datetime.fromtimestamp(os.path.getmtime(path))
        return None

    def clear_cache(self, playlist_id: str = None) -> None:
        """
        清除缓存
        :param playlist_id: 指定歌单ID，None 则清除全部
        """
        if playlist_id:
            path = self._cache_path(playlist_id)
            if os.path.exists(path):
                os.remove(path)
        else:
            for f in os.listdir(self.cache_dir):
                if f.endswith(".json"):
                    os.remove(os.path.join(self.cache_dir, f))

    def _cache_path(self, playlist_id: str) -> str:
        return os.path.join(self.cache_dir, f"{playlist_id}.json")

    def _save_cache(self, playlist: Playlist) -> None:
        """保存歌单到本地缓存"""
        path = self._cache_path(playlist.id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(playlist.to_dict(), f, ensure_ascii=False, indent=2)

    def _load_cache(self, playlist_id: str) -> Playlist:
        """从本地缓存加载歌单"""
        path = self._cache_path(playlist_id)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Playlist.from_dict(data)
