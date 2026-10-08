"""DLL 注入器：将 AwooNcmCefBridge.dll 注入到网易云 cloudmusic.exe 进程。

实现对齐 Awoo 官方 NeteaseBridgeInstaller：
- OpenProcess 仅申请最小必要权限（CREATE_THREAD / VM_* / QUERY_INFORMATION）
- 路径内存使用 PAGE_READWRITE（非可执行页），减少被杀软/DEP 拦截
- 不直接使用本进程 LoadLibraryW 地址，而是按「模块基址 + 偏移」精确解析
  目标进程中的 LoadLibraryW（兼容其实际转发到 kernelbase.dll 的情况）
- 所有句柄/地址参数都声明 64 位安全签名，避免被截断
- 失败时返回 Win32 错误码，便于判断是否为权限不足（ACCESS_DENIED）
"""
import os
import sys
import glob
import ctypes
import subprocess
from ctypes import wintypes
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Windows API 常量
# ---------------------------------------------------------------------------
# OpenProcess 权限位（与官方完全一致的最小集合）
PROCESS_CREATE_THREAD = 0x0002
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_INJECT_ACCESS = (
    PROCESS_CREATE_THREAD
    | PROCESS_VM_OPERATION
    | PROCESS_VM_READ
    | PROCESS_VM_WRITE
    | PROCESS_QUERY_INFORMATION
)

# 内存分配
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04

# Toolhelp 模块快照
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

# GetModuleHandleEx 标志
GET_MODULE_HANDLE_EX_FROM_ADDRESS = 0x00000004
GET_MODULE_HANDLE_EX_UNCHANGED_REFCOUNT = 0x00000002

# 常用 Win32 错误码
ERROR_ACCESS_DENIED = 5

CREATE_NO_WINDOW = 0x08000000
WAIT_OBJECT_0 = 0x00000000

# ---------------------------------------------------------------------------
# Win32 绑定（use_last_error 便于读取错误码）
# ---------------------------------------------------------------------------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

# 通用类型
BOOL = wintypes.BOOL
DWORD = wintypes.DWORD
HANDLE = wintypes.HANDLE
HMODULE = wintypes.HMODULE
LPDWORD = ctypes.POINTER(DWORD)
LPWSTR = wintypes.LPWSTR
LPCWSTR = wintypes.LPCWSTR

# --- kernel32 函数签名（64 位安全）---
kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = HANDLE

kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.CloseHandle.restype = BOOL

kernel32.VirtualAllocEx.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.c_size_t, DWORD, DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p

kernel32.VirtualFreeEx.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.c_size_t, DWORD]
kernel32.VirtualFreeEx.restype = BOOL

kernel32.WriteProcessMemory.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = BOOL

kernel32.GetModuleHandleW.argtypes = [LPCWSTR]
kernel32.GetModuleHandleW.restype = HMODULE

kernel32.GetProcAddress.argtypes = [HMODULE, ctypes.c_char_p]
kernel32.GetProcAddress.restype = ctypes.c_void_p

kernel32.GetModuleHandleExW.argtypes = [
    DWORD, ctypes.c_void_p, ctypes.POINTER(HMODULE)]
kernel32.GetModuleHandleExW.restype = BOOL

kernel32.GetModuleFileNameW.argtypes = [HMODULE, LPWSTR, DWORD]
kernel32.GetModuleFileNameW.restype = DWORD

kernel32.CreateRemoteThread.argtypes = [
    HANDLE, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.c_void_p, ctypes.c_void_p, DWORD, LPDWORD]
kernel32.CreateRemoteThread.restype = HANDLE

kernel32.WaitForSingleObject.argtypes = [HANDLE, DWORD]
kernel32.WaitForSingleObject.restype = DWORD

kernel32.GetExitCodeThread.argtypes = [HANDLE, LPDWORD]
kernel32.GetExitCodeThread.restype = BOOL

kernel32.CreateToolhelp32Snapshot.argtypes = [DWORD, DWORD]
kernel32.CreateToolhelp32Snapshot.restype = HANDLE

