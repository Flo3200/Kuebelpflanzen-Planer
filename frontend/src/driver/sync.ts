// Offline queue: events, photos and deviation reports are stored locally first and sent when online.
// Order on sync: photos, then events (oldest first), then reports. Everything carries a client_id,
// so a resend after a lost answer creates nothing twice on the server.
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import { idb } from "./idb";

export interface QueuedEvent {
  type: "event";
  client_id: string;
  tour_id: string;
  stop_id?: string | null;
  plant_id?: string | null;
  kind: string;
  at: string;
  photo_client_id?: string;
  data?: Record<string, unknown>;
  error?: string;
}

export interface QueuedDeviation {
  type: "deviation";
  client_id: string;
  tour_id: string;
  stop_id: string;
  plant_id?: string | null;
  kind: string;
  note?: string;
  values?: Record<string, number>;
  photo_client_ids: string[];
  at: string;
  error?: string;
}

export interface QueuedPhoto {
  client_id: string;
  stop_id: string;
  plant_id?: string | null;
  kind: string;
  blob: Blob;
  uploaded?: boolean;
  error?: string;
}

type Item = QueuedEvent | QueuedDeviation;

// errors that will never succeed: kept aside and shown, never resent automatically
const PERMANENT = new Set(["errors.event_kind", "errors.event_stop", "errors.event_plant", "errors.event_time", "errors.not_found", "errors.event_client_id"]);

export function newId(): string {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

type Status = { online: boolean; pending: number; failed: number; syncing: boolean; lastSync: string | null; lastError: string | null };
let status: Status = { online: navigator.onLine, pending: 0, failed: 0, syncing: false, lastSync: null, lastError: null };
const listeners = new Set<(s: Status) => void>();
const changeListeners = new Set<() => void>();

function setStatus(patch: Partial<Status>) {
  status = { ...status, ...patch };
  listeners.forEach((l) => l(status));
}

export function useSyncStatus(): Status {
  const [s, set] = useState(status);
  useEffect(() => {
    listeners.add(set);
    return () => void listeners.delete(set);
  }, []);
  return s;
}

/** Called whenever the local queue changed (so screens can show progress made offline). */
export function onQueueChange(fn: () => void): () => void {
  changeListeners.add(fn);
  return () => void changeListeners.delete(fn);
}

async function refreshCounts() {
  const items = await idb.all<Item>("queue");
  setStatus({ pending: items.filter((i) => !i.error).length, failed: items.filter((i) => i.error).length });
  changeListeners.forEach((f) => f());
}

export async function queuedItems(): Promise<Item[]> {
  return idb.all<Item>("queue");
}

/** Events already accepted by the server but not yet in the stored day package. */
export async function ackedEvents(): Promise<QueuedEvent[]> {
  return (await idb.get<QueuedEvent[]>("kv", "acked")) ?? [];
}

/** Forget acknowledged events once the server's day package contains them (or after two days). */
export async function pruneAcked(known: Set<string>): Promise<void> {
  const limit = new Date(Date.now() - 2 * 86_400_000).toISOString();
  const keep = (await ackedEvents()).filter((e) => !known.has(e.client_id) && e.at > limit);
  await idb.put("kv", keep, "acked");
}

export async function addEvent(ev: Omit<QueuedEvent, "type" | "client_id" | "at"> & { at?: string }): Promise<QueuedEvent> {
  const item: QueuedEvent = { type: "event", client_id: newId(), at: ev.at ?? new Date().toISOString(), ...ev };
  await idb.put("queue", item);
  await refreshCounts();
  void flush();
  return item;
}

export async function addDeviation(d: Omit<QueuedDeviation, "type" | "client_id" | "at">): Promise<void> {
  await idb.put("queue", { type: "deviation", client_id: newId(), at: new Date().toISOString(), ...d });
  await refreshCounts();
  void flush();
}

/** Shrinks a camera photo (max 1600 px, JPEG) before storing it. */
export async function shrink(file: Blob, max = 1600): Promise<Blob> {
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d")!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    return await new Promise<Blob>((res) => canvas.toBlob((b) => res(b ?? file), "image/jpeg", 0.82));
  } catch {
    return file;
  }
}

