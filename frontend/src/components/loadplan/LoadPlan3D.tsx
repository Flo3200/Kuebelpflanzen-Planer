// 3D view of a load plan (three.js). Cargo coordinates: x from the front wall to the door,
// y from the left to the right wall, z up (cm). three.js: X = x, Y = z, Z = y, in metres.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { t } from "../../i18n";
import type { LoadPlanPayload, LPPlacement, LPSpace } from "./types";
import { stopColor } from "./types";

const S = 0.01; // cm -> m
const GAP = 120; // cm between vehicle and trailer in the scene

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function spaceOffsets(spaces: LPSpace[]): Record<string, number> {
  // vehicle first, trailer behind it (towards the door side of the vehicle)
  const out: Record<string, number> = {};
  let x = 0;
  for (const sp of spaces) {
    out[sp.id] = x;
    x += sp.length + GAP;
  }
  return out;
}

function crownMesh(p: LPPlacement, material: THREE.Material, radius: number): THREE.Mesh {
  const d = p.dims;
  const h = Math.max(5, d.crown_h);
  let geo: THREE.BufferGeometry;
  switch (d.crown_shape) {
    case "cone":
      geo = new THREE.ConeGeometry(radius * S, h * S, 18);
      break;
    case "column":
      geo = new THREE.CylinderGeometry(radius * 0.85 * S, radius * 0.85 * S, h * S, 18);
      break;
    case "cylinder":
      geo = new THREE.CylinderGeometry(radius * S, radius * S, h * S, 18);
      break;
    default: {
      geo = new THREE.SphereGeometry(radius * S, 18, 12);
      geo.scale(1, h / 2 / radius, 1);
    }
  }
  const m = new THREE.Mesh(geo, material);
  m.position.y = (d.pot_h + d.crown_start + h / 2) * S;
  return m;
}

/** Plant built upright with the pot base at the origin (local Y up). */
function plantGroup(p: LPPlacement, opts: { highlight: boolean; faded: boolean }): THREE.Group {
  const d = p.dims;
  const g = new THREE.Group();
  const color = new THREE.Color(stopColor(p.stop_position));
  const potMat = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.75,
    transparent: opts.faded,
    opacity: opts.faded ? 0.25 : 1,
    emissive: opts.highlight ? new THREE.Color("#ffb347") : new THREE.Color("#000000"),
    emissiveIntensity: opts.highlight ? 0.6 : 0,
  });
  const pot =
    d.pot_shape === "round"
      ? new THREE.Mesh(new THREE.CylinderGeometry((d.pot_d / 2) * S, (d.pot_d / 2) * 0.82 * S, d.pot_h * S, 24), potMat)
      : new THREE.Mesh(new THREE.BoxGeometry(d.pot_l * S, d.pot_h * S, d.pot_w * S), potMat);
  pot.position.y = (d.pot_h / 2) * S;
  g.add(pot);
  const lying = p.orientation !== "upright";
  // lying plants: crown squeezed into the bounding box that was planned
  const radius = lying ? Math.max(d.pot_d / 2, d.box[1] / 2) : d.crown_w / 2;
  if (d.crown_start > 0) {
    const stem = new THREE.Mesh(
      new THREE.CylinderGeometry(1.5 * S, 2 * S, d.crown_start * S, 8),
      new THREE.MeshStandardMaterial({ color: "#6b4f2a", transparent: opts.faded, opacity: opts.faded ? 0.2 : 1 }),
    );
    stem.position.y = (d.pot_h + d.crown_start / 2) * S;
    g.add(stem);
  }
  const crownMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color("#4f8a4a").lerp(color, 0.25),
    roughness: 0.9,
    transparent: true,
    opacity: opts.faded ? 0.08 : opts.highlight ? 0.55 : 0.38,
    depthWrite: false,
  });
  g.add(crownMesh(p, crownMat, radius));
  return g;
}

function placePlant(p: LPPlacement, offsetX: number, opts: { highlight: boolean; faded: boolean }): THREE.Object3D {
  const d = p.dims;
  const g = plantGroup(p, opts);
  const holder = new THREE.Group();
  holder.add(g);
  if (p.orientation === "upright") {
    holder.position.set((offsetX + p.x) * S, p.z * S, p.y * S);
  } else if (p.orientation === "lying_x" || p.orientation === "tilted_x") {
    // pot towards the front wall, crown towards the door
    // local +Y (plant axis) turns towards +X; lying: axis at half the box height
    const angle = p.orientation === "lying_x" ? Math.PI / 2 : (p.angle * Math.PI) / 180;
    g.rotation.z = -angle;
    const x0 = p.x - d.box[0] / 2;
    const r = d.pot_d / 2;
    if (p.orientation === "lying_x") holder.position.set((offsetX + x0) * S, (p.z + d.box[2] / 2) * S, p.y * S);
    else holder.position.set((offsetX + x0 + r * Math.cos(angle)) * S, (p.z + r * Math.sin(angle)) * S, p.y * S);
  } else {
    // lying across: pot at the left wall side
    g.rotation.x = Math.PI / 2;
    holder.position.set((offsetX + p.x) * S, (p.z + d.box[2] / 2) * S, (p.y - d.box[1] / 2) * S);
  }
  holder.userData = { plant: p };
  return holder;
}

