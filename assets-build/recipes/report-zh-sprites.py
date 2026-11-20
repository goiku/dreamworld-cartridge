"""Typeset Simplified Chinese into the existing report sprite cells at the original CSS coordinates."""
from functools import lru_cache
from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont

root=Path(os.environ["DW_BUILD_ROOT"])/"dreamworld_assets"
suffix=Path("src/swf/report/ja")
source=root/"ja.pokemon-gl.com"/suffix
dest=root/"zh.pokemon-gl.com"/suffix
dest.mkdir(parents=True,exist_ok=True)

@lru_cache
def font(size,weight):
    f=ImageFont.truetype(os.environ["DW_BUILD_FONT"],size)
    f.set_variation_by_axes([weight])
    return f


def sheet(name):
    return Image.open(source/name).convert("RGBA")


def wipe(image,left,top,right,bottom,sample):
    """Use the original row paint; the protected icon, divider or button border is outside the cell."""
    draw=ImageDraw.Draw(image)
    for y in range(top,bottom):
        draw.line((left,y,right-1,y),fill=image.getpixel((sample,y)))


def text(image,xy,label,size,*,anchor="mm",fill="white",weight=700,outline=None):
    ImageDraw.Draw(image).text(xy,label,font=font(size,weight),anchor=anchor,fill=fill,
                               stroke_width=1 if outline else 0,stroke_fill=outline)


name="report-header.png"
im=sheet(name)
wipe(im,235,62,342,97,346)
text(im,(238,84),"报告",16,anchor="lm")
for y in (0,109):
    for start,label in ((673,"Wi-Fi 大赛"),(833,"游戏同步调查队")):
        wipe(im,start+2,y+63,start+157,y+92,start+5)
        text(im,(start+80,y+80),label,17)
im.save(dest/name)

name="report-headers.png"
im=sheet(name)
labels=["全球交换站（GTS）","GTS 排行榜","宝可梦资料","地区资料","全球对战联盟（GBU）",
        "各对战规则排行榜","常用宝可梦","Wi-Fi 大赛","大赛资料","游戏同步调查队"]
for index,label in enumerate(labels):
    y=index*35
    left=100 if index==8 else 40
    wipe(im,left,y,600,y+25,740)
    color=("#0086b0" if index<4 else "#b44019" if index<7 else "#b92b27" if index<9 else "#138442")
    text(im,(left,y+10),label,18,anchor="lm",outline=color)
im.save(dest/name)

name="report-buttons.png"
im=sheet(name)
def button(x,y,w,h,label,size=14,icon=False,disabled=False,left=False):
    begin=37 if icon else 4
    wipe(im,x+begin,y+3,x+w-3,y+h-4,x+w-2)
    xtext=x+begin+1 if icon else x+21 if left else x+w/2
    lines=label.split("\n")
    for idx,line in enumerate(lines):
        text(im,(xtext,y+(h-2)/2+(idx-(len(lines)-1)/2)*(size+4)),line,size,
             anchor="lm" if icon or left else "mm",fill="#61707b" if disabled else "white")

for y,blue,red in ((0,"GTS 排行榜","GBU 排行榜"),(45,"宝可梦资料","宝可梦资料"),(90,"地区资料",None)):
    for x in (0,200): button(x,y,200,45,blue,18,left=True)
    if red:
        for x in (400,600): button(x,y,200,45,red,18,left=True)
for y,blue,red,last in ((135,"选择宝可梦","选择赛季","Wi-Fi 大赛列表"),
                         (163,"选择地区","按地区筛选","Wi-Fi 大赛列表"),
                         (191,"选择地区","查看我的排名","查看我的排名"),
                         (219,"查看更多地区资料","选择宝可梦",None)):
    for x in (0,160): button(x,y,160,28,blue,13,icon=y!=219)
    for x in (320,480): button(x,y,160,28,red,13,icon=y!=191)
    if last: button(640,y,160,28,last,13,disabled=y==191)
for y,label in ((247,"查看 GTS 资料"),(275,"查看调查队资料")):
    for x in (0,166,332): button(x,y,166,28,label,13)
    button(498,y,182,28,"查看我的对战记录",14)
for index,label in enumerate(["综合排名","单打对战","双打对战","三打对战","射击对战","轮盘对战"]):
    for x in (0,170): button(x,303+index*40,170,40,label,15)
for y,h,label in ((303,73,"交换最多的\n宝可梦前30名"),(376,75,"最想获得的\n宝可梦前30名"),(451,78,"寄放最多的\n宝可梦前30名")):
    for x in (340,500): button(x,y,160,h,label,14,disabled=x==500)
for y in (543,567): button(340,y,262,24,"重要事项与比赛规则（PDF）",13)
im.save(dest/name)

name="dialog-pokemon-selector-buttons.png"
im=sheet(name)
for row in range(2):
    for idx,label in enumerate(("按名称排列","按图鉴编号排列","从收藏中选择")):
        x,y=idx*260,row*30
        wipe(im,x+3,y+2,x+257,y+28,x+1)
        text(im,(x+130,y+14),label,15,fill="white" if not row else "#6d7477",outline="#45515a")
im.save(dest/name)

types=("一般","火","水","电","草","冰","格斗","毒","地面","飞行","超能力","虫","岩石","幽灵","龙","恶","钢","其他")
for name in ("types-large.png","types-small.png"):
    im=sheet(name)
    for idx,label in enumerate(types):
        y=idx*17
        wipe(im,2,y+1,im.width-2,y+16,2)
        text(im,(im.width/2,y+8),label,12,weight=700)
    im.save(dest/name)
