
from swfone import *
from PIL import Image, ImageDraw, ImageFont
d=base/"ja.pokemon-gl.com/src/swf/pdw/assets/ja/spimg";out=base/"zh.pokemon-gl.com/src/swf/pdw/assets/ja/spimg";out.mkdir(parents=True,exist_ok=True)
def font(sz,weight):
 ft=ImageFont.truetype(os.environ["DW_BUILD_FONT"],sz);ft.set_variation_by_axes([weight]);return ft
def panel(name,title,body,which=None):
 canvas=Image.new('RGB',(580,340),'#142238');pen=ImageDraw.Draw(canvas)
 color='#81b7f1' if which=='捷克罗姆' else '#e5aa75'
 pen.rectangle((0,0,580,7),fill=color);pen.text((24,27),title,font=font(29,720),fill='#fff3d2')
 pen.text((25,83),'宝可梦电影特别活动　2011年7月13日至10月4日',font=font(15,520),fill=color)
 pen.line((24,121,556,121),fill='#66758a',width=1)
 x,y=25,150
 if which:
  ref=Image.open(d/name).convert('RGB')
  # The original promotional announcement includes this screenshot of the C-Gear skin.
  pic=ref.crop((27,161,215,296));pic.thumbnail((166,128));canvas.paste(pic,(24,157));x=210
 for line in body:
  pen.text((x,y),line,font=font(17,480),fill='white');y+=34
 canvas.save(out/name,quality=92,subsampling=0)
panel('campaign_image_3.jpg','欢迎来到电影特别小屋！',['到小屋内外逛一逛，和这里的宝可梦打个招呼吧。','让电影活动赠送的莱希拉姆或捷克罗姆入睡，','再前往梦之桥，就能在梦之岛帮助比克提尼打开宝箱。'])
for name,which in [('tokubetsunnahome_cgea_resiramu.jpg','莱希拉姆'),('tokubetsunnahome_cgea_zekuromu.jpg','捷克罗姆')]:
 panel(name,'小游戏通关！',['当年的电影活动曾送出','「'+which+'」C装置皮肤。','要查看现有皮肤，请到主页','打开“自定义”。'],which)
panel('tokubetsunnahome_cgea_secound.jpg','再次打开了宝箱！',['你已经完成过这次挑战。','最初的电影活动以特别C装置皮肤作为通关纪念。','在主页的“自定义”中可以查看现有皮肤。'])


# The café boards share their layout but use different original artwork.
for name in ("campaign_image_1.jpg", "campaign_image_2.jpg"):
    with Image.open(d/name) as source:
        picture = source.convert("RGB")
    from game_art_zh import lettering
    lettering(picture, (111, 5, 574, 86), "宝可梦咖啡馆", maximum=55, background="#fff8df")
    lettering(picture, (6, 90, 574, 117), "活动时间：2011年5月25日至8月30日 16:00", maximum=18, background="#fff8df")
    lettering(picture, (16, 125, 233, 194), "藤藤蛇、暖暖猪和水水獭也来了！\n进咖啡馆，看看特别的家具吧。", maximum=15, background="#fff8df")
    lettering(picture, (244, 125, 564, 174), "从咖啡馆出发，前往特别的梦之岛。\n和伊布、蚊香蝌蚪、图图犬或结草儿做朋友！", maximum=15, background="#fff8df")
    lettering(picture, (7, 291, 573, 334), "这次活动还有咖啡馆主题的 C 装置壁纸和家具。", maximum=18, background="#fff8df")
    picture.save(out/name, quality=93, subsampling=0)
