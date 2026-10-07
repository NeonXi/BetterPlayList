"""表现层：Tkinter 主窗口"""
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from ..application.dto import ShuffleRequest
from ..application.shuffle_service import ShuffleAppService
from ..domain.models import Playlist, Song
from ..domain.shuffle.factory import ShuffleStrategyFactory
from ..infrastructure.ncm_api_client import NcmApiClient, PlaylistSummary


# ========== 暗色主题配色（灰黑色调）==========
BG_PRIMARY = "#1e1e1e"      # 主背景（深灰黑）
BG_SECONDARY = "#252526"    # 次背景（编辑器灰）
BG_TERTIARY = "#2d2d30"     # 控件背景
BG_HOVER = "#37373d"        # 悬停背景
FG_PRIMARY = "#e0e0e0"      # 主文字（浅灰）
FG_SECONDARY = "#858585"    # 次文字（中灰）
ACCENT = "#0e639c"          # 强调色（蓝）
ACCENT_HOVER = "#1177bb"    # 强调色悬停
SUCCESS = "#4ec9b0"         # 成功（青绿）
WARNING = "#dcdcaa"         # 警告（黄）
ERROR = "#f48771"           # 错误（红）
BORDER = "#3c3c3c"          # 边框色


class MainWindow:
    """BetterPlayList 主窗口"""

    def __init__(self, service: ShuffleAppService, api_client: NcmApiClient = None):
        self.service = service
        self.api_client = api_client
        self.user_playlists: list[PlaylistSummary] = []
        self.stop_event = threading.Event()
        self.root = tk.Tk()
        self.root.title("BetterPlayList - 网易云智能随机播放")
        self.root.geometry("1020x700")
        self.root.minsize(820, 620)
        self.root.resizable(True, True)
        self._panel_expanded = False  # 右侧面板是否展开
        self._injecting = False        # 是否正在执行注入（轮询期间暂停更新）
        self._loading_anim_jobs = {}   # 按钮动画 after 任务
        self._is_loading = False       # 是否正在加载歌单（流式加载期间）

        # 预览面板状态
        self._preview_playlist: Playlist | None = None  # 当前预览的完整歌单
        self._preview_songs: list[Song] = []            # 重排后的歌曲列表
        self._right_mode: str = "list"                   # "list" | "preview"

        self._apply_dark_theme()
        self._build_ui()
        # 异步加载用户信息（不阻塞 UI）
        self.root.after(100, self._load_user_info)
        # 设置 orpheus 命令发送后归还焦点到本窗口
        self.root.after(200, self._setup_focus_restore)

    def _setup_focus_restore(self):
        """设置 orpheus 命令发送后归还焦点到 BPL 窗口"""
        try:
            from src.infrastructure.orpheus_client import OrpheusClient
            OrpheusClient.restore_hwnd = self.root.winfo_id()
        except Exception:
            pass

    def _apply_dark_theme(self):
        """应用暗色主题到所有控件"""
        self.root.configure(bg=BG_PRIMARY)

        style = ttk.Style()
        style.theme_use("clam")

        # 全局样式
        style.configure(".", background=BG_PRIMARY, foreground=FG_PRIMARY,
                        fieldbackground=BG_TERTIARY, bordercolor=BORDER)

        # TFrame
        style.configure("TFrame", background=BG_PRIMARY)
        style.configure("Card.TFrame", background=BG_SECONDARY)

        # TLabel
        style.configure("TLabel", background=BG_PRIMARY, foreground=FG_PRIMARY,
                        font=("Microsoft YaHei", 10))
        style.configure("Title.TLabel", background=BG_PRIMARY, foreground=FG_PRIMARY,
                        font=("Microsoft YaHei", 18, "bold"))
        style.configure("Subtitle.TLabel", background=BG_PRIMARY, foreground=FG_SECONDARY,
                        font=("Microsoft YaHei", 10))
        style.configure("Card.TLabel", background=BG_SECONDARY, foreground=FG_PRIMARY,
                        font=("Microsoft YaHei", 10))
        style.configure("CardTitle.TLabel", background=BG_SECONDARY, foreground=ACCENT_HOVER,
                        font=("Microsoft YaHei", 10, "bold"))

        # TButton
        style.configure("TButton", background=BG_TERTIARY, foreground=FG_PRIMARY,
                        padding=(12, 6), font=("Microsoft YaHei", 9, "bold"),
                        borderwidth=0, focusthickness=0)
        style.map("TButton",
                  background=[("active", BG_HOVER), ("disabled", BG_SECONDARY)],
                  foreground=[("disabled", FG_SECONDARY)])

        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        padding=(20, 8), font=("Microsoft YaHei", 10, "bold"),
                        borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER), ("disabled", BG_TERTIARY)],
                  foreground=[("disabled", FG_SECONDARY)])

        # TEntry
        style.configure("TEntry", fieldbackground=BG_TERTIARY, foreground=FG_PRIMARY,
                        insertcolor=FG_PRIMARY, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        style.map("TEntry",
                  fieldbackground=[("focus", BG_HOVER)])

        # TCombobox
        style.configure("TCombobox", fieldbackground=BG_TERTIARY, background=BG_TERTIARY,
                        foreground=FG_PRIMARY, arrowcolor=FG_PRIMARY,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG_TERTIARY)])

        # TCheckbutton
        style.configure("TCheckbutton", background=BG_SECONDARY, foreground=FG_PRIMARY,
                        font=("Microsoft YaHei", 9))
        style.map("TCheckbutton",
                  background=[("active", BG_HOVER)])

        # TSpinbox
        style.configure("TSpinbox", fieldbackground=BG_TERTIARY, foreground=FG_PRIMARY,
                        arrowcolor=FG_PRIMARY, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        style.map("TSpinbox",
                  fieldbackground=[("focus", BG_HOVER)])

        # TLabelframe
        style.configure("TLabelframe", background=BG_SECONDARY, bordercolor=BORDER,
                        relief="solid")
        style.configure("TLabelframe.Label", background=BG_SECONDARY, foreground=ACCENT_HOVER,
                        font=("Microsoft YaHei", 10, "bold"))

        # Treeview
        style.configure("Treeview", background=BG_TERTIARY, foreground=FG_PRIMARY,
                        fieldbackground=BG_TERTIARY, bordercolor=BORDER,
                        font=("Microsoft YaHei", 9), rowheight=25)
        style.configure("Treeview.Heading", background=BG_SECONDARY, foreground=FG_PRIMARY,
                        font=("Microsoft YaHei", 9, "bold"))
        style.map("Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "white")])

        # Scrollbar
        style.configure("Vertical.TScrollbar", background=BG_TERTIARY,
                        troughcolor=BG_SECONDARY, bordercolor=BORDER,
                        arrowcolor=FG_PRIMARY)
        style.configure("Horizontal.TScrollbar", background=BG_TERTIARY,
                        troughcolor=BG_SECONDARY, bordercolor=BORDER,
                        arrowcolor=FG_PRIMARY)

        # Toplevel 窗口也设为暗色
        self.root.option_add("*Toplevel.background", BG_PRIMARY)
        self.root.option_add("*Toplevel.foreground", FG_PRIMARY)

    def _build_ui(self):
        """构建界面"""
        # 主容器：用 grid 布局，大小变化时效率更高
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)
        self.main_container.columnconfigure(0, weight=1)
        self.main_container.rowconfigure(0, weight=1)

        # 左侧面板（原有内容）
        self.left_panel = ttk.Frame(self.main_container)
        self.left_panel.grid(row=0, column=0, sticky="nsew")

        # 右侧面板（歌单列表/歌曲预览，默认隐藏）
        self.right_panel = ttk.Frame(self.main_container, width=520)
        self.right_panel.grid(row=0, column=1, sticky="ns")
        self.right_panel.grid_propagate(False)
        self.right_panel.grid_remove()  # 默认隐藏

        # ===== 左侧面板内容 =====
        # 标题
        title = tk.Label(
            self.left_panel,
            text="BetterPlayList",
            font=("Microsoft YaHei", 18, "bold"),
            bg=BG_PRIMARY,
            fg=FG_PRIMARY
        )
        title.pack(pady=(15, 5))

        subtitle = tk.Label(
            self.left_panel,
            text="网易云智能随机播放工具",
            font=("Microsoft YaHei", 10),
            bg=BG_PRIMARY,
            fg=FG_SECONDARY
        )
        subtitle.pack(pady=(0, 5))

        # 用户信息显示
        self.user_info_var = tk.StringVar(value="○ 检测登录态中...")
        self.user_info_label = ttk.Label(
            self.left_panel,
            textvariable=self.user_info_var,
            foreground=FG_SECONDARY,
            font=("Microsoft YaHei", 9)
        )
        self.user_info_label.pack(pady=(0, 15))

        # 加载我的歌单（主操作按钮，置于首位）
        self.load_playlists_btn = ttk.Button(
            self.left_panel,
            text="加载我的歌单",
            command=self._on_load_playlists,
            width=20,
            style="Accent.TButton"
        )
        self.load_playlists_btn.pack(pady=(0, 12))

        # 输入区
        input_frame = ttk.LabelFrame(self.left_panel, text="参数设置", padding=10)
        input_frame.pack(fill="x", padx=20, pady=(0, 10))

        # 歌单ID（支持直接输入ID或粘贴分享链接，自动提取）
        ttk.Label(input_frame, text="歌单 ID / 链接:").grid(row=0, column=0, sticky="w", pady=5)

        # 输入框 + 歌单信息标签（上下排列）
        # column 1 可水平扩展，歌单名过长时换行而非挤出按钮
        input_frame.columnconfigure(1, weight=1)
        id_container = ttk.Frame(input_frame)
        id_container.grid(row=0, column=1, sticky="ew", padx=5, pady=5)

        self.playlist_id_var = tk.StringVar()
        id_entry = ttk.Entry(
            id_container,
            textvariable=self.playlist_id_var,
            width=30
        )
        id_entry.pack(side="top", fill="x")
        # 失去焦点或回车时自动从链接中提取 ID
        id_entry.bind("<FocusOut>", self._on_id_entry_blur)
        id_entry.bind("<Return>", self._on_id_entry_blur)

        # 歌单信息 + 加载此歌单（底部并排）
        id_bottom = ttk.Frame(id_container)
        id_bottom.pack(side="top", fill="x", pady=(2, 0))

        self.playlist_info_var = tk.StringVar(value="")
        self.playlist_info_label = ttk.Label(
            id_bottom,
            textvariable=self.playlist_info_var,
            foreground=SUCCESS,
            font=("Microsoft YaHei", 8),
            wraplength=250,
            justify="left"
        )
        self.playlist_info_label.pack(side="left")

        self.load_input_btn = ttk.Button(
            id_bottom,
            text="加载此歌单",
            command=self._on_load_input_playlist,
            width=10
        )
        self.load_input_btn.pack(side="right")

        # 算法选择
        ttk.Label(input_frame, text="随机算法:").grid(row=1, column=0, sticky="w", pady=5)
        self.strategy_var = tk.StringVar(value="super")
        # 用显示名作为下拉选项，内部维护 key 映射
        self._strategy_keys = ShuffleStrategyFactory.available_strategies()
        strategy_display_names = [
            ShuffleStrategyFactory.get_display_name(k) for k in self._strategy_keys
        ]
        self._strategy_key_by_display = dict(zip(strategy_display_names, self._strategy_keys))
        self._strategy_display_by_key = dict(zip(self._strategy_keys, strategy_display_names))
        strategy_combo = ttk.Combobox(
            input_frame,
            textvariable=self.strategy_var,
            values=strategy_display_names,
            state="readonly",
            width=20
        )
        strategy_combo.grid(row=1, column=1, sticky="w", padx=5, pady=5)
        strategy_combo.set(self._strategy_display_by_key["super"])
        strategy_combo.bind("<<ComboboxSelected>>", self._on_strategy_changed)

        # 算法描述
        self.strategy_desc_var = tk.StringVar()
        self.strategy_desc_label = ttk.Label(
            input_frame,
            textvariable=self.strategy_desc_var,
            foreground=FG_SECONDARY,
            font=("Microsoft YaHei", 8),
            wraplength=440,
            justify="left"
        )
        self.strategy_desc_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 5))
        self._update_strategy_description("super")

        # ---- 近期跳过 ----
        skip_row = ttk.Frame(input_frame)
        skip_row.grid(row=3, column=0, columnspan=3, sticky="w", pady=5)
        ttk.Label(skip_row, text="近期跳过:").pack(side="left")
        self.window_var = tk.IntVar(value=20)
        ttk.Spinbox(
            skip_row,
            from_=0,
            to=100,
            textvariable=self.window_var,
            width=8
        ).pack(side="left", padx=5)
        ttk.Label(
            skip_row,
            text="（最近听过的N首歌排到最后，0=不考虑）",
            foreground=FG_SECONDARY,
            font=("Microsoft YaHei", 8)
        ).pack(side="left", padx=5)

        # ---- 刷新此歌单 ----
        refresh_row = ttk.Frame(input_frame)
        refresh_row.grid(row=4, column=0, columnspan=3, sticky="w", pady=5)
        ttk.Button(
            refresh_row,
            text="🔄 刷新此歌单",
            command=self._on_force_refresh,
            width=16
        ).pack(side="left")
        ttk.Label(
            refresh_row,
            text="（无视缓存，重新从网易云抓取最新数据）",
            foreground=FG_SECONDARY,
            font=("Microsoft YaHei", 8)
        ).pack(side="left", padx=5)

        # ---- 清空队列 ----
        clear_row = ttk.Frame(input_frame)
        clear_row.grid(row=5, column=0, columnspan=3, sticky="w", pady=5)
        self.clear_queue_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            clear_row,
            text="插入前清空播放队列",
            variable=self.clear_queue_var
        ).pack(side="left")
        ttk.Label(
            clear_row,
            text="（勾选则先清空当前队列再插入）",
            foreground=FG_SECONDARY,
            font=("Microsoft YaHei", 8)
        ).pack(side="left", padx=5)

        # ---- 可配置分散算法的三个维度开关 ----
        self.spread_frame = ttk.Frame(input_frame)
        self.spread_frame.grid(row=6, column=0, columnspan=3, sticky="w", pady=5)

        self.spread_popularity_var = tk.BooleanVar(value=True)
        self.spread_artist_var = tk.BooleanVar(value=True)
        self.spread_era_var = tk.BooleanVar(value=True)

        def on_spread_changed():
            """分散开关变化时预览模式实时重排"""
            if self._right_mode == "preview":
                self._refresh_preview_shuffle()

        self.spread_popularity_cb = ttk.Checkbutton(
            self.spread_frame,
            text="热度分散",
            variable=self.spread_popularity_var,
            command=on_spread_changed
        )
        self.spread_popularity_cb.pack(side="left", padx=(0, 10))

        self.spread_artist_cb = ttk.Checkbutton(
            self.spread_frame,
            text="歌手分散",
            variable=self.spread_artist_var,
            command=on_spread_changed
        )
        self.spread_artist_cb.pack(side="left", padx=(0, 10))

        self.spread_era_cb = ttk.Checkbutton(
            self.spread_frame,
            text="年代分散",
            variable=self.spread_era_var,
            command=on_spread_changed
        )
        self.spread_era_cb.pack(side="left")

        # 初始状态：super 策略不显示分散开关
        self._update_spread_state("super")

        # 按钮行：执行 + 停止
        btn_frame = ttk.Frame(self.left_panel)
        btn_frame.pack(pady=(10, 2))

        self.run_btn = ttk.Button(
            btn_frame,
            text="写入播放列表",
            command=self._on_run,
            width=18,
            style="Accent.TButton"
        )
        self.run_btn.pack(side="left", padx=5)

        self.stop_btn = ttk.Button(
            btn_frame,
            text="停止",
            command=self._on_stop,
            width=10,
            state="disabled"
        )
        self.stop_btn.pack(side="left", padx=5)

        # DLL 注入按钮行
        inject_frame = ttk.Frame(self.left_panel)
        inject_frame.pack(pady=(2, 2))

        self.inject_btn = ttk.Button(
            inject_frame,
            text="注入静默通道",
            command=self._on_inject_dll,
            width=14
        )
        self.inject_btn.pack(side="left", padx=5)

        self.inject_status_var = tk.StringVar(value="")
        self.inject_status_label = ttk.Label(
            inject_frame,
            textvariable=self.inject_status_var,
            foreground=FG_SECONDARY,
            font=("Microsoft YaHei", 8)
        )
        self.inject_status_label.pack(side="left", padx=5)

        # 初始化时检测 DLL 状态
        self._check_dll_status()

        # 当前插入歌曲显示
        self.current_song_var = tk.StringVar(value="")
        self.current_song_label = ttk.Label(
            self.left_panel,
            textvariable=self.current_song_var,
            foreground=ACCENT,
            font=("Microsoft YaHei", 9)
        )
        self.current_song_label.pack(pady=(2, 2))

        # 提示信息
        self.tip_label = ttk.Label(
            self.left_panel,
            text="提示：请保持网易云为「顺序播放」状态",
            foreground=WARNING,
            font=("Microsoft YaHei", 9)
        )
        self.tip_label.pack(pady=(0, 10))

        # 底部开发者信息（先固定到底部）
        dev_frame = ttk.Frame(self.left_panel)
        dev_frame.pack(side="bottom", fill="x", pady=(5, 10))
        dev_label = tk.Label(
            dev_frame,
            text="开发者主页 → Bilibili",
            font=("Microsoft YaHei", 8),
            bg=BG_PRIMARY,
            fg=FG_SECONDARY,
            cursor="hand2"
        )
        dev_label.pack()
        dev_label.bind(
            "<Button-1>",
            lambda e: self._open_url("https://space.bilibili.com/21001459")
        )
        dev_label.bind(
            "<Enter>",
            lambda e: dev_label.configure(fg=ACCENT)
        )
        dev_label.bind(
            "<Leave>",
            lambda e: dev_label.configure(fg=FG_SECONDARY)
        )

        # 日志区（填充剩余空间）
        log_frame = ttk.LabelFrame(self.left_panel, text="运行日志", padding=5)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            font=("Consolas", 9),
            bg=BG_TERTIARY,
            fg=FG_PRIMARY,
            insertbackground=FG_PRIMARY,
            selectbackground=ACCENT,
            selectforeground="white",
            borderwidth=0,
            state="disabled",
            wrap="none"  # 关闭自动换行：避免窗口拖拽时全文重排导致卡顿
        )
        self.log_text.pack(fill="both", expand=True, pady=(0, 5))

        # ===== 右侧面板：双模式容器 =====
        # 模式1: 歌单列表
        self.playlist_list_frame = ttk.Frame(self.right_panel, padding=10)
        self.playlist_list_frame.pack(fill="both", expand=True)

        # 模式1 - 头部 + 关闭按钮
        pl_header = ttk.Frame(self.playlist_list_frame)
        pl_header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            pl_header,
            text="我的歌单",
            font=("Microsoft YaHei", 11, "bold")
        ).pack(side="left")
        ttk.Button(
            pl_header,
            text="收起",
            command=self._collapse_right_panel,
            width=6
        ).pack(side="right")

        # 模式1 - 搜索框
        pl_search_frame = ttk.Frame(self.playlist_list_frame)
        pl_search_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(pl_search_frame, text="搜索:").pack(side="left")
        self.playlist_search_var = tk.StringVar()
        search_entry = ttk.Entry(pl_search_frame, textvariable=self.playlist_search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.playlist_search_var.trace_add("write", self._on_playlist_search)

        # 模式1 - 歌单列表
        pl_list_frame = ttk.Frame(self.playlist_list_frame)
        pl_list_frame.pack(fill="both", expand=True)

        self.playlist_tree = ttk.Treeview(
            pl_list_frame,
            columns=("name", "count"),
            show="headings",
            selectmode="browse"
        )
        self.playlist_tree.heading("name", text="歌单名称")
        self.playlist_tree.heading("count", text="歌曲数")
        self.playlist_tree.column("name", width=380)
        self.playlist_tree.column("count", width=80, anchor="center")
        self.playlist_tree.bind("<Double-1>", self._on_playlist_double_click)

        pl_scrollbar = ttk.Scrollbar(pl_list_frame, orient="vertical", command=self.playlist_tree.yview)
        self.playlist_tree.configure(yscrollcommand=pl_scrollbar.set)
        self.playlist_tree.pack(side="left", fill="both", expand=True)
        pl_scrollbar.pack(side="right", fill="y")

        # 模式1 - 底部按钮
        pl_btn_frame = ttk.Frame(self.playlist_list_frame)
        pl_btn_frame.pack(fill="x", pady=(8, 0))
        ttk.Button(
            pl_btn_frame,
            text="选择此歌单",
            command=self._on_playlist_select
        ).pack(side="right")

        # 模式2: 歌曲预览（默认隐藏）
        self.song_preview_frame = ttk.Frame(self.right_panel, padding=10)
        # 不 pack，由 _enter_preview_mode 控制

        # 模式2 - 头部 + 返回按钮
        pv_header = ttk.Frame(self.song_preview_frame)
        pv_header.pack(fill="x", pady=(0, 8))
        self.preview_title_var = tk.StringVar(value="歌曲预览")
        ttk.Label(
            pv_header,
            textvariable=self.preview_title_var,
            font=("Microsoft YaHei", 11, "bold")
        ).pack(side="left")
        ttk.Button(
            pv_header,
            text="返回歌单列表",
            command=self._exit_preview_mode,
            width=10
        ).pack(side="right")

        # 模式2 - 预览数量切换
        pv_top = ttk.Frame(self.song_preview_frame)
        pv_top.pack(fill="x", pady=(0, 8))
        ttk.Label(pv_top, text="预览:").pack(side="left")
        self.preview_limit_var = tk.StringVar(value="显示全部")
        pv_limit_combo = ttk.Combobox(
            pv_top,
            textvariable=self.preview_limit_var,
            values=["显示全部", "只显示前50首"],
            state="readonly",
            width=12
        )
        pv_limit_combo.pack(side="left", padx=5)
        self.preview_limit_var.trace_add("write", self._on_preview_limit_changed)

        # 模式2 - 歌曲列表
        pv_list_frame = ttk.Frame(self.song_preview_frame)
        pv_list_frame.pack(fill="both", expand=True)

        self.preview_tree = ttk.Treeview(
            pv_list_frame,
            columns=("seq", "name", "popularity", "artist", "era", "played"),
            show="headings",
            selectmode="browse"
        )
        self.preview_tree.heading("seq", text="#")
        self.preview_tree.heading("name", text="歌名")
        self.preview_tree.heading("popularity", text="热度")
        self.preview_tree.heading("artist", text="歌手")
        self.preview_tree.heading("era", text="年代")
        self.preview_tree.heading("played", text="听过")
        self.preview_tree.column("seq", width=40, anchor="center")
        self.preview_tree.column("name", width=160)
        self.preview_tree.column("popularity", width=50, anchor="center")
        self.preview_tree.column("artist", width=110)
        self.preview_tree.column("era", width=60, anchor="center")
        self.preview_tree.column("played", width=60, anchor="center")

        pv_scrollbar = ttk.Scrollbar(pv_list_frame, orient="vertical", command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=pv_scrollbar.set)
        self.preview_tree.pack(side="left", fill="both", expand=True)
        pv_scrollbar.pack(side="right", fill="y")

        # 模式2 - 底部信息
        pv_info_frame = ttk.Frame(self.song_preview_frame)
        pv_info_frame.pack(fill="x", pady=(8, 0))
        self.preview_info_var = tk.StringVar(value="")
        ttk.Label(pv_info_frame, textvariable=self.preview_info_var).pack(side="left")

    def _expand_right_panel(self):
        """展开右侧歌单面板（grid 显示，不改窗口大小）"""
        if not self._panel_expanded:
            self.right_panel.grid()  # 恢复显示
            self._panel_expanded = True

    def _collapse_right_panel(self):
        """收起右侧歌单面板（grid 隐藏，不改窗口大小）"""
        if self._panel_expanded:
            self.right_panel.grid_remove()
            self._panel_expanded = False

    def _on_playlist_search(self, *_):
        """搜索过滤歌单"""
        if not hasattr(self, 'user_playlists'):
            return
        keyword = self.playlist_search_var.get().lower()
        self.playlist_tree.delete(*self.playlist_tree.get_children())
        for pl in self.user_playlists:
            if keyword in pl.name.lower():
                self.playlist_tree.insert(
                    "", "end",
                    values=(pl.name, pl.track_count),
                    iid=pl.id
                )

    def _on_playlist_double_click(self, _=None):
        """双击选择歌单"""
        self._on_playlist_select()

    def _on_playlist_select(self):
        """选择歌单，异步获取完整歌曲列表并进入预览模式"""
        selected = self.playlist_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择一个歌单")
            return
        playlist_id = selected[0]
        self.playlist_id_var.set(playlist_id)
        # 从已加载的歌单列表中查找名称和歌曲数，直接显示
        for pl in self.user_playlists:
            if pl.id == playlist_id:
                self._update_playlist_info(pl.name, pl.track_count)
                break
        self._log(f"已选择歌单: {playlist_id}，正在加载歌曲列表...")

        # 启动加载动画，给用户即时反馈
        self.load_input_btn.config(state="disabled")
        self._start_loading_anim(self.load_input_btn, "加载中", "input")
        self._is_loading = True
        self.run_btn.configure(state="disabled")  # 加载期间禁用写入按钮

        # 异步获取完整歌单并进入预览模式（支持流式进度 + 实时刷新列表）
        def progress_callback(current: int, total: int, partial_songs: list, playlist_name: str = ""):
            pct = int(current / total * 100) if total > 0 else 0
            self.root.after(0, lambda: self.playlist_info_var.set(
                f"正在加载歌曲详情... {current}/{total} ({pct}%)"
            ))
            # 实时更新预览列表
            if partial_songs:
                self.root.after(0, lambda s=partial_songs, n=playlist_name: self._update_preview_songs(s, n))

        def task():
            try:
                playlist = self.service.fetcher.fetch(playlist_id, progress_callback)
                self.root.after(0, lambda: self._on_fetch_success(playlist))
            except Exception as e:
                self.root.after(0, lambda: self._on_fetch_error(str(e)))

        threading.Thread(target=task, daemon=True).start()

    def _start_loading_anim(self, btn: ttk.Button, base_text: str, key: str):
        """启动按钮加载动画（文字循环: 加载中. → 加载中.. → 加载中...）"""
        self._stop_loading_anim(key)
        dots = [".", "..", "..."]
        idx = [0]  # 用列表实现闭包内可变状态

        def step():
            btn.config(text=f"{base_text}{dots[idx[0]]}")
            idx[0] = (idx[0] + 1) % len(dots)
            self._loading_anim_jobs[key] = self.root.after(400, step)

        step()

    def _stop_loading_anim(self, key: str, restore_text: str = None):
        """停止按钮加载动画"""
        job = self._loading_anim_jobs.pop(key, None)
        if job is not None:
            self.root.after_cancel(job)

    def _on_load_input_playlist(self):
        """点击"加载此歌单"按钮，加载输入框中的歌单"""
        raw = self.playlist_id_var.get().strip()
        if not raw:
            messagebox.showwarning("提示", "请先输入歌单链接或ID")
            return
        playlist_id = self._extract_playlist_id(raw)
        if not playlist_id:
            messagebox.showwarning("提示", "无法从输入中提取歌单ID")
            return
        self.playlist_id_var.set(playlist_id)
        self._log(f"手动加载歌单: {playlist_id}")

        # 启动加载动画
        self.load_input_btn.config(state="disabled")
        self._start_loading_anim(self.load_input_btn, "加载中", "input")

        self._fetch_playlist_info_async(playlist_id)

    def _on_id_entry_blur(self, event=None):
        """输入框失去焦点或回车时，自动从分享链接中提取歌单 ID"""
        raw = self.playlist_id_var.get().strip()
        if not raw:
            return
        extracted = self._extract_playlist_id(raw)
        if extracted and extracted != raw:
            self.playlist_id_var.set(extracted)
            self._log(f"已从链接中提取歌单 ID: {extracted}")
        # 无论是否提取，都尝试获取并显示歌单信息
        if extracted:
            self._fetch_playlist_info_async(extracted)

    def _on_force_refresh(self):
        """点击"刷新此歌单"按钮：无视缓存，重新从网络抓取最新歌单"""
        raw = self.playlist_id_var.get().strip()
        if not raw:
            messagebox.showwarning("提示", "请先输入歌单链接或ID，或加载一个歌单")
            return
        playlist_id = self._extract_playlist_id(raw)
        if not playlist_id:
            messagebox.showwarning("提示", "无法从输入中提取歌单ID")
            return
        self.playlist_id_var.set(playlist_id)
        self._log(f"强制刷新歌单: {playlist_id}")

        # 启动加载动画（使用独立 key，避免与"加载此歌单"冲突）
        self.load_input_btn.config(state="disabled")
        self._start_loading_anim(self.load_input_btn, "刷新中", "refresh")

        self._force_refresh_async(playlist_id)

    def _force_refresh_async(self, playlist_id: str):
        """异步强制刷新歌单（支持流式加载进度显示 + 实时刷新列表）"""
        self.playlist_info_var.set("正在强制刷新歌单...")
        self.playlist_info_label.configure(foreground=FG_SECONDARY)
        self._is_loading = True
        self.run_btn.configure(state="disabled")  # 加载期间禁用写入按钮

        def progress_callback(current: int, total: int, partial_songs: list, playlist_name: str = ""):
            pct = int(current / total * 100) if total > 0 else 0
            self.root.after(0, lambda: self.playlist_info_var.set(
                f"正在刷新歌曲详情... {current}/{total} ({pct}%)"
            ))
            # 实时更新预览列表
            if partial_songs:
                self.root.after(0, lambda s=partial_songs, n=playlist_name: self._update_preview_songs(s, n))

        def task():
            try:
                playlist = self.service.fetcher.refresh(playlist_id, progress_callback)
                self.root.after(0, lambda: self._on_fetch_success(playlist))
            except Exception as e:
                self.root.after(0, lambda: self._on_fetch_error(str(e)))

        threading.Thread(target=task, daemon=True).start()

    def _fetch_playlist_info_async(self, playlist_id: str):
        """异步获取歌单信息并进入预览模式（支持流式加载进度显示 + 实时刷新列表）"""
        self.playlist_info_var.set("正在获取歌单信息...")
        self.playlist_info_label.configure(foreground=FG_SECONDARY)
        self._is_loading = True
        self.run_btn.configure(state="disabled")  # 加载期间禁用写入按钮

        def progress_callback(current: int, total: int, partial_songs: list, playlist_name: str = ""):
            """流式进度回调：在主线程更新进度标签并实时刷新预览列表"""
            pct = int(current / total * 100) if total > 0 else 0
            self.root.after(0, lambda: self.playlist_info_var.set(
                f"正在加载歌曲详情... {current}/{total} ({pct}%)"
            ))
            # 实时更新预览列表（使用当前已加载的歌曲）
            if partial_songs:
                self.root.after(0, lambda s=partial_songs, n=playlist_name: self._update_preview_songs(s, n))
            # 每 200 首记录一次日志
            if current % 200 == 0:
                self.root.after(0, lambda c=current, t=total:
                    self._log(f"加载进度: {c}/{t} ({int(c/t*100) if t > 0 else 0}%)")
                )

        def task():
            try:
                playlist = self.service.fetcher.fetch(playlist_id, progress_callback)
                self.root.after(0, lambda: self._on_fetch_success(playlist))
            except Exception as e:
                self.root.after(0, lambda: self._on_fetch_error(str(e)))

        threading.Thread(target=task, daemon=True).start()

    def _on_fetch_success(self, playlist: Playlist):
        """歌单加载成功：停止动画、恢复按钮、进入预览"""
        self._stop_loading_anim("input")
        self._stop_loading_anim("refresh")
        self.load_input_btn.config(state="normal", text="加载此歌单")
        self._is_loading = False
        self.run_btn.configure(state="normal")  # 恢复写入按钮
        self._enter_preview_mode(playlist)

    def _on_fetch_error(self, error_msg: str):
        """歌单加载失败：停止动画、恢复按钮、显示错误"""
        self._stop_loading_anim("input")
        self._stop_loading_anim("refresh")
        self.load_input_btn.config(state="normal", text="加载此歌单")
        self._is_loading = False
        self.run_btn.configure(state="normal")  # 恢复写入按钮
        self._update_playlist_info_error()
        self._log(f"✗ 加载歌单失败: {error_msg}")

    def _update_playlist_info(self, name: str, count: int):
        """更新歌单信息显示"""
        self.playlist_info_var.set(f"📂 {name}（{count} 首）")
        self.playlist_info_label.configure(foreground=SUCCESS)

    def _update_playlist_info_error(self):
        """获取歌单信息失败"""
        self.playlist_info_var.set("⚠ 无法获取歌单信息（可能歌单不存在或为私有）")
        self.playlist_info_label.configure(foreground=WARNING)

    @staticmethod
    def _extract_playlist_id(raw: str) -> str | None:
        """
        从歌单分享链接或纯数字 ID 中提取歌单 ID。
        支持的格式：
        - 纯数字 ID: "18258393837"
        - music.163.com/playlist?id=xxx
        - music.163.com/#/playlist?id=xxx
        - music.163.com/playlist/xxx
        - 其他包含 id=数字 的链接
        """
        import re
        raw = raw.strip()
        # 纯数字直接返回
        if raw.isdigit():
            return raw
        # 匹配 id=数字（优先）
        m = re.search(r'[?&]id=(\d+)', raw)
        if m:
            return m.group(1)
        # 匹配 /playlist/数字
        m = re.search(r'/playlist/(\d+)', raw)
        if m:
            return m.group(1)
        # 匹配任意位置的 id=数字
        m = re.search(r'id=(\d+)', raw)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _open_url(url: str):
        """在默认浏览器中打开链接"""
        import webbrowser
        webbrowser.open(url)

    def _log(self, message: str):
        """向日志区追加消息"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _load_user_info(self):
        """异步加载本地网易云用户信息并显示在头部"""
        def task():
            try:
                # 实时读取本地 Cookie（确保客户端已登录）
                from src.infrastructure.ncm_api_client import NcmApiClient
                client = NcmApiClient.from_local_client()
                info = client.get_user_info()
                nickname = info.get("nickname", "未知用户")
                self.root.after(0, lambda: self._update_user_info(True, nickname))
            except Exception:
                self.root.after(0, lambda: self._update_user_info(False, None))

        threading.Thread(target=task, daemon=True).start()

    def _update_user_info(self, logged_in: bool, nickname: str | None):
        """更新头部用户信息显示"""
        if logged_in and nickname:
            self.user_info_var.set(f"● 已骇入本地账户: {nickname}")
            self.user_info_label.configure(foreground=SUCCESS)
        else:
            self.user_info_var.set("○ 未检测到登录态（公开歌单仍可用）")
            self.user_info_label.configure(foreground=WARNING)

    def _on_load_playlists(self):
        """点击加载我的歌单按钮"""
        self.load_playlists_btn.configure(state="disabled")
        self._log("正在读取本地网易云登录态并获取歌单...")

        # 启动加载动画
        self._start_loading_anim(self.load_playlists_btn, "加载中", "my")

        thread = threading.Thread(target=self._load_playlists_task, daemon=True)
        thread.start()

    def _load_playlists_task(self):
        """后台获取用户歌单列表（实时读取本地 Cookie，不依赖启动状态）"""
        import traceback
        from src.infrastructure.ncm_api_client import NcmApiClient

        try:
            # 每次点击都重新读取本地 Cookie，确保最新登录态
            client = NcmApiClient.from_local_client()
            playlists = client.get_user_playlists()
            self.root.after(0, self._show_playlist_selector, playlists)
        except Exception as e:
            error_detail = traceback.format_exc()
            self._log(f"✗ 加载歌单失败:\n{error_detail}")
            error_msg = str(e)
            self.root.after(0, lambda: self._on_playlist_load_error(error_msg))

    def _on_playlist_load_error(self, error_msg: str):
        """歌单加载失败"""
        # 停止加载动画，恢复按钮
        self._stop_loading_anim("my")
        self.load_playlists_btn.configure(state="normal", text="加载我的歌单")

        # 输出到控制台（CMD）
        print(f"[ERROR] 加载歌单失败: {error_msg}", flush=True)
        self._log(f"✗ 加载歌单失败: {error_msg}")

        # 根据错误类型给出建议
        suggestion = ""
        if "登录态" in error_msg or "MUSIC_U" in error_msg:
            suggestion = (
                "\n\n可能的原因:\n"
                "1. 网易云客户端未登录\n"
                "2. 登录态已过期，请在网易云客户端重新登录\n"
                "3. 本程序与网易云客户端的 Python 环境不一致"
            )
        elif "cryptography" in error_msg or "No module" in error_msg:
            suggestion = "\n\n请运行: pip install cryptography"

        messagebox.showerror(
            "失败",
            f"加载歌单失败:\n{error_msg}{suggestion}"
        )
        self.load_playlists_btn.configure(state="normal")

    def _show_playlist_selector(self, playlists: list[PlaylistSummary]):
        """将歌单填充到右侧面板并展开"""
        # 停止加载动画，恢复按钮文字
        self._stop_loading_anim("my")
        self.load_playlists_btn.configure(state="normal", text="加载我的歌单")

        self.user_playlists = playlists
        self._log(f"✓ 加载到 {len(playlists)} 个歌单")

        # 如果当前在预览模式，先切回歌单列表
        if self._right_mode == "preview":
            self._exit_preview_mode()

        # 清空并填充歌单列表
        self.playlist_search_var.set("")
        self.playlist_tree.delete(*self.playlist_tree.get_children())
        for pl in playlists:
            self.playlist_tree.insert(
                "", "end",
                values=(pl.name, pl.track_count),
                iid=pl.id
            )

        # 展开右侧面板
        self._expand_right_panel()

    def _on_strategy_changed(self, event=None):
        """算法选择变化时更新描述和开关状态"""
        display_name = self.strategy_var.get()
        strategy_key = self._strategy_key_by_display.get(display_name, "")
        self._update_strategy_description(strategy_key)
        self._update_spread_state(strategy_key)
        # 预览模式下实时重排
        if self._right_mode == "preview":
            self._refresh_preview_shuffle()

    def _update_spread_state(self, strategy_key: str):
        """根据策略显示/隐藏三个分散开关"""
        if strategy_key == "configurable":
            self.spread_frame.grid()
        else:
            self.spread_frame.grid_remove()

    def _update_preview_songs(self, songs: list, playlist_name: str = ""):
        """流式加载期间实时更新预览歌曲列表"""
        # 首次进入预览模式：展开面板、切换显示
        if self._right_mode != "preview":
            if not self._panel_expanded:
                self._expand_right_panel()
            self.playlist_list_frame.pack_forget()
            self.song_preview_frame.pack(fill="both", expand=True)
            self._right_mode = "preview"
            # 创建临时的 preview_playlist 对象
            if not self._preview_playlist:
                self._preview_playlist = Playlist(
                    id="",
                    name=playlist_name,
                    cover_url="",
                    songs=[]
                )

        if not self._preview_playlist:
            return

        # 更新预览播放列表的歌曲
        self._preview_playlist.songs = songs
        self._preview_songs = songs
        self._render_preview_tree()
        # 更新标题中的数量
        self.preview_title_var.set(f"随机处理结果预览 - {self._preview_playlist.name} ({len(songs)}首)")

    def _enter_preview_mode(self, playlist: Playlist):
        """进入歌曲预览模式"""
        # 确保右侧面板展开
        if not self._panel_expanded:
            self._expand_right_panel()

        self._preview_playlist = playlist
        self.preview_title_var.set(f"随机处理结果预览 - {playlist.name}")

        # 切换面板显示
        self.playlist_list_frame.pack_forget()
        self.song_preview_frame.pack(fill="both", expand=True)
        self._right_mode = "preview"

        # 更新歌单信息标签
        self._update_playlist_info(playlist.name, playlist.total)

        # 初始重排
        self._refresh_preview_shuffle()
        self._log(f"✓ 歌曲预览已加载: {playlist.name}（{playlist.total} 首）")

    def _exit_preview_mode(self):
        """退出预览模式，返回歌单列表"""
        self.song_preview_frame.pack_forget()
        self.playlist_list_frame.pack(fill="both", expand=True)
        self._right_mode = "list"
        self._preview_playlist = None
        self._preview_songs = []
        self.preview_info_var.set("")

    def _on_preview_limit_changed(self, *_):
        """预览数量切换时重新渲染"""
        self._render_preview_tree()

    def _refresh_preview_shuffle(self):
        """根据当前算法设置重新排列预览歌曲"""
        if not self._preview_playlist:
            return

        options = {
            "spread_popularity": self.spread_popularity_var.get(),
            "spread_artist": self.spread_artist_var.get(),
            "spread_era": self.spread_era_var.get(),
        }
        strategy = self._strategy_key_by_display.get(self.strategy_var.get(), "super")
        shuffler = ShuffleStrategyFactory.create(
            strategy, options if strategy == "configurable" else None
        )
        # 预览模式也考虑近期跳过，与实际执行结果保持一致
        recent_ids = self.service.history.get_recent(self.window_var.get())
        self._preview_songs = shuffler.shuffle(self._preview_playlist.songs, recent_ids)
        self._render_preview_tree()

    def _render_preview_tree(self):
        """渲染预览歌曲列表"""
        self.preview_tree.delete(*self.preview_tree.get_children())

        songs = self._preview_songs
        total = len(songs)
        if self.preview_limit_var.get() == "只显示前50首":
            songs = songs[:50]

        POPULARITY_MAP = {"cold": "冷门", "mid": "中等", "hot": "热门"}
        ERA_MAP = {
            "pre2000": "2000前", "2000s": "2000s",
            "2010s": "2010s", "2020s": "2020s", "unknown": "未知"
        }

        for i, song in enumerate(songs, 1):
            play_count_str = str(song.play_count) if song.play_count >= 0 else "-"
            self.preview_tree.insert("", "end", values=(
                i,
                song.name,
                POPULARITY_MAP.get(song.popularity_bucket, song.popularity_bucket),
                song.artist,
                ERA_MAP.get(song.era_bucket, song.era_bucket),
                play_count_str,
            ))

        limit_text = "全部" if self.preview_limit_var.get() == "显示全部" else "前50首"
        self.preview_info_var.set(f"共 {total} 首，当前显示 {len(songs)} 首（{limit_text}）")

        # 绑定双击事件：添加到下一首播放
        self.preview_tree.bind("<Double-1>", self._on_preview_double_click)

    def _on_preview_double_click(self, event=None):
        """双击预览歌曲，添加到下一首播放"""
        selected = self.preview_tree.selection()
        if not selected:
            return
        # 获取选中的索引
        index = self.preview_tree.index(selected[0])
        if index >= len(self._preview_songs):
            return
        song = self._preview_songs[index]
        self._log(f"正在添加到下一首: {song.name} - {song.artist}")

        # 后台执行
        def task():
            success = self.service.inserter.add_next(song.id)
            msg = f"✓ 已添加到下一首: {song.name}" if success else f"✗ 添加失败: {song.name}"
            self.root.after(0, lambda: self._log(msg))

        threading.Thread(target=task, daemon=True).start()

    def _update_strategy_description(self, strategy_key: str):
        """更新算法描述文本"""
        display_name = ShuffleStrategyFactory.get_display_name(strategy_key)
        desc = ShuffleStrategyFactory.get_description(strategy_key)
        self.strategy_desc_var.set(f"{display_name}\n{desc}")

    def _on_run(self):
        """点击执行按钮"""
        # 流式加载期间不允许执行
        if self._is_loading:
            messagebox.showwarning("提示", "歌单正在加载中，请等待加载完成")
            return
        raw_input = self.playlist_id_var.get().strip()
        if not raw_input:
            messagebox.showwarning("提示", "请输入歌单 ID 或粘贴分享链接")
            return
        # 尝试从链接中提取 ID（兜底：用户可能直接点执行没触发失焦）
        playlist_id = self._extract_playlist_id(raw_input)
        if not playlist_id:
            messagebox.showwarning(
                "提示",
                "无法识别的输入。请输入纯数字歌单 ID，或粘贴网易云歌单分享链接。"
            )
            return
        # 兜底：确保显示歌单信息（用户可能直接粘贴链接后点执行）
        # 注意：这里只更新输入框显示，不重复调用网络请求
        if playlist_id != raw_input:
            self.playlist_id_var.set(playlist_id)

        # 禁用按钮，启用停止按钮，防止重复点击
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.stop_event.clear()
        self.current_song_var.set("准备中...")
        self._log(f"开始处理歌单: {playlist_id}")

        # 后台线程执行，避免UI卡顿
        thread = threading.Thread(target=self._run_task, args=(playlist_id,), daemon=True)
        thread.start()

    def _on_stop(self):
        """点击停止按钮"""
        self.stop_event.set()
        self._log("正在停止...")

    def _check_dll_status(self):
        """后台线程检测 DLL 状态（tasklist/进程枚举较慢，避免阻塞 UI），并周期性轮询"""
        def task():
            from ..infrastructure.dll_injector import DllInjector
            dll_found = DllInjector.find_dll() is not None
            pid = DllInjector.get_cloudmusic_pid()
            injected = bool(pid and dll_found and DllInjector.is_injected(pid))
            try:
                self.root.after(0, lambda: self._update_inject_ui(dll_found, pid is not None, injected))
            except Exception:
                pass  # 窗口已关闭

        threading.Thread(target=task, daemon=True).start()

    def _update_inject_ui(self, dll_found: bool, ncm_running: bool, injected: bool):
        """在主线程更新注入按钮状态，并安排下一次轮询"""
        if not self._injecting:
            if not dll_found:
                self.inject_status_var.set("未找到 DLL")
                self.inject_btn.config(state="disabled", text="注入静默通道")
            elif not ncm_running:
                self.inject_status_var.set("网易云未运行")
                self.inject_btn.config(state="disabled", text="注入静默通道")
            elif injected:
                self.inject_status_var.set("静默通道已就绪")
                self.inject_btn.config(state="disabled", text="已注入")
            else:
                self.inject_status_var.set("检测到网易云运行中，可注入")
                self.inject_btn.config(state="normal", text="注入静默通道")

        # 3 秒后再次轮询（网易云启动/关闭时自动刷新状态）
        try:
            self.root.after(3000, self._check_dll_status)
        except Exception:
            pass  # 窗口已关闭

    def _on_inject_dll(self):
        """点击注入按钮"""
        from ..infrastructure.dll_injector import DllInjector

        dll_path = DllInjector.find_dll()
        if dll_path is None:
            messagebox.showerror("注入失败", "未找到 AwooNcmCefBridge.dll")
            return

        pid = DllInjector.get_cloudmusic_pid()
        if pid is None:
            messagebox.showerror("注入失败", "网易云音乐未运行，请先启动")
            return

        self._injecting = True
        self.inject_btn.config(state="disabled")
        self.inject_status_var.set("正在注入...")
        self.root.update_idletasks()

        success, error_msg = DllInjector.inject(pid, dll_path)
        self._injecting = False

        if success:
            self.inject_status_var.set("静默通道已就绪")
            self.inject_btn.config(text="已注入")
            self._log("DLL 注入成功，静默插入模式已启用")
            messagebox.showinfo("成功", "DLL 注入成功！\n现在可以静默插入歌曲，不会唤起网易云窗口。")
        else:
            self.inject_status_var.set("注入失败")
            self.inject_btn.config(state="normal")
            self._log(f"DLL 注入失败: {error_msg}")
            messagebox.showerror("注入失败", f"DLL 注入失败：{error_msg}")

    def _run_task(self, playlist_id: str):
        """后台执行任务"""
        try:
            # 插入进度回调（在主线程更新UI）
            def on_progress(current: int, total: int):
                self.root.after(0, self._update_progress, current, total)

            # 当前插入歌曲回调（在主线程更新UI）
            def on_current_song(name: str):
                self.root.after(0, self.current_song_var.set, f"正在插入: {name}")

            request = ShuffleRequest(
                playlist_id=playlist_id,
                strategy=self._strategy_key_by_display[self.strategy_var.get()],
                dedupe_window=self.window_var.get(),
                force_refresh=False,
                clear_queue=self.clear_queue_var.get(),
                spread_popularity=self.spread_popularity_var.get(),
                spread_artist=self.spread_artist_var.get(),
                spread_era=self.spread_era_var.get(),
                progress_callback=on_progress,
                current_song_callback=on_current_song,
                stop_event=self.stop_event,
            )

            self._log(f"正在获取歌单...")
            result = self.service.run(request)

            # 在主线程更新 UI
            self.root.after(0, self._update_ui, result)

        except Exception as e:
            self.root.after(0, self._on_error, str(e))

    def _update_progress(self, current: int, total: int):
        """更新插入进度"""
        # 只在每10首或最后一首时输出，避免日志刷屏
        if current % 10 == 0 or current == total:
            pct = current / total * 100
            self._log(f"插入进度: {current}/{total} ({pct:.0f}%)")

    def _update_ui(self, result):
        """更新UI显示结果"""
        if result.stopped:
            self._log(f"⏹ {result.message}")
        elif result.inserted:
            self._log(f"✓ {result.message}")
            self._log(f"  歌单: {result.playlist_name}")
            self._log(f"  共 {result.total} 首歌")
            # 显示前3首预览
            preview = result.shuffled_songs[:3]
            for i, song in enumerate(preview, 1):
                self._log(f"  {i}. {song.name} - {song.artist}")
            if len(result.shuffled_songs) > 3:
                self._log(f"  ... 共 {len(result.shuffled_songs)} 首")
        else:
            self._log(f"✗ {result.message}")
            if result.error:
                self._log(f"  错误: {result.error}")
            messagebox.showerror("失败", f"{result.message}\n{result.error or ''}")

        # 恢复按钮状态
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.current_song_var.set("")

    def _on_error(self, error_msg: str):
        """处理异常"""
        self._log(f"✗ 发生异常: {error_msg}")
        messagebox.showerror("错误", error_msg)
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.current_song_var.set("")

    def show(self):
        """显示窗口"""
        self.root.mainloop()
