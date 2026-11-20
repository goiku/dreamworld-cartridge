"""Extend the game's embedded fonts without changing the art in existing text records."""
from functools import lru_cache
from itertools import accumulate
from pathlib import Path
import os
import struct
import zlib
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

def u16(b,p=0): return struct.unpack_from('<H',b,p)[0]
def rectlen(b,p=0): return (5+4*(b[p]>>3)+7)//8
def signed_width(*values): return max(1,max((v if v>=0 else ~v).bit_length()+1 for v in values))

class Writer:
    def __init__(self): self.data=bytearray();self.acc=0;self.count=0
    def put(self,v,n):
        self.acc=(self.acc<<n)|(v&((1<<n)-1));self.count+=n
        while self.count>=8:
            self.count-=8;self.data.append((self.acc>>self.count)&255)
        self.acc&=(1<<self.count)-1
    def done(self):
        if self.count:self.put(0,8-self.count)
        return bytes(self.data)

class Reader:
    def __init__(self,data): self.data=data;self.pos=0
    def take(self,n):
        value=0
        while n:
            k=min(n,8-self.pos%8); offset=self.pos%8
            value=(value<<k)|((self.data[self.pos//8]>>(8-offset-k))&((1<<k)-1))
            self.pos+=k;n-=k
        return value

class GlyphPen(BasePen):
    def __init__(self, glyphs, scale):
        super().__init__(glyphs);self.scale=scale;self.stream=Writer();self.stream.put(0x10,8)
        self.xy=(0,0);self.first=(0,0);self.bounds=None
    def point(self,p):
        x,y=round(p[0]*self.scale),round(-p[1]*self.scale)
        if self.bounds is None:self.bounds=(x,x,y,y)
        a,b,c,d=self.bounds;self.bounds=(min(a,x),max(b,x),min(c,y),max(d,y))
        return x,y
    def _moveTo(self,p):
        x,y=self.point(p);w=self.stream
        w.put(3,6);n=signed_width(x,y);w.put(n,5);w.put(x,n);w.put(y,n);w.put(1,1)
        self.first=self.xy=(x,y)
    def line(self,p):
        dx,dy=p[0]-self.xy[0],p[1]-self.xy[1];self.xy=p
        if dx==0 and dy==0:return
        n=max(2,signed_width(dx,dy));w=self.stream
        assert n<=17
        w.put(3,2);w.put(n-2,4);w.put(1,1);w.put(dx,n);w.put(dy,n)
    def _lineTo(self,p): self.line(self.point(p))
    def _qCurveToOne(self,p1,p2):
        x,y=self.xy;cx,cy=self.point(p1);ex,ey=self.point(p2)
        vals=(cx-x,cy-y,ex-cx,ey-cy);n=max(2,signed_width(*vals));w=self.stream
        assert n<=17
        w.put(2,2);w.put(n-2,4)
        for v in vals: w.put(v,n)
        self.xy=ex,ey
    def _closePath(self): self.line(self.first)
    def _endPath(self): pass
    def record(self):
        self.stream.put(0,6);b=self.bounds or (0,0,0,0)
        w=Writer();n=signed_width(*b);w.put(n,5)
        for v in b:w.put(v,n)
        return self.stream.done(),w.done()

@lru_cache(maxsize=1)
def _font(): return TTFont(os.environ["DW_BUILD_FONT"],lazy=True)
@lru_cache(maxsize=4)
def _glyphset(weight): return _font().getGlyphSet(location={'wght':weight})
@lru_cache(maxsize=24000)
def _shape(code,em,weight):
    name=_font().getBestCmap().get(code)
    if not name:return None
    glyphs=_glyphset(weight);glyph=glyphs[name];scale=em/_font()['head'].unitsPerEm
    pen=GlyphPen(glyphs,scale);glyph.draw(pen);shape,box=pen.record()
    return shape,round(glyph.width*scale),box

def read_font(t, data):
    flags=data[2];nName=data[4];pos=5+nName;count=u16(data,pos);pos+=2
    wide=bool(flags&8);offsize=4 if wide else 2
    offsets=struct.unpack_from('<'+('I' if wide else 'H')*(count+1),data,pos)
    shapes=[data[pos+x:pos+y] for x,y in zip(offsets,offsets[1:])]
    pos+=offsets[-1];width=2 if flags&4 else 1
    codes=list(struct.unpack_from('<'+('H' if width==2 else 'B')*count,data,pos));pos+=width*count
    if flags&128:
        heights=data[pos:pos+6];pos+=6
        advance=list(struct.unpack_from('<'+'h'*count,data,pos));pos+=2*count
        boxes=[]
        for _ in range(count):
            n=rectlen(data,pos);boxes.append(data[pos:pos+n]);pos+=n
    else: heights=b'';advance=[0]*count;boxes=[b'']*count
    return codes,dict(zip(codes,zip(shapes,advance,boxes))),heights,data[pos:]

def extend_font(t,data,characters):
    flags=data[2];nName=data[4];name=data[5:5+nName].rstrip(b'\0').decode('utf8','replace')
    codes,glyphs,heights,kern=read_font(t,data)
    weight=700 if flags&1 or name.endswith(('B','Bold','W6','Std B')) else 450
    for code in characters-glyphs.keys():
        record=_shape(code,20480 if t==75 else 1024,weight)
        if record:glyphs[code]=record
    if len(glyphs)==len(codes):return data, None
    ordered=sorted(glyphs); all_shapes=[glyphs[c][0] for c in ordered];n=len(ordered)
    out=bytearray(data[:5+nName]);out[2]|=12;out+=struct.pack('<H',n)
    offsets=list(accumulate((len(s) for s in all_shapes),initial=4*(n+1)))
    out+=struct.pack('<'+'I'*(n+1),*offsets)+b''.join(all_shapes)+struct.pack('<'+'H'*n,*ordered)
    if flags&128:
        out+=heights+struct.pack('<'+'h'*n,*(glyphs[c][1] for c in ordered))+b''.join(glyphs[c][2] for c in ordered)
        if flags&4:out+=kern
        else:
            count=u16(kern);out+=kern[:2]
            for i in range(count):
                a,b,v=struct.unpack_from('<BBh',kern,2+4*i);out+=struct.pack('<HHh',a,b,v)
    to_idx={code:i for i,code in enumerate(ordered)}
    return bytes(out),[to_idx[c] for c in codes]

def tags(d):
    pos=0
    while pos<len(d):
        tag=u16(d,pos);pos+=2;t,l=tag>>6,tag&63
        if l==63:l=struct.unpack_from('<I',d,pos)[0];pos+=4
        yield t,d[pos:pos+l];pos+=l
        if t==0:break
def tag(t,d):
    return (struct.pack('<H',t<<6|len(d)) if len(d)<63 else struct.pack('<HI',t<<6|63,len(d)))+d

def remap_text(t,d,maps):
    pos=2+rectlen(d,2)
    r=Reader(d[pos:])
    if r.take(1):
        n=r.take(5);r.take(n*2)
    if r.take(1):
        n=r.take(5);r.take(n*2)
    n=r.take(5);r.take(n*2);pos+=(r.pos+7)//8
    oldn=d[pos];adv=d[pos+1];head=d[:pos];pos+=2; font=None; records=[];maxindex=0
    while (flags:=d[pos]) != 0:
        begin=pos;pos+=1
        if flags&8:font=u16(d,pos);pos+=2
        if flags&4:pos+=4 if t==33 else 3
        if flags&1:pos+=2
        if flags&2:pos+=2
        if flags&8:pos+=2
        count=d[pos];pos+=1;sub=d[begin:pos];r=Reader(d[pos:]);gs=[]
        for _ in range(count):
            ix=r.take(oldn);shift=r.take(adv)
            if font in maps:ix=maps[font][ix]
            maxindex=max(maxindex,ix);gs.append((ix,shift))
        pos+=(r.pos+7)//8;records.append((sub,gs))
    n=max(oldn,maxindex.bit_length());out=bytearray(head)+bytes((n,adv))
    for sub,gs in records:
        w=Writer()
        for ix,shift in gs: w.put(ix,n);w.put(shift,adv)
        out+=sub+w.done()
    return bytes(out)+b'\0'

def extend_swf(blob,font_ids,text):
    assert blob[:3] in (b'FWS',b'CWS')
    raw=zlib.decompress(blob[8:]) if blob[:3]==b'CWS' else blob[8:]
    offset=rectlen(raw)+4;parts=list(tags(raw[offset:]));new=[];maps={}
    chars={ord(c) for c in text if 31<ord(c)<65536}
    for typ,d in parts:
        if typ in (48,75) and u16(d) in font_ids:
            d,remap=extend_font(typ,d,chars)
            if remap is not None:maps[u16(d)]=remap
        new.append((typ,d))
    if not maps:return blob
    def rewrite(parts):
        out=bytearray()
        for t,d in parts:
            if t in (11,33):d=remap_text(t,d,maps)
            elif t==73 and u16(d) in maps:continue
            elif t==39:d=d[:4]+rewrite(tags(d[4:]))
            out+=tag(t,d)
        return out
    raw=raw[:offset]+rewrite(new)
    return b'CWS'+blob[3:4]+struct.pack('<I',len(raw)+8)+zlib.compress(raw,6)
