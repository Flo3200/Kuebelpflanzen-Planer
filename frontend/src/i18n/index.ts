// All UI texts come from <lang>.json. t("a.b.c", {n: 3}) replaces {n} in the text.
import de from "./de.json";

type Catalog = { [key: string]: string | Catalog };

const catalogs: Record<string, Catalog> = { de: de as Catalog };
let current = "de";

export function setLanguage(lang: string) {
  if (catalogs[lang]) current = lang;
}

export function t(key: string, params?: Record<string, string | number | null | undefined>): string {
  let node: string | Catalog | undefined = catalogs[current];
  for (const part of key.split(".")) {
    if (node && typeof node === "object" && part in node) node = node[part];
    else {
      node = undefined;
      break;
    }
  }
  let text = typeof node === "string" ? node : key;
  if (params) {
    for (const [k, v] of Object.entries(params)) text = text.split(`{${k}}`).join(String(v ?? ""));
  }
  return text;
}

/** Like t(), but returns undefined if the key does not exist. */
export function tMaybe(key: string): string | undefined {
  const value = t(key);
  return value === key ? undefined : value;
}

const numberFormats = new Map<string, Intl.NumberFormat>();

export function fmtNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const key = `${current}-${digits}`;
  let f = numberFormats.get(key);
  if (!f) {
    f = new Intl.NumberFormat("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    numberFormats.set(key, f);
  }
  return f.format(value);
}

export function fmtMoney(value: number | null | undefined, currency = "EUR"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return new Intl.NumberFormat("de-DE", { style: "currency", currency }).format(value);
}

export function fmtDate(value: string | Date | null | undefined, withTime = false): string {
  if (!value) return "–";
  const d = typeof value === "string" ? new Date(value) : value;
  return d.toLocaleString("de-DE", withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}

export function fmtMinutes(min: number | null | undefined): string {
  if (min === null || min === undefined || Number.isNaN(min)) return "–";
  const m = Math.round(min);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}