export async function addPhoto(blob: Blob, meta: { stop_id: string; plant_id?: string | null; kind: string }): Promise<string> {
  const client_id = newId();
  await idb.put("photos", { client_id, blob: await shrink(blob), ...meta });
  void flush();
  return client_id;
}

export async function discardFailed(client_id: string): Promise<void> {
  await idb.del("queue", client_id);
  await refreshCounts();
}

/** What the server gets: the item without the local bookkeeping fields. */
function payload(item: Item): Record<string, unknown> {
  const out: Record<string, unknown> = { ...item };
  delete out.type;
  delete out.error;
  return out;
}

let running: Promise<void> | null = null;

export function flush(): Promise<void> {
  if (running) return running;
  running = doFlush().finally(() => {
    running = null;
  });
  return running;
}

async function doFlush(): Promise<void> {
  if (!navigator.onLine) {
    setStatus({ online: false });
    await refreshCounts();
    return;
  }
  setStatus({ syncing: true, online: true });
  try {
    // 1. photos
    for (const p of await idb.all<QueuedPhoto>("photos")) {
      if (p.uploaded) continue;
      const form = new FormData();
      form.append("file", p.blob, "foto.jpg");
      form.append("client_id", p.client_id);
      form.append("stop_id", p.stop_id);
      form.append("kind", p.kind);
      if (p.plant_id) form.append("plant_id", p.plant_id);
      await api.upload("/api/driver/photos", form);
      await idb.del("photos", p.client_id);
    }
    // 2. events
    const items = (await idb.all<Item>("queue")).filter((i) => !i.error);
    const events = items.filter((i): i is QueuedEvent => i.type === "event").sort((a, b) => a.at.localeCompare(b.at));
    const sent: QueuedEvent[] = [];
    for (let i = 0; i < events.length; i += 200) {
      const chunk = events.slice(i, i + 200);
      const res = await api.post<{ results: { client_id: string; ok: boolean; error?: string }[] }>("/api/driver/events", {
        events: chunk.map(payload),
      });
      for (const r of res.results) {
        const item = chunk.find((e) => e.client_id === r.client_id);
        if (!item) continue;
        if (r.ok) {
          await idb.del("queue", r.client_id);
          sent.push(item);
        }
        else if (r.error && PERMANENT.has(r.error)) await idb.put("queue", { ...item, error: r.error });
        // anything else (e.g. photo not there yet) stays queued and is tried again
      }
    }
    // sent events stay visible locally until the next day package contains them
    if (sent.length) await idb.put("kv", [...((await idb.get<QueuedEvent[]>("kv", "acked")) ?? []), ...sent], "acked");
    // 3. deviation reports
    for (const d of items.filter((i): i is QueuedDeviation => i.type === "deviation")) {
      try {
        await api.post("/api/driver/deviations", payload(d));
        await idb.del("queue", d.client_id);
      } catch (e) {
        if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 401) await idb.put("queue", { ...d, error: e.code });
        else throw e;
      }
    }
    setStatus({ lastSync: new Date().toISOString(), lastError: null });
  } catch (e) {
    setStatus({ lastError: e instanceof Error ? e.message : String(e), online: navigator.onLine });
  } finally {
    setStatus({ syncing: false });
    await refreshCounts();
  }
}

let started = false;

export function startSync(): void {
  if (started) return;
  started = true;
  window.addEventListener("online", () => {
    setStatus({ online: true });
    void flush();
  });
  window.addEventListener("offline", () => setStatus({ online: false }));
  setInterval(() => void flush(), 30_000);
  void refreshCounts().then(() => flush());
}
