"""从本地网易云 PC 客户端读取登录 Cookie（MUSIC_U）"""
import base64
import ctypes
import ctypes.wintypes
import json
import os
import sqlite3
import tempfile
import shutil


# Windows DPAPI 解密
class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _dpapi_decrypt(encrypted: bytes) -> bytes:
    """用 Windows DPAPI 解密数据"""
    blob_in = DATA_BLOB()
    blob_in.cbData = len(encrypted)
    blob_in.pbData = ctypes.cast(encrypted, ctypes.POINTER(ctypes.c_byte))

    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise RuntimeError("DPAPI 解密失败")

    try:
        result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return result
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _aes_gcm_decrypt(key: bytes, data: bytes) -> bytes:
    """用 AES-256-GCM 解密 Chromium v10 cookie"""
    # data 格式: v10 (3字节) + nonce (12字节) + ciphertext + tag (16字节)
    nonce = data[3:15]
    ciphertext = data[15:-16]
    tag = data[-16:]

    # 尝试用 cryptography 库
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext + tag, None)
    except ImportError:
        pass

    # 备用：用 pycryptodome
    try:
        from Crypto.Cipher import AES
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)
    except ImportError:
        pass

    # 两个库都没有，抛出明确错误
    raise RuntimeError(
        "缺少 AES 解密库，请安装依赖:\n"
        "  pip install cryptography\n"
        "或: pip install pycryptodome"
    )


class NcmLocalCookieReader:
    """
    从本地网易云 PC 客户端读取登录 Cookie
    """

    def __init__(self, cloudmusic_dir: str = None):
        """
        :param cloudmusic_dir: 网易云安装目录，默认 %LOCALAPPDATA%/NetEase/CloudMusic
        """
        if cloudmusic_dir is None:
            cloudmusic_dir = os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "NetEase", "CloudMusic"
            )
        self.cloudmusic_dir = cloudmusic_dir

    def _find_webapp_dir(self) -> str:
        """找到 webapp 目录（如 webapp91x64）"""
        for name in os.listdir(self.cloudmusic_dir):
            if name.startswith("webapp") and os.path.isdir(
                os.path.join(self.cloudmusic_dir, name)
            ):
                return os.path.join(self.cloudmusic_dir, name)
        raise RuntimeError("未找到网易云 webapp 目录")

    def get_cookies(self) -> dict[str, str]:
        """
        读取网易云 music.163.com 域下的所有 Cookie
        :return: {cookie_name: cookie_value}
        """
        webapp_dir = self._find_webapp_dir()
        cookies_db = os.path.join(webapp_dir, "Cookies")
        local_prefs = os.path.join(webapp_dir, "LocalPrefs.json")

        # 1. 读取加密密钥
        with open(local_prefs, "r", encoding="utf-8") as f:
            prefs = json.load(f)
        encrypted_key = base64.b64decode(prefs["os_crypt"]["encrypted_key"])
        # 去掉 "DPAPI" 前缀（前5字节），用 DPAPI 解密得到 AES 密钥
        aes_key = _dpapi_decrypt(encrypted_key[5:])

        # 2. 直接以只读模式连接原数据库查询，不复制
        #    SQLite 只读模式不受其他进程写入锁定影响
        import time
        last_error = None
        rows = []
        for attempt in range(3):
            try:
                conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True)
                c = conn.cursor()
                c.execute(
                    "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%music.163.com%'"
                )
                rows = c.fetchall()
                conn.close()
                break
            except Exception as e:
                last_error = e
                conn.close() if 'conn' in dir() else None
                time.sleep(0.5)

        if not rows:
            raise RuntimeError(
                f"读取网易云 Cookies 失败（尝试3次）: {last_error}"
            )

        # 3. 解密每个 cookie
        cookies = {}
        decrypt_failed = []
        for name, encrypted_value in rows:
            if not encrypted_value:
                continue
            try:
                if encrypted_value[:3] == b"v10":
                    value = _aes_gcm_decrypt(aes_key, encrypted_value)
                else:
                    value = _dpapi_decrypt(encrypted_value)
                cookies[name] = value.decode("utf-8", errors="replace")
            except Exception:
                decrypt_failed.append(name)
                continue

        # 如果 MUSIC_U 没读到，说明可能是加密库缺失或登录态无效
        if "MUSIC_U" not in cookies:
            print(f"[WARN] 未读取到 MUSIC_U Cookie")
            print(f"[WARN] 成功解密 {len(cookies)} 个，失败 {len(decrypt_failed)} 个")
            if decrypt_failed:
                print(f"[WARN] 解密失败的 cookie: {decrypt_failed[:5]}...")

        return cookies

    def get_music_u(self) -> str | None:
        """获取 MUSIC_U Cookie（登录态标识）"""
        cookies = self.get_cookies()
        return cookies.get("MUSIC_U")

    def get_cookie_string(self) -> str:
        """获取完整的 Cookie 字符串（用于请求头）"""
        cookies = self.get_cookies()
        return "; ".join(f"{k}={v}" for k, v in cookies.items())


if __name__ == "__main__":
    reader = NcmLocalCookieReader()
    try:
        music_u = reader.get_music_u()
        print(f"MUSIC_U: {music_u[:20]}..." if music_u else "未获取到 MUSIC_U")
        cookies = reader.get_cookies()
        print(f"\n共获取到 {len(cookies)} 个 cookie")
        for name in ["MUSIC_U", "__csrf", "NMTID", "os", "appver"]:
            if name in cookies:
                val = cookies[name]
                print(f"  {name}: {val[:30]}{'...' if len(val) > 30 else ''}")
    except Exception as e:
        print(f"读取失败: {e}")
