# Pokémon Dream World — from the Tree of Dreams to a DS cartridge

English · [日本語](docs/README.ja.md) · [简体中文](docs/README.zh-CN.md)

A community restoration of the Generation V Dream World. Play on a computer, befriend a Pokémon on the Island of Dreams, wish for it at the tree, and catch it in the Entree Forest on your cartridge. This repository supplies the source changes and setup tools for a private server.

## Cartridge test

On November 20, 2026, I woke up Axew on my Japanese *Pokémon Black* cartridge. The server recorded the cartridge completing its download of Cleffa. I then caught Cleffa in the Entree Forest. Its summary on my console lists the encounter location as ハイリンクの森 (Entree Forest) and the level at encounter as 10. The Simplified Chinese website was tested separately in a browser. [Cartridge photo](docs/images/cleffa-cartridge.jpg)

The upstream revision used here listed wishing at the tree and sending a new friend back as unfinished. Earlier Game Sync experiments had already enabled forest captures from downloaded encounter data. We found no earlier public demonstration of this particular restored website-to-cartridge sequence in the sources reviewed as of November 20, 2026. Its worldwide priority remains unknown. [Upstream status at the revision used here](https://github.com/minibug1021/dreamworld-reawakened/blob/77174d2f3084b83b80544161dca8ad2d325654b8/readme.md#things-that-are-not-working) · [2023 Game Sync developer report](https://github.com/mm201/pkmn-classic-framework/issues/8#issuecomment-1552963901)

## Start the server on Windows

Allow at least **6 GB of free disk space**. The unpacked website mirror alone is about 3.8 GiB. On its first run, the installer downloads the upstream revisions used for this release and prepares the game assets. The mirror can take a while to download and unpack. Wait for `Ready at` before continuing. If you already have the matching archives, pass their paths to `setup.py` with `--assets-archive` (GitHub source `.tar.gz`) and `--ruffle-archive` (Ruffle self-hosted `.zip`).

Use a Windows PC, a DS-family console and a Generation V save with the C-Gear unlocked. Connect the PC and console to a network where they can reach each other. Install Git, Python 3.11 or later, and uv. Open PowerShell and run the commands below. If you already downloaded and extracted the repository, open PowerShell in the folder containing `setup.py` and start at the third command. [Git for Windows](https://git-scm.com/downloads/win) · [Python for Windows](https://www.python.org/downloads/windows/) · [uv installation](https://docs.astral.sh/uv/getting-started/installation/)

```powershell
git clone https://github.com/goiku/dreamworld-cartridge.git
cd dreamworld-cartridge
python setup.py
cd runtime
uv sync --frozen
uv run --frozen python launch_windows.py --lan
```

If Windows uses the Python Launcher, use `py -3 setup.py` in place of `python setup.py`. Keep the server window open while playing. It prints the Game Sync address for your DS and a website address for each available language. The English site uses port 8080, Japanese 8081 and Simplified Chinese 8088. [English homepage on your PC](http://127.0.0.1:8080/)

## Bring your first partner home

1. **Connect the cartridge.** In the Wi-Fi settings used by your game, set primary DNS to the private IPv4 address printed as `Game Sync address`. On the C-Gear touch **Wi-Fi → Game Sync** (ゲームシンク on the Japanese cartridge). Tuck in one Pokémon and wait for confirmation. Find your save's Game Sync ID under **Game Sync Settings** on the game's main menu.
2. **Link your save.** Open the local homepage, create an account on this server, sign in, and register your save's Game Sync ID. If registration asks for activation, the server operator can run the command below in a second PowerShell window inside `runtime`. Replace `PlayerName` with the registered username. Server operators can activate accounts locally without configuring email.
3. **Make a friend on the website.** Enter Dream World, cross the rainbow bridge and complete an encounter's minigame. At the Tree of Dreams, offer one Berry and select the Pokémon you befriended. New players receive five Berries of one kind on their first visit.
4. **Prepare to wake up.** Return home on the website. Use the power button in the upper right, choose to end the visit and wake your Pokémon, then check the partner shown and confirm.
5. **Catch your partner.** On the DS repeat **Wi-Fi → Game Sync** to wake the Pokémon you tucked in. After syncing finishes, use **Wireless → Entralink** (ハイリンク), walk north into the forest and talk to your new partner to start the encounter.

```powershell
uv run --frozen python -m scripts.activate_account PlayerName
```

If the site does not recognize the ID, check that the cartridge finished its first sync with **this server** and that you used its Game Sync ID. A Friend Code is a separate number used for multiplayer. If a sync is interrupted, keep the same server and save, follow the message on the console, and return to Game Sync to check its state.

## Play with a friend on another network

Both players need a Windows PC on the same local network as their own DS. Connect both PCs to the same private Tailscale network. Each console continues to use its local Wi-Fi. The relay has been tested with simulated console traffic. A battle or trade between two physical consoles on separate networks still needs verification. [Tailscale connection guide](https://tailscale.com/docs/how-to/connect-to-devices)

For the example below, both **separate** home networks reserve the same available LAN address for their PC. Replace the example addresses with your own. Use `tailscale ip -4` on each PC to find its Tailscale address and `tailscale ping` with the other PC's address to check connectivity.

| Address | Host | Friend |
| --- | --- | --- |
| PC on Tailscale | 100.64.10.1 | 100.64.10.2 |
| PC on its own LAN | 192.168.50.20 | 192.168.50.20 |
| DS on its own LAN | 192.168.50.31 | 192.168.50.32 |

Finish any active sync and stop the LAN server with Ctrl+C. On the host, open PowerShell in the release folder and launch the server in local mode.

```powershell
$env:DW_RELAY_STATE = Join-Path (Get-Location) "tools\DreamWorld-VPN-state.json"
cd runtime
uv run --frozen python launch_windows.py
```

Open three separate PowerShell windows in the release folder. Run line **1** on the host PC for the relay hub, **2** on the host PC for its DS, and **3** on the friend's PC for their DS. The friend needs a copy of this repository and uv. Use the same `--relay-ip` on all three commands. It must be assigned to both PCs on their respective DS-facing networks and reachable by each DS.

```powershell
# 1
uv run tools/DreamWorld-VPN.py host --bind 100.64.10.1 --peer 100.64.10.1 --peer 100.64.10.2 --relay-ip 192.168.50.20
# 2
uv run tools/DreamWorld-VPN.py gateway --bind 192.168.50.20 --peer 192.168.50.31 --host 100.64.10.1 --tailscale-ip 100.64.10.1 --relay-ip 192.168.50.20 --no-web
# 3
uv run tools/DreamWorld-VPN.py gateway --bind 192.168.50.20 --peer 192.168.50.32 --host 100.64.10.1 --tailscale-ip 100.64.10.2 --relay-ip 192.168.50.20
```

After both gateways report `Battle hub confirmed the connection`, set each console's primary DNS to **its own PC's LAN address**. Each player opens the local website on their PC and uses their own account. For a friend battle or direct trade, register each other's Friend Code and enter the Pokémon Center Wi-Fi Club. For a standard GTS trade, one player deposits a Pokémon, the other searches and trades, then the first returns to collect it. To check the relay locally, run `uv run tools/DreamWorld-VPN.py self-test` in the release folder.

## Project sources and changes

I’m goiku, and I performed the cartridge test myself. OpenAI Codex assisted with the source changes, localization and tests for this restoration.

After installation, you can also check the wish and cartridge download using a temporary test save. From the release folder, run `runtime\.venv\Scripts\python.exe tools/check-cartridge.py runtime`. A successful run prints `PASS`. [Cartridge test source](tools/check-cartridge.py)

Review the changes in the [website source patch](source/web.patch) and the [Game Sync source patch](source/game-sync.patch).

Original artwork, music and Flash minigames come from Pokémon. The restoration community preserved the website and developed the server and Game Sync support. Ruffle plays Flash content in a modern browser. [Dream World Reawakened](https://github.com/minibug1021/dreamworld-reawakened) · [game-sync-python](https://github.com/minibug1021/game-sync-python) · [Entralinked](https://github.com/kuroppoi/entralinked) · [dreamworld-assets](https://github.com/minibug1021/dreamworld-assets) · [Ruffle](https://ruffle.rs/)

This version adds the working wish and return path, saves the selected partner through a failed wake-up attempt, and fixes item pickup in the Icy Cave. Its Japanese-based Simplified Chinese interface uses established Pokémon terms, machine-assisted translation and edited text. It also integrates standard GTS, friend-room and private-network relay services.
