import { describe, expect, it } from "vitest";
import { stopColor, STOP_COLORS } from "../components/loadplan/types";
import de from "./de.json";
import { t, tMaybe } from "./index";

describe("translations", () => {
  it("inserts parameters", () => {
    expect(t("loadplan.step_of", { n: 2, total: 5 })).toBe("Schritt 2 von 5");
  });

  it("returns undefined for unknown keys with tMaybe", () => {
    expect(tMaybe("does.not.exist")).toBeUndefined();
  });

  it("has a German text for every driver event kind and deviation kind", () => {
    const kinds = ["shift_start", "depart", "arrive", "carry_start", "plant_done", "loaded", "leave", "break_start", "break_end", "unload", "shift_end", "qr_scan"];
    for (const k of kinds) expect(tMaybe(`driverapp.kinds.${k}`)).toBeTruthy();
    for (const k of ["plant_heavier", "plant_bigger", "path_different", "customer_absent", "damage", "other"]) {
      expect(tMaybe(`driverapp.deviation.${k}`)).toBeTruthy();
      expect(tMaybe(`deviations.kinds.${k}`)).toBeTruthy();
    }
  });

  it("has no empty texts", () => {
    const empty: string[] = [];
    const walk = (node: unknown, path: string) => {
      if (typeof node === "string") {
        if (!node.trim()) empty.push(path);
      } else if (node && typeof node === "object") {
        for (const [k, v] of Object.entries(node)) walk(v, path ? `${path}.${k}` : k);
      }
    };
    walk(de, "");
    expect(empty).toEqual([]);
  });
});

describe("load plan colours", () => {
  it("gives every stop a colour and repeats after the palette", () => {
    expect(stopColor(1)).toBe(STOP_COLORS[0]);
    expect(stopColor(STOP_COLORS.length + 1)).toBe(STOP_COLORS[0]);
    expect(stopColor(0)).toBe(STOP_COLORS[0]);
  });
});
