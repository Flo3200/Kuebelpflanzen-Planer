import { describe, expect, it } from "vitest";
import { hm, onBreak, stopProgress, tourEvents, type DEvent, type DTour } from "./data";
import type { QueuedEvent } from "./sync";

const ev = (kind: string, at: string, stop: string | null = "s1", id = `${kind}-${at}`): DEvent => ({ client_id: id, kind, stop_id: stop, plant_id: null, at });

describe("driver progress", () => {
  it("keeps the time of each step per stop", () => {
    const events = [ev("arrive", "2026-10-19T09:00:00Z"), ev("carry_start", "2026-10-19T09:05:00Z"), ev("arrive", "2026-10-19T10:00:00Z", "s2")];
    expect(stopProgress(events, "s1")).toEqual({ arrive: "2026-10-19T09:00:00Z", carry_start: "2026-10-19T09:05:00Z" });
    expect(stopProgress(events, "s2")).toEqual({ arrive: "2026-10-19T10:00:00Z" });
  });

  it("knows whether a break is running", () => {
    expect(onBreak([ev("break_start", "a", null)])).toBe(true);
    expect(onBreak([ev("break_start", "a", null), ev("break_end", "b", null)])).toBe(false);
    expect(onBreak([])).toBe(false);
  });

  it("merges server events with queued ones without duplicates, sorted by time", () => {
    const tour = { id: "t1", events: [ev("arrive", "2026-10-19T09:00:00Z", "s1", "a")] } as unknown as DTour;
    const queued: QueuedEvent[] = [
      { type: "event", client_id: "a", tour_id: "t1", stop_id: "s1", kind: "arrive", at: "2026-10-19T09:00:00Z" },
      { type: "event", client_id: "b", tour_id: "t1", stop_id: "s1", kind: "carry_start", at: "2026-10-19T09:03:00Z" },
      { type: "event", client_id: "c", tour_id: "other", stop_id: "x", kind: "arrive", at: "2026-10-19T08:00:00Z" },
    ];
    const merged = tourEvents(tour, queued);
    expect(merged.map((e) => e.client_id)).toEqual(["a", "b"]);
    expect(merged[1].queued).toBe(true);
  });

  it("formats minutes after midnight", () => {
    expect(hm(0)).toBe("00:00");
    expect(hm(605)).toBe("10:05");
    expect(hm(null)).toBe("–");
  });
});
