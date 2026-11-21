"""Draw translated Flash outline lettering at the original registration point and size."""
import math
import struct

from PIL import Image, ImageDraw
from swf_font import Reader, Writer, rectlen, signed_width, tag, u16
from game_art_zh import BROWN, CLEAR, PAPER, encode, lettering


# IDs refer to shapes, independent of the corresponding game's bitmap IDs.
WORDS = {
    "game1/game.swf": {
        51:"游戏时间到了",54:"游戏时间到了",122:"仔细听",124:"仔细听",
        300:"仔细听",302:"仔细听",304:"仔细听",310:"仔细听",312:"仔细听",
    },
    "game3.swf": {
        55:"已飞过\n200 米",63:"已飞过\n400 米",71:"已飞过\n600 米",79:"已飞过\n800 米",
        271:"返回",291:"下一页",316:"玩法说明",640:"剩余时间",655:"得分",663:"分",725:"剩余距离",
        750:"速度",796:"Ⅱ  空格键",821:"已暂停",845:"查看玩法",863:"返回游戏",886:"是",896:"否",
    },
    "game4.ja.swf": {
        103:"连击",206:"结束游戏",208:"结束游戏",416:"取消",421:"确定",605:"开始",608:"玩法说明",
        612:"目标达成！",614:"击破了！",
    },
    "game8.swf": {301:"剩余时间",316:"得分",324:"分",526:"是",536:"否",758:"确定"},
}
LAYOUTS = {"game3.swf": {542,545}, "game4.ja.swf": {430}}


def bounds(data):
    reader = Reader(data[2:])
    bits = reader.take(5)
    values = [reader.take(bits) for _ in range(4)]
    return tuple(v-(1<<bits) if v & (1<<(bits-1)) else v for v in values)


def image_shape(data, bitmap_id, size):
    left,right,top,bottom = bounds(data)
    width,height = right-left,bottom-top
    matrix = Writer()
    matrix.put(1,1)
    sx,sy = round(width*65536/size[0]),round(height*65536/size[1])
    bits = signed_width(sx,sy)
    matrix.put(bits,5);matrix.put(sx,bits);matrix.put(sy,bits)
    matrix.put(0,1)
    bits = signed_width(left,top)
    matrix.put(bits,5);matrix.put(left,bits);matrix.put(top,bits)
    fills = b"\x01\x41"+struct.pack("<H",bitmap_id)+matrix.done()+b"\0"
    path = Writer()
    path.put(0x10,8)
    path.put(5,6)  # move to the original top-left and select fill style 1 on the right
    path.put(bits,5);path.put(left,bits);path.put(top,bits);path.put(1,1)
    for vertical,delta in ((0,width),(1,height),(0,-width),(1,-height)):
        bits = max(2,signed_width(delta))
        path.put(3,2);path.put(bits-2,4);path.put(0,1);path.put(vertical,1);path.put(delta,bits)
    path.put(0,6)
    return data[:2+rectlen(data,2)]+fills+path.done()


def render(movie, ident, size, images):
    w,h=size
    im=Image.new("RGBA",size)
    if movie=="game4.ja.swf" and ident==430:
        draw=ImageDraw.Draw(im)
        draw.rounded_rectangle((0,0,w-1,h-1),radius=12,fill=PAPER,outline=BROWN,width=2)
        lettering(im,(20,11,w-20,65),"吼鲸王喷水 · 玩法说明",maximum=32)
        for y,words in [(75,"左右移动鼠标，让吼鲸王游到下落的宝可梦下方。"),
                        (121,"点击喷水，把宝可梦弹向和它图案相配的彩球。"),
                        (167,"瞄准右侧标出的目标数量。连续击破彩球可以提高得分倍率。"),
                        (213,"宝可梦落进海里时，得分倍率会下降。")]:
            lettering(im,(24,y,w-24,y+41),words,maximum=22)
        for index, (buddy,ball) in enumerate(((90,117),(93,135),(96,145),(99,155))):
            x=42+index*173
            for source,left in ((images[buddy],x),(images[ball],x+65)):
                ico=source.copy();ico.thumbnail((64,64))
                im.alpha_composite(ico,(left,300))
        return im
    if movie=="game3.swf" and ident==542:
        for y,value in ((0,"飞行时间"),(.32,"得分"),(.59,"时间奖励"),(.84,"加速奖励")):
            lettering(im,(0,int(y*h),int(w*.5),min(h,int((y+.19)*h))),value)
        return im
    if movie=="game3.swf" and ident==545:
        lettering(im,(0,0,int(w*.22),int(h*.58)),"合计")
        lettering(im,(int(w*.87),0,w,int(h*.59)),"分")
        return im
    words=WORDS[movie][ident]
    fill="white";outline=None
    if movie=="game4.ja.swf" and ident in (206,208):
        draw=ImageDraw.Draw(im);draw.rounded_rectangle((0,0,w-1,h-1),radius=h//8,fill="#d9d2b4")
        edge=h//7;draw.rounded_rectangle((edge,edge,w-1-edge,h-1-edge),radius=h//11,
                                          fill=BROWN if ident==206 else "#e87e00")
        lettering(im,(edge,edge,w-edge,h-edge),words,fill=fill,maximum=round(h*.47))
    else:
        if movie=="game3.swf" and ident in (55,63,71,79,640,655,663) or movie=="game8.swf" and ident in (301,316,324):
            fill=BROWN
        if movie=="game3.swf" and ident in (725,750) or movie=="game4.ja.swf" and ident in (103,612,614):
            fill="#ffc540";outline="#6b3b13"
        if movie=="game3.swf" and ident in (316,796,821):
            outline="#345869"
        lettering(im,(0,0,w,h),words,fill=fill,outline=outline)
    return im


def shape_tags(movie, data, bitmap_id, images):
    ident=u16(data)
    left,right,top,bottom=bounds(data)
    # Rasterize short glyphs at 3x to keep their edges sharp on zoomed displays.
    scale=1 if ident in LAYOUTS.get(movie,()) else 3
    size=(max(2,math.ceil((right-left)/20)*scale),max(2,math.ceil((bottom-top)/20)*scale))
    im=render(movie,ident,size,images)
    return tag(36,encode(bitmap_id,im))+tag(32,image_shape(data,bitmap_id,size))
