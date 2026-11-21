import {crc} from "./pwt-save.mjs";

const DAY = 86400000;
function checkedDate(year, month, day) {
    const value = new Date(Date.UTC(year, month - 1, day));
    if (year < 2000 || year > 2099 || value.getUTCFullYear() !== year ||
        value.getUTCMonth() !== month - 1 || value.getUTCDate() !== day) throw Error("date");
    return value;
}
const ordinal = date => (date.getTime() - Date.UTC(date.getUTCFullYear(), 0, 1)) / DAY;

export function prepareTuckSave(original, dateText) {
    if (!(original instanceof Uint8Array) || original.length !== 0x80000) throw Error("invalid");
    if (!/^\d{4}-\d\d-\d\d$/.test(dateText)) throw Error("date");
    const today = checkedDate(...dateText.split("-").map(Number));
    const yesterday = today.getTime() === Date.UTC(2000, 0, 1)
        ? new Date(Date.UTC(2099, 11, 31)) : new Date(today.getTime() - DAY);
    const game = original[0x1941f];
    if (![20, 21, 22, 23].includes(game)) throw Error("invalid");
    const [stride, table, tableSize, tableSum, trainerSize] = game >= 22
        ? [0x26000, 0x25f00, 0x94, 0x25fa2, 0xb0] : [0x24000, 0x23f00, 0x8c, 0x23f9a, 0x68];
    const bytes = new Uint8Array(original);
    let changed = false, awake = false;
    for (const base of [0, stride]) {
        const slot = bytes.subarray(base, base + stride);
        if (base && (slot.every(x => x === 0) || slot.every(x => x === 255))) continue;
        const view = new DataView(slot.buffer, slot.byteOffset, slot.byteLength);
        const sum = (pos, len) => crc(slot.subarray(pos, pos + len));
        const blocks = [[0x19400, trainerSize, 54], [0x1d300, 0x1ac, 70], [0x1d900, 0x5c, 74]];
        if (slot[0x1941f] !== game || sum(table, tableSize) !== view.getUint16(tableSum, true)) throw Error("invalid");
        for (const [pos, len, mirror] of blocks) {
            const check = sum(pos, len);
            if (view.getUint16(pos + len + 2, true) !== check || view.getUint16(table + mirror, true) !== check)
                throw Error("invalid");
        }
        const wait = view.getUint32(0x1d944, true);
        if (wait > 1440) throw Error("invalid");
        if (slot[0x1d4a3]) continue;
        awake = true;
        const [weekday, day, month, year] = slot.subarray(0x1d300, 0x1d304);
        let lastDay = 0;
        if (!(weekday === 0 && day === 1 && month === 1 && year === 0xda)) {
            if (weekday > 6) throw Error("invalid");
            try { lastDay = ordinal(checkedDate(2000 + year, month, day)); }
            catch { throw Error("invalid"); }
        }
        if (lastDay !== ordinal(today) && !wait) continue;
        if (lastDay === ordinal(today)) {
            slot.set([yesterday.getUTCDay(), yesterday.getUTCDate(), yesterday.getUTCMonth() + 1,
                yesterday.getUTCFullYear() - 2000], 0x1d300);
        }
        view.setUint32(0x1d944, 0, true);
        for (const [pos, len, mirror] of blocks.slice(1)) {
            const check = sum(pos, len);
            view.setUint16(pos + len + 2, check, true);
            view.setUint16(table + mirror, check, true);
        }
        view.setUint16(tableSum, sum(table, tableSize), true);
        changed = true;
    }
    return {bytes, status: changed ? "prepared" : awake ? "ready" : "asleep"};
}
