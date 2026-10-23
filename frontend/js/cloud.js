// Cloud save: the whole local database goes to a private GitHub gist, so PC and phone can share their saves.
import { api } from "./api.js";
import { $, h } from "./util.js";

const TOKEN_URL = "github.com/settings/tokens/new?scopes=gist&description=Datacenter%20Tycoon";
const device = () => (/Android/i.test(navigator.userAgent) ? "Android" : "PC");
const when = (ts) => new Date(ts * 1000).toLocaleString();
const days = (tick) => `day ${Math.floor(tick / 24) + 1}`;
const worldList = (worlds) => (worlds && worlds.length ? worlds.map((w) => `${w.name} (${days(w.tick)})`).join(", ") : "no worlds");

let busy = false;

export async function renderCloud() {
  const box = $("cloud");
  const body = $("cloud-body");
  let status;
  try {
    status = await api.cloudStatus();
  } catch (e) {
    // 403 = multiplayer server: the feature does not exist there. Other errors (e.g. no internet) are shown.
    box.hidden = e.status === 403;
    if (e.status !== 403) body.replaceChildren(h("p", { class: "bad" }, e.message), connectForm());
    return;
  }
  box.hidden = false;
  body.replaceChildren(status.connected ? connectedView(status) : connectForm());
}

function connectForm(note) {
  const input = h("input", { type: "password", placeholder: "GitHub token (gist scope)", autocomplete: "off" });
  const msg = h("p", { class: "bad", style: "min-height:1.2rem;margin:.2rem 0" }, note || "");
  return h("div", {},
    h("p", { class: "muted", style: "font-size:.85rem" },
      "Your saves are stored in a private GitHub gist. Create a token once (classic token, only the 'gist' scope) at: ",
      h("code", {}, TOKEN_URL), " and paste the same token on every device. The token stays on this device."),
    input, msg,
    h("button", { class: "small", onclick: async (ev) => {
      ev.target.disabled = true;
      try { await api.cloudConnect(input.value); await renderCloud(); } catch (e) { msg.textContent = e.message; ev.target.disabled = false; }
    } }, "Connect"));
}

function connectedView(s) {
  const msg = h("p", { style: "min-height:1.2rem;margin:.4rem 0" });
  const say = (text, cls = "") => { msg.className = cls; msg.textContent = text; };
  const run = (label, fn) => async (ev) => {
    if (busy) return;
    busy = true;
    const buttons = [...ev.target.closest("#cloud-body").querySelectorAll("button")];
    buttons.forEach((b) => (b.disabled = true));
    say(label + "...");
    try { await fn(); } catch (e) { say(e.message, "bad"); } finally { busy = false; buttons.forEach((b) => (b.disabled = false)); }
  };
  const remote = s.remote;
  return h("div", {},
    h("p", { style: "font-size:.88rem;margin:.3rem 0" }, `Connected as ${s.login || "GitHub user"}.`),
    h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, "This device")), h("div", { class: "sub" }, worldList(s.local))),
    h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, "Cloud")),
      h("div", { class: "sub" }, remote ? `${worldList(remote.worlds)} - saved ${when(remote.saved_at)} from ${remote.device}` : "Nothing saved yet")),
    h("div", { class: "row", style: "margin-top:.4rem" },
      h("button", { class: "small", onclick: run("Uploading", async () => {
        if (remote && !confirm(`Replace the cloud save from ${remote.device} (${when(remote.saved_at)}) with the saves of this device?`)) { say(""); return; }
        await api.cloudUpload(device());
        say("Uploaded.", "good");
        await renderCloud();
      }) }, "Upload"),
      h("button", { class: "small secondary", disabled: !remote, onclick: run("Downloading", async () => {
        if (!confirm(`Replace ALL saves on this device with the cloud save (${worldList(remote.worlds)})? A backup file of the current database is kept.`)) { say(""); return; }
        await api.cloudDownload();
        say("Downloaded. Reloading...", "good");
        setTimeout(() => location.reload(), 600);
      }) }, "Download"),
      h("button", { class: "small danger", onclick: async () => { await api.cloudDisconnect(); await renderCloud(); } }, "Disconnect")),
    msg);
}
