(() => {
  const tools = document.getElementById("dw-friend-tools");
  if (!tools) return;
  const target = JSON.parse(document.getElementById("dw-friend-data").textContent);
  const updated = tools.querySelector("[data-updated]");
  const adventure = tools.querySelector("[data-adventure]");
  const profile = tools.querySelector("[data-profile]");
  const panel = document.getElementById("dw-friend-panel");
  const frame = panel.querySelector("iframe");
  const roster = tools.querySelector("[data-roster]");
  const owner = tools.querySelector("[data-owner]");
  const time = tools.querySelector("time");
  let navigation = 0;

  function show(room, showRoster = false) {
    const profilePath = room && "/islands/" + room.shared_island_id + "/profile";
    if (panel.open && profile.getAttribute("href") !== profilePath) panel.close();
    tools.hidden = !room && !showRoster;
    roster.hidden = Boolean(room);
    owner.hidden = updated.hidden = adventure.hidden = profile.hidden = !room;
    if (room) {
      owner.textContent = room.pgl_name;
      const stamp = new Date(room.shared_updated_at * 1000);
      time.dateTime = stamp.toISOString();
      time.textContent = stamp.toLocaleString(document.documentElement.lang || undefined);
      const path = "/islands/" + room.shared_island_id;
      adventure.href = path + "/adventure";
      profile.href = profilePath;
    }
  }

  profile.addEventListener("click", event => {
    if (!panel.showModal || event.ctrlKey || event.shiftKey || event.metaKey || event.altKey) return;
    event.preventDefault();
    frame.src = profile.href + "?in_room=1";
    panel.showModal();
  });
  panel.addEventListener("close", () => frame.removeAttribute("src"));

  const gameApi = target && "/islands/" + target.island_id + "/game-api/";
  if (gameApi) {
    // The archived header uses jQuery before Flash starts. Its ordinary homepage
    // initializer settles old Berries; the visiting tab explicitly reads them only.
    window.jQuery.ajaxPrefilter((options, original) => {
      if (original.url === "/api/" && original.data?.p === "pgl.top.init") options.url = gameApi;
    });
  }
  window.dwVisitIsOpen = () => Boolean(target);
  window.dwVisitTarget = () => target && {...target, api_url: gameApi};
  window.dwVisitScene = (scene, ownHome) => {
    if (target && scene === "scene_home" && ownHome) {
      location.assign("/pdw/");
      return true;
    }
    return false;
  };

  // Ruffle can pass a URL or an existing Request for its root and nested movies.
  // Only the two bootstrap files on a direct visit use our read-only variants.
  const movies = new Set(["/src/swf/theme/assets/common/main.swf", "/src/swf/pdw/assets/pdw_main.swf"]);
  const bridge = new Set(["pdw.home.my_bridge", "pdw.home.friend_bridge", "pdw.home.friend_list",
                          "pdw.home.my_island_area", "pdw.home.friend_island_area"]);
  const originalFetch = window.fetch;
  window.fetch = function(resource, options) {
    const url = new URL(resource instanceof Request ? resource.url : resource, location.href);
    if (url.origin !== location.origin) return originalFetch.call(this, resource, options);
    if (target && movies.has(url.pathname)) {
      url.searchParams.set("dw-visit", "1");
      resource = resource instanceof Request ? new Request(url, resource) : url;
    }
    const pending = originalFetch.call(this, resource, options);
    if (url.pathname !== "/api/" && !/^\/islands\/[a-f0-9]{64}\/game-api\/$/.test(url.pathname)) return pending;
    const action = url.searchParams.get("p");
    if (action === "pdw.home.friend_island") {
      const generation = ++navigation;
      // The timestamp comes from the same response as the visible furniture.
      // A background sync cannot relabel a room still displaying an older layout.
      pending.then(response => response.ok ? response.clone().json() : null).then(room => {
        if (generation === navigation) show(room && /^[a-f0-9]{64}$/.test(room.shared_island_id) ? room : null);
      }).catch(() => { if (generation === navigation) show(null); });
    } else if (action === "pdw.home.my_island" || bridge.has(action)) {
      ++navigation;
      show(null, bridge.has(action));
    }
    return pending;
  };

  function moveTools() {
    const movie = document.getElementById("flashcontent");
    if (movie) movie.parentNode.insertBefore(tools, movie);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", moveTools);
  else moveTools();
})();
