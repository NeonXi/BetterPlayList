"""随机策略工厂"""
from .strategy import ShuffleStrategy
from .super_shuffle import SuperShuffle
from .configurable_shuffle import ConfigurableShuffle


class ShuffleStrategyFactory:
    """策略工厂：根据名称创建随机策略"""

    # 算法描述（名称 -> (显示名, 技术描述)）
    DESCRIPTIONS = {
        "super": (
            "SuperShuffle 强力洗牌",
            "基于 Fisher-Yates 公平洗牌，叠加两层约束优化：\n"
            "1. 同歌手去相邻：贪心扫描交换，避免连续两首同一歌手\n"
            "2. 近期去重：将最近播放窗口内的歌曲后置，降低短期重复概率\n"
            "时间复杂度 O(n²)，空间 O(n)，适合 1000 首以内歌单。"
        ),
        "configurable": (
            "可配置分散随机",
            "基于 Fisher-Yates 公平洗牌 + 冲突最小化贪心分散：\n"
            "在下方勾选的维度上，相邻歌曲尽量来自不同分组：\n"
            "· 热度分散：冷门(<40)/中等(40-70)/热门(>=70)\n"
            "· 歌手分散：同一歌手不连续出现\n"
            "· 年代分散：2000前/2000s/2010s/2020s\n"
            "分散为软约束，小歌单或分布不均时允许少量冲突。"
        ),
    }

    @staticmethod
    def create(strategy_name: str, options: dict | None = None) -> ShuffleStrategy:
        """
        创建随机策略
        :param strategy_name: 策略名称
        :param options: 可选配置（仅 configurable 策略使用）
        """
        if strategy_name == "super":
            return SuperShuffle()
        if strategy_name == "configurable":
            opts = options or {}
            return ConfigurableShuffle(
                spread_popularity=opts.get("spread_popularity", True),
                spread_artist=opts.get("spread_artist", True),
                spread_era=opts.get("spread_era", True),
            )
        raise ValueError(f"未知的随机策略: {strategy_name}，可选: {list(ShuffleStrategyFactory.DESCRIPTIONS.keys())}")

    @staticmethod
    def available_strategies() -> list[str]:
        return ["super", "configurable"]

    @staticmethod
    def get_display_name(strategy_name: str) -> str:
        """获取算法显示名"""
        return ShuffleStrategyFactory.DESCRIPTIONS.get(
            strategy_name, (strategy_name, "")
        )[0]

    @staticmethod
    def get_description(strategy_name: str) -> str:
        """获取算法技术描述"""
        return ShuffleStrategyFactory.DESCRIPTIONS.get(
            strategy_name, ("", "暂无描述")
        )[1]
