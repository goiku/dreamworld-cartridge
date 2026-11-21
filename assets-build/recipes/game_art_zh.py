"""Replace lettering baked into the Japanese game artwork. Coordinates are in original pixels."""
from functools import lru_cache
from io import BytesIO
import os
from pathlib import Path
import struct
import zlib

from PIL import Image, ImageDraw, ImageFont
from swfone import base, basegame, payload_offset, tags, unpack
from swf_font import tag, u16


LABELS = {
    "game1/game.swf": {
        42:"游", 33:"戏", 45:"时", 36:"间", 39:"到", 48:"了",
        67:"读取中", 248:"发现树果！",
    },
    "game2.swf": {50:"通信中", 261:"时间到！"},
    "game3.swf": {
        37:"时间到！", 135:"读取中", 150:"通信中", 155:"到达终点！", 175:"加速！",
        191:"分", 208:"分", 226:"+450", 229:"+1500", 366:"↓ 减速！",
        462:"和宝可梦一起飞向天空！", 479:"查看玩法", 501:"开始游戏",
        605:"真可惜！", 606:"没能在时间内到达终点",
    },
    "game4.ja.swf": {
        73:"正在读取…", 76:"通信中", 85:"得分倍率提升！", 210:"分", 211:"得分",
        216:"剩余时间", 236:"得分倍率降低！", 526:"挑战失败", 540:"游戏结束",
        542:"彩球计数", 545:"连击奖励", 548:"无失误奖励", 551:"击破的彩球",
        554:"合计", 557:"个", 560:"分", 563:"倍", 569:"总得分", 572:"分", 575:"最高",
        578:"次", 581:"得分", 618:"时间到！",
    },
    "game5.swf": {16:"游戏结束"},
    "game6.swf": {412:"游戏结束"},
    "game8.swf": {
        130:"读取中", 153:"通信中", 183:"终点", 353:"和勾魂眼一起收集宝石！",
        371:"查看玩法", 393:"开始游戏", 417:"玩法说明", 443:"宝石", 458:"高山植物",
        597:"出发！", 610:"终点！", 722:"到达终点！", 738:"时间到！",
        793:"真可惜！\n没能到达终点",
    },
    "game9.swf": {250:"开始！"},
    "game9/game.swf": {250:"开始！"},
    "game11.swf": {22:"游戏结束"},
    "game12.swf": {424:"游戏结束"},
}
BROWN = "#633e25"
PAPER = "#f5efd9"
BLUE = "#087bb1"
CLEAR = (0, 0, 0, 0)


@lru_cache(maxsize=200)
def face(size):
    font = ImageFont.truetype(os.environ["DW_BUILD_FONT"], size)
    font.set_variation_by_axes([680])
    return font


