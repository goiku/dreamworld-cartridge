"""Build Chinese help images at the original URLs and sizes used by the Dream World client."""
import html
import json
from pathlib import Path
import re
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageOps
from game_art_zh import BROWN, base, lettering

PDW = Path("src/swf/pdw/assets/ja")
SOURCE = base/"ja.pokemon-gl.com"/PDW
TARGET = base/"zh.pokemon-gl.com"/PDW
CAPTIONS = json.loads(Path(__file__).with_name("tutorial-steps-zh.json").read_text("utf-8-sig"))
BADGES = {
    "footprint_ds":"掌机好友", "footprint_gts":"认识的人", "footprint_invite":"好友申请",
    "footprint_pdw":"梦友", "world_0":"梦友", "news_01":"脚印", "news_02":"树果田",
    "news_03":"分享架", "news_04":"梦友", "news_05":"梦境目录", "news_06":"特别小屋",
    "board_01":"标有蓝色圆点的宝可梦\n会被送往连入之森。",
    "board_01_trial":"登记游戏同步 ID 后，\n就可以把伙伴送回自己的卡带。",
}


def tutorial_pictures():
    directory = TARGET/"img"
    directory.mkdir(parents=True, exist_ok=True)
    for chapter, steps in CAPTIONS.items():
        pictures = sorted((SOURCE/"img").glob(f"tutorial{chapter}-*.jpg"))
        for picture, caption in zip(pictures, steps, strict=True):
            for path in (picture, picture.with_suffix(".png")):
                if not path.is_file():
                    continue
                with Image.open(path) as original:
                    w,h = original.size
                    bar_height = max(20, h//8)
                    result = Image.new("RGB", (w,h), "#fffdf3")
                    inset = ImageOps.contain(original.convert("RGB"), (w,h-bar_height), Image.Resampling.LANCZOS)
                    result.paste(inset, ((w-inset.width)//2,0))
                    ImageDraw.Draw(result).line((0,h-bar_height,w,h-bar_height), fill="#c4b389")
                    lettering(result,(2,h-bar_height+1,w-2,h),caption,maximum=max(12,h//14))
                    result.save(directory/path.name,quality=93,subsampling=0)

    for name in ("catalog_01", "catalog_01_s", "takarabako_1", "takarabako_2"):
        with Image.open(SOURCE/"img"/(name+".png")) as source:
            im = source.convert("RGBA")
        w,h = im.size
        if name.startswith("catalog"):
            lettering(im,(w//5,h//3,w-w//5,h-h//3),"新",fill="white",background="#d5250e")
        else:
            words = "和森林里的服务员对话领取道具" if name.endswith("1") else "点右上角电源按钮，准备唤醒"
            lettering(im,(1,h-25,w-1,h-1),words,background="#fffbed",maximum=13)
        im.save(directory/(name+".png"))

    texts = {el.get("id"): el.text for el in ElementTree.parse(TARGET/"xml/tutorial_strings.xml").iter("string")}
    for path in (SOURCE/"img").glob("*.png"):
        key = path.stem
        if key not in BADGES and key not in texts:
            continue
        im = Image.open(path).convert("RGBA")
        w,h = im.size
        if key in texts and key not in BADGES:
            label = html.unescape(re.sub("<[^>]+>","",texts[key]))
            im = Image.new("RGBA",im.size)
            lettering(im,(0,0,w,h),label,maximum=22)
        elif key.startswith("board_"):
            im = Image.new("RGBA",im.size)
            lettering(im,(0,0,w,h),BADGES[key],fill="white",outline=BROWN)
        else:
            # Keep the transparent border, ribbon ends and speech tail. Only clear its printed face.
            box = (max(2,w//9),1,w-max(2,w//9),h-5 if key=="world_0" else h-1)
            background = im.getpixel((box[0],h//2))
            lettering(im,box,BADGES[key],background=background,fill=BROWN if key.startswith("news_") else "white")
        im.save(directory/path.name)


def format_text():
    translations = {el.get("id"):el.text for el in ElementTree.parse(TARGET/"xml/at_01_pdw_strings.xml").iter("string")}
    translations["h_ha_2"] = "小卡比兽它们出现了。"
    for name in ("at_01_pdw_format.xml", "backup_at_01_pdw_format.xml"):
        tree = ElementTree.parse(SOURCE/"xml"/name)
        for el in tree.iter("string"):
            if re.search("[ぁ-ヿ]",el.text or ""):
                el.text = translations[el.attrib["id"]]
        tree.write(TARGET/"xml"/name,encoding="utf-8",xml_declaration=True)


if __name__ == "__main__":
    tutorial_pictures()
    format_text()
