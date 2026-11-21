# Pokémon Dream World — from the Tree of Dreams to a DS cartridge

English · [日本語](docs/README.ja.md) · [简体中文](docs/README.zh-CN.md)

A community restoration of the Generation V Dream World. Play on a computer, befriend a Pokémon on the Island of Dreams, wish for it at the tree, and catch it in the Entree Forest on your cartridge. This repository supplies the source changes and setup tools for a private server.

[Dream World player guide](docs/gameplay.en.md)

Updating an existing installation? After applying the source update, rebuild the Chinese game artwork and illustrated tutorials with the following command. It reuses your installed archive and Ruffle.

```powershell
uv run --no-project --python 3.13 --with pillow==13.0.0 --with fonttools==4.68.0 python assets-build/build.py runtime --update-game-text
```

## Try all 12 minigames

Open **Minigame practice** on the home page or above the Dream World. Choose a game, then use **Play again** or return to the list. No account, sleeping Pokémon or DS connection is required. Practice provides its own Pokémon and Berry. Scores, items and encounters stay out of your regular save. The menu uses your selected language. Some original games have text embedded in their artwork. [Open practice on the host PC](http://127.0.0.1:8080/practice/)

On another device connected to the same network, use the address under **Phone access** on the server’s website, then choose practice. For normal Dream World rewards and cartridge transfers, use the regular island.

## Play with a paired friend

Open the friend's profile from **Dream Pals** to water a dry plot or offer an item for a named shelf item. Both servers must have the update and have synced at least once. You can then leave requests while the owner is offline. Your server reserves your offer. When the servers reconnect, it delivers the item or returns your offer if the slot has changed. The profile shows the result.

When playing under your own visiting account, the promotions page carries your saved receipts and queued gifts. Sync back to your home server before receiving them on your cartridge. Scan physical albums on the home server.

## Japanese PWT tournaments

In **Promotions → Japanese catalog → Pokémon World Tournament**, download any of the 10 archived files (9 tournament numbers, including an early and corrected Junior Division file). For Japanese **Black 2 / White 2**, you can also select a raw 512 KiB save backup. The browser reads the three slots, shows installed tournaments and offers to create a new copy using a free slot. Each additional choice works on that copy. Keep the original backup. The browser copy workflow has been tested on disposable data. The Wi-Fi download at the PWT serves nine tournaments, including the corrected Junior Division file. The download list and file checksums have been tested. Reception on a physical Black 2 or White 2 cartridge is still unverified. [Tournament archive](https://projectpokemon.org/home/files/category/51-pok%C3%A9mon-world-tournaments/) · [Save format](https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Saves/SAV5B2W2.cs)

## Play solo on your local network

**Connect your DS and the PC running Dream World to the same home network.** The same Wi-Fi or hotspot works as long as its devices can communicate. Solo play requires no Tailscale account or invitation.

1. **Start Dream World on your PC.** After the [first-time Windows setup](#start-the-server-on-windows), double-click `Start-DreamWorld-LAN.cmd` in the `runtime` folder. Keep its window open while you play.
2. **Find the DNS on the Dream World website.** On that PC, open the Dream World homepage or game page and click **Find my DS DNS** above the game. If no address appears, check the LAN server and Wi-Fi connection, then click **Check again**. [Open the DNS guide on this PC](http://127.0.0.1:8080/player-guide/#dns)
3. **Enter the displayed address on your DS.** Under **Where to enter the DNS**, select your console model. In the Wi-Fi connection the game uses, turn off automatic DNS, enter the displayed number as **Primary DNS**, then save and run the connection test. You can keep this setting for later sessions while the address stays the same.

**To play on a phone or tablet**, start the LAN server and connect the phone to the PC's Wi-Fi. On the PC, click **Phone web address** on the homepage or above the game. Enter the address shown, including the port, in the phone's browser. Sign in with the account linked to your cartridge. The DS can be offline once its tuck-in sync finishes. Reconnect it when you are ready to wake the Pokémon. When the PC changes Wi-Fi in automatic LAN mode, refresh this page after the new connection is ready. It will show the new address. The mobile layout was tested in an emulated mobile browser. [Find the phone address on this PC](http://127.0.0.1:8080/player-guide/phone/)

### Play on the server PC with melonDS 1.1

1. Start the server and open the console DNS guide on that PC. Select **melonDS on this PC**. The guide uses the configured game-server address. [Open the emulator DNS guide](http://127.0.0.1:8080/player-guide/#melonDS)
2. Use indirect networking in melonDS. In the game’s Nintendo Wi-Fi Connection Settings, open the connection for **melonAP**, turn off automatic DNS and enter the primary DNS shown by the guide. Save and run the connection test. When the server listens on loopback, the address is `10.64.0.1`. [melonDS 1.1 network settings](https://github.com/melonDS-emu/melonDS/blob/1.1/src/net/Net_Slirp.cpp#L39-L42)
3. Load the in-game save. On the lower screen choose **C-Gear → Wi-Fi → Game Sync**, then tuck in a Pokémon. If the website recognizes the ID but is waiting for its game version, finish the tuck-in once and retry registration. If a translated game still goes black before the connection prompt after a successful connection test, keep a copy of the in-game `.sav` and test that copy with your own unmodified copy of the same Japanese edition.

### Remove the tuck-in limit

**Original DS cartridge with only a DNS change.** A private server can accept another tuck-in immediately after a wake. I verified two uploads around a confirmed wake for all four games using test saves. On the cartridge, Game Sync compares its saved date with the DS clock before requesting the list of Pokémon it can send. The normal wake reply contains no setting to reset that date. You can keep the same Pokémon asleep and return to its Dream World from the website until you choose to wake it.

Save in-game and close melonDS. In the website’s **Remove the tuck-in limit** panel, enter the date shown on the DS. Choose the melonDS save folder, select your save, then choose **Back up and update selected save**. Alternatively, select one 512 KiB .sav and download the unlocked copy. Use the copy as your emulator save or restore it to your cartridge. The browser processes it on your device. The server cannot change the clock check inside a stock cartridge over Wi-Fi. [Open the web tool](http://127.0.0.1:8080/player-guide/#tuck-in)

The DNS guide shows the address to enter even with the DS turned off. From your own profile, the playable Dream World status now opens the game. The sign at your house shows the trainer on the selected cartridge.

On Windows, save in-game and close melonDS. Double-click `Start-melonDS.cmd` in the installed `runtime` folder. Select your melonDS 1.1 executable, the game you normally play, your unmodified copy of the same edition and region, and your latest in-game `.sav`. The helper creates a private copy. Each player sets up their own save once. For future sessions, open `DreamWorld.cmd` in the new folder.

| Button in 解除睡眠限制 | When to use it |
| --- | --- |
| 平时游玩（汉化版） | Play your usual game. Save in-game and close melonDS before switching. |
| 申请入睡（原版） | Clear the clock-change and same-day waits, start the original game, then choose **Wi-Fi → ゲームシンク → はい** on the Japanese C-Gear. |
| 唤醒并领取（原版） | After preparing to wake on the website, open the original game and use Game Sync to receive your rewards. |

All three buttons use the same profile save. Tuck-in backs up the file before it changes the timer. Other activities using this clock-change timer are released too. The helper reads the date set in melonDS. When the last tuck-in would block that date, it adjusts the last-tuck-in date in the awake save slot. Both checks have automated tests for Black, White, Black 2 and White 2. A second completed tuck-in on the same day still needs an in-game test. To update an existing helper, open the new Start-melonDS.cmd, choose 更新「解除睡眠限制」, and select your existing play folder. On a stock DS the game checks its local timer before the server receives a save. If you can export and restore your own cartridge save, the helper can write a separate 512 KiB copy for the date displayed on your DS. Keep the same console and clock when you play again. [Player guide on the server PC](http://127.0.0.1:8080/player-guide/#tuck-in) · [Save field](https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Saves/Substructures/Gen5/AdventureInfo5.cs#L36) · [Nintendo Game Sync FAQ](https://www.nintendo.co.jp/ds/irbj/qa/index.html) · [Game Sync date check](https://github.com/fuddlesworth/pokebw2/blob/3afa377e9056f6ba75e572f9296b1637fc694a44/src/ov199/gsync_state.c#L1446-L1473)

### Repair Game Sync in Simplified Chinese White v2.1

Run [the local ROM repair tool](tools/repair-white-sync.py) with Python 3.11 or later. With no arguments it asks for your unmodified Japanese White ROM, your Simplified Chinese v2.1 ROM, then a **new** output filename. It checks both inputs and builds the repaired copy on your PC. With an existing play profile, open **解除睡眠限制 → 改用《白》汉化同步修复版** and select the result. For a new profile select the repaired ROM for both game choices. Everyday play, tuck-in and wake-up then share the repaired game and the same save.

The v2.1 translation stored a 47-entry graphics archive at `a/1/4/3`, where Game Sync reads 28 entries. The tool restores the Japanese wireless program and its matching resources, places the translated artwork in `a/0/4/3`, and keeps the Chinese font, messages and Wi-Fi settings artwork. It also translates the C-Gear’s Game Sync label in both text modes. On the melonDS 1.1 core, the same save and inputs reached the connection prompt in Japanese White and in the repaired Chinese copy. The original translation stayed black. This check stops at the connection prompt.


## Receive an event distribution

Open **Promotions → Cartridge delivery queue** to see the order for your selected save. The first Wonder Card is next on a fresh DS connection. The wake-up list shows the partners and items in the current batch, followed by anything deferred. While open, the page refreshes every 15 seconds. [Open the queue](http://127.0.0.1:8080/campaign/queue/)

Under **Mystery Gift**, choose **Queue all unclaimed cards** to append confirmed unclaimed cards from all pages. The button counts only cards it can add. If a gift allows only one of several versions, select your preferred version individually in the list. Each new DS connection offers the next queued card.

Open **Event distributions** from Dream World and select your linked cartridge. After updating, use Game Sync once with that game. The page lists events for its version and language. [Open the English event page on the server PC](http://127.0.0.1:8080/campaign/)

- **Dream World promotions.** Select **Send to my save**, finish your visit and prepare to wake up. Wake your Pokémon with Game Sync, then catch your partner in Entree Forest. The page records delivery when the game acknowledges the download. Its history covers this server’s promotions.
- **Mystery Gift.** Select **Send to my save**. On the game's title screen choose **Mystery Gift → Receive Gift → Get via Nintendo WFC**. Pick up the gift from the deliveryman in a Pokémon Center and save. Receive one card at a time. If several are waiting, choose **Receive this card next**.
- **Check receipts.** The next Game Sync with a readable album distinguishes a card received from a gift collected. **Check a save backup** also reads the latest raw 512 KiB `.sav` for the linked game. Variants sharing a card number can share a receipt. The page identifies a specific variant when the album contains enough information.

The server fetches an individual card from a pinned archive when requested. Temporary-save tests cover the web and cartridge protocols. I (goiku) received a C-Gear skin, a Dream World promotion and a Mystery Gift on my own Japanese Black cartridge. The Cleffa photo below documents the Tree of Dreams path. [Generation V event archive](https://github.com/projectpokemon/EventsGallery/tree/f1f3095183ee54dca63216164adb1f278714ec55/Released/Gen%205) · [Dream World encounter reference](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Legality/Encounters/Data/Gen5/Encounters5Dream.cs)

While the website is waiting for the DS to wake your Pokémon, you can still queue an event partner or save a C-Gear skin. The delivery is fixed when the DS starts downloading. Partners queued later or left over when space runs out stay queued for the next wake-up. Mystery Gifts can be received separately from the title screen. [Open the receiving instructions on the server PC](http://127.0.0.1:8080/player-guide/#distributions)

### Japanese cartridge events

**Japanese event catalogue** lists the 472 Japanese Wonder Cards preserved in the Generation V release archive and 47 Dream World entries across Black, White, Black 2 and White 2. Each distinct card file counts once. Dream World entries count game and move variants. Browse all four games while signed out. Search by species, original card title or card number (for example `#2046`). Select your own cartridge to request compatible gifts. [Open the catalogue](http://127.0.0.1:8080/campaign/japan/) · [Original card files](https://github.com/projectpokemon/EventsGallery/tree/f1f3095183ee54dca63216164adb1f278714ec55/Released/Gen%205/Wondercards/JPN)

The Sinnoh starter set now includes Japanese Black and White. The Café Forest recreation offers four species with three possible moves each and a choice of gender. In Black 2 and White 2 the strategy-guide app's Gothorita brings Imprison and one Focus Band. The partner and item wait together if the next wake-up has insufficient space. [Encounter data](https://github.com/kwsch/PKHeX/blob/6c9583883c7551ac74a4b74180cead249d4277b8/PKHeX.Core/Legality/Encounters/Data/Gen5/Encounters5Dream.cs) · [Publisher’s Gothorita announcement](https://www.4gamer.net/games/148/G014842/20121214008/)

Six Japanese tournament promotions award nine Berry types in Black 2 and White 2. Choose the Treasure Chest to grow them in Dream World, or send the entire set to your cartridge on wake-up. Each save can claim either destination once. [Tournament announcement](https://www.4gamer.net/games/148/G014842/20130315042/)

**For offline hosting**, run `.venv\Scripts\python.exe scripts\prepare_japanese_gifts.py` in the installed DreamWorld folder once. It downloads 142 KiB and verifies each Japanese card against its archive hash. The host can then distribute them on the local network with Internet access disconnected. The catalogue opens without the download. When the cache is absent, the server fetches the selected card on demand. Card numbers shared by several variants are marked for review when the album cannot identify which one was received. A recorded exact variant stays received after the card is discarded.

## Visit a friend's island while they are offline

Each player signs in on their own server using the account linked to their cartridge. Choose **View friends** in Dream World to save a copy of a friend's island.

- **Pair once for automatic updates.** Start the same server release on both PCs. Connect them to the same LAN or private Tailscale network. One player generates an invitation on the friends page and privately sends the entire code to the other player. The code is valid for 30 minutes. Choose the LAN code on the same Wi-Fi or the Tailscale code between homes. The recipient pastes it into their own friends page and pairs. While both servers are online, they check for new snapshots about every 30 seconds and deliver queued footprints. The consoles and battle relay can stay off. If Windows Firewall blocks the connection, allow TCP 8094 from your local network or your friend's Tailscale address.
- **Share a file.** The owner selects **Export my island snapshot** and sends the file. The visitor selects **Import a friend’s snapshot** on their own site and can visit immediately. Pair the servers when you want automatic updates and footprint delivery. Importing an older file preserves the newer cached version.

**Visit from home.** Choose your friend on the Dream Pal Map, or open **View friends** and select **Visit home**. This takes you to their island in the original Dream World. Choose **Enter room** to see where they put their furniture. The last update time tells you how recent the island is. Pairing keeps that same island up to date while both servers are running. You can keep visiting it after your friend switches off their PC and console. You can inspect the garden and Share Shelf as the owner left them. Open **Game record · Help on this island** above the room to water a dry plot or offer a shelf trade after pairing. The panel shows pending requests and their results. Close it to return to the same room. Your footprint stays on your PC until it can be delivered, and a repeated delivery counts once. [Original Dream World help for visiting friends](https://github.com/minibug1021/dreamworld-assets/blob/6e0550dab8552cd54bd976d4023f9ec0c43f6d7c/en.pokemon-gl.com/support/help/world/820/index.html#L161)

**Find your own encounter.** Tuck in a Pokémon on your home server. Start a visitor adventure from the friend's house and choose the trail that matches the footprint sample. Befriend the Pokémon, offer one Berry from your own chest at the Tree of Dreams, then choose to prepare to wake up and finish. Wake your Pokémon on your home server and catch your new partner in the Entree Forest. The adventure and delivery belong to the visitor's save. The host keeps their Pokémon and inventory.

The snapshot includes display information known to Game Sync, such as game version, trainer name, badges, play time, tucked-in Pokémon, Dream Points, inventory, furniture, medals and Friend Board. It omits the full cartridge save, box and party lists, Game Sync ID, passwords and sign-in credentials. Anyone receiving the file can read its display information.

## Cartridge test

The cartridge photo below documents the original solo Tree of Dreams route. Catching a partner from an offline friend's island on a physical Japanese Black cartridge still needs a separate playthrough. The [offline visit check](tools/check-offline-island.py) exercises a Japanese Black wake download and its encounter fields with temporary saves.

On November 20, 2026, I woke up Axew on my Japanese *Pokémon Black* cartridge. The server recorded the cartridge completing its download of Cleffa. I then caught Cleffa in the Entree Forest. Its summary on my console lists the encounter location as ハイリンクの森 (Entree Forest) and the level at encounter as 10. The Simplified Chinese website was tested separately in a browser. [Cartridge photo](docs/images/cleffa-cartridge.jpg)

The upstream revision used here listed wishing at the tree and sending a new friend back as unfinished. Earlier Game Sync experiments had already enabled forest captures from downloaded encounter data. We found no earlier public demonstration of this particular restored website-to-cartridge sequence in the sources reviewed as of November 20, 2026. Its worldwide priority remains unknown. [Upstream status at the revision used here](https://github.com/minibug1021/dreamworld-reawakened/blob/77174d2f3084b83b80544161dca8ad2d325654b8/readme.md#things-that-are-not-working) · [2023 Game Sync developer report](https://github.com/mm201/pkmn-classic-framework/issues/8#issuecomment-1552963901)

### Moving a caught Pokémon to Pokémon HOME

Visitor adventures look for a species and form displayed on your friend's island among the encounters you have unlocked in your own game. After you make a wish, your cartridge generates a new partner. If the original game font cannot display a nickname, the website shows the species name in your selected language, such as Cleffa in English or ピィ in Japanese. On a Japanese cartridge, skip the nickname prompt after catching it to keep ピィ.

The official path is **Pokémon Black → Poké Transporter → Pokémon Bank → Pokémon HOME**. It requires a Nintendo 3DS-family system with the two 3DS apps previously downloaded and a paid Pokémon HOME Premium Plan. This is a one-way move. Bank service and transfers to HOME are scheduled to end on **February 26, 2027 at 03:00 UTC**. [Poké Transporter instructions](https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/manual-3DS-poke-transporter-en) · [Pokémon HOME transfer guide](https://home.pokemon.com/en-us/move/) · [Service closure announcement](https://www.pokemon.co.jp/info/2022/02/220216_gm01.html)

This project tests the Forest encounter data sent to a Black cartridge. Pokémon HOME acceptance for a partner obtained through this restoration is unverified. This is a community project without official certification. The website's nickname display update does not edit Pokémon already caught on your cartridge.

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

### Update an existing installation

Finish any active Game Sync and close the server and relay windows. In the original Git checkout, open PowerShell in the folder containing `setup.py` and run the two commands below. This updates the installed source and reuses the large website mirror already on disk. Then start the server again. [Source updater](tools/apply-source.py)

```powershell
git pull --ff-only
python tools/apply-source.py runtime
```

## Bring your first partner home

1. **Tuck in a Pokémon.** On the C-Gear touch **Wi-Fi → Game Sync** (ゲームシンク on the Japanese cartridge). Tuck in one Pokémon and wait for confirmation. Find your save's Game Sync ID under **Game Sync Settings** on the game's main menu.
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

After both gateways report `Battle hub confirmed the connection`, set each console's primary DNS to **its own PC's LAN address** for multiplayer. For a friend battle or direct trade, register each other's Friend Code on the shared game server and enter the Pokémon Center Wi-Fi Club. For a standard GTS trade, one player deposits a Pokémon, the other searches and trades, then the first returns to collect it. To check the relay locally, run `uv run tools/DreamWorld-VPN.py self-test` in the release folder.

If GTS deposit stopped with error 13265 on an older server, update the host and re-enter GTS. The server now answers the name check that follows Pokémon validation. Check the current deposit before submitting another offer.

I tested this across two networks. I deposited a level 15 Panpour in Pokémon White on melonDS, then used a DS on a separate hotspot to trade a level 10 Panpour for it. The server recorded one completed exchange and the depositing game subsequently confirmed collection.

### Visit a friend's Dream World and take your rewards home

Either PC can host. First install or update both servers. Each player needs an activated account on their **own** server with their cartridge linked. Each pairing is for one host, one home account and one cartridge. The host creates a separate visitor profile, even if a local player has the same username. Pairing stops if the host already has a save for that Game Sync ID.

1. **Prepare your cartridge at home.** As the visitor, tuck a Pokémon in on your own server and wait for the DS to confirm. Close your local Dream World website and stop your LAN server with Ctrl+C. Leave the Pokémon asleep until you get home.
2. **Send an invitation from the host PC.** Start the server and the private relay using the commands above, then double-click `runtime/Invite-Friend.cmd`. Privately send the visitor your PC's Tailscale IPv4 address and the one-use code, valid for 30 minutes. Keep the server and relay running through the visitor's final sync.
3. **Join from the visitor PC.** Start the visitor gateway (command **3** above, with web forwarding enabled). Double-click `runtime/Visit-Friend.cmd` and enter the host's Tailscale address. Enter your own username and password on your PC, then enter the invitation code at first pairing. Your password is checked locally. The browser opens the visiting account automatically. The default website language is Simplified Chinese. To visit in English, run `.\Visit-Friend.cmd --lang en` in PowerShell inside `runtime`. Use `--lang ja` for Japanese.
4. **Play on the host and finish on the website.** Wish for a partner, choose any items to send to the cartridge, then return home on the website and choose to prepare your Pokémon to wake up. Close the game tab. Press Ctrl+C **in the visitor's sync window** and wait for `Final sync complete`. If the connection dropped, reconnect, keep the host and gateway running, and run `uv run --frozen python -m scripts.visit_friend --once` from the visitor's `runtime` folder.
5. **Return to your own server.** After the final sync succeeds, stop the visitor gateway and restart `Start-DreamWorld-LAN.cmd`. Check your own server's DNS and wake your Pokémon on the DS. The selected partner can be caught in the Entree Forest. The website's Treasure Chest and the items selected for cartridge delivery are recorded separately. For a visit in the other direction, swap roles and have the new host issue an invitation.

If both copies have new progress, synchronization pauses. Close the visiting browser and pause play on both PCs. From the visitor's `runtime` folder, run `uv run --frozen python -m scripts.visit_friend --once --resolve host` to keep the friend's server copy, or use `--resolve home` to keep your own PC's copy. The tool writes both versions to `visit-conflict-*.json` in the visitor's save folder before applying your choice. GTS deposits and Friend Codes remain on the game server where they were registered.

The integration test uses two temporary servers and synthetic cartridges. It checks visits in both directions, a browser wish, conflict recovery and the home server's wake-up download. You can run `runtime\.venv\Scripts\python.exe tools/check-visit.py runtime` from the release folder. The physical cartridge capture documented above was a separate solo test. [Two-server test](tools/check-visit.py)

## Project sources and changes

I’m goiku, and I performed the cartridge test myself. OpenAI Codex assisted with the source changes, localization and tests for this restoration.

After installation, you can also check the wish and cartridge download using a temporary test save. From the release folder, run `runtime\.venv\Scripts\python.exe tools/check-cartridge.py runtime`. A successful run prints `PASS`. [Cartridge test source](tools/check-cartridge.py)

The website finds the DNS to display by checking for a reply from the local game DNS service. Browse the [website DNS lookup](source/web/utils/player_dns.py), [Game Sync DNS responder](source/game-sync/entralinked/network/dns/server.py), [player guide page](source/web/templates/player_guide.html), and [sign-in and session handling](source/web/api/pgl_top.py). The installer applies the [website source patch](source/web.patch) and the [Game Sync source patch](source/game-sync.patch).

Original artwork, music and Flash minigames come from Pokémon. The restoration community preserved the website and developed the server and Game Sync support. Ruffle plays Flash content in a modern browser. [Dream World Reawakened](https://github.com/minibug1021/dreamworld-reawakened) · [game-sync-python](https://github.com/minibug1021/game-sync-python) · [Entralinked](https://github.com/kuroppoi/entralinked) · [dreamworld-assets](https://github.com/minibug1021/dreamworld-assets) · [Ruffle](https://ruffle.rs/)

This version adds the working wish and return path, saves the selected partner through a failed wake-up attempt, and fixes item pickup in the Icy Cave. Its Japanese-based Simplified Chinese interface uses established Pokémon terms, machine-assisted translation and edited text. It also integrates standard GTS, friend-room and private-network relay services.
