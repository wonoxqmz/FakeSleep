# -*- coding: utf-8 -*-
"""
假休眠 FakeSleep
----------------
客厅值守工具。两个模式，互斥切换：

  F2   黑屏模式   全屏纯黑盖住所有显示器 —— 本机看不见，远程也看不见
  F1   隐私模式   铺一层纯黑遮罩，但让系统把遮罩排除在屏幕捕获之外 ——
                  本机屏幕像素级全黑，远程控制软件（RustDesk / BilldDesk / ToDesk…）
                  看到的仍是完整实时桌面

两个模式期间都会阻止系统休眠、熄屏、屏保。再按一次对应热键，或按 Esc，恢复正常。

为什么隐私模式能做到"远程看得见、本机看不见"：
    普通遮罩会被 DXGI Desktop Duplication 一起抓走，远程端跟本机一样全黑 —— 所以不能用普通遮罩。
    Win10 2004 起，窗口可以调 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)：这个窗口只画在
    显示器上，任何屏幕捕获（DXGI / GDI / 截图 / 远控）都看不到它。于是一块纯黑全屏窗口盖住桌面，
    本机是全黑，而捕获出来的画面里那块黑根本没有，远控看到的是正常桌面。
    再配合 WS_EX_TRANSPARENT 让鼠标点击穿过遮罩，远控依然能操作底下的真窗口。

    （旧方案是 DDC/CI 硬件调光，但不少显示器不认这个命令，屏幕还是亮的；仍然保留为 method=ddc）
"""

import configparser
import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import byref, c_uint32, c_void_p, c_wchar, WINFUNCTYPE
from ctypes import wintypes

APP_TITLE = "假休眠"
APP_VER = "1.3.3"

# ---------------------------------------------------------------- 基础工具


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DIR = app_dir()
LOG_PATH = os.path.join(DIR, "fakesleep.log")
CFG_PATH = os.path.join(DIR, "config.ini")


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ---------------------------------------------------------------- Win32

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dxva2 = ctypes.WinDLL("dxva2")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
GA_ROOT = 2
WDA_EXCLUDEFROMCAPTURE = 0x00000011
LWA_ALPHA = 0x2

kernel32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
kernel32.SetThreadExecutionState.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, c_void_p, c_void_p, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD,
                                              ctypes.c_ubyte, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL

dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [c_void_p, ctypes.POINTER(c_uint32)]
dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
dxva2.DestroyPhysicalMonitors.restype = wintypes.BOOL


def keep_system_awake(keep_display=False):
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    if keep_display:
        flags |= ES_DISPLAY_REQUIRED
    return kernel32.SetThreadExecutionState(flags)


def release_awake():
    kernel32.SetThreadExecutionState(ES_CONTINUOUS)


# ---------------------------------------------------------------- 遮罩（本机黑、远程正常）

def hwnd_of(widget):
    """Tk 控件 -> 真正的顶层窗口句柄"""
    return user32.GetAncestor(widget.winfo_id(), GA_ROOT)


def exclude_from_capture(widget):
    """让窗口从所有屏幕捕获里消失（Win10 2004+）。屏幕照常显示，截图/远控看不到它。"""
    hwnd = hwnd_of(widget)
    if not hwnd:
        return False
    ok = bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    if not ok:
        log("SetWindowDisplayAffinity 失败 err=%d（系统可能低于 Win10 2004）"
            % ctypes.get_last_error())
    return ok


def make_click_through(widget):
    """鼠标点击穿过这个窗口，落到下面的真窗口上（远控才能继续操作软件）"""
    hwnd = hwnd_of(widget)
    if not hwnd:
        return False
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    return True


# ---------------------------------------------------------------- DDC/CI 亮度


class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [("hPhysicalMonitor", c_void_p), ("szPhysicalMonitorDescription", c_wchar * 128)]


dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [c_void_p, wintypes.DWORD,
                                                  ctypes.POINTER(PHYSICAL_MONITOR)]
dxva2.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL
dxva2.DestroyPhysicalMonitors.argtypes = [wintypes.DWORD, ctypes.POINTER(PHYSICAL_MONITOR)]
dxva2.GetMonitorBrightness.argtypes = [c_void_p, ctypes.POINTER(c_uint32),
                                       ctypes.POINTER(c_uint32), ctypes.POINTER(c_uint32)]
dxva2.GetMonitorBrightness.restype = wintypes.BOOL
dxva2.SetMonitorBrightness.argtypes = [c_void_p, wintypes.DWORD]
dxva2.SetMonitorBrightness.restype = wintypes.BOOL
dxva2.GetMonitorContrast.argtypes = [c_void_p, ctypes.POINTER(c_uint32),
                                     ctypes.POINTER(c_uint32), ctypes.POINTER(c_uint32)]
