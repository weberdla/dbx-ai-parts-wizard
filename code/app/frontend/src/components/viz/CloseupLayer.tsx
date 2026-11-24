import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html, Line } from '@react-three/drei';
import * as THREE from 'three';
import type { CloseupResponse } from './types';
import type { MapTheme } from './theme';

const money = (v: number | null) => (v == null ? '' : `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`);

interface Props {
  data: CloseupResponse;
  anchor: [number, number, number]; // where the group's knot sits in the map
  scale: number; // world units per 1.0 of L2 distance
  theme: MapTheme;
}

// The group "blooms" out of its knot: positions are true-distance MDS coords around the anchor.
export default function CloseupLayer({ data, anchor, scale, theme }: Props) {
  const plantColor = (p: string) => theme.plant[p] ?? theme.plantFallback;
  const grp = useRef<THREE.Group>(null);
  const t = useRef(0);

  useFrame((_, dt) => {
    if (!grp.current || t.current >= 1) return;
    t.current = Math.min(1, t.current + dt / 0.9);
    const e = 1 - Math.pow(1 - t.current, 3);
    grp.current.scale.setScalar(Math.max(0.001, e));
  });

  const m = useMemo(() => data.members.map((p) => new THREE.Vector3(...p.pos).multiplyScalar(scale)), [data, scale]);
  const n = useMemo(() => data.neighbors.map((p) => new THREE.Vector3(...p.pos).multiplyScalar(scale)), [data, scale]);
  const bestPrice = Math.min(...data.members.map((x) => x.best_price ?? Infinity));
  // Groups are chained (each part within the threshold of another member), so the boundary
  // wraps the whole group; green lines show only the pairs that are actually within threshold.
  const groupR = Math.max(...data.members.map((p) => Math.hypot(...p.pos)));
  const r = Math.max(data.threshold, groupR * 1.12 + 0.02) * scale;
  const matchEdges = data.edges.filter((e) => e.l2 <= data.threshold);
  const labeled = useMemo(() => new Set([...data.neighbors.map((nb, i) => [nb.l2, i] as const)].sort((x, y) => x[0] - y[0]).slice(0, 3).map(([, i]) => i).concat(data.neighbors.flatMap((nb, i) => (nb.gt_label === 'hard_negative' ? [i] : [])))), [data]);
  // Push each member's card outward from the group center so close duplicates don't stack.
  const cardPos = (v: THREE.Vector3) => {
    const d = v.clone();
    if (d.lengthSq() < 1e-8) d.set(0, 1, 0);
    d.normalize();
    return [d.x * 0.06, d.y * 0.06 + 0.012, d.z * 0.06] as [number, number, number];
  };

  return (
    <group ref={grp} position={anchor} scale={0.001}>
      {/* match threshold boundary */}
      <mesh>
        <sphereGeometry args={[r, 48, 32]} />
        <meshBasicMaterial color={theme.threshold} transparent opacity={theme.name === 'light' ? 0.05 : 0.06} depthWrite={false} />
      </mesh>
      <mesh>
        <sphereGeometry args={[r, 24, 16]} />
        <meshBasicMaterial color={theme.threshold} wireframe transparent opacity={theme.name === 'light' ? 0.08 : 0.12} depthWrite={false} />
      </mesh>

      {/* neighbor -> nearest member (outside the threshold) */}
      {data.neighbors.map((nb, i) => (
        <Line key={`nl${i}`} points={[n[i], m[nb.nearest_member]]} color={theme.otherLine} lineWidth={1} transparent opacity={0.45} dashed dashSize={0.012} gapSize={0.008} />
      ))}
      {/* member <-> member (inside) */}
      {matchEdges.map((e, i) => (
        <Line key={`me${i}`} points={[m[e.a], m[e.b]]} color={theme.dupLine} lineWidth={2.2} transparent opacity={0.9} />
      ))}
      {matchEdges.length <= 3 && matchEdges.map((e, i) => (
        <Html key={`mel${i}`} position={m[e.a].clone().add(m[e.b]).multiplyScalar(0.5)} center zIndexRange={[10, 0]}>
          <div className="cu-edge">L2 {e.l2.toFixed(3)}</div>
        </Html>
      ))}

      {data.neighbors.map((nb, i) => (
        <group key={`n${i}`} position={n[i]}>
          <mesh>
            <sphereGeometry args={[0.0075, 16, 12]} />
            <meshBasicMaterial color={theme.lookalike} />
          </mesh>
          {labeled.has(i) && (
            <Html position={[0, -0.022, 0]} center zIndexRange={[10, 0]}>
              <div className="cu-nbr">
                <b>{nb.part_number}</b> · L2 {nb.l2.toFixed(2)}
                {nb.gt_label === 'hard_negative' && <span className="cu-twin"> · near-twin, not a match</span>}
                {nb.differs_on && <div>differs on {nb.differs_on}</div>}
              </div>
            </Html>
          )}
        </group>
      ))}

      {data.members.map((p, i) => (
        <group key={`m${i}`} position={m[i]}>
          <mesh>
            <sphereGeometry args={[0.013, 24, 16]} />
            <meshBasicMaterial color={plantColor(p.plant_id)} />
          </mesh>
          <mesh>
            <sphereGeometry args={[0.02, 24, 16]} />
            <meshBasicMaterial color={plantColor(p.plant_id)} transparent opacity={0.18} depthWrite={false} />
          </mesh>
          <Html position={cardPos(m[i])} center zIndexRange={[20, 10]}>
            <div className="cu-card" style={{ borderColor: plantColor(p.plant_id) }}>
              <b>{p.part_number}</b>
              <span className={p.best_price === bestPrice ? 'best' : ''}>{p.plant_id} · {money(p.best_price)}</span>
            </div>
          </Html>
        </group>
      ))}
    </group>
  );
}
