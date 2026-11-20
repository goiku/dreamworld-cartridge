"use strict";
const stage = document.getElementById("stage");
const message = document.getElementById("status");
window.practiceStatus = function (state) {
    message.textContent = {playing: "", finished: message.dataset.finished, error: message.dataset.error}[state];
};
async function startPractice() {
    try {
        const player = window.RufflePlayer.newest().createPlayer();
        stage.append(player);
        await player.ruffle().load({
            // The two café games resolve their component movies from the stage URL.
            url: "/practice/pdw/assets/game/player.swf",
            parameters: {game: stage.dataset.game, lang: stage.dataset.lang, buddy: stage.dataset.buddy},
            allowScriptAccess: true, autoplay: "on", unmuteOverlay: "visible",
            backgroundColor: "#f6f6ed", scale: "showAll"
        });
    } catch (error) {
        window.practiceStatus("error");
    }
}
window.addEventListener("load", startPractice, {once:true});
