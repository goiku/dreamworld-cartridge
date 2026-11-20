from pathlib import Path
import os
import collections, zlib, struct, re, sys, json
base=Path(os.environ["DW_BUILD_ROOT"])/"dreamworld_assets"
basegame="src/swf/pdw/assets/game"
shared=base/"shared.pokemon-gl.com"/basegame
ja=base/"ja.pokemon-gl.com"/basegame
def unpack(blob):
 assert blob[:3] in (b'FWS',b'CWS')
 return (blob[8:] if blob[:3]==b'FWS' else zlib.decompress(blob[8:]))
def leb(buf,p):
 n=0
 for shift in range(0,35,7):
  b=buf[p];p+=1;n|=(b&127)<<shift
  if b<128:return n,p
 return n,p
def enc(n):
 out=bytearray()
 while n>=128:out.append(128|(n&127));n>>=7
 out.append(n);return out
def payload_offset(data):
 return (5 + 4*(data[0]>>3)+7)//8 + 4
def tags(data,p):
 while p<len(data):
  info=struct.unpack_from('<H',data,p)[0];p+=2
  code=info>>6; ln=info&63
  if ln==63:ln=struct.unpack_from('<I',data,p)[0];p+=4
  yield code,data[p:p+ln];p+=ln
def abc_strings(b):
 p=b.index(b'\0',4)+1+4
 for i in range(3):
  n,p=leb(b,p)
  if i==2:p+=max(0,n-1)*8
  else:
   for j in range(1,n):_,p=leb(b,p)
 n,p=leb(b,p)
 out=[]
 for i in range(1,n):
  st=p;sz,p=leb(b,p)
  out.append((st,p+sz,b[p:p+sz].decode('utf8','surrogateescape')));p+=sz
 return out
