(() => {
  const card = document.getElementById("dns");
  const message = document.getElementById("dns-message");
  const address = document.getElementById("dns-address");
  const refresh = document.getElementById("refresh-dns");
  const copy = document.getElementById("copy-dns");

  async function check() {
    refresh.disabled = true;
    address.hidden = true;
    address.textContent = "";
    copy.hidden = true;
    copy.textContent = copy.dataset.copy;
    message.textContent = card.dataset.checking;
    try {
      const response = await fetch(card.dataset.endpoint, {cache: "no-store"});
      if (!response.ok) throw new Error("DNS lookup unavailable");
      const result = await response.json();
      if (result.status === "ready" && result.address) {
        address.textContent = result.address;
        address.hidden = false;
        copy.hidden = !navigator.clipboard?.writeText;
        message.textContent = card.dataset.ready;
      } else {
        message.textContent = result.status === "ambiguous" ? card.dataset.ambiguous : card.dataset.offline;
      }
    } catch {
      message.textContent = card.dataset.offline;
    } finally {
      refresh.disabled = false;
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
  refresh.addEventListener("click", check);
  check();
})();
