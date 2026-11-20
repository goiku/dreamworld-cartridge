from pathlib import Path
import os
import sys,shutil
from swf_font import extend_swf,read_font,tags,rectlen,u16,zlib
root=Path(os.environ["DW_BUILD_ROOT"])
assets=root/"dreamworld_assets"
zh=assets/"zh.pokemon-gl.com"
words=set()
for base in (zh,root/"raw_text/zh"):
    for f in base.rglob("*"):
        if f.is_file() and (f.suffix in (".xml",".json",".txt",".html",".js") or base.name=="zh"):
            words.update(f.read_text("utf-8-sig",errors="ignore"))
for lead in range(0xb0,0xd8):
    words.update(b"".join(bytes((lead,i)) for i in range(0xa1,0xff)).decode("gb2312","ignore"))
text="".join(sorted(words))
for name,ids in (("src/swf/theme/assets/common/font.swf",{5,12}),("src/swf/pdw/assets/fonts.swf",{1})):
    print(name,len(text),flush=True)
    dest=zh/name
    data=extend_swf((assets/"shared.pokemon-gl.com"/name).read_bytes(),ids,text)
    raw=zlib.decompress(data[8:])
    for t,d in tags(raw[rectlen(raw)+4:]):
        if t in (48,75) and u16(d) in ids:
            codes,glyphs,_,_=read_font(t,d)
            assert set(map(ord,"简体梦寻欢迎将宝可梦带回"))<=set(codes)
            print(u16(d),len(codes),len(glyphs[ord("简")][0]),flush=True)
    dest.parent.mkdir(exist_ok=True,parents=True)
    dest.write_bytes(data)
shutil.copyfile(Path(__file__).with_name("OFL.txt"), zh/"NotoSansSC-OFL.txt")
