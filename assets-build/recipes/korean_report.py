from pathlib import Path
import os
import re

assets = Path(os.environ["DW_BUILD_ROOT"])/"dreamworld_assets"
ja = (assets / "ja.pokemon-gl.com/report/index.html").read_text(encoding="utf8")
ko = (assets / "ko.pokemon-gl.com/profile/index.html").read_text(encoding="utf8")
before, footer = ja.split('    <div id="footer">')
head, rest = before.split('    <div id="header">')
header, main = rest.split('    <div id="main">')
header = ko.split('    <div id="header">')[1].split('    <div id="main">')[0]
footer = ko.split('    <div id="footer">')[1]
head = head.replace("<html>", '<html lang="ko">').replace("/ja/", "/ko/")
head = re.sub(r'  <script type="text/javascript">\s*var _gaq\b.*?</script>\n', '', head, flags=re.S)
labels = dict(line.split("|") for line in """レポート|리포트
Wi-Fi大会|Wi-Fi 대회
ゲームシンク調査隊|게임싱크 조사대
更新|업데이트
GTSランキング|GTS 랭킹
ポケモン情報|포켓몬 정보
地域情報|지역 정보
？|?
ニックネーム|닉네임
せいかく|성격
親|어버이
住んでいるところ|사는 곳
GTSにあずけた日時|GTS에 맡긴 일시
ポケモンたちが旅した距離は|포켓몬이 여행한 거리
地球|지구
周分|바퀴
GTSにあずけられているポケモンの数|현재 GTS에 맡겨진 포켓몬 수
これまでにトレードされたポケモンの数|지금까지 교환된 포켓몬 수
トレードの多いポケモン トップ30|많이 교환된 포켓몬 TOP 30
希望の多いポケモン トップ30|가장 많이 찾는 포켓몬 TOP 30
あずけられている数の多いポケモン トップ30|가장 많이 맡겨진 포켓몬 TOP 30
Topへ戻る|처음으로 돌아가기
ポケモンを選ぶ|포켓몬 선택
タイプ|타입
たかさ|키
おもさ|몸무게
GTSにあずけられている|GTS에 맡겨진
の数|의 수
ポケモントレード トップ10|포켓몬 교환 TOP 10
切り替え|전환
このポケモンと今までにトレードされたポケモン|지금까지 이 포켓몬과 교환된 포켓몬
このポケモンをほしい人があずけているポケモン|이 포켓몬을 원하는 사람이 맡긴 포켓몬
ブックマークに追加する|즐겨찾기에 추가
ブックマークから削除する|즐겨찾기에서 삭제
地域を選ぶ|지역 선택
首都|수도
面積|면적
人口|인구
人|명
インターネット人口|인터넷 이용자 수
観光客数|관광객 수
プレイしているゲームソフト|플레이 중인 게임 소프트웨어
GTS情報を見る|GTS 정보 보기
調査隊情報を見る|조사대 정보 보기
GTS参加人数|GTS 참가자 수
GTSにあずけているポケモンの数|GTS에 맡긴 포켓몬 수
トレードされたポケモン トップ5|많이 교환된 포켓몬 TOP 5
この地域からGTSにあずけられているポケモン|이 지역에서 GTS에 맡긴 포켓몬
位|위
この地域でねむっているポケモン トップ3|이 지역에서 가장 많이 잠든 포켓몬 TOP 3
GBUランキング|GBU 랭킹
レーティング|레이팅
ランキング|랭킹
トレーナー名|트레이너 이름
対戦ルールごとのランキング|대전 룰별 랭킹
ランキングについてくわしくはこちら|랭킹에 대한 자세한 설명
シーズンを選択|시즌 선택
地域で絞り込む|지역별로 보기
総合|종합
シングル|싱글
ダブル|더블
トリプル|트리플
シューター|슈터
ローテーション|로테이션
前へ|이전
次へ|다음
自分の順位を見る|내 순위 보기
あなたの対戦成績を見る|내 대전 성적 보기
よく手持ちに入れられているポケモン|배틀에 자주 참가하는 포켓몬
閉じる|닫기
と一緒によく手持ちに入れられているポケモン|와 함께 자주 배틀에 참가하는 포켓몬
過去の大会一覧|지난 대회 목록
Wi-Fi大会一覧へ|Wi-Fi 대회 목록으로
大会の情報|대회 정보
開催期間|개최 기간
対戦ルール|대전 룰
大会概要|대회 개요
使用ゲームソフト|사용하는 게임 소프트웨어
参加者数|참가자 수
重要事項/レギュレーション (PDF)|중요 사항 및 대회 규정 (PDF)
開催地域の一覧|개최 지역 목록
強かったプレイヤーが手持ちに入れていたポケモン トップ10|상위권 트레이너가 사용한 포켓몬 TOP 10
と一緒によく手持ちに入れられていたポケモン|와 함께 자주 배틀에 참가한 포켓몬
のトレンド|의 배틀 경향
わざ|기술
とくせい|특성
もちもの|지닌물건
この地域でいちばんねむっているポケモン|이 지역에서 가장 많이 잠든 포켓몬
この地域の情報をもっとみる|이 지역의 정보 더 보기
なまえ順で選ぶ|이름순으로 선택
ずかん番号順で選ぶ|도감 번호순으로 선택
ブックマークから選ぶ|즐겨찾기에서 선택
表示できるデータがありません。|표시할 수 있는 데이터가 없습니다.
トレーナー名：|트레이너 이름:
レーティング：|레이팅:
さんの対戦成績|님의 대전 성적
総合ランキング|종합 랭킹
勝敗数|승패 수
勝|승
敗|패""".splitlines())
seen=set()
def translate(match):
    key = match[2]
    if key in labels:
        seen.add(key)
        return match[1] + labels[key] + match[3]
    assert not re.search('[ぁ-ヿ一-鿿]',key), key
    return match[0]
words = re.split(r'(<[^>]+>)',main)
for index in range(0,len(words),2):
    words[index] = re.sub(r'^(\s*)(.*?)(\s*)$', translate, words[index], flags=re.S)
assert seen==set(labels),set(labels)-seen
main = ''.join(words).replace('와 함께 자주', '와(과) 함께 자주')
main = main.replace('GTS에 맡겨진<span', 'GTS에 맡겨진 <span')
path = assets / "ko.pokemon-gl.com/report/index.html"
path.parent.mkdir(exist_ok=True)
path.write_text(head+'    <div id="header">'+header+'    <div id="main">'+main+'    <div id="footer">'+footer,encoding="utf8")
