from pathlib import Path
import os
import sys,zlib,struct
from PIL import Image,ImageDraw,ImageFont
from swfone import *

import swf_font as f
orig=shared.parent/'pdw_opening.swf';dest=base/'zh.pokemon-gl.com/src/swf/pdw/assets/pdw_opening.swf'
blob=orig.read_bytes();d=unpack(blob);at=payload_offset(d);out=bytearray(d[:at]);im=Image.new('RGBA',(430,320),'white')
draw=ImageDraw.Draw(im)
def write(x,y,txt,size,fill,anchor='lm',bold=False):
 ft=ImageFont.truetype(os.environ["DW_BUILD_FONT"],size)
 ft.set_variation_by_axes([700 if bold else 490])
 draw.text((x,y),txt,font=ft,fill=fill,anchor=anchor)
draw.rounded_rectangle((1,0,428,28),radius=14,fill='#dcdcdc')
write(215,14,'游玩小约定',19,'#333333','mm',True)
for n,top in enumerate((59,145,232),1):
 draw.rounded_rectangle((0,top,54,top+66),radius=4,fill='#b78ec0')
 write(27,top+13,'约定',12,'#64476b','mm',True)
 draw.ellipse((14,top+31,41,top+58),fill='white');write(27,top+44,str(n),16,'#9c72a6','mm',True)
for x in range(0,430,3):
 for y in (135,221,319): draw.point((x,y),fill='#999999')
for y,txt,color in [(73,'长时间游玩宝可梦全球连接时，','#333333'),(94,'每小时请休息10到15分钟。','#f14859'),(115,'眼睛或手感到疲劳时，也要及时休息。','#333333'),(169,'游玩宝可梦全球连接时，','#333333'),(190,'请保持房间光线明亮。','#f14859'),(248,'如果在游玩时感到身体不适，','#333333'),(269,'请立即停止游戏，','#333333'),(290,'并告诉家人。','#f14859')]:
 write(71,y,txt,15,color,bold=True)
for t,b in tags(d,at):
 if t==36 and f.u16(b)==12:
  assert b[2]==5 and struct.unpack_from('<HH',b,3)==im.size
  rgba=im.tobytes(); raw=bytearray(len(rgba));raw[0::4]=rgba[3::4];raw[1::4]=rgba[::4];raw[2::4]=rgba[1::4];raw[3::4]=rgba[2::4]
  b=b[:7]+zlib.compress(raw,9)
 out+=f.tag(t,b)
dest.write_bytes(b'CWS'+blob[3:4]+struct.pack('<I',len(out)+8)+zlib.compress(out,6))

