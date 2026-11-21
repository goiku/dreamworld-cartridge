"""Display an empty report when there is no published season or tournament."""
import json

MESSAGES = {
    "zh": ("本服还没有排位赛季。掌机的排位战绩尚未接入。", "本服还没有已发布成绩的 Wi-Fi 大会。"),
    "ja": ("現在、このサーバーにはレーティングシーズンがありません。ゲーム機からの対戦成績の受信は未対応です。", "このサーバーでは、Wi-Fi大会の結果はまだ公開されていません。"),
    "en": ("There are no ranked seasons on this server yet. Ranked results from game systems are not yet supported.", "No Wi-Fi Competition results have been published on this server yet."),
    "fr": ("Aucune saison classée pour le moment. Ce serveur ne reçoit pas encore les résultats des combats classés sur console.", "Ce serveur n’a encore publié aucun résultat de tournoi Wi-Fi."),
    "it": ("Non ci sono ancora stagioni di lotte a punteggio. Il server non riceve ancora i risultati dalla console.", "Il server non ha ancora pubblicato risultati di gare Wi-Fi."),
    "de": ("Auf diesem Server gibt es noch keine Ranglistensaison. Ergebnisse von Ranglistenkämpfen auf dem Nintendo DS werden noch nicht erfasst.", "Auf diesem Server wurden noch keine Ergebnisse von Wi-Fi-Turnieren veröffentlicht."),
    "es": ("Todavía no hay temporadas de combates por puntos. El servidor aún no recibe los resultados de la consola.", "Todavía no se han publicado resultados de torneos Wi-Fi en este servidor."),
    "ko": ("아직 이 서버에는 레이팅 시즌이 없습니다. 게임기에서 레이팅배틀 결과를 받는 기능은 아직 지원하지 않습니다.", "이 서버에는 아직 공개된 Wi-Fi 대회 결과가 없습니다."),
}


def patch_report(data: bytes, language: str) -> bytes:
    season, competition = (json.dumps(message).encode() for message in MESSAGES[language])
    # Keep the archived sections intact so reports with data retain their usual layout.
    helper = b"""
function setReportNotice(section, message) {
  if (!document.getElementById('report-notice-style')) {
    $('<style id="report-notice-style">.report-has-notice > :not(.report-notice){display:none!important}.report-notice{margin:0;padding:48px 32px;background:white;color:#333;text-align:center;font-size:16px;line-height:1.6}</style>').appendTo('head');
  }
  var host = $(section).toggleClass('report-has-notice', !!message);
  host.children('.report-notice').remove();
  if (message) $('<p class="report-notice" role="status"></p>').text(message).appendTo(host);
}
"""
    data = data.replace(b"$('#gbu').show();", b"$('#gbu').show();\n"
                        b"      setReportNotice('#gbu', this.seasons.length ? null : " + season + b");\n"
                        b"      if (!this.seasons.length) return;")
    data = data.replace(b"if (!self.last_wifi_comp) {",
                        b"setReportNotice('#wifi-competitions', data.length ? null : " + competition + b");\n"
                        b"        if (!data.length) return;\n        if (!self.last_wifi_comp) {")
    data = data.replace(b"if (!disableAutoNavigation) {",
                        b"if (!disableAutoNavigation && !$('.report-notice:visible').length) {")
    data = data.replace(b"if (always || !target.isLooking()) {",
                        b"var notice = $('.report-notice:visible');\n"
                        b"        if (notice.length) target = notice;\n        if (always || !target.isLooking()) {")
    data = data.replace(b"states.subtype = validate(path[2], ['', 'ranking', 'trend']);",
                        b"states.subtype = this.seasons.length ? validate(path[2], ['', 'ranking', 'trend']) : '';")
    return helper + data
