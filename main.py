"""
BetterPlayList - 网易云智能随机播放工具
入口文件
"""
import os
import sys
import logging

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.infrastructure.ncm_api_client import NcmApiClient
from src.infrastructure.cached_playlist_fetcher import CachedPlaylistFetcher
from src.infrastructure.orpheus_inserter import OrpheusInserter
from src.infrastructure.history_store import HistoryStore
from src.application.shuffle_service import ShuffleAppService
from src.presentation.main_window import MainWindow


def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def get_base_dir():
    """获取程序基础目录（开发时为脚本目录，打包后为 exe 所在目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def main():
    setup_logging()

    base_dir = get_base_dir()
    sys.path.insert(0, base_dir)

    # 数据目录（exe 同目录下的 data 文件夹）
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    history_path = os.path.join(data_dir, "history.json")
    playlist_cache_dir = os.path.join(data_dir, "playlists")

    # 尝试从本地网易云客户端读取 Cookie（支持私有歌单 + 加载我的歌单）
    api_client = None
    try:
        api_client = NcmApiClient.from_local_client()
        logging.info("已从本地网易云客户端读取登录态")
    except Exception as e:
        logging.warning(f"读取本地登录态失败，将使用公开模式: {e}")
        api_client = NcmApiClient()

    # 组装依赖（用缓存装饰器包装歌单抓取）
    fetcher = CachedPlaylistFetcher(api_client, playlist_cache_dir)
    inserter = OrpheusInserter()
    history = HistoryStore(history_path)
    service = ShuffleAppService(fetcher, inserter, history)

    # 启动 GUI
    app = MainWindow(service, api_client=api_client)
    try:
        app.show()
    except KeyboardInterrupt:
        print("\n已退出 BetterPlayList")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