function spaceObject(sp: LPSpace, offsetX: number): THREE.Group {
  const g = new THREE.Group();
  const line = new THREE.LineBasicMaterial({ color: cssVar("--text-muted", "#5d6b61") });
  const box = new THREE.BoxGeometry(sp.length * S, sp.height * S, sp.width * S);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box), line);
  edges.position.set((offsetX + sp.length / 2) * S, (sp.height / 2) * S, (sp.width / 2) * S);
  g.add(edges);
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(sp.length * S, sp.width * S),
    new THREE.MeshStandardMaterial({ color: cssVar("--surface-3", "#ebe2d2"), roughness: 1, side: THREE.DoubleSide }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.set((offsetX + sp.length / 2) * S, 0, (sp.width / 2) * S);
  g.add(floor);
  // front wall slightly tinted so the orientation is clear
  const wall = new THREE.Mesh(
    new THREE.PlaneGeometry(sp.width * S, sp.height * S),
    new THREE.MeshStandardMaterial({ color: "#9aa79c", transparent: true, opacity: 0.25, side: THREE.DoubleSide, depthWrite: false }),
  );
  wall.rotation.y = Math.PI / 2;
  wall.position.set(offsetX * S, (sp.height / 2) * S, (sp.width / 2) * S);
  g.add(wall);
  // door opening outline at the back
  const door = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.PlaneGeometry(sp.door_w * S, sp.door_h * S)),
    new THREE.LineBasicMaterial({ color: cssVar("--accent", "#c2693e") }),
  );
  door.rotation.y = Math.PI / 2;
  door.position.set((offsetX + sp.length) * S, (sp.door_h / 2) * S, (sp.width / 2) * S);
  g.add(door);
  const obstacleMat = new THREE.MeshStandardMaterial({ color: "#8d8a83", roughness: 0.8 });
  for (const ob of sp.obstacles) {
    const m = new THREE.Mesh(new THREE.BoxGeometry((ob.x1 - ob.x0) * S, ob.z1 * S, (ob.y1 - ob.y0) * S), obstacleMat);
    m.position.set((offsetX + (ob.x0 + ob.x1) / 2) * S, (ob.z1 / 2) * S, ((ob.y0 + ob.y1) / 2) * S);
    g.add(m);
  }
  const shelfMat = new THREE.MeshStandardMaterial({ color: "#b8925a", roughness: 0.7, transparent: true, opacity: 0.85 });
  for (const sh of sp.shelves) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(sh.length * S, 2 * S, sh.depth * S), shelfMat);
    m.position.set((offsetX + sh.x0 + sh.length / 2) * S, (sh.z - 1) * S, (sh.y0 + sh.depth / 2) * S);
    g.add(m);
  }
  return g;
}

export function LoadPlan3D(props: { plan: LoadPlanPayload; step: number | null; height?: number; onPick?: (p: LPPlacement) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef<{ renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls; plants: THREE.Group } | null>(null);
  const onPick = useRef(props.onPick);
  onPick.current = props.onPick;

  // scene, camera and controls once per plan
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      el.textContent = t("loadplan.no_webgl");
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a7a60, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(-3, 6, 4);
    scene.add(sun);
    const offsets = spaceOffsets(props.plan.spaces);
    for (const sp of props.plan.spaces) scene.add(spaceObject(sp, offsets[sp.id]));
    const plants = new THREE.Group();
    scene.add(plants);
    const total = props.plan.spaces.reduce((a, sp) => a + sp.length + GAP, -GAP);
    const width = Math.max(...props.plan.spaces.map((sp) => sp.width), 150);
    const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 100);
    // view from behind the door, slightly from above and from the right
    camera.position.set((total + 260) * S, 260 * S, (width + 220) * S);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set((total / 2) * S, 50 * S, (width / 2) * S);
    controls.enableDamping = true;
    controls.update();
    state.current = { renderer, scene, camera, controls, plants };

    const resize = () => {
      const w = el.clientWidth || 600;
      const h = el.clientHeight || 420;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();
    const ray = new THREE.Raycaster();
    const click = (e: MouseEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      const v = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(v, camera);
      const hit = ray.intersectObjects(plants.children, true)[0];
      let o: THREE.Object3D | null = hit?.object ?? null;
      while (o && !o.userData.plant) o = o.parent;
      if (o && onPick.current) onPick.current(o.userData.plant as LPPlacement);
    };
    renderer.domElement.addEventListener("click", click);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      renderer.domElement.removeEventListener("click", click);
      controls.dispose();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose?.();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
        else mat?.dispose?.();
      });
      renderer.dispose();
      renderer.domElement.remove();
      state.current = null;
    };
  }, [props.plan]);

  // plants: everything up to the current step, the current one highlighted
  useEffect(() => {
    const s = state.current;
    if (!s) return;
    s.plants.children.slice().forEach((c) => {
      s.plants.remove(c);
      c.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose?.();
        (m.material as THREE.Material | undefined)?.dispose?.();
      });
    });
    const offsets = spaceOffsets(props.plan.spaces);
    for (const p of props.plan.placements) {
      if (props.step != null && p.sequence > props.step) continue;
      const highlight = props.step != null && p.sequence === props.step;
      s.plants.add(placePlant(p, offsets[p.space_id] ?? 0, { highlight, faded: false }));
    }
  }, [props.plan, props.step]);

  return <div ref={host} className="loadplan-3d" style={{ height: props.height ?? 440 }} aria-label={t("loadplan.view_3d")} role="img" />;
}
