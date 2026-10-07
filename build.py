"""
BetterPlayList 打包脚本 v2.0
用法：
    python build.py              # 打包成单文件 exe
    python build.py --debug      # 打包时保留控制台窗口（便于调试）
    python build.py --pyarmor    # 使用 PyArmor 加密代码后再打包（需安装 pyarmor）
"""
import os
import sys
import shutil
import subprocess
import argparse


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRY_SCRIPT = os.path.join(PROJECT_DIR, "main.py")
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
SPEC_FILE = os.path.join(PROJECT_DIR, "BetterPlayList.spec")
EXE_NAME = "BetterPlayList_v2.0"


def clean():
    """清理旧的构建产物"""
    for path in (DIST_DIR, BUILD_DIR, SPEC_FILE):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            os.remove(path)
    print("[清理] 已清理旧构建产物")


def build(debug: bool = False, pyarmor: bool = False):
    """执行 PyInstaller 打包"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                # 单文件
        "--name", EXE_NAME,
        "--clean",                  # 清理缓存
        "--noconfirm",              # 覆盖确认
    ]

    if debug:
        print("[调试] 保留控制台窗口")
    else:
        cmd += ["--noconsole"]       # GUI 程序，隐藏控制台

    # 隐藏导入（cryptography 的 C 扩展有时需要显式指定）
    hidden_imports = [
        "cryptography",
        "cryptography.hazmat.primitives.ciphers.aead",
        "requests",
        "urllib3",
        "certifi",
        "charset_normalizer",
        "idna",
    ]
    for imp in hidden_imports:
        cmd += ["--hidden-import", imp]

    # 包含的数据文件：将 AwooNcmCefBridge.dll 打包进 exe（静默注入用）
    dll_path = os.path.join(PROJECT_DIR, "assets", "AwooNcmCefBridge.dll")
    if os.path.exists(dll_path):
        cmd += ["--add-binary", f"{dll_path};assets/"]
        print(f"[打包] 包含 DLL: {dll_path}")
    else:
        print("[警告] 未找到 assets/AwooNcmCefBridge.dll，注入功能将不可用")

    cmd += [ENTRY_SCRIPT]

    print(f"[打包] 开始打包...")
    print(f"[打包] 命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode != 0:
        print(f"[失败] 打包失败，返回码: {result.returncode}")
        sys.exit(1)

    exe_path = os.path.join(DIST_DIR, f"{EXE_NAME}.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"[成功] 打包完成: {exe_path}")
        print(f"[成功] 文件大小: {size_mb:.1f} MB")
    else:
        print(f"[失败] 未找到生成的 exe: {exe_path}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="BetterPlayList 打包脚本 v2.0")
    parser.add_argument("--debug", action="store_true", help="保留控制台窗口（调试用）")
    parser.add_argument("--pyarmor", action="store_true", help="使用 PyArmor 加密代码（需先 pip install pyarmor）")
    args = parser.parse_args()

    clean()

    if args.pyarmor:
        # 先安装 pyarmor
        print("[PyArmor] 安装 pyarmor...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyarmor", "-q"], check=True)
        # 使用 pyarmor 打包（pyarmor 会自动调用 PyInstaller）
        print("[PyArmor] 使用 PyArmor 加密打包...")
        result = subprocess.run(
            [sys.executable, "-m", "pyarmor", "pack",
             "-e", "--onefile --noconsole --name " + EXE_NAME,
             "-x", " --exclude src.infrastructure.awoo_client",  # 排除测试文件
             ENTRY_SCRIPT],
            cwd=PROJECT_DIR
        )
        if result.returncode != 0:
            print(f"[失败] PyArmor 打包失败")
            sys.exit(1)
        # PyArmor 输出路径与 PyInstaller 不同，需要移动
        pyarmor_exe = os.path.join(PROJECT_DIR, "dist", EXE_NAME + ".exe")
        if os.path.exists(pyarmor_exe):
            size_mb = os.path.getsize(pyarmor_exe) / (1024 * 1024)
            print(f"[成功] PyArmor 加密打包完成: {pyarmor_exe}")
            print(f"[成功] 文件大小: {size_mb:.1f} MB")
        else:
            # 尝试从默认位置找
            default_exe = os.path.join(PROJECT_DIR, "dist", "BetterPlayList.exe")
            if os.path.exists(default_exe):
                shutil.move(default_exe, pyarmor_exe)
                size_mb = os.path.getsize(pyarmor_exe) / (1024 * 1024)
                print(f"[成功] PyArmor 加密打包完成: {pyarmor_exe}")
                print(f"[成功] 文件大小: {size_mb:.1f} MB")
            else:
                print(f"[失败] 未找到生成的 exe")
                sys.exit(1)
    else:
        build(debug=args.debug)

    print("\n[完成] 可在 dist/ 目录找到 BetterPlayList_v2.0.exe")
    print("[完成] 将 exe 拷贝到目标电脑即可运行，无需安装 Python")


if __name__ == "__main__":
    main()
