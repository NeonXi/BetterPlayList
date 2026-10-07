"""DLL 注入器：将 AwooNcmCefBridge.dll 注入到 cloudmusic.exe 进程"""
import os
import sys
import glob
import ctypes
from ctypes import wintypes

# Windows API 常量
PROCESS_ALL_ACCESS = 0x1F0FFF
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READWRITE = 0x40
LIST_MODULES_ALL = 0x03


class DllInjector:
    """将 AwooNcmCefBridge.dll 注入到 cloudmusic.exe"""

    # AwooMusicBot DLL 名称
    DLL_NAME = "AwooNcmCefBridge.dll"

    @staticmethod
    def _get_bundled_path() -> str | None:
        """获取打包时捆绑的 DLL 路径（支持 PyInstaller 单文件模式）"""
        # PyInstaller 会把附加文件解压到 _MEIPASS 临时目录
        if hasattr(sys, '_MEIPASS'):
            bundled = os.path.join(sys._MEIPASS, "assets", DllInjector.DLL_NAME)
            if os.path.isfile(bundled):
                return bundled
        # 开发模式：从项目根目录查找
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        dev_path = os.path.join(project_root, "assets", DllInjector.DLL_NAME)
        if os.path.isfile(dev_path):
            return dev_path
        return None

    @staticmethod
    def find_dll() -> str | None:
        """
        在系统上搜索 AwooNcmCefBridge.dll
        :return: DLL 完整路径，未找到返回 None
        """
        # 1. 先检查打包捆绑的 DLL
        bundled = DllInjector._get_bundled_path()
        if bundled:
            return bundled

        # 2. 再搜索常见安装路径
        search_roots = [
            os.path.expandvars(r"%APPDATA%\嗷呜点歌机"),
            os.path.expandvars(r"%LOCALAPPDATA%\嗷呜点歌机"),
            r"C:\Program Files\嗷呜点歌机",
            r"C:\Program Files (x86)\嗷呜点歌机",
        ]

        for root in search_roots:
            if not os.path.isdir(root):
                continue
            # 递归搜索
            pattern = os.path.join(root, "**", DllInjector.DLL_NAME)
            for path in glob.glob(pattern, recursive=True):
                if os.path.isfile(path):
                    return path

        return None

    @staticmethod
    def get_cloudmusic_pid() -> int | None:
        """获取网易云进程 PID"""
        try:
            import subprocess
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq cloudmusic.exe', '/FO', 'CSV'],
                capture_output=True, timeout=5,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            # Windows tasklist 输出为 GBK 编码
            output = result.stdout.decode('gbk', errors='replace')
            for line in output.split('\n')[1:]:
                if line.strip():
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        return int(parts[1])
        except Exception:
            pass
        return None

    @staticmethod
    def is_injected(pid: int) -> bool:
        """
        检测 DLL 是否已注入到目标进程
        :param pid: 目标进程 PID
        :return: 是否已注入
        """
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi

        # 声明函数签名，避免 64 位句柄被当作 32 位 int 截断
        psapi.EnumProcessModulesEx.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
        ]
        psapi.GetModuleBaseNameW.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, wintypes.LPWSTR, wintypes.DWORD
        ]

        h_process = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
        )
        if not h_process:
            return False

        try:
            modules = (ctypes.c_void_p * 1024)()
            cb_needed = wintypes.DWORD(0)

            if psapi.EnumProcessModulesEx(
                h_process, modules,
                ctypes.sizeof(modules), ctypes.byref(cb_needed),
                LIST_MODULES_ALL
            ):
                count = cb_needed.value // ctypes.sizeof(ctypes.c_void_p)
                for i in range(count):
                    module_name = ctypes.create_unicode_buffer(260)
                    if psapi.GetModuleBaseNameW(h_process, modules[i], module_name, 260):
                        if DllInjector.DLL_NAME.lower() in module_name.value.lower():
                            return True
        finally:
            kernel32.CloseHandle(h_process)

        return False

    @staticmethod
    def inject(pid: int, dll_path: str) -> tuple[bool, str]:
        """
        将 DLL 注入到目标进程
        :param pid: 目标进程 PID
        :param dll_path: DLL 完整路径
        :return: (是否成功, 错误信息)
        """
        kernel32 = ctypes.windll.kernel32

        # 打开目标进程
        h_process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not h_process:
            return False, "无法打开网易云进程（可能需要管理员权限）"

        try:
            # 在目标进程中分配内存（用于存放 DLL 路径）
            dll_path_bytes = dll_path.encode('utf-16-le') + b'\x00\x00'
            mem_size = len(dll_path_bytes)
            remote_mem = kernel32.VirtualAllocEx(
                h_process, None, mem_size,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE
            )
            if not remote_mem:
                return False, "无法在目标进程中分配内存"

            try:
                # 写入 DLL 路径到目标进程
                written = ctypes.c_size_t(0)
                if not kernel32.WriteProcessMemory(
                    h_process, remote_mem, dll_path_bytes, mem_size, ctypes.byref(written)
                ):
                    return False, "无法写入 DLL 路径到目标进程"

                # 获取 LoadLibraryW 地址
                h_kernel32 = kernel32.GetModuleHandleW("kernel32.dll")
                if not h_kernel32:
                    return False, "无法获取 kernel32.dll 句柄"

                load_library_addr = kernel32.GetProcAddress(h_kernel32, b"LoadLibraryW")
                if not load_library_addr:
                    return False, "无法获取 LoadLibraryW 地址"

                # 创建远程线程，调用 LoadLibraryW
                thread_id = wintypes.DWORD(0)
                h_thread = kernel32.CreateRemoteThread(
                    h_process, None, 0,
                    load_library_addr, remote_mem,
                    0, ctypes.byref(thread_id)
                )
                if not h_thread:
                    return False, "无法创建远程线程"

                try:
                    # 等待线程结束（最多 5 秒）
                    wait_result = kernel32.WaitForSingleObject(h_thread, 5000)
                    if wait_result != 0:  # WAIT_OBJECT_0 = 0
                        return False, "远程线程执行超时"

                    # 检查线程退出码（LoadLibrary 返回的模块句柄）
                    exit_code = wintypes.DWORD(0)
                    if kernel32.GetExitCodeThread(h_thread, ctypes.byref(exit_code)):
                        if exit_code.value == 0:
                            return False, "LoadLibraryW 返回 NULL，DLL 加载失败"
                finally:
                    kernel32.CloseHandle(h_thread)

                return True, ""

            finally:
                # 释放分配的内存
                kernel32.VirtualFreeEx(h_process, remote_mem, 0, MEM_RELEASE)

        finally:
            kernel32.CloseHandle(h_process)
