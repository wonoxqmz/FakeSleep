# 假休眠 FakeSleep

<div align="center">
<img src="icon.png" width="96" alt="FakeSleep 图标" />
</div>

> **开源仓库（主）**：<https://gitee.com/i-dont-want-to-pick-a-name/FakeSleep>
> **下载**：到 [Gitee Releases](https://gitee.com/i-dont-want-to-pick-a-name/FakeSleep/releases) 拿成品——
> `FakeSleep-Setup-v1.3.4.exe`（安装包，推荐）或 `FakeSleep.exe`（免安装单文件）。
> **网页下载页**：<https://fakesleep.pages.dev>（Cloudflare Pages）
>
> GitHub 旧仓库（`longchangjin2-arch/FakeSleep`）因账号被暂停已不可访问，主仓库已迁到 Gitee。

## 这是什么

客厅 / 机房值守小工具。跑项目不敢关机，又不想让屏幕亮着像在开机。

**两个模式，按键切换，互斥：**

| 热键 | 模式 | 本机屏幕 | 远程控制软件 |
| --- | --- | --- | --- |
| **F2** | 黑屏 | 全屏纯黑 | 跟着一起黑（看不到画面） |
| **F1** | **隐私** | **像素级纯黑（真的全黑）** | **完整实时画面，鼠标还能点** ✅ |

两个模式期间都会阻止系统休眠、熄屏、弹屏保。再按一次对应热键，或按 `Esc`，恢复正常。

## 为什么隐私模式能让"远程看得见、本机看不见"

普通黑色窗口不行：屏幕捕获（DXGI Desktop Duplication / GDI BitBlt）会把它一起抓走，远程端看到的和本机一样全黑。

> 早期版本用的是 **DDC/CI 硬件调光**（把显示器亮度+对比度拧到 0）。问题是**不少显示器根本不执行这个命令**——
> 软件读回来的值是 0，屏幕却还是亮的，等于白干。如果你的显示器正好不认，这条路就走不通。

现在默认走系统级方案：**把遮罩窗口从屏幕捕获里排除掉**。

```
SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)   // Win10 2004+
```

这个窗口**只画在显示器上**，任何捕获途径（DXGI 复制、GDI 截图、PrintScreen、远控软件）都拿不到它。
所以铺一块全屏纯黑窗口盖住桌面：本机看到的是**纯黑像素**，捕获出来的画面里那块黑压根不存在，远控看到的是正常桌面。

再叠加 `WS_EX_TRANSPARENT | WS_EX_LAYERED` 让鼠标**点击穿过**遮罩，远控的键鼠照样操作底下的窗口。

想用回旧方案：`config.ini` 里 `[privacy] method = ddc`（或 `both` 两个一起上）。

## 用法

1. 双击 `FakeSleep.exe`（或桌面快捷方式）
2. 小面板上按 **F2**（黑屏）或 **F1**（隐私全黑），也可以点对应按钮
3. 再按一次对应热键，或按 `Esc`，恢复

两个热键都是**全局注册**的，窗口最小化、在别的软件里都能按。面板最小化即可后台常驻。

### 手机远控没有功能键怎么办

手机远控 App 的软键盘通常**只有 Ctrl / Alt / Shift，没有 F1~F12**，所以光靠热键在手机上出不来也进不去。为此留了两条鼠标通路：

| 场景 | 怎么操作 |
| --- | --- |
| 进去 | 直接点面板上的「黑屏 F2」「隐私 F1」两个大按钮（远控里就是点鼠标） |
| 从黑屏出来 | **双击屏幕任意处**，或**单击屏幕右上角 80×80 的隐形热区** |
| 从隐私模式出来 | 屏幕右上角有个半透明的小「恢复 ×」，点一下就恢复（远控上可见可点；想要老的大绿条或不显示，改 config.ini 的 `exit_button`） |

> 隐私模式下屏幕是真的黑，如果一时忘了热键：按 `F1` / `F2` / `Esc` 都能恢复；
> 极端情况可以用 `FakeSleep.exe --brightness=100` 直接拉回亮度（Win+R 输入即可）。

## 版本更新提示

程序里有个轻量的更新提醒，**只提示、不打扰**（先问 Gitee，失败再问 GitHub）：

- **启动时**静默查一次 GitHub 最新 Release，查到新版就在面板左下角显示一行橙色小字「发现新版本 vX.Y.Z · 点此下载」，点它打开浏览器；没有新版显示「已是最新」；**断网 / 查不到就什么都不显示，绝不影响主功能**。
- **手动查**：点左下角的「检查更新」，随时再查一次。
- 全程**只发一次 GET 请求**（优先 `gitee.com/api/v5/repos/i-dont-want-to-pick-a-name/FakeSleep/releases/latest`，失败才退回 GitHub），不自动下载、不弹窗、不上报任何信息。
- 想彻底断网：`config.ini` 里设 `[update] check_on_start = no`，手动按钮仍然可用。

> 换句话说：**旧版本不会自己催你更新**，现在这个提示是 v1.2.2 才加的 —— 比它更早的版本永远安静运行，需要自己去 Releases 页面下载。

## 它做了什么

| 行为 | 说明 |
| --- | --- |
| 黑屏 | 覆盖**所有显示器**的虚拟桌面区域，鼠标光标同时隐藏 |
| 隐私调光 | DDC/CI（`SetMonitorBrightness`）把物理显示器亮度压到 `dim_value`，退出时恢复原值 |
| 阻止系统休眠 | `SetThreadExecutionState(ES_CONTINUOUS \| ES_SYSTEM_REQUIRED)`，每 25 秒续一次 |
| 阻止熄屏/屏保 | 叠加 `ES_DISPLAY_REQUIRED`（黑屏模式可在 config.ini 关掉，让显示器自己熄灯更省电） |
| 退出即恢复 | 关掉程序会清除休眠限制，**并强制把亮度恢复到进入前的值** |
| 顶住不露馅 | 黑屏期间每 1.2 秒把自己顶回最顶层，`Win+D`、弹窗、通知都盖不住它 |
| 更新提示 | 启动静默查一次 GitHub Release，仅显示一行文字，可配置关闭 |

## 需要注意

- **F2 / F1 是全局注册的**，程序运行期间其他软件的 F2、F1 会被它抢走（F1 在很多软件里是「帮助」键，介意就改配置）。
- 黑屏用 F2 而不是常见的 F11，是因为手机远控 App 的软键盘上没有 F11 这类功能键。
  不想抢就在 `config.ini` 里加 `ctrl = yes` 或换成别的键。
- 隐私模式默认用 **F1**（键盘最左上角，摸黑也好按）。F12 常被远控软件（RustDesk / BilldDesk）占用，所以没用它。
- 热键被占用会自动降级：黑屏 `F2 → Ctrl+Alt+F2 → Ctrl+Alt+B`，隐私 `F1 → Ctrl+Alt+F1 → Ctrl+Alt+P`，面板上显示实际生效的键。
- **隐私模式（默认 veil）需要 Win10 2004 或更新**（`SetWindowDisplayAffinity`）。低于这个版本请在 `config.ini` 里把 `method` 改成 `ddc`。
- 极少数远控软件用驱动级捕获，可能不认系统的捕获排除；如果远控那边也是一片黑，就改用 `method = both` 或 `ddc`。
- 旧的 DDC/CI 调光（`method = ddc`）**需要显示器支持 DDC/CI**，而且有的显示器会假装成功（读回 0 但屏幕不暗）。
- 黑屏时按 `Ctrl+Alt+Del` 仍然能进系统安全界面，这是 Windows 行为，防止误锁死。
- 卡巴斯基可能对 PyInstaller 单文件 exe 首次运行报警，放行即可。

## 配置文件 config.ini

首次运行自动生成在 exe 同目录：

```ini
[hotkey]           ; 黑屏模式
key = F2
ctrl = no
alt = no
shift = no

[privacy]          ; 隐私模式
key = F1
ctrl = no
alt = no
shift = no
method = veil      ; veil = 遮罩排除捕获（推荐）/ ddc = 硬件调光 / both
exit_button = corner ; corner = 右上角迷你恢复按钮 / bar = 底部大条 / off = 不显示
dim_value = 0      ; 仅 ddc·both 用：亮度，0 = 最暗
dim_contrast = 0   ; 仅 ddc·both 用：对比度；-1 = 不动

[display]
keep_display_on = yes   ; 黑屏模式下是否强行不让显示器熄灯

[update]
check_on_start = yes    ; 启动时是否查一次最新版本（no = 完全不联网）
```

改完重启程序生效。

## 命令行

```
FakeSleep.exe                正常启动（小面板）
FakeSleep.exe --black        启动直接进黑屏
FakeSleep.exe --dim          启动直接进隐私调光
FakeSleep.exe --brightness=100   直接把亮度拉到 100 后退出（摸黑救急用）
```

## 两种安装方式

**A. 安装包（推荐）** — 双击 `FakeSleep-Setup-v1.3.4.exe`：

- 图形向导，可自选安装目录、是否建桌面快捷方式、是否开机自启
- 装完在「设置 → 应用 → 已安装的应用」里能正常卸载（写 HKCU 卸载项，不需要管理员权限）
- 静默安装：`FakeSleep-Setup-v1.3.4.exe /S /DIR="D:\Apps\FakeSleep" [/NOICONS]`
- 静默卸载：`"<安装目录>\uninstall.exe" /S`

**B. 免安装** — 直接双击 `FakeSleep.exe`，绿色单文件。

## 文件

- `FakeSleep.exe` — 主程序（也可从 [Gitee Releases](https://gitee.com/i-dont-want-to-pick-a-name/FakeSleep/releases) 下载）
- `FakeSleep-Setup-v1.3.4.exe` — 安装包
- `fakesleep.py` — 源码（纯标准库，仅 tkinter + ctypes）
- `installer.py` — 安装器源码（tkinter 向导 + 注册表 + 快捷方式）
- `make_icon.py` — 图标生成器（纯标准库）
- `make_shortcut.py` — 桌面快捷方式生成器（ctypes 调 Shell COM）
- `config.ini` — 配置（首次运行生成）
- `fakesleep.log` — 运行日志
- `site/` — Cloudflare Pages 下载页源文件（`index.html`、`version.json`、`_headers`）

## 自己动手

```bash
# 打包主程序
pip install pyinstaller
pyinstaller --onefile --noconsole --icon icon.ico --name FakeSleep fakesleep.py

# 打包安装器（把主程序打进去）
pyinstaller --onefile --noconsole --icon icon.ico --name FakeSleep-Setup-v1.3.4 ^
    --add-data "FakeSleep.exe;." --add-data "config.ini;." --add-data "icon.ico;." ^
    --add-data "README.md;." --add-data "LICENSE;." installer.py

# 重新生成图标 / 桌面快捷方式
python make_icon.py
python make_shortcut.py
```

## 协议

[MIT](LICENSE) © 2026 LCJ (longchangjin2-arch)

## 更新日志

### 2026-10-30 v1.3.4
- **更新检查改走自家下载页**：优先读 <https://fakesleep.pages.dev/version.json>，
  失败再退到 Gitee API（匿名有时 403），再退 GitHub。三种都失败就静默，不打扰。
- **Cloudflare Pages 下载页正式上线**：<https://fakesleep.pages.dev>
  （页面源文件放在仓库 `site/` 目录，`_headers` 指定 MIME 与安全头）
- 安装包 / 绿色版文件名同步升到 v1.3.4

### 2026-10-30 v1.3.3
- **仓库迁到 Gitee**：GitHub 账号被暂停（403 suspended），主仓库改为 <https://gitee.com/i-dont-want-to-pick-a-name/FakeSleep>
- **更新检查改走 Gitee API**（`gitee.com/api/v5/...releases/latest`），GitHub 作为备用源；两者都失败仍然静默
- 新增 Cloudflare Pages 下载页：<https://fakesleep.pages.dev>

### 2026-10-24 v1.3.2
- **隐私模式的恢复按钮缩小**：原来的大绿条挡视线/挡操作，默认改为**右上角 64×20 半透明「恢复 ×」**
- 新增 `[privacy] exit_button = corner | bar | off`：`bar` 回老样式，`off` 彻底不显示
  （`off` 时只能按 F1 / Esc 退出，手机远控会没法出来，慎用）

### 2026-10-24 v1.3.1
- **修复卸载器误删快捷方式**：卸载时先读 .lnk 指向的目标，只删指向本安装目录的快捷方式；
  指向别处的同名「假休眠.lnk」（比如绿色版用户自建的）不再被误删

### 2026-10-23 v1.3.0
- **隐私模式重写：遮罩 + 捕获排除**（`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`）—— 本机**像素级纯黑**，
  远程照常看到完整桌面。旧版靠 DDC/CI 调光，实测在 ViewSonic 这台显示器上**根本不生效**（读回 0 但屏幕还亮着）
- 遮罩设 `WS_EX_TRANSPARENT | WS_EX_LAYERED` 点击穿透，远控键鼠可以继续操作底下的窗口
- 新增 `[privacy] method = veil | ddc | both`，DDC 老方案保留可选；`dim_value` / `dim_contrast` 只对 ddc·both 生效
- 实测：遮罩后截图像素与遮罩前一致（= 捕获里看不见遮罩），`WindowFromPoint` 命中下层窗口（= 点击穿透）

### 2026-10-18 v1.2.2
- **新增版本更新提示**：启动静默查一次 GitHub 最新 Release，有新版只在面板左下角显示一行小字，点开即下载页；断网静默忽略，绝不弹窗、不自动下载
- 面板左下角加「检查更新」手动入口；`config.ini` 新增 `[update] check_on_start` 可彻底关掉联网
- **手机远控友好**：黑屏时**双击屏幕任意处**或单击**右上角隐形热区**即可退出（远控软键盘没有功能键时也能出来）
- **隐私模式新增「恢复显示」小条**：屏幕下方浮一个绿色按钮，本机全黑看不见，远控里点一下即恢复 —— 解决"从手机进隐私模式后出不来"的问题
- 面板高度 404 → 420，底部加版本状态行

### 2026-10-18 v1.2.1
- 黑屏模式热键 F11 → **F2**：手机远控 App 的软键盘上没有 F11 功能键，远程没法按
- 现在的键位：`F2` 黑屏、`F1` 隐私调光，都在键盘最左边一排

### 2026-10-18 v1.2.0
- 隐私调光增强：**亮度归零 + 对比度归零**双重压暗，屏幕明显更黑（原来只调亮度有微弱背光）
- 对比度可配置（`dim_contrast`），恢复时同时还原亮度与对比度

### 2026-10-18 v1.1.1
- 隐私模式热键 F10 → **F1**（键盘最左上角，摸黑也好按）
- 黑屏模式改用 F2（v1.2.1，手机远控软键盘上没有 F11）

### 2026-10-17 v1.1.0
- **新增隐私模式（F10）**：DDC/CI 硬件调光到 0 —— 本机屏幕变黑，远控软件看到完整实时画面
- 两个模式互斥切换，共用一个全局热键线程（`RegisterHotKey` 多 slot）
- 隐私模式支持多显示器；退出程序时强制恢复亮度，绝不把屏幕留在全黑
- 新增 `--dim`、`--brightness=N` 命令行开关，摸黑时可救急
- F12 被远控软件占用，隐私热键默认改为 F10

### 2026-10-17 v1.0.0
- 首个版本：F11 全局热键切换全屏黑屏，跨多显示器覆盖
- 黑屏期间阻止系统休眠 + 熄屏 + 屏保
- 热键自动降级（F11 → Ctrl+Alt+F11 → Ctrl+Alt+B）
- 单实例保护、config.ini 配置、运行日志
- 开源发布：GitHub 仓库 + Release 附打包好的 exe / 安装包
- 带自绘图标（make_icon.py）；桌面快捷方式一键生成（make_shortcut.py）
