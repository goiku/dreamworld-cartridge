# ポケモンドリームワールド　ゆめの木からDSのハイリンクの森へ

[English](../README.md) · 日本語 · [简体中文](README.zh-CN.md)

第五世代のポケモンドリームワールドを有志が復元したものです。パソコンでゆめしまを訪れ、仲良くなったポケモンをゆめの木で選ぶと、自分のゲームカードの「ハイリンクの森」で捕まえられます。このリポジトリには、個人用サーバーを構築するためのソースコードの変更とセットアップ用ツールを収録しています。

## 実機での捕獲記録

2026 年 11 月 20 日、日本語版『ポケットモンスターブラック』で、プレイヤーがキバゴを起こしました。サーバーには、新しい仲間のピィを送信し、ゲームカードからダウンロード完了の応答を受け取った記録があります。その後、プレイヤーはゲーム内でピィを捕獲しました。実機のステータス画面には「ハイリンクの森で」「Lv.10のときに」「出会った。」と表示されています。簡体字中国語のウェブ版は、これとは別にブラウザーで動作を確認しています。[ゲームカードでの捕獲写真](images/cleffa-cartridge.jpg)

土台にしたバージョンでは、ゆめの木での願いごとと、新しい仲間をゲームに送る機能が未実装とされていました。以前から、ゲームシンクで出会いのデータを受け取り、森で捕まえることに成功した開発者の記録はあります。2026 年 11 月 20 日までに確認した公開資料では、復元したウェブサイトで仲良くなり、願いごとをして、実機で捕獲するまでを示した、これより早い記録は見つかっていません。世界初かどうかは不明です。[元のバージョンの実装状況](https://github.com/minibug1021/dreamworld-reawakened/blob/77174d2f3084b83b80544161dca8ad2d325654b8/readme.md#things-that-are-not-working) · [2023 年のゲームシンク開発記録](https://github.com/mm201/pkmn-classic-framework/issues/8#issuecomment-1552963901)

## Windowsでサーバーを起動する

ディスクに **6 GB 以上の空き容量**を用意してください。元のウェブサイトのミラーだけで展開後約 3.8 GiB あります。初回は、この版が使う上流のソースと素材をダウンロードしてゲーム用のファイルを準備します。ミラーのダウンロードと展開には時間がかかるため、`Ready at` の表示を待ってから次に進みます。該当バージョンのアーカイブを持っている場合は、`setup.py` の `--assets-archive` に GitHub のウェブ素材の `.tar.gz`、`--ruffle-archive` に Ruffle のセルフホスト版 `.zip` のパスを指定できます。

Windows PC、DS シリーズの本体、Cギアを入手済みの第五世代のセーブデータを用意します。PC と DS は互いに通信できる同じローカルネットワークに接続してください。Git、Python 3.11 以降、uv をインストールします。PowerShell を開き、以下のコマンドを順に実行してください。すでにリポジトリをダウンロードして展開した場合は、`setup.py` があるフォルダーで PowerShell を開き、3 行目から実行します。[Git のダウンロード](https://git-scm.com/downloads/win) · [Python のダウンロード](https://www.python.org/downloads/windows/) · [uv のインストール](https://docs.astral.sh/uv/getting-started/installation/)

```powershell
git clone https://github.com/goiku/dreamworld-cartridge.git
cd dreamworld-cartridge
python setup.py
cd runtime
uv sync --frozen
uv run --frozen python launch_windows.py --lan
```

Windows の Python ランチャーを使う場合は、`python setup.py` の代わりに `py -3 setup.py` を実行します。プレイ中はサーバーのウィンドウを開いたままにします。DS に設定する `Game Sync address` と、各言語のウェブサイトのアドレスが表示されます。英語版はポート 8080、日本語版は 8081、簡体字中国語版は 8088 です。[このPCの日本語版ホームページ](http://127.0.0.1:8081/)

## 新しい仲間をゲームカードに連れて帰る

1. **ゲームカードを接続する。** ゲームが使う Wi-Fi 接続設定を開き、プライマリ DNS に、PC の `Game Sync address` に表示されたローカル IPv4 アドレスを入力します。Cギア下画面の **「Wi-Fi」→「ゲームシンク」** を選び、ポケモンを 1 匹寝かせて、通信完了の表示を待ちます。ゲームシンクIDコードはゲームのメインメニューの「ゲームシンク設定」で確認できます。
2. **セーブデータを登録する。** PC でローカルのホームページを開き、このサーバー用のアカウントを作成します。ログインして、先ほどのゲームシンクIDコードを登録します。有効化を求められた場合は、サーバー管理者が `runtime` フォルダーでもう一つ PowerShell を開き、下に示す有効化コマンドの `PlayerName` を登録したユーザー名に置き換えて実行します。管理者はメールの設定を省略し、PC 上でアカウントを有効にできます。
3. **ウェブで仲良くなる。** ドリームワールドに入り、虹の橋を渡ります。出会ったポケモンのミニゲームをクリアし、ゆめの木できのみを 1 個お供えして、連れて帰りたい仲間を選びます。初回には同じ種類のきのみを 5 個もらえます。
4. **起こす準備をする。** ウェブで自分のホームに戻り、右上の電源ボタンを押します。ポケモンを起こす準備をして終了する方を選び、連れて帰る仲間を確認して終了します。
5. **ゲームで捕まえる。** DS で再び **「Wi-Fi」→「ゲームシンク」** を選び、寝かせたポケモンを起こします。通信完了後、Cギアの **「WIRELESS」→「ハイリンク」** でハイリンクへ移動します。北へ進み、「ハイリンクの森」で仲間に話しかけると捕獲できます。

```powershell
uv run --frozen python -m scripts.activate_account PlayerName
```

ウェブサイトで ID が見つからない場合は、**今使っているサーバー**にそのゲームカードから初回の同期が完了しているか、ゲームシンクIDコードを正しく入力したかを確認します。ともだちコードは対戦・交換に使う別の番号です。通信が途切れた場合は、同じサーバーとセーブデータのまま本体の表示に従い、再びゲームシンクで状態を確認してください。

## 別のネットワークにいる友だちと遊ぶ

それぞれのプレイヤーが、手元の DS と同じローカルネットワークに接続した Windows PC を 1 台ずつ用意します。2 台の PC は同じ Tailscale プライベートネットワークに参加し、DS はそれぞれの Wi-Fi に接続したままにします。中継プログラムは模擬端末による通信でテスト済みです。異なるネットワーク上の実機 2 台で対戦・交換を最後まで行う試験は未実施です。[Tailscale の接続ガイド](https://tailscale.com/docs/how-to/connect-to-devices)

以下は、**互いに独立した**二つの家庭内ネットワークで、それぞれの PC に同じ空き LAN アドレスを予約する例です。例のアドレスを実際の値に置き換えます。各 PC の Tailscale アドレスは `tailscale ip -4` で確認でき、`tailscale ping` の後に相手のアドレスを指定すれば疎通を確認できます。

| アドレス | ホスト | 友だち |
| --- | --- | --- |
| PC の Tailscale アドレス | 100.64.10.1 | 100.64.10.2 |
| PC の自宅 LAN アドレス | 192.168.50.20 | 192.168.50.20 |
| DS の自宅 LAN アドレス | 192.168.50.31 | 192.168.50.32 |

進行中のゲームシンクが完了したら、Ctrl+C で LAN モードを停止します。ホストの PC で配布フォルダーから PowerShell を開き、サーバーをローカルモードで起動します。

```powershell
$env:DW_RELAY_STATE = Join-Path (Get-Location) "tools\DreamWorld-VPN-state.json"
cd runtime
uv run --frozen python launch_windows.py
```

配布フォルダーで PowerShell を個別に開きます。コマンド **1** はホスト PC で中継の中心を起動し、**2** は同じ PC の別ウィンドウで手元の DS を接続します。**3** は友だちの PC で実行します。友だちの PC にもこのリポジトリのコピーと uv が必要です。`--relay-ip` には 3 回とも同じ値を使います。このアドレスは両方の PC でそれぞれ DS 側のネットワークに割り当てられ、その DS から到達できる必要があります。

```powershell
# 1
uv run tools/DreamWorld-VPN.py host --bind 100.64.10.1 --peer 100.64.10.1 --peer 100.64.10.2 --relay-ip 192.168.50.20
# 2
uv run tools/DreamWorld-VPN.py gateway --bind 192.168.50.20 --peer 192.168.50.31 --host 100.64.10.1 --tailscale-ip 100.64.10.1 --relay-ip 192.168.50.20 --no-web
# 3
uv run tools/DreamWorld-VPN.py gateway --bind 192.168.50.20 --peer 192.168.50.32 --host 100.64.10.1 --tailscale-ip 100.64.10.2 --relay-ip 192.168.50.20
```

両側のゲートウェイに `Battle hub confirmed the connection` と表示されたら、それぞれの DS のプライマリ DNS を**同じ家にある PC の LAN アドレス**に設定します。ウェブは各自の PC で開き、自分のアカウントでログインします。フレンド対戦・交換はお互いのともだちコードを登録し、ポケモンセンターの Wi-Fi クラブに入ります。通常の GTS 交換では、一人がポケモンを預け、もう一人が検索して交換したら、預けた側が GTS に入り直して受け取ります。中継の単体テストは配布フォルダーから `uv run tools/DreamWorld-VPN.py self-test` で実行できます。

## 開発元と変更点

実機のゲームカードでピィを捕まえたのは goiku です。本復元版のソースコードの変更、ローカライズ、テストには OpenAI Codex が協力しました。

インストール後は、一時的なテスト用セーブデータで、願いごとからゲームカードへのダウンロードまでを確認できます。配布フォルダーで `runtime\.venv\Scripts\python.exe tools/check-cartridge.py runtime` を実行し、`PASS` と表示されれば成功です。[ゲームカード用テストのソースコード](../tools/check-cartridge.py)

[ウェブサイトのソース差分](../source/web.patch)と[ゲームシンクのソース差分](../source/game-sync.patch)で実装を確認できます。

原作のイラスト、音楽、Flash ミニゲームはポケモンの作品です。有志による復元プロジェクトがウェブ資産を保存し、サーバーとゲームシンクを開発しました。ブラウザーでの Flash の再生には Ruffle を利用しています。[Dream World Reawakened](https://github.com/minibug1021/dreamworld-reawakened) · [game-sync-python](https://github.com/minibug1021/game-sync-python) · [Entralinked](https://github.com/kuroppoi/entralinked) · [dreamworld-assets](https://github.com/minibug1021/dreamworld-assets) · [Ruffle](https://ruffle.rs/)

この版では、ゆめの木で願いごとをして、新しい仲間をゲームに送るところまで動作します。起こす途中で通信が切れても選択した仲間は保持されます。「ひんやり穴」で光るアイテムを拾う操作も修正しました。日本語版を基にした簡体字中国語の画面には、既存のポケモン用語、機械翻訳、校訂したテキストを使用しています。通常の GTS、フレンドルーム、プライベートネットワーク経由の中継機能も組み込んでいます。
