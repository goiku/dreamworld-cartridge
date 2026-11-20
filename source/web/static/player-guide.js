(() => {
  const card = document.getElementById("dns");
  const message = document.getElementById("dns-message");
  const address = document.getElementById("dns-address");
  const refresh = document.getElementById("refresh-dns");
  const copy = document.getElementById("copy-dns");

  const device = document.getElementById("dns-device");
  let generation = 0;
  if (location.hash === "#melonDS") {
    device.value = "melonDS";
    card.scrollIntoView();
  }

  async function check() {
    const current = ++generation;
    const emulator = device.value === "melonDS";
    const offline = emulator ? card.dataset.emulatorOffline : card.dataset.offline;
    document.getElementById("emulator-guide").hidden = !emulator;
    refresh.disabled = true;
    address.hidden = true;
    address.textContent = "";
    copy.hidden = true;
    copy.textContent = copy.dataset.copy;
    message.textContent = card.dataset.checking;
    try {
      const response = await fetch(emulator ? device.dataset.emulator : card.dataset.endpoint, {cache: "no-store"});
      if (!response.ok) throw new Error("DNS lookup unavailable");
      const result = await response.json();
      if (generation !== current) return;
      if (result.status === "ready" && result.address) {
        address.textContent = result.address;
        address.hidden = false;
        copy.hidden = !navigator.clipboard?.writeText;
        message.textContent = card.dataset.ready;
      } else {
        message.textContent = result.status === "ambiguous" && !emulator ? card.dataset.ambiguous : offline;
      }
    } catch {
      if (generation === current) message.textContent = offline;
    } finally {
      if (generation === current) refresh.disabled = false;
    }
  }

  copy.addEventListener("click", async () => {
    const value = address.textContent;
    try {
      await navigator.clipboard.writeText(value);
      if (address.textContent === value) copy.textContent = copy.dataset.copied;
    } catch {
      const range = document.createRange();
      range.selectNodeContents(address);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  });
  device.addEventListener("change", check);
  refresh.addEventListener("click", check);
  check();
})();