def lettering(im, box, words, *, fill=BROWN, outline=None, background=None, maximum=84):
    left, top, right, bottom = box
    if background is not None:
        im.paste(background, box)
    draw = ImageDraw.Draw(im)
    for size in range(min(maximum, bottom-top), 0, -1):
        width = max(1, size//16) if outline else 0
        font = face(size)
        spacing = max(1, size//6)
        a,b,c,d = draw.multiline_textbbox((0,0), words, font=font, spacing=spacing, align="center", stroke_width=width)
        if c-a <= right-left-2 and d-b <= bottom-top-2:
            break
    pos = ((left+right-c-a)//2, (top+bottom-b-d)//2)
    draw.multiline_text(pos, words, font=font, fill=fill, stroke_width=width,
                        stroke_fill=outline, spacing=spacing, align="center")


def decode(kind, data):
    if kind in (21, 35):
        start = 6 if kind == 35 else 2
        im = Image.open(BytesIO(data[start:])).convert("RGBA")
        if kind == 35:
            alpha = zlib.decompress(data[start + int.from_bytes(data[2:6], "little"):])
            im.putalpha(Image.frombytes("L", im.size, alpha))
        return im
    size = struct.unpack_from("<HH", data, 3)
    pixels = zlib.decompress(data[7:] if data[2] == 5 else data[8:])
    if data[2] == 5:
        return Image.frombytes("RGBa", size, pixels, "raw", "aRGB").convert("RGBA")
    if data[2] != 3:
        raise ValueError("Unexpected bitmap encoding")
    count = data[7]+1
    palette = Image.frombytes("RGBa", (count,1), pixels[:4*count]).convert("RGBA")
    indexed = Image.frombytes("P", size, pixels[4*count:], "raw", "P", (size[0]+3)&~3, 1)
    indexed.putpalette(palette.convert("RGB").tobytes())
    indexed.info["transparency"] = palette.getchannel("A").tobytes()
    return indexed.convert("RGBA")


def encode(ident, im):
    r,g,b,a = im.convert("RGBa").split()
    words = Image.merge("RGBA", (a,r,g,b)).tobytes()
    return struct.pack("<HBHH", ident, 5, *im.size) + zlib.compress(words, 9)


def special_game_image(movie, ident, im):
    w,h = im.size
    if movie == "game1/game.swf":
        if ident == 117:
            lettering(im,(88,0,274,31),"玩法说明",background=CLEAR)
            for y,words in [(47,"点击摇晃的草丛或树木，\n看看里面藏着什么。"),
                            (106,"仔细听，如果听到叫声，\n迷路的宝可梦就在附近。"),
                            (165,"找到掉落的东西后，\n仔细搜索周围。")]:
                lettering(im,(83,y,349,y+44),words,background=PAPER)
            lettering(im,(26,119,64,144),"仔细听",fill="white",background="#ef9900")
        elif ident in (390,392,394):
            # Preserve each hover/pressed ring and replace its central lettering.
            color=im.getpixel((w//2, h//4))
            lettering(im,(15,23,w-15,h-23),"仔细\n听",fill="white",background=color)
    if movie == "game4.ja.swf":
        if ident == 197:
            for box,words in [((42,63,164,85),"目标数量"),((42,166,168,187),"彩球计数")]:
                lettering(im,box,words,background="#bf956d",fill="#442512",maximum=16)
            lettering(im,(38,396,92,417),"倍率",background=BROWN,fill="#ffce78",maximum=15)
        elif ident == 603:
            lettering(im,(0,0,w,88),"和吼鲸王一起玩！\n借助水柱跳起来，击破彩球。",fill="#df682f",outline="white",background=CLEAR)
        elif ident in (623,625,627,629):
            lettering(im,(19,65,w-19,84),"击中它！",fill=BLUE,background="#fff9e9")
        elif ident == 636:
            lettering(im,(16,16,w-16,h-16),"点击鼠标\n喷出水柱",fill=BLUE,background="#fff9e9")
    if movie == "game3.swf":
        if ident == 238:
            lettering(im,(0,0,w,92),"和会飞的宝可梦一起玩吧！\n移动手旗，引导宝可梦尽快到达终点。",fill=BROWN,background=CLEAR)
            for box,label in [((112,96,356,204),"手旗\n宝可梦会跟着手旗飞。\n移动鼠标，引导它飞向终点。"),
                              ((466,96,758,204),"云朵\n撞到云朵会减速，\n要提早绕开！"),
                              ((133,214,380,326),"同属性标记\n收集与宝可梦属性相同的标记。\n连续集齐三个可以加速！"),
                              ((479,214,758,326),"弱点属性标记\n碰到弱点属性会减速，\n还可能暂时无法移动。")]:
                lettering(im,box,label,fill=BROWN,background=CLEAR,maximum=19)
        elif ident == 253:
            lettering(im,(104,0,w,h),"遇见的宝可梦",fill="#ca6a00",background="white")
        elif ident == 254:
            # Retain the annotated course and arrows. Redraw its labels, including the pictured HUD.
            for box,label in [((0,0,151,22),"剩余时间"),((0,23,106,96),"时间用完前\n飞到终点！"),
                              ((512,0,750,46),"得分栏\n显示当前得分"),((630,89,752,119),"空格键"),
                              ((629,122,789,211),"想中途暂停时，\n按键盘空格键。"),((631,228,774,255),"你的宝可梦"),
                              ((632,258,788,287),"遇见的宝可梦"),((0,282,105,319),"剩余距离"),
                              ((0,318,161,352),"降到零即到达终点"),((234,310,362,352),"速度栏\n尽量达到最高速度"),
                              ((418,309,658,352),"能量栏\n集齐三个标记即可加速")]:
                lettering(im,box,label,fill="#cc7400",background=CLEAR,maximum=17)
            for box,label in [((230,54,321,69),"时间  01:22"),((337,54,427,69),"得分  600"),
                              ((436,54,493,68),"空格暂停"),((130,275,170,290),"剩余距离"),((239,275,279,290),"速度")]:
                lettering(im,box,label,fill="white",background="#57452f",maximum=12)


SPECIAL = {"game1/game.swf": {117,390,392,394}, "game3.swf": {238,253,254},
           "game4.ja.swf": {197,603,623,625,627,629,636}}


def translate_art(movie, blob):
    raw = unpack(blob)
    start = payload_offset(raw)
    out = bytearray(raw[:start])
    pending = set(LABELS[movie]) | SPECIAL.get(movie,set())
    from game_shapes_zh import WORDS, LAYOUTS, shape_tags
    shapes = set(WORDS.get(movie, {})) | LAYOUTS.get(movie,set())
    parts = list(tags(raw,start))
    used_ids = {u16(data) for kind,data in parts if len(data)>=2}
    bitmap_ids = (i for i in range(60000,65535) if i not in used_ids)
    images = {u16(data):decode(kind,data) for kind,data in parts
              if movie=="game4.ja.swf" and kind in (21,35,36) and u16(data) in (90,93,96,99,117,135,145,155)}
    for kind,data in parts:
        if kind in (2,22,32,83) and u16(data) in shapes:
            shapes.remove(u16(data))
            out.extend(shape_tags(movie,data,next(bitmap_ids),images))
            continue
        if kind in (21,35,36) and u16(data) in pending:
            ident = u16(data)
            im = decode(kind,data)
            if ident in LABELS[movie]:
                label = LABELS[movie][ident]
                im = Image.new("RGBA", im.size)
                lettering(im,(0,0,*im.size),label,fill="#fff4c2",outline="#56361f")
            else:
                special_game_image(movie,ident,im)
            data,kind = encode(ident,im),36
            pending.remove(ident)
        out.extend(tag(kind,data))
    if shapes:
        raise ValueError(f"{movie}: missing shapes {sorted(shapes)}")
    if pending:
        raise ValueError(f"{movie}: missing artwork {sorted(pending)}")
    return b"CWS"+blob[3:4]+struct.pack("<I",8+len(out))+zlib.compress(out,6)


if __name__ == "__main__":
    directory = base/"zh.pokemon-gl.com"/basegame
    for movie in LABELS:
        path = directory/movie
        result = translate_art(movie,path.read_bytes())
        path.write_bytes(result)
        if movie == "game4.ja.swf":
            (directory/"game4.swf").write_bytes(result)
