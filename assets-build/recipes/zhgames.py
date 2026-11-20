from swfone import *
import html, math, tempfile, os
from html.parser import HTMLParser
scratch=Path(__file__).resolve().parent

import swf_font as font
from xml.etree import ElementTree as ET
zbase=base/"zh.pokemon-gl.com"
abc_table=json.loads((scratch/"zh-game-list.json").read_text("utf8"))
abc_values={abc_table[i-1]:v.replace('|','\n') for f in scratch.glob('gc-*.json') for i,v in json.loads(f.read_text("utf8"))}
abc_values.update({'読みこみ中です。':'正在读取……','アチャモ':'火稚鸡','読み込みに失敗しました / ':'未能读取 / ','<poke>はホエルオーの背中で楽しく遊べなかった。':'没能在吼鲸王背上玩尽兴。'})
abc_values['ホエルオーの背中で楽しく遊べなかった。']='没能在吼鲸王背上玩尽兴。'
static_table=json.loads((scratch/'static-zlist.json').read_text('utf8'))
static_labels=dict(zip(static_table,(scratch/'static-zh.txt').read_text('utf8').splitlines(),strict=True))
static_by_key={key:(s,static_labels[s]) for s,keys in static_table.items() for key in keys}
def normalized(s):return re.sub(r'\s+','',html.unescape(re.sub('<[^>]+>','',s)))
static_map={normalized(s):t for s,t in static_labels.items()}
def edit_text(d):
 pos=2+font.rectlen(d,2);flags=int.from_bytes(d[pos:pos+2],'big');pos+=2
 fid=None
 if flags&0x100:fid=font.u16(d,pos);pos+=2
 if flags&0x80:pos=d.index(0,pos)+1
 if flags&0x100:pos+=2
 if flags&0x400:pos+=4
 if flags&0x200:pos+=2
 if flags&0x20:pos+=9
 pos=d.index(0,pos)+1
 return fid,pos,d[pos:-1].decode('utf8') if flags&0x8000 else ''
def trans_edit(d):
 fid,pos,val=edit_text(d)
 zh=static_map.get(normalized(val))
 if not zh:return d,None
 if '<font' in val.lower():
  # Keep alignment, color and typeface; reflow multi-line labels to their original number of paragraphs.
  parts=re.split(r'(<[^>]*>)',val)
  index=[i for i in range(0,len(parts),2) if parts[i].strip()]
  if not index:return d,None
  counts=[len(parts[i]) for i in index];used=0
  for j,i in enumerate(index):
   end=round(sum(counts[:j+1])*len(zh)/sum(counts))
   # Tokens must remain contiguous for the original ActionScript call to replace them.
   for m in re.finditer(r'\[[^\]]*\]',zh):
    if m.start()<end<m.end():end=m.end()
   end=max(used,end);parts[i]=html.escape(zh[used:end],quote=False);used=end
  val=''.join(parts)
 else:val=zh
 return d[:pos]+val.encode()+b'\0',fid
def trans_abc(d,used):
 replacements=[(a,b,abc_values[s]) for a,b,s in abc_strings(d) if s in abc_values]
 if not replacements:return d
 out=bytearray();pos=0
 for a,b,s in replacements:
  tmp=s.encode();out.extend(d[pos:a]);out.extend(enc(len(tmp)));out.extend(tmp);pos=b;used.add(s)
 return bytes(out)+d[pos:]
def static_opts(t,d):
 pos=2+font.rectlen(d,2);r=font.Reader(d[pos:])
 for _ in range(2):
  if r.take(1):r.take(r.take(5)*2)
 r.take(r.take(5)*2);pos+=(r.pos+7)//8
 oldn,adv=d[pos:pos+2];pos+=2;flags=d[pos];start=pos;pos+=1
 assert flags&8;fid=font.u16(d,pos);pos+=2
 if flags&4:pos+=4 if t==33 else 3
 if flags&1:pos+=2
 if flags&2:pos+=2
 height=font.u16(d,pos);pos+=2
 count=d[pos];r=font.Reader(d[pos+1:]); total=0
 for _ in range(count):
  r.take(oldn);x=r.take(adv);total+=x-(1<<adv) if x&(1<<(adv-1)) else x
 end=pos+1+(r.pos+7)//8
 assert d[end:]==b'\0',(t,fid,d[end:])
 return start,d[start:pos],fid,total