dxva2.GetMonitorContrast.restype = wintypes.BOOL
dxva2.SetMonitorContrast.argtypes = [c_void_p, wintypes.DWORD]
dxva2.SetMonitorContrast.restype = wintypes.BOOL

MONITORENUMPROC = WINFUNCTYPE(ctypes.c_int, c_void_p, c_void_p, c_void_p, c_void_p)


class Monitors:
    """枚举物理显示器并保持句柄，退出时销毁。用法：with Monitors() as m: m.items"""

    def __init__(self):
        self.hmons = []
        self.arrays = []
        self.items = []

    def _cb(self, hmon, hdc, rect, data):
        self.hmons.append(hmon)
        return 1

    def __enter__(self):
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(self._cb), 0)
        for hmon in self.hmons:
            n = c_uint32()
            if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(c_void_p(hmon), byref(n)) or n.value == 0:
                continue
            arr = (PHYSICAL_MONITOR * n.value)()
            if not dxva2.GetPhysicalMonitorsFromHMONITOR(c_void_p(hmon), n.value, arr):
                continue
            self.arrays.append((n.value, arr))
            for pm in arr:
                mn, cur, mx = c_uint32(), c_uint32(), c_uint32()
                ok = bool(dxva2.GetMonitorBrightness(pm.hPhysicalMonitor, byref(mn), byref(cur), byref(mx)))
                if ok:
                    mn_, cur_, mx_ = mn.value, cur.value, mx.value
                else:
                    mn_, cur_, mx_ = 0, None, 100
                cmn, ccur, cmx = c_uint32(), c_uint32(), c_uint32()
                cok = bool(dxva2.GetMonitorContrast(pm.hPhysicalMonitor, byref(cmn), byref(ccur), byref(cmx)))
                self.items.append({"handle": pm.hPhysicalMonitor,
                                   "desc": pm.szPhysicalMonitorDescription,
                                   "min": mn_, "cur": cur_, "max": mx_, "ok": ok,
                                   "contrast_ok": cok,
                                   "contrast": ccur.value if cok else None})
        return self

    def __exit__(self, *exc):
        for n, arr in self.arrays:
            dxva2.DestroyPhysicalMonitors(n, arr)
        self.arrays.clear()
        return False


def read_brightness():
    """返回 [(desc, current)]，读不到的是 None"""
    with Monitors() as m:
        return [(i["desc"], i["cur"]) for i in m.items]


def supports_dimming():
    with Monitors() as m:
        return any(i["ok"] for i in m.items)


def set_brightness(value, items=None):
    """把能控制亮度的显示器都设成 value，返回成功个数"""
    if items is None:
        with Monitors() as m:
            return set_brightness(value, m.items)
    n = 0
    for i in items:
        if not i["ok"]:
            continue
        if dxva2.SetMonitorBrightness(i["handle"], int(value)):
            n += 1
    return n


def set_contrast(value, items=None):
    """把能控制对比度的显示器都设成 value，返回成功个数；value<0 表示不动"""
    if value is None or value < 0:
        return 0
    if items is None:
        with Monitors() as m:
            return set_contrast(value, m.items)
    n = 0
    for i in items:
        if not i.get("contrast_ok"):
            continue
        if dxva2.SetMonitorContrast(i["handle"], int(value)):
            n += 1
    return n


# ---------------------------------------------------------------- 配置

DEFAULT_CFG = """[hotkey]
; 黑屏模式热键（F11 手机远控软键盘上没有，改用 F2）
key = F2
ctrl = no
alt = no
shift = no

[privacy]
; 隐私模式热键（本机黑屏，但远程控制软件照常看到画面）
; F1 在键盘最左上角，摸黑也好按；若被占用会自动降级到 Ctrl+Alt+F1
key = F1
ctrl = no
alt = no
shift = no
; 隐私模式怎么做出来：
;   veil = 铺一层纯黑遮罩，但让系统把遮罩排除在屏幕捕获之外 —— 本机像素级全黑，
;          远程控制软件照常看到桌面（推荐，Win10 2004 及以上支持）
;   ddc  = 用 DDC/CI 把显示器硬件亮度/对比度调暗（有的显示器不认，屏幕还是不够黑）
;   both = 两个一起上（遮罩为主，调光当备份）
method = veil
; 隐私模式时屏幕上那个退出的按钮：
;   corner = 右上角一个半透明的小「恢复 ×」（默认，基本不挡东西）
;   bar    = 屏幕下方的大绿条（v1.2.2 的老样式）
;   off    = 不显示任何按钮（纯键盘退出：F1 / Esc；手机远控将无法退出，慎用）
exit_button = corner
; 下面是 ddc / both 生效时用的值
; 按下隐私模式时把亮度调到多少（0 = 最暗）。有的显示器 0 仍有背光，可试 0/5/10
dim_value = 0
; 对比度也一起归零，屏幕会更黑（大多数显示器推荐 0）；-1 = 不动对比度
dim_contrast = 0

[display]
; yes = 黑屏模式下强行不让显示器熄灯
; no  = 允许显示器自动熄灯，更省电
keep_display_on = yes

[update]
; yes = 启动后静默查一次 GitHub 最新版本（只查一次，失败就当没发生，不弹窗不下载）
; no  = 完全不联网；面板上的「检查更新」仍然可以手动点
check_on_start = yes
"""