kernel32.FormatMessageW.argtypes = [
    DWORD, ctypes.c_void_p, DWORD, DWORD, LPWSTR, DWORD, ctypes.c_void_p]
kernel32.FormatMessageW.restype = DWORD


class MODULEENTRY32W(ctypes.Structure):
    """Toolhelp32 模块条目（宽字符版）"""
    _fields_ = [
        ("dwSize", DWORD),
        ("th32ModuleID", DWORD),
        ("th32ProcessID", DWORD),
        ("GlblcntUsage", DWORD),
        ("ProccntUsage", DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", DWORD),
        ("hModule", HMODULE),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]


kernel32.Module32FirstW.argtypes = [HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32FirstW.restype = BOOL
kernel32.Module32NextW.argtypes = [HANDLE, ctypes.POINTER(MODULEENTRY32W)]
kernel32.Module32NextW.restype = BOOL


# ---------------------------------------------------------------------------
# 窗口枚举（用于定位主播放窗口）
# ---------------------------------------------------------------------------
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


WNDENUMPROC = ctypes.WINFUNCTYPE(BOOL, HANDLE, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = BOOL
user32.GetWindowThreadProcessId.argtypes = [HANDLE, LPDWORD]
user32.GetWindowThreadProcessId.restype = DWORD
user32.GetClassNameW.argtypes = [HANDLE, LPWSTR, DWORD]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [HANDLE, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = BOOL


@dataclass
class NeteaseEndpoint:
    """网易云主播放端点：进程 PID + 主窗口句柄"""
    pid: int
    hwnd: int


def _read_window_class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _get_window_rect(hwnd):
    rect = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect
    return None


def _find_native_command_window(process_id: int) -> int:
    """
    寻找属于该进程的 OrpheusBrowserHost 大窗口。
    优先选择 ≥400×300 的大窗口，其次是最小化的有标题窗口。
    """
    best_handle = 0
    best_rank = 0
    best_area = 0

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        nonlocal best_handle, best_rank, best_area
        pid = DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != process_id:
            return True
        if _read_window_class(hwnd).lower() != "orpheusbrowserhost":
            return True
        rect = _get_window_rect(hwnd)
        if rect is None:
            return True
        width = max(0, rect.right - rect.left)
        height = max(0, rect.bottom - rect.top)
        area = width * height
        is_large = width >= 400 and height >= 300

        # 最小化且有标题也作为备选
        is_minimized_with_title = False
        if not is_large:
            user32.IsIconic.argtypes = [HANDLE]
            user32.IsIconic.restype = BOOL
            title_buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextLengthW.argtypes = [HANDLE]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [HANDLE, LPWSTR, ctypes.c_int]
            user32.GetWindowTextW.restype = ctypes.c_int
            n = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if n > 0:
                tb = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, tb, n + 1)
                title = tb.value
            is_minimized_with_title = bool(user32.IsIconic(hwnd)) and bool(title.strip())

        rank = 2 if is_large else (1 if is_minimized_with_title else 0)
        if rank > best_rank or (rank == best_rank and rank > 0 and area > best_area):
            best_rank = rank
            best_area = area
            best_handle = hwnd
        return True

    user32.EnumWindows(callback, 0)
    return best_handle


def _format_win32_error(code: int) -> str:
    """把 Win32 错误码转成「错误码 + 系统消息（中文）」"""
    FORMAT_MESSAGE_FROM_SYSTEM = 0x00001000
    buf = ctypes.create_unicode_buffer(512)
    n = kernel32.FormatMessageW(
        FORMAT_MESSAGE_FROM_SYSTEM, None, code, 0, buf, 512, None)
    message = buf.value.strip() if n else ""
    if code == ERROR_ACCESS_DENIED:
        message = (message or "拒绝访问") + "（权限不足）"
    return f"Win32 错误 {code}: {message}".strip()


class DllInjector:
    """将 AwooNcmCefBridge.dll 注入到 cloudmusic.exe。"""

    DLL_NAME = "AwooNcmCefBridge.dll"

    # ------------------------------------------------------------------
    # DLL 路径
    # ------------------------------------------------------------------
    @staticmethod
    def _get_bundled_path() -> str | None:
        """获取捆绑的 DLL 路径（支持 PyInstaller 单文件模式 _MEIPASS）"""
        if hasattr(sys, "_MEIPASS"):
            bundled = os.path.join(sys._MEIPASS, "assets", DllInjector.DLL_NAME)
            if os.path.isfile(bundled):
                return bundled
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        dev_path = os.path.join(project_root, "assets", DllInjector.DLL_NAME)
        if os.path.isfile(dev_path):
            return dev_path
        return None

    @staticmethod
    def find_dll() -> str | None:
        """先取捆绑 DLL，再兜底搜索嗷呜点歌机安装目录。"""
        bundled = DllInjector._get_bundled_path()
        if bundled:
            return bundled

        search_roots = [
            os.path.expandvars(r"%APPDATA%\嗷呜点歌机"),
            os.path.expandvars(r"%LOCALAPPDATA%\嗷呜点歌机"),
            r"C:\Program Files\嗷呜点歌机",
            r"C:\Program Files (x86)\嗷呜点歌机",
        ]
        for root in search_roots:
            if not os.path.isdir(root):
                continue
            for path in glob.glob(
                    os.path.join(root, "**", DllInjector.DLL_NAME),
                    recursive=True):
                if os.path.isfile(path):
                    return path
        return None

    # ------------------------------------------------------------------
    # 端点发现
    # ------------------------------------------------------------------
    @staticmethod
    def _list_cloudmusic_pids() -> list[int]:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq cloudmusic.exe", "/FO", "CSV"],
                capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW)
            output = result.stdout.decode("gbk", errors="replace")
            pids = []
            for line in output.split("\n")[1:]:
                if line.strip():
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        try:
                            pids.append(int(parts[1]))
                        except ValueError:
                            continue
            return pids
        except Exception:
            return []

    @staticmethod
    def find_endpoint() -> NeteaseEndpoint | None:
        """
        查找网易云主播放端点。遍历所有 cloudmusic 进程（PID 从大到小），
        返回第一个拥有 OrpheusBrowserHost 大窗口的进程。
        """
        pids = DllInjector._list_cloudmusic_pids()
        if not pids:
            return None
        for pid in sorted(pids, reverse=True):
            hwnd = _find_native_command_window(pid)
            if hwnd:
                return NeteaseEndpoint(pid=pid, hwnd=hwnd)
        return None

    # ------------------------------------------------------------------
    # 模块检测
    # ------------------------------------------------------------------
    @staticmethod
    def find_existing_bridge(pid: int) -> str | None:
        """若目标进程已加载 bridge，返回该 bridge 的完整路径，否则 None。"""
        return DllInjector._find_remote_module_path(pid, DllInjector.DLL_NAME)

    @staticmethod
    def _find_remote_module_path(pid: int, module_name: str) -> str | None:
        """用 Toolhelp 快照在目标进程查找指定模块的 ExePath。"""
        snapshot = kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            return None
        try:
            entry = MODULEENTRY32W()
            entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
            if not kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
                return None
            target = module_name.lower()
            while True:
                if entry.szModule.lower() == target:
                    return entry.szExePath or ""
                entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
                if not kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snapshot)
        return None

    # ------------------------------------------------------------------
    # LoadLibrary 远程解析
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_remote_load_library(pid: int) -> int:
        """
        精确解析目标进程内 LoadLibraryW 的地址：
        1. 取本进程 kernel32!LoadLibraryW
        2. GetModuleHandleEx 确认该函数真正所属模块（kernel32 或 kernelbase）
        3. 在目标进程找同名模块基址
        4. 目标地址 = 远程模块基址 + (本地LoadLibrary - 本地模块基址)
        """
        local_kernel32 = kernel32.GetModuleHandleW("kernel32.dll")
        local_load_library = kernel32.GetProcAddress(
            local_kernel32, b"LoadLibraryW")
        if not local_kernel32 or not local_load_library:
            return 0

        local_owner = HMODULE(0)
        ok = kernel32.GetModuleHandleExW(
            GET_MODULE_HANDLE_EX_FROM_ADDRESS
            | GET_MODULE_HANDLE_EX_UNCHANGED_REFCOUNT,
            local_load_library, ctypes.byref(local_owner))
        if not ok or not local_owner:
            return 0

        owner_path_buf = ctypes.create_unicode_buffer(260)
        if not kernel32.GetModuleFileNameW(
                local_owner, owner_path_buf, 260):
            return 0
        owner_name = os.path.basename(owner_path_buf.value)

        remote_owner_base = DllInjector._find_remote_module_base(
            pid, owner_name)
        if not remote_owner_base:
            return 0

        offset = local_load_library - local_owner.value
        return remote_owner_base + offset

    @staticmethod
    def _find_remote_module_base(pid: int, module_name: str) -> int:
        """用 Toolhelp 快照取目标进程内指定模块的基址。"""
        snapshot = kernel32.CreateToolhelp32Snapshot(
            TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            return 0
        try:
            entry = MODULEENTRY32W()
            entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
            if not kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
                return 0
            target = module_name.lower()
            while True:
                if entry.szModule.lower() == target:
                    return ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
                if not kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            kernel32.CloseHandle(snapshot)
        return 0

    # ------------------------------------------------------------------
    # 注入
    # ------------------------------------------------------------------
    @staticmethod
    def inject(pid: int, dll_path: str) -> tuple[bool, str]:
        """
        把 bridge DLL 注入到目标进程。
        :return: (是否成功, 错误信息)
        """
        h_process = kernel32.OpenProcess(PROCESS_INJECT_ACCESS, False, pid)
        if not h_process:
            code = ctypes.get_last_error()
            hint = ""
            if code == ERROR_ACCESS_DENIED:
                hint = "；网易云可能以管理员身份运行，请用管理员权限重启本程序后重试"
            return False, f"无法打开网易云进程{hint}（{_format_win32_error(code)}）"

        remote_mem = 0
        h_thread = 0
        try:
            # 写入 DLL 完整路径（UTF-16LE，含结尾 \0）
            path_bytes = (dll_path + "\0").encode("utf-16-le")
            mem_size = len(path_bytes)
            remote_mem = kernel32.VirtualAllocEx(
                h_process, None, mem_size,
                MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
            if not remote_mem:
                return False, "无法在目标进程分配内存（{}）".format(
                    _format_win32_error(ctypes.get_last_error()))

            written = ctypes.c_size_t(0)
            if not kernel32.WriteProcessMemory(
                    h_process, remote_mem, path_bytes, mem_size,
                    ctypes.byref(written)) or written.value != mem_size:
                return False, "无法写入 DLL 路径（{}）".format(
                    _format_win32_error(ctypes.get_last_error()))

            load_library_addr = DllInjector._resolve_remote_load_library(pid)
            if not load_library_addr:
                return False, "无法解析目标进程的 LoadLibraryW（{}）".format(
                    _format_win32_error(ctypes.get_last_error()))

            thread_id = DWORD(0)
            h_thread = kernel32.CreateRemoteThread(
                h_process, None, 0,
                load_library_addr, remote_mem,
                0, ctypes.byref(thread_id))
            if not h_thread:
                return False, "无法创建远程线程（{}）".format(
                    _format_win32_error(ctypes.get_last_error()))

            wait_result = kernel32.WaitForSingleObject(h_thread, 10000)
            if wait_result != WAIT_OBJECT_0:
                return False, "远程加载线程未在 10 秒内结束"

            exit_code = DWORD(0)
            if kernel32.GetExitCodeThread(h_thread, ctypes.byref(exit_code)):
                if exit_code.value == 0:
                    return False, "LoadLibraryW 返回 NULL，bridge DLL 加载失败"

            return True, ""
        finally:
            if h_thread:
                kernel32.CloseHandle(h_thread)
            if remote_mem:
                kernel32.VirtualFreeEx(h_process, remote_mem, 0, MEM_RELEASE)
            kernel32.CloseHandle(h_process)
