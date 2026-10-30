# -*- coding: utf-8 -*-
"""
假休眠 FakeSleep —— 安装程序（自研，纯标准库）

构建：
    pyinstaller --onefile --noconsole --icon icon.ico --name FakeSleep-Setup-v1.0.0 ^
        --add-data "FakeSleep.exe;." installer.py

行为：
    双击             图形安装向导
    /S               静默安装（默认目录、建桌面快捷方式、不设开机自启）
    /DIR=<路径>      指定安装目录（配合 /S 或向导默认值）
    /NOICONS         不建任何快捷方式
    /uninstall       图形卸载
    /uninstall /S    静默卸载
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time
import winreg
from ctypes import POINTER, Structure, byref, c_int, c_ubyte, c_uint, c_ushort, c_void_p
from ctypes import WINFUNCTYPE, c_wchar_p

APP_NAME = "假休眠"
APP_ID = "FakeSleep"
APP_VER = "1.3.3"
APP_FULL = "假休眠 FakeSleep"
PUBLISHER = "LCJ"
HOMEPAGE = "https://github.com/longchangjin2-arch/FakeSleep"
MAIN_EXE = "FakeSleep.exe"
UNINST_EXE = "uninstall.exe"
SETUP_LOG = os.path.join(os.environ.get("TEMP", "."), "fakesleep_setup.log")

BG = "#101014"
CARD = "#1b1b22"
FG = "#ececf2"
DIM = "#8b8b98"
GREEN = "#3ddc84"
RED = "#ff5f56"
FONT = "Microsoft YaHei UI"


# ------------------------------------------------------------------ 基础

def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def log(msg):
    try:
        with open(SETUP_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def default_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP_ID)


def desktop_dir():
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
    val, _ = winreg.QueryValueEx(key, "Desktop")
    winreg.CloseKey(key)
    return os.path.expandvars(val)


def start_menu_dir():
    base = os.environ.get("APPDATA") or ""
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")


def kill_running():
    try:
        subprocess.run(["taskkill", "/IM", MAIN_EXE, "/F"],
                       capture_output=True, creationflags=0x08000000)
    except Exception:
        pass


# ------------------------------------------------------------------ 快捷方式（IShellLink COM）

ole32 = ctypes.WinDLL("ole32")
S_OK = 0
CLSCTX_INPROC_SERVER = 1


class GUID(Structure):
    _fields_ = [("Data1", c_uint), ("Data2", c_ushort), ("Data3", c_ushort),
                ("Data4", c_ubyte * 8)]


def _guid(s):
    p = s.strip("{}").split("-")
    return GUID(int(p[0], 16), int(p[1], 16), int(p[2], 16),
                (c_ubyte * 8)(*(bytes.fromhex(p[3]) + bytes.fromhex(p[4]))))


CLSID_ShellLink = _guid("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = _guid("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = _guid("0000010B-0000-0000-C000-000000000046")


_com_ready = False


def create_lnk(lnk_path, target, workdir, desc, icon=None):
    global _com_ready
    if not _com_ready:
        ole32.CoInitialize(None)
        _com_ready = True
    psl = c_void_p()
    ole32.CoCreateInstance(byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER,
                           byref(IID_IShellLinkW), byref(psl))
    vtbl = ctypes.cast(ctypes.cast(psl, POINTER(c_void_p))[0], POINTER(c_void_p))

    def call(idx, argspec, *args):
        hr = WINFUNCTYPE(c_int, c_void_p, *argspec)(vtbl[idx])(psl, *args)
        if hr != S_OK:
            raise OSError("COM #%d -> 0x%08X" % (idx, hr & 0xFFFFFFFF))

    call(20, [c_wchar_p], target)          # SetPath
    call(9, [c_wchar_p], workdir)          # SetWorkingDirectory
    call(7, [c_wchar_p], desc)             # SetDescription
    call(17, [c_wchar_p, c_int], icon or target, 0)  # SetIconLocation

    ppf = c_void_p()
    hr = WINFUNCTYPE(c_int, c_void_p, POINTER(GUID), POINTER(c_void_p))(vtbl[0])(
        psl, byref(IID_IPersistFile), byref(ppf))
    if hr != S_OK:
        raise OSError("QueryInterface -> 0x%08X" % (hr & 0xFFFFFFFF))
    vpf = ctypes.cast(ctypes.cast(ppf, POINTER(c_void_p))[0], POINTER(c_void_p))
    hr = WINFUNCTYPE(c_int, c_void_p, c_wchar_p, c_int)(vpf[6])(ppf, lnk_path, 1)  # Save
    if hr != S_OK:
        raise OSError("Save -> 0x%08X" % (hr & 0xFFFFFFFF))


def read_lnk_target(lnk_path):
    """读出 .lnk 指向的目标路径；读不出来返回 None。"""
    global _com_ready
    if not _com_ready:
        ole32.CoInitialize(None)
        _com_ready = True
    try:
        psl = c_void_p()
        ole32.CoCreateInstance(byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER,
                               byref(IID_IShellLinkW), byref(psl))
        vtbl = ctypes.cast(ctypes.cast(psl, POINTER(c_void_p))[0], POINTER(c_void_p))
        ppf = c_void_p()
        hr = WINFUNCTYPE(c_int, c_void_p, POINTER(GUID), POINTER(c_void_p))(vtbl[0])(
            psl, byref(IID_IPersistFile), byref(ppf))                     # QueryInterface
        if hr != S_OK:
            return None
        vpf = ctypes.cast(ctypes.cast(ppf, POINTER(c_void_p))[0], POINTER(c_void_p))
        hr = WINFUNCTYPE(c_int, c_void_p, c_wchar_p, c_int)(vpf[5])(ppf, lnk_path, 0)  # Load
        if hr != S_OK:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        hr = WINFUNCTYPE(c_int, c_void_p, c_wchar_p, c_int, c_void_p, c_uint)(
            vtbl[3])(psl, buf, 1024, None, 4)                             # GetPath, SLGP_RAWPATH
        if hr != S_OK:
            return None
        return buf.value or None
    except Exception as e:
        log("读 lnk %s 失败 %r" % (lnk_path, e))
        return None


def _same_file(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


# ------------------------------------------------------------------ 安装 / 卸载动作

UNINST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def do_install(target_dir, want_desktop, want_autorun, say=lambda m: None):
    t0 = time.time()

    def mark(msg):
        say(msg)
        log("  %s (%.1fs)" % (msg, time.time() - t0))

    target_dir = os.path.abspath(target_dir)
    mark("正在创建安装目录…")
    os.makedirs(target_dir, exist_ok=True)

    # 覆盖安装时先关掉旧进程，否则 exe 被占用复制会失败
    if os.path.exists(os.path.join(target_dir, MAIN_EXE)):
        kill_running()
        time.sleep(0.5)

    mark("正在复制程序文件…")
    src = resource(MAIN_EXE)
    if not os.path.exists(src):
        raise RuntimeError("安装包内缺少 %s（打包时未 add-data）" % MAIN_EXE)
    shutil.copy2(src, os.path.join(target_dir, MAIN_EXE))

    cfgsrc = resource("config.ini")
    cfgdst = os.path.join(target_dir, "config.ini")
    if os.path.exists(cfgsrc) and not os.path.exists(cfgdst):
        shutil.copy2(cfgsrc, cfgdst)

    readme = resource("README.md")
    if os.path.exists(readme):
        shutil.copy2(readme, os.path.join(target_dir, "README.md"))
    lic = resource("LICENSE")
    if os.path.exists(lic):
        shutil.copy2(lic, os.path.join(target_dir, "LICENSE"))

    mark("正在准备卸载程序…")
    me = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    uninst = os.path.join(target_dir, UNINST_EXE)
    if os.path.abspath(me) != os.path.abspath(uninst):
        shutil.copy2(me, uninst)

    exe_path = os.path.join(target_dir, MAIN_EXE)

    mark("正在注册卸载信息…")
    size_kb = 0
    for root, _, files in os.walk(target_dir):
        for f in files:
            try:
                size_kb += os.path.getsize(os.path.join(root, f)) // 1024
            except OSError:
                pass
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINST_KEY) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "%s v%s" % (APP_FULL, APP_VER))
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VER)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, exe_path)
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, target_dir)
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, '"%s" /uninstall' % uninst)
        winreg.SetValueEx(k, "QuietUninstallString", 0, winreg.REG_SZ, '"%s" /uninstall /S' % uninst)
        winreg.SetValueEx(k, "HelpLink", 0, winreg.REG_SZ, HOMEPAGE)
        winreg.SetValueEx(k, "URLInfoAbout", 0, winreg.REG_SZ, HOMEPAGE)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)

    if want_autorun:
        mark("正在设置开机自启…")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, '"%s"' % exe_path)

    # 快捷方式放最后：这一步偶尔会被杀软扫描拖慢，别让它挡在前面
    if want_desktop:
        mark("正在创建桌面快捷方式…")
        try:
            create_lnk(os.path.join(desktop_dir(), "假休眠.lnk"), exe_path,
                       target_dir, "假休眠 FakeSleep - F11 全屏黑屏")
        except Exception as e:
            say("桌面快捷方式创建失败：%s" % e)
            log("desktop lnk 失败 %r" % (e,))

    mark("正在创建开始菜单项…")
    try:
        sm = os.path.join(start_menu_dir(), "假休眠")
        os.makedirs(sm, exist_ok=True)
        create_lnk(os.path.join(sm, "假休眠.lnk"), exe_path, target_dir,
                   "假休眠 FakeSleep - F11 全屏黑屏")
    except Exception as e:
        log("start menu 失败 %r" % (e,))

    log("安装完成 -> %s" % target_dir)
    mark("安装完成")


def schedule_delete(folder):
    """进程退出后由 cmd 反复尝试删掉整个安装目录（含自身）。

    注意：必须先把 cmd 的工作目录切走，否则当前 cwd 就是安装目录时 rmdir 会失败
    （目录被句柄占用），留下一个空壳目录。
    """
    cmd = ('ping 127.0.0.1 -n 3 >nul & cd /d "%%TEMP%%" & '
           'for /l %%i in (1,1,15) do @if exist "%s" (ping 127.0.0.1 -n 2 >nul & rmdir /s /q "%s")'
           % (folder, folder))
    subprocess.Popen(cmd, shell=True, creationflags=0x08000000)


def do_uninstall(say=lambda m: None, from_dir=None):
    if not getattr(sys, "frozen", False) and from_dir is None:
        say("开发模式下不执行卸载（请用安装目录里的 uninstall.exe 测试）")
        log("拒绝开发模式卸载")
        return

    target_dir = os.path.abspath(from_dir or (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
                                              else os.path.dirname(os.path.abspath(__file__))))
    # 安全阀：只删确实装过本程序的目录
    if not os.path.exists(os.path.join(target_dir, MAIN_EXE)):
        say("目标目录里没有 %s，已取消卸载" % MAIN_EXE)
        log("卸载中止：%s 不含主程序" % target_dir)
        return

    say("正在关闭正在运行的程序…")
    kill_running()
    time.sleep(0.6)

    # 自己的 cwd 若停在安装目录里，目录会被句柄占住删不掉
    try:
        os.chdir(os.environ.get("TEMP") or "C:\\")
    except OSError:
        pass

    say("正在删除快捷方式…")
    my_exe = os.path.join(target_dir, MAIN_EXE)
    for p in (os.path.join(desktop_dir(), "假休眠.lnk"),
              os.path.join(start_menu_dir(), "假休眠", "假休眠.lnk")):
        try:
            if not os.path.exists(p):
                continue
            tgt = read_lnk_target(p)
            # 只删指向本安装目录的快捷方式，别把用户自己建的别的「假休眠.lnk」误删
            if tgt and _same_file(tgt, my_exe):
                os.remove(p)
                log("已删快捷方式 %s -> %s" % (p, tgt))
            else:
                log("保留快捷方式 %s（指向 %s）" % (p, tgt))
        except Exception as e:
            log("删除 %s 失败 %r" % (p, e))
    try:
        os.rmdir(os.path.join(start_menu_dir(), "假休眠"))
    except OSError:
        pass

    say("正在清理注册表…")
    for root, key in ((winreg.HKEY_CURRENT_USER, UNINST_KEY),
                      (winreg.HKEY_CURRENT_USER, RUN_KEY)):
        try:
            if key == RUN_KEY:
                with winreg.OpenKey(root, key, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, APP_ID)
            else:
                winreg.DeleteKey(root, key)
        except FileNotFoundError:
            pass
        except OSError as e:
            log("注册表清理 %s -> %r" % (key, e))

    say("正在删除文件…")
    log("卸载 -> %s" % target_dir)
    schedule_delete(target_dir)


# ------------------------------------------------------------------ 图形界面

def run_gui(uninstall=False):
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("%s 安装程序" % APP_FULL if not uninstall else "%s 卸载" % APP_FULL)
    root.configure(bg=BG)
    root.resizable(False, False)
    w, h = 460, 460 if not uninstall else 300
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))
    try:
        root.iconbitmap(resource("icon.ico"))
    except Exception:
        pass

    tk.Label(root, text="假 休 眠" if not uninstall else "卸载 假休眠", bg=BG, fg=FG,
             font=(FONT, 18, "bold")).pack(anchor="w", padx=26, pady=(22, 0))
    tk.Label(root, text="FakeSleep v%s  ·  %s" % (APP_VER, PUBLISHER), bg=BG, fg=DIM,
             font=(FONT, 8)).pack(anchor="w", padx=26, pady=(2, 0))

    card = tk.Frame(root, bg=CARD)
    card.pack(fill="x", padx=26, pady=16)

    if not uninstall:
        tk.Label(card, text="安装到", bg=CARD, fg=DIM, font=(FONT, 9)).pack(anchor="w", padx=14, pady=(12, 4))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", padx=14, pady=(0, 10))
        path_var = tk.StringVar(value=default_dir())
        ent = tk.Entry(row, textvariable=path_var, bg="#0c0c10", fg=FG, insertbackground=FG,
                       relief="flat", font=(FONT, 9))
        ent.pack(side="left", fill="x", expand=True, ipady=4)

        def browse():
            d = filedialog.askdirectory(initialdir=os.path.dirname(path_var.get()) or "C:\\")
            if d:
                path_var.set(d)

        tk.Button(row, text="浏览", command=browse, bg="#2a2a34", fg=FG, relief="flat",
                  bd=0, font=(FONT, 8), activebackground="#353542",
                  activeforeground=FG, cursor="hand2", padx=10).pack(side="left", padx=(6, 0))

        desk_var = tk.BooleanVar(value=True)
        auto_var = tk.BooleanVar(value=False)
        for var, text in ((desk_var, "创建桌面快捷方式"), (auto_var, "开机自动启动（可选）")):
            cb = tk.Checkbutton(card, text=text, variable=var, bg=CARD, fg=FG, selectcolor="#0c0c10",
                                activebackground=CARD, activeforeground=FG, font=(FONT, 9),
                                bd=0, highlightthickness=0, anchor="w", cursor="hand2")
            cb.pack(anchor="w", padx=12, pady=1)
        tk.Frame(card, bg=CARD, height=8).pack()

    status = tk.Label(root, text="准备就绪" if not uninstall else "将删除程序文件、快捷方式与开机自启项",
                      bg=BG, fg=DIM, font=(FONT, 9), justify="left", wraplength=404, anchor="w")
    status.pack(fill="x", padx=26)

    def say(msg):
        status.configure(text=msg)
        root.update_idletasks()
        log("[ui] " + msg)

    def finish_install():
        btn.configure(state="disabled", text="安装中…")
        target = path_var.get().strip().strip('"')
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", "无法创建目录：\n%s" % e)
            btn.configure(state="normal", text="开始安装")
            return

        def step_install():
            try:
                do_install(target, desk_var.get(), auto_var.get(), say)
            except Exception as e:
                log("安装异常 %r" % (e,))
                status.configure(text="安装失败：%s" % e, fg=RED)
                btn.configure(state="normal", text="重试")
                return
            status.configure(text="✅ 安装完成，可以开始使用了", fg=GREEN)
            btn.configure(text="完成并启动   %s" % MAIN_EXE, state="normal",
                          command=lambda: launch_and_close(target))

        root.after(80, step_install)

    def launch_and_close(target):
        try:
            subprocess.Popen([os.path.join(target, MAIN_EXE)], cwd=target)
        except Exception as e:
            log("启动失败 %r" % (e,))
        root.destroy()

    def do_confirm_uninstall():
        if not messagebox.askyesno("确认卸载", "确定要卸载 %s 吗？" % APP_FULL):
            return
        btn.configure(state="disabled", text="卸载中…")

        def step():
            try:
                do_uninstall(say)
            except Exception as e:
                log("卸载异常 %r" % (e,))
                status.configure(text="卸载失败：%s" % e, fg=RED)
                return
            status.configure(text="✅ 已卸载", fg=GREEN)
            root.after(1200, root.destroy)

        root.after(80, step)

    btn = tk.Button(root, text="开始卸载" if uninstall else "开始安装",
                    command=do_confirm_uninstall if uninstall else finish_install,
                    bg=GREEN, fg="#08130c", activebackground="#35c877", activeforeground="#08130c",
                    relief="flat", bd=0, font=(FONT, 11, "bold"), cursor="hand2")
    btn.pack(fill="x", padx=26, ipady=9, pady=14)

    tk.Label(root, text="MIT License  ·  %s" % HOMEPAGE, bg=BG, fg="#5d5d68",
             font=(FONT, 7)).pack(side="bottom", pady=8)

    root.mainloop()


# ------------------------------------------------------------------ 入口

def arg(name):
    for a in sys.argv[1:]:
        if a.lower() == name.lower():
            return True
    return False


def arg_value(prefix):
    for a in sys.argv[1:]:
        if a.lower().startswith(prefix.lower()):
            return a[len(prefix):].strip('"')
    return None


def is_uninstall_mode():
    """/uninstall 显式指定，或本程序就叫 uninstall.exe（安装目录里那份副本）"""
    if arg("/uninstall"):
        return True
    if getattr(sys, "frozen", False):
        return os.path.basename(sys.executable).lower().startswith("uninstall")
    return False


def main():
    log("setup 启动 argv=%r uninst=%s" % (sys.argv, is_uninstall_mode()))
    silent = arg("/S")

    if is_uninstall_mode():
        if silent:
            do_uninstall(say=lambda m: log(m))
        else:
            run_gui(uninstall=True)
        return

    if silent:
        target = arg_value("/DIR=") or default_dir()
        do_install(target, not arg("/NOICONS"), False, say=lambda m: log(m))
        return

    run_gui(uninstall=False)


if __name__ == "__main__":
    main()
