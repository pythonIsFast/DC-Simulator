// Formatting and DOM helpers.
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export const money = (cents) => usd.format(Math.round(cents / 100));
export const money2 = (cents) => usd2.format(cents / 100);
export const signedMoney = (cents) => (cents >= 0 ? "+" : "-") + usd.format(Math.abs(Math.round(cents / 100)));
export const num = (v, digits = 0) => Number(v).toLocaleString("en-US", { maximumFractionDigits: digits });
export const pct = (v, digits = 0) => (v * 100).toFixed(digits) + " %";
export const kw = (w) => (w / 1000).toFixed(1) + " kW";

export function dateText(tick) {
  const day = Math.floor(tick / 24) + 1;
  const hour = String(Math.floor(tick % 24)).padStart(2, "0");
  return `Day ${day}, ${hour}:00`;
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const $ = (id) => document.getElementById(id);

export function bar(fraction, kind = "") {
  const f = Math.max(0, Math.min(1, fraction || 0));
  return h("div", { class: "bar " + kind }, h("i", { style: `width:${(f * 100).toFixed(1)}%` }));
}

export function stat(label, value, cls = "") {
  return h("div", { class: "stat" }, h("span", { class: "muted" }, label), h("span", { class: cls }, value));
}

// Collapsible sections are rebuilt on every state update; remember which ones the user opened.
const detailState = new Map();
export function keepDetails(root, scope) {
  root.querySelectorAll("details").forEach((d) => {
    const title = (d.querySelector("summary")?.textContent || "").replace(/\s*\(.*\)$/, "");
    const key = `${scope}:${title}`;
    if (detailState.has(key)) d.open = detailState.get(key);
    d.addEventListener("toggle", () => detailState.set(key, d.open));
  });
}
