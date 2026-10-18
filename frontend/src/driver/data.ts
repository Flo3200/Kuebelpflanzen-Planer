// Day package for the driver (today and tomorrow), cached for offline use, plus the local view of
// progress: server events merged with events still waiting in the queue.
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { LoadPlanPayload } from "../components/loadplan/types";
import type { TourHead } from "../components/loadplan/LoadPlanView";
import { idb } from "./idb";
import { ackedEvents, onQueueChange, pruneAcked, queuedItems, type QueuedEvent } from "./sync";

export interface DPlant {
  id: string;
  number: number;
  name: string;
  label: string | null;
  pot_d: number;
  pot_h: number;
  height: number;
  crown_w: number;
  weight: number | null;
  crew: number | null;
  equipment: string | null;
  can_tilt: boolean | null;
  sensitive: boolean | null;
  must_secure: boolean;
  notes: string | null;
  photos: { id: string; url: string; kind: string }[];
}

export interface DStop {
  id: string;
  position: number;
  status: string;
  arrival_min: number;
  start_min: number;
  end_min: number;
  team_size: number;
  predicted_min: number;
  experiment: boolean;
  order: { id: string; number: string; notes: string | null; direction: string } | null;
  customer: { name: string; phone: string | null; notes: string | null; preferred_contact: string | null } | null;
  address: {
    street: string;
    postal_code: string;
    city: string;
    lat: number | null;
    lon: number | null;
    parking_notes: string | null;
    bell_notes: string | null;
    access_notes: string | null;
  } | null;
  nav: { google?: string; apple?: string };
  plants: DPlant[];
  paths: {
    id: string;
    name: string;
    notes: string | null;
    length_m: number;
    segments: { kind: string; length_m: number; steps: number; min_width_cm: number | null; surface: string; slope_pct: number; elevator: boolean; notes: string | null }[];
    photos: { id: string; url: string; kind: string }[];
  }[];
  equipment: string[];
}

export interface DEvent {
  client_id: string;
  kind: string;
  stop_id: string | null;
  plant_id: string | null;
  at: string;
  queued?: boolean;
}

export interface DTour {
  id: string;
  date: string;
  label: string;
  trip_no: number;
  color: string;
  status: string;
  start_min: number;
  end_min: number;
  breaks: { start: number; end: number }[];
  distance_km: number;
  vehicle: { name: string; plate?: string };
  trailer: { name: string; plate?: string } | null;
  members: { id: string; name: string; phone: string | null; driver: boolean }[];
  stops: DStop[];
  events: DEvent[];
  load: { tour: TourHead; plan: LoadPlanPayload | null };
}

export interface DriverMe {
  name: string;
  staff_id: string | null;
  settings: { per_plant_events: boolean; require_pickup_photo: boolean; qr_module: boolean };
}

export interface DayPackage {
  from: string;
  days: number;
  generated_at: string;
  tours: DTour[];
}

export function isNetworkError(e: unknown): boolean {
  return !(e instanceof ApiError) || e.status === 0 || e.status >= 500;
}

/** Driver identity; offline the last known one is used. null = must log in. */
export function useDriverMe() {
  const [me, setMe] = useState<DriverMe | null | undefined>(undefined);
  const load = useCallback(async () => {
    try {
      const m = await api.get<DriverMe>("/api/driver/me");
      await idb.put("kv", m, "me");
      setMe(m);
    } catch (e) {
      if (isNetworkError(e)) setMe((await idb.get<DriverMe>("kv", "me")) ?? null);
      else setMe(null);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return { me, reload: load };
}

/** Today + tomorrow; refreshed when online, otherwise the stored copy. */
export function useDay() {
  const [day, setDay] = useState<DayPackage | null>(null);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<QueuedEvent[]>([]);
  const load = useCallback(async () => {
    const cached = await idb.get<DayPackage>("kv", "day");
    if (cached) setDay(cached);
    try {
      const fresh = await api.get<DayPackage>("/api/driver/day", { days: 2 });
      await idb.put("kv", fresh, "day");
      await pruneAcked(new Set(fresh.tours.flatMap((x) => x.events.map((e) => e.client_id))));
      setDay(fresh);
      setOffline(false);
      setError(null);
    } catch (e) {
      if (isNetworkError(e)) setOffline(true);
      else setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  const loadQueue = useCallback(async () => {
    const waiting = (await queuedItems()).filter((i): i is QueuedEvent => i.type === "event" && !i.error);
    setQueued([...(await ackedEvents()), ...waiting]);
  }, []);
  useEffect(() => {
    void load();
    void loadQueue();
    const off = onQueueChange(() => void loadQueue());
    const timer = setInterval(() => void load(), 5 * 60_000);
    return () => {
      off();
      clearInterval(timer);
    };
  }, [load, loadQueue]);
  return { day, offline, error, reload: load, queued };
}

/** All events of a tour: from the server plus those still waiting locally. */
export function tourEvents(tour: DTour, queued: QueuedEvent[]): DEvent[] {
  const known = new Set(tour.events.map((e) => e.client_id));
  const local = queued
    .filter((q) => q.tour_id === tour.id && !known.has(q.client_id))
    .map((q) => ({ client_id: q.client_id, kind: q.kind, stop_id: q.stop_id ?? null, plant_id: q.plant_id ?? null, at: q.at, queued: true }));
  return [...tour.events, ...local].sort((a, b) => a.at.localeCompare(b.at));
}

export const STEP_KINDS = ["arrive", "carry_start", "loaded", "leave"] as const;

/** Progress of one stop: time of each step done (last one wins). */
export function stopProgress(events: DEvent[], stopId: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of events) if (e.stop_id === stopId) out[e.kind] = e.at;
  return out;
}

export function onBreak(events: DEvent[]): boolean {
  let open = false;
  for (const e of events) {
    if (e.kind === "break_start") open = true;
    if (e.kind === "break_end") open = false;
  }
  return open;
}

export function hm(min: number | null | undefined): string {
  if (min == null) return "–";
  const m = Math.round(min);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
}

export function localDate(d = new Date()): string {
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60_000).toISOString().slice(0, 10);
}
