// Shapes of the load plan payload (backend: app/packing/service.py result_payload).

export interface LPDims {
  pot_shape: "round" | "square";
  pot_d: number;
  pot_l: number;
  pot_w: number;
  pot_h: number;
  crown_shape: string;
  crown_w: number;
  crown_h: number;
  crown_start: number;
  total_h: number;
  box: [number, number, number];
  weight: number;
}

export interface LPPlacement {
  plant_id: string;
  order_id: string;
  stop_position: number;
  number: number;
  label: string;
  sequence: number;
  space_id: string;
  level: string;
  orientation: "upright" | "lying_x" | "lying_y" | "tilted_x";
  angle: number;
  x: number;
  y: number;
  z: number;
  dims: LPDims;
  instruction: string;
  secure: boolean;
}

export interface LPObstacle {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  z1: number;
}

export interface LPShelf {
  id: string;
  name: string;
  x0: number;
  y0: number;
  length: number;
  depth: number;
  z: number;
  clearance: number;
  max_load: number;
  blocks_floor: boolean;
}

export interface LPSpace {
  id: string;
  name: string;
  kind: string;
  length: number;
  width: number;
  height: number;
  door_w: number;
  door_h: number;
  payload: number;
  obstacles: LPObstacle[];
  shelves: LPShelf[];
}

export interface LoadPlanPayload {
  ok?: boolean;
  message?: string;
  placements: LPPlacement[];
  metrics: {
    spaces?: Record<string, Record<string, number>>;
    placed?: number;
    unplaced?: number;
    seconds?: number;
    /** package G: rules | ai_start | compare */
    mode?: string;
    ai?: { model: string; seconds: number; cost_eur: number };
    ai_error?: string;
    start?: { positions_proposed: number; positions_valid: number; score: number };
    compare?: { winner: string; rules: Record<string, any>; ai_start: Record<string, any> };
  };
  violations: string[];
  unplaced: { plant_id: string; number: number; reason: string; label?: string }[];
  spaces: LPSpace[];
  iterations?: number;
}

// One colour per stop; the same palette as the tours (works on light and dark backgrounds).
export const STOP_COLORS = ["#2b5139", "#c2693e", "#2f5f8a", "#8a6d1d", "#7b4b8a", "#3d8a85", "#a33b4f", "#5c7a2e", "#4a5a9a", "#b0782a"];

export function stopColor(position: number): string {
  return STOP_COLORS[(Math.max(1, position) - 1) % STOP_COLORS.length];
}
