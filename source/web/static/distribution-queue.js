(() => {
  let etag;
  let loading = false;
  async function refresh() {
    if (document.hidden || loading) return;
    loading = true;
    const error = document.getElementById("queue-error");
    try {
      const response = await fetch(location.href, {
        cache: "no-store",
        headers: etag ? {"If-None-Match": etag} : {},
      });
      if (response.status !== 304) {
        if (!response.ok) throw new Error("Queue unavailable");
        const page = new DOMParser().parseFromString(await response.text(), "text/html");
        const next = page.getElementById("receiver-queue");
        if (!next) throw new Error("Missing queue");
        const current = document.getElementById("receiver-queue");
        if (!current.isEqualNode(next)) current.replaceWith(next);
        etag = response.headers.get("ETag");
      }
      error.hidden = true;
    } catch {
      error.hidden = false;
    } finally {
      loading = false;
    }
  }
  window.setInterval(refresh, 15000);
  document.addEventListener("visibilitychange", refresh);
  window.addEventListener("pageshow", event => { if (event.persisted) refresh(); });
})();
