# -*- coding: utf-8 -*-
"""生成桌面快捷方式（假休眠.lnk），用 ctypes 调 Shell COM，不依赖第三方库。

换机或重装系统后运行一次即可：
    python make_shortcut.py
"""
import ctypes
import os
import winreg
from ctypes import POINTER, Structure, byref, c_int, c_ubyte, c_uint, c_ushort, c_void_p
from ctypes import WINFUNCTYPE, c_wchar_p

ole32 = ctypes.WinDLL("ole32")

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "FakeSleep.exe")
WORKDIR = os.path.dirname(os.path.abspath(__file__))
DESC = "假休眠 FakeSleep - F2 全屏黑屏 / F1 隐私调光，阻止系统休眠"

S_OK = 0
CLSCTX_INPROC_SERVER = 1


class GUID(Structure):
    _fields_ = [("Data1", c_uint), ("Data2", c_ushort), ("Data3", c_ushort),
                ("Data4", c_ubyte * 8)]


def guid(s):
    p = s.strip("{}").split("-")
    return GUID(int(p[0], 16), int(p[1], 16), int(p[2], 16),
                (c_ubyte * 8)(*(bytes.fromhex(p[3]) + bytes.fromhex(p[4]))))


CLSID_ShellLink = guid("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = guid("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = guid("0000010B-0000-0000-C000-000000000046")


def desktop_dir():
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
    val, _ = winreg.QueryValueEx(key, "Desktop")
    winreg.CloseKey(key)
    return os.path.expandvars(val)


class IShellLink:
    def __init__(self, ptr):
        self.p = ptr
        self.vtbl = ctypes.cast(ctypes.cast(ptr, POINTER(c_void_p))[0], POINTER(c_void_p))

    def _call(self, index, argspec, *args):
        fn = WINFUNCTYPE(c_int, c_void_p, *argspec)(self.vtbl[index])
        hr = fn(self.p, *args)
        if hr != S_OK:
            raise OSError("COM call #%d failed: 0x%08X" % (index, hr & 0xFFFFFFFF))

    def set_path(self, s):
        self._call(20, [c_wchar_p], s)          # IShellLinkW::SetPath

    def set_workdir(self, s):
        self._call(9, [c_wchar_p], s)           # SetWorkingDirectory

    def set_desc(self, s):
        self._call(7, [c_wchar_p], s)           # SetDescription

    def set_icon(self, s, i):
        self._call(17, [c_wchar_p, c_int], s, i)  # SetIconLocation

    def save(self, path):
        ppf = c_void_p()
        hr = WINFUNCTYPE(c_int, c_void_p, POINTER(GUID), POINTER(c_void_p))(
            self.vtbl[0])(self.p, byref(IID_IPersistFile), byref(ppf))  # QueryInterface
        if hr != S_OK:
            raise OSError("QueryInterface failed: 0x%08X" % (hr & 0xFFFFFFFF))
        vtbl = ctypes.cast(ctypes.cast(ppf, POINTER(c_void_p))[0], POINTER(c_void_p))
        save_fn = WINFUNCTYPE(c_int, c_void_p, c_wchar_p, c_int)(vtbl[6])  # IPersistFile::Save
        hr = save_fn(ppf, path, 1)
        if hr != S_OK:
            raise OSError("Save failed: 0x%08X" % (hr & 0xFFFFFFFF))


def main():
    if not os.path.exists(TARGET):
        raise SystemExit("找不到 %s，请先把 FakeSleep.exe 和本脚本放在一起" % TARGET)
    ole32.CoInitialize(None)
    psl = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER,
                           byref(IID_IShellLinkW), byref(psl))
    link = IShellLink(psl)
    link.set_path(TARGET)
    link.set_workdir(WORKDIR)
    link.set_desc(DESC)
    link.set_icon(TARGET, 0)
    out = os.path.join(desktop_dir(), "假休眠.lnk")
    link.save(out)
    print("已在桌面创建快捷方式:", out)


if __name__ == "__main__":
    main()