KEY_MAP = {
    "ESC": 0x1B, "ESCAPE": 0x1B, "SPACE": 0x20, "PAUSE": 0x13,
    "SCROLLLOCK": 0x91, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
    "DELETE": 0x2E, "PAGEUP": 0x21, "PAGEDOWN": 0x22, "TAB": 0x09,
}
for _i in range(1, 25):
    KEY_MAP["F%d" % _i] = 0x6F + _i
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEY_MAP[_c] = ord(_c)
for _c in "0123456789":
    KEY_MAP[_c] = ord(_c)


def vk_of(name):
    return KEY_MAP.get(str(name).strip().upper())


def _yes(s):
    return str(s).strip().lower() in ("yes", "true", "1", "on")


class Config:
    def __init__(self):
        self.key, self.vk = "F2", KEY_MAP["F2"]
        self.ctrl = self.alt = self.shift = False
        self.p_key, self.p_vk = "F1", KEY_MAP["F1"]
        self.p_ctrl = self.p_alt = self.p_shift = False
        self.method = "veil"
        self.exit_button = "corner"
        self.dim_value = 0
        self.dim_contrast = 0
        self.keep_display_on = True
        self.check_on_start = True
        self.load()

    def load(self):
        if not os.path.exists(CFG_PATH):
            try:
                with open(CFG_PATH, "w", encoding="utf-8") as f:
                    f.write(DEFAULT_CFG)
            except Exception:
                pass
        try:
            cp = configparser.ConfigParser()
            cp.read(CFG_PATH, encoding="utf-8")
            k = cp.get("hotkey", "key", fallback="F2")
            if vk_of(k):
                self.key, self.vk = k.strip().upper(), vk_of(k)
            self.ctrl = _yes(cp.get("hotkey", "ctrl", fallback="no"))
            self.alt = _yes(cp.get("hotkey", "alt", fallback="no"))
            self.shift = _yes(cp.get("hotkey", "shift", fallback="no"))

            pk = cp.get("privacy", "key", fallback="F1")
            if vk_of(pk):
                self.p_key, self.p_vk = pk.strip().upper(), vk_of(pk)
            self.p_ctrl = _yes(cp.get("privacy", "ctrl", fallback="no"))
            self.p_alt = _yes(cp.get("privacy", "alt", fallback="no"))
            self.p_shift = _yes(cp.get("privacy", "shift", fallback="no"))
            m = str(cp.get("privacy", "method", fallback="veil")).strip().lower()
            if m not in ("veil", "ddc", "both"):
                m = "veil"
            self.method = m
            eb = str(cp.get("privacy", "exit_button", fallback="corner")).strip().lower()
            self.exit_button = eb if eb in ("corner", "bar", "off") else "corner"
            try:
                self.dim_value = max(0, min(100, int(cp.get("privacy", "dim_value", fallback="0"))))
            except ValueError:
                self.dim_value = 0
            try:
                self.dim_contrast = max(-1, min(100, int(cp.get("privacy", "dim_contrast", fallback="0"))))
            except ValueError:
                self.dim_contrast = 0

            self.keep_display_on = _yes(cp.get("display", "keep_display_on", fallback="yes"))
            self.check_on_start = _yes(cp.get("update", "check_on_start", fallback="yes"))
        except Exception as e:
            log("config 读取失败: %r" % (e,))

    @staticmethod
    def _label(key, ctrl, alt, shift):
        parts = []
        if ctrl:
            parts.append("Ctrl")
        if alt:
            parts.append("Alt")
        if shift:
            parts.append("Shift")
        parts.append(key)
        return "+".join(parts)

    def label(self):
        return self._label(self.key, self.ctrl, self.alt, self.shift)

    def p_label(self):
        return self._label(self.p_key, self.p_ctrl, self.p_alt, self.p_shift)


