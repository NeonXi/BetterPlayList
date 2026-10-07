"""网易云歌单抓取客户端（直接调用网易云公开 API，无第三方依赖）"""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests

from ..domain.models import Song, Playlist


# 网易云 API 接口
PLAYLIST_DETAIL_URL = "https://music.163.com/api/v3/playlist/detail"
SONG_DETAIL_URL = "https://music.163.com/api/v3/song/detail"
USER_ACCOUNT_URL = "https://music.163.com/api/nuser/account/get"
USER_PLAYLIST_URL = "https://music.163.com/api/user/playlist"
PLAY_RECORD_URL = "https://music.163.com/api/v1/play/record"

# 请求头（模拟浏览器）
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com/",
    "Cookie": "os=pc; appver=3.1.37;",
}


@dataclass
class PlaylistSummary:
    """歌单摘要（用于列表展示）"""
    id: str
    name: str
    track_count: int
    cover_url: str


class PlaylistFetcher(ABC):
    """歌单抓取接口"""

    @abstractmethod
    def fetch(self, playlist_id: str) -> Playlist:
        ...


class NcmApiClient(PlaylistFetcher):
    """
    网易云 API 客户端（直接 requests 调用，无需 pyncm）
    支持抓取歌单全部歌曲、获取用户歌单列表
    """

    def __init__(self, cookie: str = None, timeout: int = 15):
        """
        :param cookie: 网易云 Cookie（MUSIC_U），抓取公开歌单可留空
        :param timeout: 请求超时秒数
        """
        self.timeout = timeout
        self.headers = dict(DEFAULT_HEADERS)
        if cookie:
            self.headers["Cookie"] = cookie

    @classmethod
    def from_local_client(cls) -> "NcmApiClient":
        """从本地网易云 PC 客户端读取 Cookie 创建实例"""
        from .ncm_local_cookie import NcmLocalCookieReader
        cookie = NcmLocalCookieReader().get_cookie_string()
        return cls(cookie=cookie)

    def get_user_info(self) -> dict:
        """获取当前登录用户信息"""
        resp = requests.get(USER_ACCOUNT_URL, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"获取用户信息失败: {data.get('message', data.get('code'))}")
        profile = data.get("profile")
        if not profile:
            # 输出调试信息帮助排查
            cookie_str = self.headers.get("Cookie", "")
            has_music_u = "MUSIC_U=" in cookie_str
            print(f"[DEBUG] get_user_info profile is None")
            print(f"[DEBUG] Cookie 长度: {len(cookie_str)}")
            print(f"[DEBUG] 包含 MUSIC_U: {has_music_u}")
            print(f"[DEBUG] 返回数据 keys: {list(data.keys())}")
            print(f"[DEBUG] account: {data.get('account')}")
            raise RuntimeError(
                "未检测到网易云登录态。\n"
                "请确保网易云 PC 客户端已启动并登录，"
                "然后重启本程序。"
            )
        return profile

    def get_user_playlists(self) -> list[PlaylistSummary]:
        """获取当前登录用户的歌单列表"""
        profile = self.get_user_info()
        uid = profile.get("userId")
        if not uid:
            raise RuntimeError("无法获取用户ID")

        # 分页获取全部歌单
        all_playlists = []
        offset = 0
        limit = 1000
        while True:
            resp = requests.get(
                USER_PLAYLIST_URL,
                params={"uid": uid, "limit": limit, "offset": offset},
                headers=self.headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                raise RuntimeError(f"获取用户歌单失败: {data.get('code')}")
            batch = data.get("playlist", [])
            all_playlists.extend(batch)
            if len(batch) < limit:
                break
            offset += limit

        return [
            PlaylistSummary(
                id=str(p["id"]),
                name=p.get("name", ""),
                track_count=p.get("trackCount", 0),
                cover_url=p.get("coverImgUrl", ""),
            )
            for p in all_playlists
        ]

    def get_playlist_info(self, playlist_id: str) -> tuple[str, int]:
        """
        轻量获取歌单元信息（名称 + 歌曲数），不抓取歌曲列表。
        用于在用户填入歌单 ID 后快速显示歌单信息。
        :return: (歌单名称, 歌曲数)
        """
        playlist_info = self._fetch_playlist_detail(playlist_id)
        name = playlist_info.get("name", "未知歌单")
        track_count = playlist_info.get("trackCount", 0)
        return name, track_count

    def fetch(self, playlist_id: str, progress_callback=None) -> Playlist:
        """
        抓取歌单全部歌曲
        :param playlist_id: 歌单ID
        :param progress_callback: 进度回调 callback(current, total, partial_songs, playlist_name)，每批歌曲详情完成后调用
        """
        # 1. 获取歌单详情
        playlist_info = self._fetch_playlist_detail(playlist_id)
        track_count = playlist_info.get("trackCount", 0)

        if track_count == 0:
            return Playlist(
                id=playlist_id,
                name=playlist_info.get('name', '未知歌单'),
                cover_url=playlist_info.get('coverImgUrl', ''),
                songs=[]
            )

        # 2. 获取歌曲列表
        #    trackIds 上限 1000，如被截断则通过分页接口补充剩余歌曲
        track_ids = [t["id"] for t in playlist_info.get("trackIds", [])]
        if not track_ids:
            # 没有 trackIds（如榜单歌单），从 tracks 中提取
            track_ids = [t["id"] for t in playlist_info.get("tracks", [])]

        # 检查是否被 1000 首上限截断
        if track_count > len(track_ids) and track_count > 0:
            print(f"[DEBUG] 歌单被截断: trackCount={track_count}, trackIds={len(track_ids)}, 开始分页获取剩余歌曲...")
            remaining = self._fetch_remaining_tracks(playlist_id, len(track_ids), track_count)
            print(f"[DEBUG] 分页获取完成: 剩余 {len(remaining)} 首，总计 {len(track_ids)} 首")
            track_ids.extend(remaining)

        playlist_name = playlist_info.get('name', '未知歌单')
        cover_url = playlist_info.get('coverImgUrl', '')

        if not track_ids:
            all_tracks = playlist_info.get("tracks", [])
        else:
            all_tracks = self._fetch_song_details(
                track_ids,
                progress_callback,
                playlist_name=playlist_name,
                cover_url=cover_url
            )

        # 3. 获取本账号播放次数映射（song_id -> play_count）
        play_count_map = self._fetch_play_counts()

        # 4. 转换为领域模型
        songs = [self._to_song(t, play_count_map) for t in all_tracks]

        return Playlist(
            id=playlist_id,
            name=playlist_info.get('name', '未知歌单'),
            cover_url=playlist_info.get('coverImgUrl', ''),
            songs=songs
        )

    def _fetch_play_counts(self) -> dict:
        """
        获取本账号每首歌的累计播放次数
        :return: {song_id_str: play_count}，未登录或失败时返回空 dict
        """
        try:
            profile = self.get_user_info()
            uid = profile.get("userId")
            if not uid:
                return {}

            resp = requests.post(
                PLAY_RECORD_URL,
                data={"uid": uid, "type": 0},  # type=0 全部时间
                headers=self.headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 200:
                return {}

            result = {}
            for item in data.get("allData", []):
                song_id = str(item.get("song", {}).get("id", ""))
                if song_id:
                    result[song_id] = item.get("playCount", 0)
            return result
        except Exception:
            # 未登录、网络错误等情况静默失败，不影响主流程
            return {}

    def _fetch_remaining_tracks(self, playlist_id: str, offset: int, total: int) -> list[int]:
        """
        当 playlist/detail 返回的 trackIds 被截断（>1000）时，
        通过分页接口获取剩余歌曲ID
        :param playlist_id: 歌单ID
        :param offset: 已获取的歌曲数（起始偏移）
        :param total: 歌单总歌曲数
        :return: 剩余歌曲ID列表
        """
        remaining_ids = []
        limit = 200  # 每页数量，网易云分页接口通常限制 200
        current_offset = offset

        while current_offset < total:
            try:
                resp = requests.get(
                    "https://music.163.com/api/playlist/track/all",
                    params={
                        "id": playlist_id,
                        "limit": limit,
                        "offset": current_offset
                    },
                    headers=self.headers,
                    timeout=self.timeout
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 200:
                    print(f"[DEBUG] 分页接口返回 code={data.get('code')}, message={data.get('message', 'N/A')}")
                    break
                songs = data.get("songs", [])
                if not songs:
                    print(f"[DEBUG] 分页接口返回空列表，offset={current_offset}")
                    break
                remaining_ids.extend([s["id"] for s in songs])
                print(f"[DEBUG] 分页获取: offset={current_offset}, 获取 {len(songs)} 首，累计 {len(remaining_ids)} 首")
                current_offset += len(songs)
                # 避免请求过快
                import time
                time.sleep(0.1)
            except Exception as e:
                print(f"[DEBUG] 分页接口异常: {e}")
                break

        return remaining_ids

    def _fetch_playlist_detail(self, playlist_id: str) -> dict:
        """获取歌单详情"""
        resp = requests.get(
            PLAYLIST_DETAIL_URL,
            params={"id": playlist_id},
            headers=self.headers,
            timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 200:
            raise RuntimeError(f"获取歌单详情失败，code={data.get('code')}")

        # 网易云网页端 API 返回的歌单在 result 字段（旧版）或 playlist 字段（v3）
        playlist = data.get("playlist") or data.get("result")
        if not playlist:
            raise RuntimeError("获取歌单详情失败：返回数据中无歌单信息")

        return playlist

    def _fetch_song_details(self, track_ids: list[int], progress_callback=None,
                           playlist_name: str = '', cover_url: str = '') -> list[dict]:
        """
        批量获取歌曲详情（每次最多 200 首，避免 URL 过长返回 400）
        :param progress_callback: 进度回调 callback(current, total, partial_songs)，每批完成后调用
        """
        all_tracks = []
        batch_size = 200

        for i in range(0, len(track_ids), batch_size):
            batch = track_ids[i:i + batch_size]
            # 构造 c 参数：[{"id":123},{"id":456}]
            c_param = json.dumps([{"id": tid} for tid in batch], separators=(',', ':'))

            resp = requests.get(
                SONG_DETAIL_URL,
                params={"c": c_param},
                headers=self.headers,
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == 200:
                batch_songs = data.get("songs", [])
                all_tracks.extend(batch_songs)
                # 流式进度回调：传递转换后的 Song 对象列表
                if progress_callback:
                    partial_songs = [self._to_song(t) for t in all_tracks]
                    progress_callback(len(all_tracks), len(track_ids), partial_songs, playlist_name)

        return all_tracks

    def _to_song(self, raw: dict, play_count_map: dict | None = None) -> Song:
        """将 API 返回的原始数据转换为 Song 模型"""
        artists = raw.get('ar', [])
        artist = artists[0]['name'] if artists else '未知歌手'
        album_info = raw.get('al', {})
        album = album_info.get('name', '未知专辑') if isinstance(album_info, dict) else '未知专辑'
        song_id = str(raw['id'])

        return Song(
            id=song_id,
            name=raw.get('name', '未知歌曲'),
            artist=artist,
            album=album,
            duration_ms=raw.get('dt', 0),
            popularity=raw.get('pop', 0),
            publish_time=raw.get('publishTime', 0),
            play_count=play_count_map.get(song_id, -1) if play_count_map else -1,
        )
