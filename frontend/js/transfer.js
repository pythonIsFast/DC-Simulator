// Move saves between devices: export all worlds into one file, import such a file on another device.
import { getToken } from "./api.js";
import { $, h } from "./util.js";

const days = (tick) => `day ${Math.floor(tick / 24) + 1}`;
const worldList = (worlds) => (worlds.length ? worlds.map((w) => `${w.name} (${days(w.tick)})`).join(", ") : "no worlds");

async function raw(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/octet-stream";
  const res = await fetch(path, { method, headers, body, cache: "no-store" });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return res;
}

function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

// The Android app provides window.AndroidBridge (system "save as" dialog); in a browser a normal download is used.
function deliver(name, buffer) {
  if (window.AndroidBridge) { window.AndroidBridge.saveFile(name, toBase64(buffer)); return; }
  const url = URL.createObjectURL(new Blob([buffer], { type: "application/octet-stream" }));
  const a = h("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export async function renderTransfer() {
  const box = $("transfer");
  const body = $("transfer-body");
  let info;
  try {
    info = await (await raw("GET", "/api/save/info")).json();
  } catch {
    box.hidden = true;  // multiplayer server (or server not reachable): the feature does not apply
    return;
  }
  box.hidden = false;

  const msg = h("p", { style: "min-height:1.2rem;margin:.4rem 0" });
  const say = (text, cls = "") => { msg.className = cls; msg.textContent = text; };
  const picker = h("input", { type: "file", hidden: true });
  picker.addEventListener("change", async () => {
    const file = picker.files[0];
    picker.value = "";
    if (!file) return;
    try {
      const data = await file.arrayBuffer();
      const worlds = (await (await raw("POST", "/api/save/inspect", data)).json()).worlds;
      if (!confirm(`This file contains: ${worldList(worlds)}.\n\nReplace ALL saves on this device with it? A backup copy of the current saves is kept.`)) return;
      await raw("POST", "/api/save/import", data);
      say("Imported. Reloading...", "good");
      setTimeout(() => location.reload(), 600);
    } catch (e) { say(e.message, "bad"); }
  });

  body.replaceChildren(
    h("p", { class: "muted", style: "font-size:.85rem" },
      "Export saves all your worlds into one file. Send it to your other device (cloud drive, messenger, e-mail, USB) and import it there. Importing replaces all saves on that device."),
    h("div", { class: "item" }, h("div", { class: "title" }, h("span", {}, "This device")), h("div", { class: "sub" }, worldList(info.worlds))),
    h("div", { class: "row", style: "margin-top:.4rem" },
      h("button", { class: "small", onclick: async () => {
        try {
          const res = await raw("GET", "/api/save/export");
          deliver(res.headers.get("X-Filename") || "datacenter-tycoon.dcsave", await res.arrayBuffer());
          say(window.AndroidBridge ? "Choose where to save the file." : "Save file downloaded.", "good");
        } catch (e) { say(e.message, "bad"); }
      } }, "Export save file"),
      h("button", { class: "small secondary", onclick: () => picker.click() }, "Import save file"), picker),
    msg);
}