def trans_static(t,d,fonts,txt):
 start,sub,fid,total=static_opts(t,d)
 ordered,_glyphs,_,_=fonts[fid];indexed={c:i for i,c in enumerate(ordered)}
 if any(ord(c) not in indexed for c in txt):raise ValueError((fid,txt))
 glyphs=[indexed[ord(c)] for c in txt];n=max(glyphs).bit_length() or 1
 xs=[round((j+1)*total/len(txt))-round(j*total/len(txt)) for j in range(len(txt))];adv=max(font.signed_width(x) for x in xs);w=font.Writer()
 for idx,x in zip(glyphs,xs):w.put(idx,n);w.put(x,adv)
 return d[:start-2]+bytes((n,adv))+sub+bytes([len(glyphs)])+w.done()+b'\0'
def build(p,relative,game):
 blob=p.read_bytes();raw=unpack(blob);at=payload_offset(raw);parts=list(tags(raw,at));used=set();static={};font_ids=set()
 for t,d in parts:
  if t==82:trans_abc(d,used)
  if t==37:
   new,fid=trans_edit(d)
   if new!=d:
    used.add(static_map[normalized(edit_text(d)[2])])
    if fid is not None:font_ids.add(fid)
  elif t in (11,33):
   key=f'static{game}_{font.u16(d)}'
   if key in static_by_key:
    txt=static_by_key[key][1];fid=static_opts(t,d)[2];static[font.u16(d)]=txt;used.add(txt);font_ids.add(fid)
 if game in (1,7,9):
  ef=zbase/basegame/f'game{game}/strings_ja.xml'
  for el in ET.fromstring(ef.read_bytes()).iter("string"):
   if el.text:used.add(el.text)
 if not used:return None
 allfonts={font.u16(d):d[5:5+d[4]].rstrip(b'\0').decode('utf8','replace') for t,d in parts if t in (48,75)}
 chosen={fid for fid,name in allfonts.items() if fid in font_ids or (game in (1,7,9) and ('ゴ' in name or name=='Osaka')) or (game==3 and name=='_ゴシック')}
 # Empty device font declarations are not mapped to an embedded font by Flash; preserve these,
 # except when static outlines require actual glyphs or they already supply editable text.
 glyphs=''.join(sorted(set(''.join(used))))
 blob=font.extend_swf(blob,chosen,glyphs);raw=unpack(blob);at=payload_offset(raw);parts=list(tags(raw,at))
 fonts={font.u16(d):font.read_font(t,d) for t,d in parts if t in (48,75)}
 out=bytearray(raw[:at])
 for t,d in parts:
  if t==82:d=trans_abc(d,used)
  if t==37:d=trans_edit(d)[0]
  if t in (11,33) and font.u16(d) in static:d=trans_static(t,d,fonts,static[font.u16(d)])
  out.extend(font.tag(t,d))
 new=b'CWS'+blob[3:4]+struct.pack('<I',len(out)+8)+zlib.compress(out,6)
 dest=zbase/basegame/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(new)
 assert len(unpack(new))==int.from_bytes(new[4:8],'little')-8
 print(relative,'bytes',len(new),'strings',len(used),'font',chosen,'static',len(static),flush=True)
 return {'path':dest.relative_to(base).as_posix(),'font_ids':sorted(chosen),'glyphs':glyphs}
if __name__=='__main__':
 manifest=[]
 for i in range(1,13):
  for name in ([f'game4.ja.swf'] if i==4 else [f'game{i}.swf']):
   item=build(shared/name,name,i)
   if item:manifest.append(item)
 for i in range(1,5):
  name=f'gameInfo{i}.swf'
  for source,rel in [(shared/name,name),(ja/'ja'/name,'ja/'+name)]:build(source,rel,i+20)
 (zbase/basegame/'game4.swf').write_bytes((zbase/basegame/'game4.ja.swf').read_bytes())