# ---------------------------------------------------------------- 全局热键

HOTKEY_BLACK = 1
HOTKEY_DIM = 2


class Hotkey(threading.Thread):
    """独立线程注册 RegisterHotKey 并跑消息循环，命中后通过 queue 通知 UI。"""

    def __init__(self, specs, out_queue):
        super().__init__(daemon=True)
        self.specs = specs        # {slot: [(vk, mods, label), ...]}
        self.q = out_queue
        self.thread_id = 0
        self.labels = {}

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        for slot, cands in self.specs.items():
            for vk, mods, name in cands:
                if user32.RegisterHotKey(None, slot, mods, vk):
                    self.labels[slot] = name
                    log("热键注册成功: %s -> slot %d" % (name, slot))
                    break
            else:
                self.labels[slot] = "-"
                log("热键注册失败: slot %d 全部候选被占用" % slot)
        self.q.put(("hotkey_ready", None))

        msg = wintypes.MSG()
        while True:
            r = user32.GetMessageW(byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            if msg.message == WM_HOTKEY:
                self.q.put(("hotkey", msg.wParam))

    def stop(self):
        try:
            for slot in self.specs:
                user32.UnregisterHotKey(None, slot)
            if self.thread_id:
                user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        except Exception:
            pass


# ---------------------------------------------------------------- 更新检查

GITEE_REPO = "i-dont-want-to-pick-a-name/FakeSleep"
GH_REPO = "longchangjin2-arch/FakeSleep"
# 依次尝试：Gitee 是主仓库，GitHub 留作备用（万一哪天 GitHub 恢复了）
UPDATE_SOURCES = [
    ("Gitee", "https://gitee.com/api/v5/repos/%s/releases/latest" % GITEE_REPO,
     "https://gitee.com/%s/releases" % GITEE_REPO),
    ("GitHub", "https://api.github.com/repos/%s/releases/latest" % GH_REPO,
     "https://github.com/%s/releases" % GH_REPO),
]
REL_PAGE = UPDATE_SOURCES[0][2]


def _vtuple(s):
    """"1.2.2" -> (1, 2, 2)；乱七八糟的东西一律当 0"""
    out = []
    for part in str(s).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def fetch_latest(timeout=6):
    """依次问 Gitee / GitHub 要最新 release，返回 (tag, url, 来源)。全失败抛最后一个异常。"""
    import json
    import urllib.request

    last = None
    for name, api, page in UPDATE_SOURCES:
        try:
            req = urllib.request.Request(api, headers={
                "User-Agent": "FakeSleep/%s" % APP_VER,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            tag = str(data.get("tag_name") or "")
            if not tag:
                raise ValueError("返回里没有 tag_name")
            return tag, str(data.get("html_url") or page), name
        except Exception as e:
            last = e
            log("从 %s 查更新失败: %r" % (name, e))
    raise last if last else RuntimeError("没有可用的更新源")


# ---------------------------------------------------------------- 主程序

BG = "#101014"
CARD = "#1b1b22"
FG = "#ececf2"
DIM = "#8b8b98"
GREEN = "#3ddc84"
AMBER = "#f0b429"
RED = "#ff5f56"
FONT = "Microsoft YaHei UI"

MODE_IDLE, MODE_BLACK, MODE_DIM = "idle", "black", "dim"


class App:
    def __init__(self):
        self.cfg = Config()
        self.q = queue.Queue()
        self.mode = MODE_IDLE
        self.black_win = None
        self.veil_win = None
        self.saved_brightness = []
        self.last_toggle = 0.0
        self.hotkey_name = self.cfg.label()
        self.dim_name = self.cfg.p_label()
        self.dim_supported = self.cfg.method != "ddc" or supports_dimming()
        self.dim_bar = None
        self.upd_checking = False
        self.upd_new = False
        self.update_url = REL_PAGE

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self._center(460, 420)
        self._build_ui()
        self.root.bind("<F2>", lambda e: self.toggle_black())
        self.root.bind("<F1>", lambda e: self.toggle_dim())
        self.root.bind("<Escape>", lambda e: self.exit_current())

        self.hotkey = Hotkey(self._hotkey_specs(), self.q)
        self.hotkey.start()

        keep_system_awake(False)
        self._tick_awake()
        self._poll()
        self.root.after(60, self._center_raise)
        self._warn_if_dark()
        # 启动 1.5 秒后静默查一次更新（失败就当没发生）
        if self.cfg.check_on_start:
            self.root.after(1500, lambda: self.check_update(silent=True))

    # ---------- 热键表
    def _hotkey_specs(self):
        c = self.cfg
        base = MOD_NOREPEAT
        if c.ctrl:
            base |= MOD_CONTROL
        if c.alt:
            base |= MOD_ALT
        if c.shift:
            base |= MOD_SHIFT
        pbase = MOD_NOREPEAT
        if c.p_ctrl:
            pbase |= MOD_CONTROL
        if c.p_alt:
            pbase |= MOD_ALT
        if c.p_shift:
            pbase |= MOD_SHIFT

        black = [(c.vk, base, c.label()),
                 (0x71, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, "Ctrl+Alt+F2"),
                 (0x42, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, "Ctrl+Alt+B")]
        dim = [(c.p_vk, pbase, c.p_label()),
               (0x70, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, "Ctrl+Alt+F1"),
               (0x50, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, "Ctrl+Alt+P")]
        return {HOTKEY_BLACK: black, HOTKEY_DIM: dim}

    # ---------- UI
    def _center(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))

    def _center_raise(self):
        try:
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _build_ui(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=24, pady=(20, 0))
        tk.Label(head, text="假 休 眠", bg=BG, fg=FG, font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(head, text="FakeSleep v%s  ·  客厅值守" % APP_VER, bg=BG, fg=DIM,
                 font=(FONT, 8)).pack(anchor="w", pady=(2, 0))

        card = tk.Frame(self.root, bg=CARD)
        card.pack(fill="x", padx=24, pady=12)
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=14, pady=11)
        self.dot = tk.Label(inner, text="●", bg=CARD, fg=GREEN, font=(FONT, 11))
        self.dot.pack(side="left")
        txt = tk.Frame(card, bg=CARD)
        txt.pack(side="left", fill="x", expand=True, padx=(22, 0))
        self.st_main = tk.Label(txt, text="待机 · 已阻止系统休眠", bg=CARD, fg=FG,
                                font=(FONT, 10), anchor="w")
        self.st_main.pack(anchor="w")
        self.st_sub = tk.Label(txt, text="黑屏 %s   隐私 %s" % (self.hotkey_name, self.dim_name),
                               bg=CARD, fg=DIM, font=(FONT, 8), anchor="w")
        self.st_sub.pack(anchor="w", pady=(2, 0))

        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=24)
        self.btn_black = tk.Button(row, text="黑屏  %s" % self.hotkey_name, font=(FONT, 10, "bold"),
                                   bg=GREEN, fg="#08130c", activebackground="#35c877",
                                   activeforeground="#08130c", relief="flat", bd=0,
                                   cursor="hand2", command=self.toggle_black)
        self.btn_black.pack(side="left", fill="x", expand=True, ipady=9)

        dim_bg = AMBER if self.dim_supported else "#3a3a44"
        self.btn_dim = tk.Button(row, text="隐私  %s" % self.dim_name, font=(FONT, 10, "bold"),
                                 bg=dim_bg, fg="#141005" if self.dim_supported else DIM,
                                 activebackground="#d9a11f" if self.dim_supported else "#3a3a44",
                                 activeforeground="#141005", relief="flat", bd=0,
                                 cursor="hand2" if self.dim_supported else "arrow",
                                 command=self.toggle_dim,
                                 state="normal" if self.dim_supported else "disabled")
        self.btn_dim.pack(side="left", fill="x", expand=True, ipady=9, padx=(8, 0))

        tip = ("黑屏：所有显示器纯黑，远程也看不到画面。\n"
               "隐私：纯黑遮罩 + 从屏幕捕获里排除 —— 本机像素级全黑，"
               "远程控制软件照常看到完整桌面。\n"
               "两个模式都会阻止系统休眠，随时按热键或 Esc 恢复。\n"
               "手机远控没有功能键？点上面的按钮进去，黑屏双击屏幕 / 隐私点右上角「恢复 ×」出来。")
        tk.Label(self.root, text=tip, bg=BG, fg=DIM, font=(FONT, 8),
                 justify="left", wraplength=412).pack(fill="x", padx=24, pady=(12, 0))

        foot = tk.Frame(self.root, bg=BG)
        foot.pack(side="bottom", fill="x", padx=24, pady=(0, 9))
        self.lbl_upd = tk.Label(foot, text="检查更新", bg=BG, fg=DIM, font=(FONT, 8),
                                cursor="hand2")
        self.lbl_upd.pack(side="left")
        self.lbl_upd.bind("<Button-1>", lambda e: self._on_upd_click())

        self.btn_quit = tk.Button(foot, text="退出程序", font=(FONT, 9), bg=BG, fg=DIM,
                                  activebackground=BG, activeforeground=FG, relief="flat", bd=0,
                                  cursor="hand2", command=self.quit)
        self.btn_quit.pack(side="right")

    # ---------- 状态与提示
    def _warn_if_dark(self):
        """上次异常退出可能把亮度留在 0，启动时提示一下"""
        try:
            levels = read_brightness()
        except Exception:
            return
        dark = [d for d, c in levels if c == 0]
        if dark:
            self.st_sub.configure(text="注意：%s 亮度为 0，按隐私热键可恢复" % dark[0], fg=AMBER)
            log("启动时检测到亮度 0")

    def _set_status(self, main, sub=None, color=GREEN):
        self.st_main.configure(text=main, fg=FG)
        self.dot.configure(fg=color)
        if sub:
            self.st_sub.configure(text=sub, fg=DIM)
        self.root.update_idletasks()

    # ---------- 更新检查
    def check_update(self, silent=True):
        if self.upd_checking:
            return
        self.upd_checking = True
        if not silent:
            self.lbl_upd.configure(text="正在检查…", fg=DIM, cursor="arrow")
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self):
        try:
            tag, url, src = fetch_latest()
            self.q.put(("update", (tag, url, "", src)))
        except Exception as e:
            self.q.put(("update", ("", "", "%s" % e, "")))

    def _on_update(self, payload):
        tag, url, err, src = payload
        self.upd_checking = False
        if err:
            log("检查更新失败: %s" % err)
            self.lbl_upd.configure(text="检查更新（没连上，点此重试）", fg=DIM, cursor="hand2")
            return
        if _vtuple(tag) > _vtuple(APP_VER):
            self.upd_new = True
            self.update_url = url or REL_PAGE
            self.lbl_upd.configure(text="发现新版本 %s · 点此下载" % tag, fg=AMBER, cursor="hand2")
            log("发现新版本 %s（当前 %s，来源 %s）" % (tag, APP_VER, src))
        else:
            self.upd_new = False
            self.lbl_upd.configure(text="v%s · 已是最新" % APP_VER, fg=DIM, cursor="hand2")
            log("已是最新（远端 %s，来源 %s）" % (tag or "?", src))

    def _on_upd_click(self):
        if self.upd_new:
            self._open_url(self.update_url)
        else:
            self.check_update(silent=False)

    @staticmethod
    def _open_url(url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            log("打开浏览器失败 %r" % (e,))

    def _tick_awake(self):
        keep_display = self.cfg.keep_display_on if self.mode == MODE_BLACK else (self.mode == MODE_DIM)
        keep_system_awake(keep_display)
        self.root.after(25000, self._tick_awake)

    # ---------- 热键消息轮询
    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "hotkey":
                    if payload == HOTKEY_BLACK:
                        self.toggle_black()
                    elif payload == HOTKEY_DIM:
                        self.toggle_dim()
                elif kind == "hotkey_ready":
                    hk = self.hotkey.labels
                    self.hotkey_name = hk.get(HOTKEY_BLACK, "-")
                    self.dim_name = hk.get(HOTKEY_DIM, "-")
                    self.btn_black.configure(text="黑屏  %s" % self.hotkey_name)
                    self.btn_dim.configure(text="隐私  %s" % self.dim_name)
                    self.st_sub.configure(
                        text="黑屏 %s   隐私 %s" % (self.hotkey_name, self.dim_name), fg=DIM)
                elif kind == "update":
                    self._on_update(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    # ---------- 模式切换
    def _debounce(self):
        now = time.time()
        if now - self.last_toggle < 0.35:
            return False
        self.last_toggle = now
        return True

    def exit_current(self):
        if self.mode == MODE_BLACK:
            self.exit_black()
        elif self.mode == MODE_DIM:
            self.exit_dim()

    def toggle_black(self):
        if not self._debounce():
            return
        if self.mode == MODE_BLACK:
            self.exit_black()
        else:
            if self.mode == MODE_DIM:
                self.exit_dim()
            self.enter_black()

    def toggle_dim(self):
        if not self._debounce():
            return
        if self.mode == MODE_DIM:
            self.exit_dim()
        else:
            if self.mode == MODE_BLACK:
                self.exit_black()
            self.enter_dim()

    # ---------- 黑屏模式
    def enter_black(self):
        if self.mode == MODE_BLACK:
            return
        self.mode = MODE_BLACK
        self.root.withdraw()

        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or self.root.winfo_screenwidth()
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or self.root.winfo_screenheight()

        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.configure(bg="black", cursor="none")
        w.geometry("%dx%d+%d+%d" % (vw, vh, vx, vy))
        w.attributes("-topmost", True)
        w.bind("<Escape>", lambda e: self.exit_black())
        w.bind("<F2>", lambda e: self.exit_black())
        w.bind("<F1>", lambda e: self.toggle_dim())
        # 手机远控没有功能键时的出路：双击屏幕任意处，或单击右上角热区
        w.bind("<Double-Button-1>", lambda e: self.exit_black())
        w.bind("<Button-1>", self._black_click)
        self.black_win = w

        try:
            w.update_idletasks()
            w.deiconify()
            w.lift()
            w.focus_force()
            w.grab_set()
        except Exception as e:
            log("黑屏窗口聚焦异常: %r" % (e,))

        keep_system_awake(self.cfg.keep_display_on)
        self._guard_black()
        log("进入黑屏 (%dx%d+%d+%d)" % (vw, vh, vx, vy))

    def _black_click(self, ev):
        """黑屏时啥也看不见：单击右上角 80x80 热区也能退出，方便手机远控"""
        try:
            w = ev.widget
            if ev.x >= w.winfo_width() - 80 and ev.y <= 80:
                self.exit_black()
        except Exception:
            pass

    def _guard_black(self):
        """黑屏期间把自己顶回最上层，防止 Win+D / 弹窗把桌面露出来"""
        if self.mode != MODE_BLACK or self.black_win is None:
            return
        w = self.black_win
        try:
            if w.state() == "withdrawn":
                w.deiconify()
            w.attributes("-topmost", True)
            w.lift()
        except Exception:
            pass
        self.root.after(1200, self._guard_black)

    def exit_black(self):
        if self.mode != MODE_BLACK:
            return
        self.mode = MODE_IDLE
        w, self.black_win = self.black_win, None
        if w is not None:
            try:
                w.grab_release()
                w.destroy()
            except Exception:
                pass
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        keep_system_awake(False)
        log("退出黑屏")

    # ---------- 隐私模式（DDC/CI 调光）
    def _show_dim_bar(self):
        """给手机远控留的鼠标退路。corner = 右上角迷你按钮；bar = 底部大条；off = 不显示"""
        self._hide_dim_bar()
        style = self.cfg.exit_button
        if style == "off":
            log("exit_button=off，不显示恢复按钮")
            return
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.45)      # 半透明，别挡视线
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        if style == "bar":
            w.configure(bg=BG)
            bw, bh = 172, 42
            w.geometry("%dx%d+%d+%d" % (bw, bh, (sw - bw) // 2, sh - bh - 80))
            tk.Button(w, text="恢复显示", font=(FONT, 10, "bold"), bg=GREEN, fg="#08130c",
                      activebackground="#35c877", activeforeground="#08130c",
                      relief="flat", bd=0, cursor="hand2",
                      command=self.exit_dim).pack(fill="both", expand=True, padx=3, pady=3)
        else:
            w.configure(bg="#222228")
            bw, bh = 64, 20
            w.geometry("%dx%d+%d+%d" % (bw, bh, sw - bw - 8, 8))
            tk.Button(w, text="恢复 ×", font=(FONT, 8), bg="#3a3a44", fg=FG,
                      activebackground="#4a4a55", activeforeground=FG,
                      relief="flat", bd=0, cursor="hand2",
                      command=self.exit_dim).pack(fill="both", expand=True)
        w.bind("<Escape>", lambda e: self.exit_dim())
        self.dim_bar = w
        try:
            w.lift()
        except Exception:
            pass

    def _hide_dim_bar(self):
        w, self.dim_bar = self.dim_bar, None
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass

    def enter_dim(self):
        if self.mode == MODE_DIM:
            return
        method = self.cfg.method
        veiled = False
        dimmed = 0

        if method in ("veil", "both"):
            veiled = self._veil_on()
            if not veiled and method == "veil":
                self._set_status("这台系统不支持遮罩排除", "需要 Win10 2004 及以上；或把 config.ini 的 method 改成 ddc", RED)
                return

        if method in ("ddc", "both"):
            dimmed = self._ddc_darken()
            if method == "ddc" and dimmed == 0:
                self._set_status("调光没有生效", "显示器拒绝了 DDC/CI，可把 config.ini 的 method 改成 veil", RED)
                return

        self.mode = MODE_DIM
        self.root.withdraw()
        self._show_dim_bar()
        self._guard_veil()
        keep_system_awake(True)
        log("进入隐私模式 method=%s 遮罩=%s 调光显示器=%d" % (method, veiled, dimmed))

    def _veil_on(self):
        """纯黑遮罩，但从屏幕捕获里排除：本机像素级全黑，远程看到的是桌面"""
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or self.root.winfo_screenwidth()
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or self.root.winfo_screenheight()

        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.configure(bg="black", cursor="none")
        w.geometry("%dx%d+%d+%d" % (vw, vh, vx, vy))
        w.attributes("-topmost", True)
        try:
            w.update_idletasks()
            w.deiconify()
            w.lift()
        except Exception as e:
            log("遮罩窗口异常 %r" % (e,))

        ok = exclude_from_capture(w)
        make_click_through(w)   # 远控要用底下真窗口，遮罩不能吃鼠标
        self.veil_win = w
        log("遮罩 %dx%d+%d+%d 捕获排除=%s" % (vw, vh, vx, vy, ok))
        return ok

    def _veil_off(self):
        w, self.veil_win = self.veil_win, None
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass

    def _guard_veil(self):
        """遮罩期间保持置顶，且让「恢复显示」小条压在它上面可点"""
        if self.mode != MODE_DIM or self.veil_win is None:
            return
        try:
            self.veil_win.attributes("-topmost", True)
            self.veil_win.lift()
            if self.dim_bar is not None:
                self.dim_bar.attributes("-topmost", True)
                self.dim_bar.lift()
        except Exception:
            pass
        self.root.after(1500, self._guard_veil)

    def _ddc_darken(self):
        """DDC/CI 硬件调光，返回改到的显示器个数"""
        try:
            with Monitors() as m:
                self.saved_brightness = [(i["handle"], i["cur"], i["contrast"], i["contrast_ok"])
                                         for i in m.items
                                         if i["ok"] and i["cur"] is not None]
                n = set_brightness(self.cfg.dim_value, m.items)
                set_contrast(self.cfg.dim_contrast, m.items)
        except Exception as e:
            log("调光失败 %r" % (e,))
            return 0
        return n

    def _ddc_restore(self):
        if not self.saved_brightness:
            return
        try:
            with Monitors() as m:
                by_handle = {i["handle"]: i for i in m.items}
                restored = False
                for handle, cur, con, con_ok in self.saved_brightness:
                    item = by_handle.get(handle)
                    if item and item["ok"]:
                        dxva2.SetMonitorBrightness(item["handle"], int(cur))
                        restored = True
                    if item and con_ok and item.get("contrast_ok") and con is not None:
                        dxva2.SetMonitorContrast(item["handle"], int(con))
                if not restored:
                    set_brightness(100, m.items)
            log("已恢复亮度/对比度")
        except Exception as e:
            log("恢复亮度失败 %r" % (e,))
        self.saved_brightness = []

    def exit_dim(self):
        if self.mode != MODE_DIM:
            return
        self.mode = MODE_IDLE
        self._veil_off()
        self._ddc_restore()
        self._hide_dim_bar()
        self.root.deiconify()
        self.root.lift()
        keep_system_awake(False)
        log("退出隐私模式")

    # ---------- 退出
    def quit(self):
        log("程序退出")
        self._hide_dim_bar()
        self._veil_off()
        try:
            self.hotkey.stop()
        except Exception:
            pass
        # 关键：绝不能把亮度留在 0
        self._ddc_restore()
        release_awake()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------- 入口


def main():
    # 命令行救急：摸黑时也能用（Win+R 输入 exe 路径加参数）
    for a in sys.argv[1:]:
        if a.lower().startswith("--brightness="):
            try:
                v = int(a.split("=", 1)[1])
            except ValueError:
                v = 100
            v = max(0, min(100, v))
            n = set_brightness(v)
            log("命令行设置亮度 %d，影响 %d 个显示器" % (v, n))
            print("brightness -> %d (%d monitors)" % (v, n))
            return

    ctypes.set_last_error(0)
    kernel32.CreateMutexW(None, False, "Local\\FakeSleep_SingleInstance")
    if ctypes.get_last_error() == 183:
        log("已有实例在运行，退出本次启动")
        return

    log("启动 v%s" % APP_VER)
    app = App()
    for a in sys.argv[1:]:
        low = a.lower()
        if low == "--black":
            app.root.after(300, app.enter_black)
        elif low == "--dim":
            app.root.after(300, app.enter_dim)
        elif low == "--smoke-test":
            app.root.after(1800, app.quit)
    app.run()


if __name__ == "__main__":
    main()
