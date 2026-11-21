import {prepareTuckSave} from "./tuck-save.mjs";

const el = id => document.getElementById("tuck-" + id);
const labels = JSON.parse(el("labels").textContent);
const date = el("date"), picker = el("file"), folderButton = el("folder"), list = el("list");
const write = el("write"), download = el("download"), status = el("status");
const now = new Date();
date.value = [now.getFullYear(), String(now.getMonth()+1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
folderButton.hidden = !window.showDirectoryPicker;
let directory, handle, selected, original, prepared, generation = 0;

function reset() {
    generation++;
    original = prepared = null;
    if (download.href) URL.revokeObjectURL(download.href);
    download.removeAttribute("href");
    download.hidden = write.hidden = true;
    status.textContent = "";
    return generation;
}
async function inspect() {
    const id = reset();
    if (!selected && !handle) return;
    try {
        const file = handle ? await handle.getFile() : selected;
        if (file.size !== 0x80000) throw Error("invalid");
        const data = new Uint8Array(await file.arrayBuffer());
        if (id !== generation) return;
        const result = prepareTuckSave(data, date.value);
        status.textContent = labels[result.status];
        if (result.status !== "prepared") return;
        original = data;
        prepared = result.bytes;
        download.download = file.name.replace(/\.sav$/i, "") + "-tuck-in.sav";
        download.href = URL.createObjectURL(new Blob([prepared], {type: "application/octet-stream"}));
        download.hidden = false;
        write.hidden = !handle;
    } catch (err) {
        if (id === generation) status.textContent = labels[err.message] || labels.invalid;
    }
}
function busy(value) {
    for (const input of [picker, date, list, folderButton, write]) input.disabled = value;
}
picker.onchange = () => {
    directory = handle = null;
    list.hidden = true;
    selected = picker.files[0];
    inspect();
};
date.oninput = inspect;
folderButton.onclick = async () => {
    busy(true);
    try {
        const folder = await window.showDirectoryPicker({mode: "readwrite", id: "dream-world-saves"});
        reset();
        directory = folder;
        selected = handle = null;
        picker.value = "";
        list.replaceChildren(new Option(labels.file, ""));
        list.hidden = true;
        const names = [];
        for await (const [name, entry] of folder.entries()) {
            if (entry.kind === "file" && /\.sav$/i.test(name)) names.push(name);
        }
        for (const name of names.sort()) list.add(new Option(name, name));
        list.hidden = !names.length;
        if (!names.length) status.textContent = labels.empty;
        if (names.length === 1) {
            list.value = names[0];
            handle = await folder.getFileHandle(list.value);
            await inspect();
        }
    } catch (err) {
        if (err.name !== "AbortError") status.textContent = labels.access;
    } finally { busy(false); }
};
list.onchange = async () => {
    reset();
    handle = null;
    busy(true);
    try {
        if (list.value) handle = await directory.getFileHandle(list.value);
        await inspect();
    } catch { status.textContent = labels.access; }
    finally { busy(false); }
};
async function put(file, bytes) {
    const stream = await file.createWritable({mode: "exclusive"});
    try { await stream.write(bytes); await stream.close(); }
    catch (err) { await stream.abort().catch(() => {}); throw err; }
}
write.onclick = async () => {
    if (!handle || !prepared || write.disabled) return;
    busy(true);
    let stream, backupName;
    try {
        stream = await handle.createWritable({mode: "exclusive"});
        const current = new Uint8Array(await (await handle.getFile()).arrayBuffer());
        if (current.length !== original.length || !original.every((v, i) => current[i] === v)) {
            await stream.abort();
            stream = null;
            await inspect();
            status.textContent = labels.changed;
            return;
        }
        backupName = handle.name + "." + crypto.randomUUID() + ".bak";
        const backup = await directory.getFileHandle(backupName, {create: true});
        await put(backup, original);
        const savedBackup = new Uint8Array(await (await backup.getFile()).arrayBuffer());
        if (savedBackup.length !== original.length || !savedBackup.every((v, i) => v === original[i])) throw Error();
        await stream.write(prepared);
        await stream.close();
        stream = null;
        reset();
        status.textContent = labels.done.replace("{file}", backupName);
    } catch {
        if (stream) await stream.abort().catch(() => {});
        status.textContent = labels.access;
    } finally { busy(false); }
};
