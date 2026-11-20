// B2/W2 extdata layout and CRCs follow PKHeX SAV5B2W2.SetPWT and PlayerData5B2W2.
const TRAINER = 0x19400, TABLE = 0x25f00, DATA = 0x1214, BLOCK = 0x1314;
const view = bytes => new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
function crc(bytes) {
    let value = 0xffff;
    for (const byte of bytes) {
        value ^= byte << 8;
        for (let bit=0; bit<8; bit++)
            value = ((value << 1) ^ ((value & 0x8000) ? 0x1021 : 0)) & 0xffff;
    }
    return value;
}
function checksummed(bytes,start,size) {
    return crc(bytes.subarray(start,start+size));
}
function validTournament(block) {
    if (block.length!==BLOCK) return false;
    const v=view(block),sum=checksummed(block,0,DATA);
    return v.getUint16(DATA,true)===1 && v.getUint16(DATA+2,true)===sum
        && v.getUint32(0x1300,true)===sum && v.getUint32(0x1304,true)===1
        && v.getUint32(0x1308,true)===BLOCK && v.getUint32(0x130c,true)===0x31053527
        && v.getUint16(0x1312,true)===checksummed(block,0x1300,4);
}
export function inspect(bytes) {
    if (bytes.length!==0x80000 || bytes[TRAINER+0x1e]!==1 || ![22,23].includes(bytes[TRAINER+0x1f]))
        throw Error("invalid");
    const v=view(bytes),sum=checksummed(bytes,TRAINER,0xb0);
    if (sum!==v.getUint16(0x194b2,true) || sum!==v.getUint16(0x25f36,true)
        || checksummed(bytes,TABLE,0x94)!==v.getUint16(0x25fa2,true)) throw Error("invalid");
    return [0,1,2].map(index=>{
        const offset=0x7a000+index*0x1400,flag=v.getUint16(TRAINER+0x52+index*2,true);
        const block=bytes.subarray(offset,offset+BLOCK);
        const empty = flag===0 && v.getUint32(TRAINER+0xa0+index*4,true)===0
            && (block.every(b=>b===0) || block.every(b=>b===255));
        return {offset,empty,number:flag===0xc21e?v.getUint16(offset+8,true):null,
                crc:checksummed(block,0,DATA)};
    });
}
export function install(bytes,block) {
    const slots=inspect(bytes);
    if (!validTournament(block)) throw Error("unavailable");
    const number=view(block).getUint16(8,true);
    if (slots.some(slot=>slot.number===number)) throw Error("already");
    const index=slots.findIndex(slot=>slot.empty);
    if (index<0) throw Error("full");
    const updated=bytes.slice(),v=view(updated);
    updated.set(block,slots[index].offset);
    v.setUint16(TRAINER+0x52+2*index,0xc21e,true);
    v.setUint32(TRAINER+0xa0+4*index,1,true);
    const sum=checksummed(updated,TRAINER,0xb0);
    v.setUint16(0x194b2,sum,true);
    v.setUint16(0x25f36,sum,true);
    v.setUint16(0x25fa2,checksummed(updated,TABLE,0x94),true);
    return updated;
}
