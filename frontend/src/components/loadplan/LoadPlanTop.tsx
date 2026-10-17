// Top view of a load plan (SVG): front wall on the left, door on the right.
import { t } from "../../i18n";
import type { LoadPlanPayload, LPPlacement, LPSpace } from "./types";
import { stopColor } from "./types";

const PAD = 28;
const GAP = 60;

function PlantShape({ p, current, dim, onPick }: { p: LPPlacement; current: boolean; dim: boolean; onPick?: (p: LPPlacement) => void }) {
  const d = p.dims;
  const color = stopColor(p.stop_position);
  const common = {
    fill: color,
    stroke: current ? "var(--accent)" : "var(--surface)",
    strokeWidth: current ? 3 : 1,
    opacity: dim ? 0.35 : 1,
    style: { cursor: onPick ? "pointer" : undefined },
    onClick: onPick ? () => onPick(p) : undefined,
  };
  const label = (
    <text x={p.x} y={p.y} textAnchor="middle" dominantBaseline="central" fontSize={Math.max(9, Math.min(16, d.pot_d * 0.45))} fill="#fff" fontWeight={600} pointerEvents="none">
      {p.sequence}
    </text>
  );
  const title = <title>{`${p.sequence}. ${p.label} – ${p.instruction}`}</title>;
  if (p.orientation === "upright") {
    return (
      <g>
        {/* crown outline: may overlap neighbouring crowns by the allowed amount */}
        <circle cx={p.x} cy={p.y} r={d.crown_w / 2} fill={color} fillOpacity={dim ? 0.04 : 0.1} stroke={color} strokeOpacity={0.5} strokeDasharray="4 3" pointerEvents="none" />
        {d.pot_shape === "round" ? (
          <circle cx={p.x} cy={p.y} r={d.pot_d / 2} {...common}>
            {title}
          </circle>
        ) : (
          <rect x={p.x - d.pot_l / 2} y={p.y - d.pot_w / 2} width={d.pot_l} height={d.pot_w} rx={3} {...common}>
            {title}
          </rect>
        )}
        {label}
      </g>
    );
  }
  const [lx, ly] = d.box;
  const x0 = p.x - lx / 2;
  const y0 = p.y - ly / 2;
  // lying: pot end darker (front wall for lying_x, left wall for lying_y)
  const pot =
    p.orientation === "lying_y" ? <rect x={p.x - d.pot_d / 2} y={y0} width={d.pot_d} height={d.pot_h} fill="#000" fillOpacity={0.25} pointerEvents="none" /> : <rect x={x0} y={p.y - d.pot_d / 2} width={d.pot_h} height={d.pot_d} fill="#000" fillOpacity={0.25} pointerEvents="none" />;
  return (
    <g>
      <rect x={x0} y={y0} width={lx} height={ly} rx={ly / 2.5} {...common} fillOpacity={dim ? 0.3 : 0.85}>
        {title}
      </rect>
      {pot}
      {label}
    </g>
  );
}

function SpaceSvg({ sp, placements, step, onPick }: { sp: LPSpace; placements: LPPlacement[]; step: number | null; onPick?: (p: LPPlacement) => void }) {
  const floor = placements.filter((p) => p.space_id === sp.id && p.level === "floor");
  const shelved = placements.filter((p) => p.space_id === sp.id && p.level !== "floor");
  const visible = (p: LPPlacement) => step == null || p.sequence <= step;
  return (
    <g>
      <text x={0} y={-10} fontSize={14} fill="var(--text-muted)">
        {sp.name} · {sp.length}×{sp.width}×{sp.height} cm
      </text>
      <rect x={0} y={0} width={sp.length} height={sp.width} fill="var(--surface-2)" stroke="var(--text-muted)" strokeWidth={2} />
      {/* front wall and door */}
      <line x1={0} y1={0} x2={0} y2={sp.width} stroke="var(--text)" strokeWidth={5} />
      <line x1={sp.length} y1={(sp.width - sp.door_w) / 2} x2={sp.length} y2={(sp.width + sp.door_w) / 2} stroke="var(--accent)" strokeWidth={5} />
      <text x={sp.length + 8} y={sp.width / 2} fontSize={12} fill="var(--accent)" dominantBaseline="central" transform={`rotate(90 ${sp.length + 8} ${sp.width / 2})`} textAnchor="middle">
        {t("loadplan.door")}
      </text>
      <text x={-8} y={sp.width / 2} fontSize={12} fill="var(--text-muted)" dominantBaseline="central" transform={`rotate(-90 -8 ${sp.width / 2})`} textAnchor="middle">
        {t("loadplan.front_wall")}
      </text>
      {sp.obstacles.map((ob, i) => (
        <rect key={i} x={ob.x0} y={ob.y0} width={Math.min(ob.x1, sp.length) - ob.x0} height={ob.y1 - ob.y0} fill="url(#lp-hatch)" stroke="var(--text-faint)">
          <title>{t("loadplan.obstacle", { h: ob.z1 })}</title>
        </rect>
      ))}
      {sp.shelves.map((sh) => (
        <rect key={sh.id} x={sh.x0} y={sh.y0} width={sh.length} height={sh.depth} fill="none" stroke="#b8925a" strokeWidth={2} strokeDasharray="6 4">
          <title>{t("loadplan.shelf", { name: sh.name, z: sh.z })}</title>
        </rect>
      ))}
      {floor.map((p) => (visible(p) ? <PlantShape key={p.plant_id} p={p} current={p.sequence === step} dim={step != null && p.sequence < step} onPick={onPick} /> : null))}
      {shelved.map((p) =>
        visible(p) ? (
          <g key={p.plant_id} opacity={0.9}>
            <PlantShape p={p} current={p.sequence === step} dim={false} onPick={onPick} />
          </g>
        ) : null,
      )}
    </g>
  );
}

export function LoadPlanTop(props: { plan: LoadPlanPayload; step: number | null; onPick?: (p: LPPlacement) => void }) {
  const spaces = props.plan.spaces;
  let x = PAD;
  const offsets = spaces.map((sp) => {
    const o = x;
    x += sp.length + GAP;
    return o;
  });
  const w = x - GAP + PAD;
  const h = Math.max(...spaces.map((sp) => sp.width), 100) + PAD * 2 + 10;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="loadplan-top" role="img" aria-label={t("loadplan.view_top")}>
      <defs>
        <pattern id="lp-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" fill="var(--surface-3)" />
          <line x1="0" y1="0" x2="0" y2="8" stroke="var(--text-faint)" strokeWidth="2" />
        </pattern>
      </defs>
      {spaces.map((sp, i) => (
        <g key={sp.id} transform={`translate(${offsets[i]} ${PAD + 10})`}>
          <SpaceSvg sp={sp} placements={props.plan.placements} step={props.step} onPick={props.onPick} />
        </g>
      ))}
    </svg>
  );
}
