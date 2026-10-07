# [弃用] DLL 注入批量写入播放队列 — 方案设想

> 状态：**已弃用**（2026-10-07）
> 原因：现有的 AwooMusicBot 命名管道静默逐首插入（约 0.05 秒/首，100 首约 12 秒）已满足需求；
> 本方案实现难度大、稳定性差、易造成网易云进程崩溃，收益与成本不成比例。
> 本文档仅记录探索结论与设想，供未来需要"一秒写入整个播放列表"时参考。

## 目标

绕过逐首 `ADD_NEXT`，直接在网易云 CEF 页面上下文中执行一段批量 JavaScript，
一次性将整个打乱后的歌单写入播放队列。

## 背景：已排除的方案

| 方案 | 结果 |
|------|------|
| 直接修改 `playingList` 文件 | 网易云不实时重读该文件，无效 |
| 修改文件 + PAUSE/RESUME 触发刷新 | 无效 |
| AwooMusicBot 管道执行自定义 JS | 管道只支持固定命令（ADD_NEXT / PLAY / PAUSE / RESUME 等），自定义命令一律返回 `ERR unknown-command` |
| 网易云 127.0.0.1:20017 HTTP 服务 | 所有路径返回 404 |
| orpheus:// 协议批量参数 | 无批量接口，且会唤起窗口 |

## 已探明的技术事实（探索结论）

以下结论均已在网易云 3.1.41.205529 + CEF 91.2.3 (Chromium 91) 上验证：

1. **AwooNcmCefBridge.dll 已注入网易云浏览器进程**，内部通过 CEF DevTools 协议
   `Runtime.evaluate` 执行 JS，说明"在网易云页面上下文执行 JS"这条路是通的。
2. **CefBrowser 全局对象可定位**：AwooNcmCefBridge.dll 的 `.data` 段偏移 `+0x10f8`
   处保存了一个 CefBrowser 指针（虚函数表位于 libcef.dll 内，已验证）。
3. **Python 侧可用 ctypes + keystone-engine 完成注入**：
   `VirtualAllocEx` 分配内存 → 写入 x64 shellcode → `CreateRemoteThread` 执行，
   无需 C++ 编译器。调用 CefBrowser 虚函数表偏移 6 的函数可拿到一个
   libcef 内部对象（疑似 CefFrame）。
4. **风险**：盲目试探虚函数表偏移曾两次导致网易云进程崩溃
   （错位的虚函数调用栈损坏）。线程上下文也是个坑——CEF 的
   `CefFrame::ExecuteJavaScript` 要求运行在浏览器 UI 线程，
   裸的 `CreateRemoteThread` 线程直接调用不可靠。

## 设想中的实现路线（未实现）

```
Python (ctypes)
  │  1. 定位网易云浏览器进程 PID
  │  2. 读 AwooNcmCefBridge.dll .data +0x10f8 → CefBrowser*
  │  3. CefBrowser::GetMainFrame() → CefFrame*   （虚函数表偏移待精确确认）
  │  4. 分配远程内存，写入批量 JS（cef_string_t: UTF-16 指针 + 长度 + dtor）
  │  5. 通过远程线程调用 CefFrame::ExecuteJavaScript(code, url, 0)
  ▼
网易云页面上下文执行批量 JS（伪代码）：
  const ids = [id1, id2, ...];
  // 调用网易云内部播放队列 API（需逆向确定，如 playerAPI / nm 全局对象）
  ids.forEach(id => /* appendToQueue(id) */);
```

### 关键障碍

1. **虚函数表偏移不确定**：CEF 91 的 CefBrowser/CefFrame 虚函数表布局需要
   对照 CEF 官方头文件逐一定位，盲测会导致进程崩溃。
2. **线程安全**：ExecuteJavaScript 必须在 CEF UI 线程执行。正确做法是
   `CefPostTask(TID_UI, ...)`，shellcode 需先拿到 task runner 再投递任务，
   复杂度进一步上升。
3. **网易云内部 API 未知**：即便能执行 JS，"把歌曲加入播放队列"对应的
   网易云前端内部函数还需单独逆向（orpheus 协议背后调用的就是它）。
4. **版本脆弱**：DLL 基址、.data 偏移、虚函数表布局都随网易云/点歌机
   版本变化，每次升级都要重新标定。

### 若未来重启此方案，建议的替代路径

- **优先**：逆向网易云前端 JS，找到"加入播放队列"的内部函数后，
  向 AwooMusicBot 提 issue / 自行 patch 其 bridge DLL 增加 `EVAL` 命令。
- **次选**：用 Frida（Python 可用）代替手写 shellcode，注入后 hook
  CefFrame 的现有调用点，在同一 UI 线程上下文顺带执行批量 JS，
  避开线程投递问题。
- **不推荐**：继续裸写 CreateRemoteThread + 虚函数表盲调。

## 当前采用的方案（对照）

`src/infrastructure/awoo_client.py` — 通过命名管道
`\\.\pipe\AwooNcmCefBridge-v1-{pid}` 逐首发送 `ADD_NEXT {songId}`，
间隔 0.05 秒，全程静默不唤起窗口。`orpheus_inserter.py` 中优先使用该方式，
管道不可用时回退 orpheus 协议。
