# 宝可梦梦世界 · 从梦之树到 NDS 卡带

[English](../README.md) · [日本語](README.ja.md) · 简体中文

这是第五世代梦世界的社区复原版。你可以在电脑上探索梦之岛、和宝可梦交朋友、到梦之树许愿，再用自己的卡带到连入之森亲手捕获它。本仓库提供搭建私服所需的源码改动和安装工具。

## 实机捕获记录

2026 年 11 月 20 日，一位玩家在日版《宝可梦 黑》卡带中唤醒了牙牙。服务器收到了卡带完成下载的回执，记录显示送出的新伙伴是皮宝宝。玩家随后在游戏里抓到了它。实机的能力页面记载，相遇地点为「ハイリンクの森」（连入之森），相遇等级为 10。简体中文网页另外经过了浏览器实测。[查看卡带实拍](images/cleffa-cartridge.jpg)

本项目采用的上游版本把梦之树许愿和新伙伴回传列为尚未完成的功能。此前已经有开发者通过游戏同步下载遭遇数据，并在森林里捕获宝可梦。截至 2026 年 11 月 20 日，在所查公开资料中，尚未找到更早展示「复活网页结交、许愿、回传、实机捕获」全过程的记录。全球首次的归属仍无定论。[所用上游版本的功能说明](https://github.com/minibug1021/dreamworld-reawakened/blob/77174d2f3084b83b80544161dca8ad2d325654b8/readme.md#things-that-are-not-working) · [2023 年开发者的游戏同步记录](https://github.com/mm201/pkmn-classic-framework/issues/8#issuecomment-1552963901)

## 在 Windows 上启动私服

请预留至少 **6 GB 磁盘空间**。仅解压原版网页镜像就需要约 3.8 GiB。首次安装会下载本版使用的上游代码和资源，并准备游戏文件。镜像较大，下载和解压可能需要一段时间，看到 `Ready at` 后再继续。如果手头已经有对应版本的压缩包，可给 `setup.py` 加上 `--assets-archive` 指定 GitHub 网页资源 `.tar.gz` 的路径，用 `--ruffle-archive` 指定 Ruffle 自托管版 `.zip` 的路径。

准备一台 Windows 电脑、一台 DS 系列掌机，以及一个已经获得 C-Gear（C 装置）的第五世代存档。让电脑和掌机连接到能互相访问的局域网。安装 Git、Python 3.11 或更高版本以及 uv。打开 PowerShell，依次运行以下命令。如果已经下载并解压本仓库，在含有 `setup.py` 的目录中打开 PowerShell，从第三条命令开始。[下载 Git](https://git-scm.com/downloads/win) · [下载 Python](https://www.python.org/downloads/windows/) · [安装 uv](https://docs.astral.sh/uv/getting-started/installation/)

```powershell
git clone https://github.com/goiku/dreamworld-cartridge.git
cd dreamworld-cartridge
python setup.py
cd runtime
uv sync --frozen
uv run --frozen python launch_windows.py --lan
```

如果电脑使用 Windows 的 Python 启动器，可以用 `py -3 setup.py` 运行安装程序。游玩期间保持窗口开启。窗口会显示供掌机使用的 `Game Sync address`，以及各语言的网页地址。英语端口为 8080，日语为 8081，简体中文为 8088。[打开本机中文版首页](http://127.0.0.1:8088/)

## 第一次把梦世界伙伴带回卡带

1. **连接卡带。** 打开这款游戏使用的 Wi-Fi 连接设置，把主 DNS 填成窗口中 `Game Sync address` 后面的局域网 IPv4 地址。在 C-Gear 下屏点 **Wi-Fi → 游戏同步**（日文「ゲームシンク」），让一只宝可梦入睡，等游戏提示同步完成。存档的游戏同步 ID 可以在游戏主菜单的「ゲームシンク設定」里查看。
2. **绑定存档。** 在电脑上打开本机网页，注册这个私服的账号并登录，再登记该存档的游戏同步 ID。如果网页提示需要激活，服主可以在 `runtime` 目录另开 PowerShell，运行下方的激活命令，把 `PlayerName` 换成玩家注册时填写的用户名。服主可以在本机激活账号，无需配置邮件服务。
3. **在网页结交伙伴。** 进入梦世界，跨过彩虹桥，通过小游戏与遇见的宝可梦交朋友。到梦之树献出一枚树果，选择想带走的伙伴。首次进入梦世界会收到同一种树果五枚。
4. **在网页准备唤醒。** 回到梦世界小屋，点右上角电源按钮，选「准备唤醒并结束」。核对要带走的伙伴，然后点「结束梦世界」。
5. **在卡带捕获。** 回到掌机，点 **Wi-Fi → 游戏同步**，唤醒先前入睡的宝可梦。同步结束后，打开 **WIRELESS → ハイリンク**，往北走进「ハイリンクの森」。和你选中的伙伴对话就能开始捕获。

```powershell
uv run --frozen python -m scripts.activate_account PlayerName
```

如果网页提示找不到 ID，先确认卡带在**当前这台私服**完成过一次同步，再核对游戏同步 ID。好友代码是联机时使用的另一组号码。同步中断时，保留同一台服务器和同一份存档，按照掌机提示操作，再进入游戏同步查看当前状态。

## 和不同网络的好友联机

双方各需要一台 Windows 电脑，分别与各自的掌机连接同一个局域网。两台电脑加入同一个 Tailscale 私有网络，掌机继续使用当地 Wi-Fi。转接程序已经通过模拟掌机通信测试，跨网的两台实体掌机完成对战或交换仍待验证。[Tailscale 设备互连说明](https://tailscale.com/docs/how-to/connect-to-devices)

下面的示例适合两个**彼此独立**的家庭网络。两边各自为电脑保留同一个可用的局域网地址，使用时请换成自己的地址。在两台电脑上分别运行 `tailscale ip -4` 查看各自的 Tailscale 地址，再用 `tailscale ping` 加对方地址确认互通。

| 地址 | 房主 | 好友 |
| --- | --- | --- |
| 电脑的 Tailscale 地址 | 100.64.10.1 | 100.64.10.2 |
| 电脑在本地局域网的地址 | 192.168.50.20 | 192.168.50.20 |
| 掌机在本地局域网的地址 | 192.168.50.31 | 192.168.50.32 |

等正在进行的同步结束后，用 Ctrl+C 停止局域网模式。房主在发布包目录打开 PowerShell，以本机模式启动服务。

```powershell
$env:DW_RELAY_STATE = Join-Path (Get-Location) "tools\DreamWorld-VPN-state.json"
cd runtime
uv run --frozen python launch_windows.py
```

分别在发布包目录打开三个 PowerShell 窗口。命令 **1** 由房主运行，用来启动转接中心。命令 **2** 也由房主运行，用来连接房主的掌机。命令 **3** 由好友在自己的电脑上运行，用来连接好友的掌机。好友电脑需要一份本仓库和 uv。三条命令中的 `--relay-ip` 要一致，两台电脑都要在各自连接掌机的网络上拥有这个地址，各自的掌机也都要能访问它。

```powershell
# 1
uv run tools/DreamWorld-VPN.py host --bind 100.64.10.1 --peer 100.64.10.1 --peer 100.64.10.2 --relay-ip 192.168.50.20
# 2
uv run tools/DreamWorld-VPN.py gateway --bind 192.168.50.20 --peer 192.168.50.31 --host 100.64.10.1 --tailscale-ip 100.64.10.1 --relay-ip 192.168.50.20 --no-web
# 3
uv run tools/DreamWorld-VPN.py gateway --bind 192.168.50.20 --peer 192.168.50.32 --host 100.64.10.1 --tailscale-ip 100.64.10.2 --relay-ip 192.168.50.20
```

两边的网关窗口都出现 `Battle hub confirmed the connection` 后，各自把掌机的主 DNS 填成**当地电脑的局域网地址**，在电脑上打开本机网页，用各自的账号登录。好友对战或直接交换需要双方登记彼此的好友代码，再进入宝可梦中心的 Wi-Fi 俱乐部。普通 GTS 交换由一人预放，一人搜索并交换，预放者再次进入即可领取。要在本机自检转接程序，可在发布包目录运行 `uv run tools/DreamWorld-VPN.py self-test`。

## 来源与本次改动

goiku 在实体卡带上抓到了皮宝宝，OpenAI Codex 协助完成了本次复原的源码修改、汉化和测试。

安装后，还可以用临时测试存档检查许愿和卡带下载流程。在发布包目录运行 `runtime\.venv\Scripts\python.exe tools/check-cartridge.py runtime`，通过时会显示 `PASS`。[查看卡带测试源码](../tools/check-cartridge.py)

可直接查看[网页服务源码补丁](../source/web.patch)和[卡带游戏同步源码补丁](../source/game-sync.patch)。

原版的美术、音乐和 Flash 小游戏来自宝可梦。复原社区保存了网页资源，开发了服务器和游戏同步程序。现代浏览器通过 Ruffle 运行 Flash 内容。[Dream World Reawakened](https://github.com/minibug1021/dreamworld-reawakened) · [game-sync-python](https://github.com/minibug1021/game-sync-python) · [Entralinked](https://github.com/kuroppoi/entralinked) · [dreamworld-assets](https://github.com/minibug1021/dreamworld-assets) · [Ruffle](https://ruffle.rs/)

本版补通了许愿和新伙伴回传，唤醒通信中断后仍会保留已选伙伴，也修复了冰洞发光道具的拾取。简体中文以日版网页为底，结合现有宝可梦中文术语、机器辅助翻译和文本校订。本版另外接入了普通 GTS、好友联机房间和私有网络转接。
