package {
    import flash.display.DisplayObject;
    import flash.display.Loader;
    import flash.display.MovieClip;
    import flash.events.Event;
    import flash.events.IOErrorEvent;
    import flash.external.ExternalInterface;
    import flash.geom.PerspectiveProjection;
    import flash.net.URLRequest;
    import flash.utils.getDefinitionByName;

    // Runs in a new movie per visit. The only inputs come from the practice page.
    public class Practice extends MovieClip {
        private var bridge:Object;
        private var pokemon:Object;
        private var chest:Object;
        private var course:Object;
        private var fonts:Loader;
        private var game:Loader;
        private var number:int;
        private var language:String;
        private const common:String = "/src/swf/theme/assets/common/";
        private const assets:String = "/src/swf/pdw/assets/";

        public function Practice() {
            super();
            stop();
            addEventListener(Event.ADDED_TO_STAGE, begin);
            if (stage) begin(null);
        }

        private function begin(event:Event):void {
            removeEventListener(Event.ADDED_TO_STAGE, begin);
            addEventListener(Event.ADDED, prepareRoot, true);
            stage.addEventListener(Event.ADDED_TO_STAGE, prepareRoot, true, 1000);
            number = int(loaderInfo.parameters.game);
            language = String(loaderInfo.parameters.lang);
            if (number < 1 || number > 12 || "|ja|en|fr|it|de|es|ko|".indexOf("|"+language+"|") < 0) return;
            bridge = getDefinitionByName("common.gameBridge");
            pokemon = getDefinitionByName("bfp.common.PokemonBridge");
            chest = getDefinitionByName("bfp.chest.chestBridge");
            pokemon["lang"] = language;
            pokemon["PATH"] = common;
            pokemon["rootMC"] = this;
            pokemon["POKEMONPATH"] = "/src/swf/theme/assets/global/parts/pokemon/scaled";
            pokemon["POKEMONPATH2"] = "/src/swf/theme/assets/global/parts/pokemon/scaled2";
            bridge["myPokemonId"] = number == 6 ? 643 : 25;
            bridge["myFormId"] = 0;
            bridge["encountPokemonId"] = number == 6 ? 494 : 173;
            bridge["encountFormId"] = 0;
            bridge["encountPokemonName"] = String(loaderInfo.parameters.buddy);
            bridge["romID"] = 21;
            bridge["areaNo"] = 3;
            bridge["langCode"] = language;
            bridge["pauseFlag"] = false;
            bridge["addEventListener"]("closeGame", finished);
            bridge["addEventListener"]("finishGame", finished);
            chest["addEventListener"]("open_chest", practiceBerry);
            fonts = new Loader();
            fonts.contentLoaderInfo.addEventListener(Event.COMPLETE, fontReady);
            fonts.contentLoaderInfo.addEventListener(IOErrorEvent.IO_ERROR, failed);
            fonts.load(new URLRequest(common + "font.swf"));
        }

        private function practiceBerry(event:Event):void {
            chest["selectedItemData"] = {pokeitem_id:155, item_cnt:1};
            chest["dispatchEvent"](new Event("selected_yes"));
        }

        private function prepareRoot(event:Event):void {
            var child:DisplayObject = event.target as DisplayObject;
            if (child && child.root && !child.root.transform.perspectiveProjection)
                child.root.transform.perspectiveProjection = new PerspectiveProjection();
        }

        private function fontReady(event:Event):void {
            var font:Object = getDefinitionByName("bfp.common.FontManager");
            font["init"]();
            pokemon["addEventListener"]("RENDER_LOADED", ready);
            pokemon["standalone"](common + "poke.swf");
        }

        private function ready(event:Event):void {
            pokemon["removeEventListener"]("RENDER_LOADED", ready);
            if (number == 1) {
                var builder:Class = getDefinitionByName("bfp.pdw.yumeshima.buildBg") as Class;
                course = new builder();
                course["areaNo"] = 3;
                course["addEventListener"]("initialized", loadGame);
                course["create"](assets + "area/template3.swf");
            } else {
                loadGame(null);
            }
        }

        private function loadGame(event:Event):void {
            if (course) bridge["courseData"] = course["courseDataMain"]["mainDataArray"];
            var suffix:String = number == 4 ? "." + language : "";
            game = new Loader();
            game.contentLoaderInfo.addEventListener(IOErrorEvent.IO_ERROR, failed);
            game.contentLoaderInfo.addEventListener(Event.COMPLETE, showGame);
            game.load(new URLRequest(assets + "game/game" + number + suffix + ".swf"));
            addChild(game);
        }

        private function showGame(event:Event):void {
            game.content.transform.perspectiveProjection = new PerspectiveProjection();
            if (number == 5 || number == 11)
                addEventListener(Event.ENTER_FRAME, startCafe);
            if (ExternalInterface.available) ExternalInterface.call("practiceStatus", "playing");
        }

        // A fully cached load can signal completion before the café's first-frame
        // script calls stop(). Resume once that frame has initialized its text area.
        private function startCafe(event:Event):void {
            var movie:MovieClip = game.content as MovieClip;
            if (movie.currentFrame == 1) {
                if (movie.framesLoaded < 2 || !movie["_textArea"] || !movie["_textArea"]["text"].length) return;
                movie.gotoAndPlay(2);
            }
            removeEventListener(Event.ENTER_FRAME, startCafe);
        }

        private function finished(event:Event):void {
            if (ExternalInterface.available) ExternalInterface.call("practiceStatus", "finished");
        }

        private function failed(event:Event):void {
            if (ExternalInterface.available) ExternalInterface.call("practiceStatus", "error");
        }
    }
}
