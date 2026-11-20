import {install,inspect} from "./pwt-save.mjs";
const t=JSON.parse(document.getElementById("text").textContent);
const picker=document.getElementById("save"), message=document.getElementById("message");
const copy=document.getElementById("copy"), buttons=[...document.querySelectorAll("button[data-number]")];
let current=null, generation=0, busy=false;
function render() {
    const slots=current?inspect(current):[];
    for (const button of buttons) {
        const found=slots.find(slot=>slot.number===Number(button.dataset.number));
        button.hidden=!current;
        button.disabled=busy || !!found || !slots.some(slot=>slot.empty);
        button.textContent=found?(found.crc===Number(button.dataset.crc)?t.installed:t.related):t.add;
    }
}
function discardCopy() {
    if (copy.href) URL.revokeObjectURL(copy.href);
    copy.removeAttribute("href");
    copy.hidden=true;
}
picker.addEventListener("change",async()=>{
    const file=picker.files[0],id=++generation;
    discardCopy(); current=null; busy=false; message.textContent=""; render();
    if (!file) return;
    try {
        if(file.size!==0x80000) throw Error("invalid");
        const data=new Uint8Array(await file.arrayBuffer());
        const slots=inspect(data);
        if (id!==generation) return;
        current=data;
        message.textContent=slots.some(slot=>slot.empty)?t.ready:t.full;
    } catch {if(id===generation) message.textContent=t.invalid;}
    render();
});
for (const button of buttons) button.addEventListener("click",async()=>{
    if (!current || busy) return;
    const id=generation;
    busy=true; render(); message.textContent=t.loading;
    try {
        const res=await fetch(button.parentElement.querySelector("a").href);
        if(!res.ok) throw Error("unavailable");
        const block=new Uint8Array(await res.arrayBuffer());
        if(id!==generation) return;
        const updated=install(current,block);
        discardCopy();
        copy.href=URL.createObjectURL(new Blob([updated],{type:"application/octet-stream"}));
        copy.download=picker.files[0].name.replace(/\.sav$/i,"")+"-PWT.sav";
        copy.hidden=false;
        current=updated; message.textContent=t.saved; copy.click();
    } catch(error) {if(id===generation) message.textContent=t[error.message] || t.unavailable;}
    finally {if(id===generation){busy=false;render();}}
});
