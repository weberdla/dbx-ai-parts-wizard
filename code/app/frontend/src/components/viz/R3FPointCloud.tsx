import { useMemo, useRef, useEffect } from 'react';
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import type { FlyTo, PointCloudProps } from './types';
import CloseupLayer from './CloseupLayer';

// Soft round sprite so points read as dots, not squares.
function makeDotTexture(): THREE.Texture {
  const s = 64;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d')!;
  const grd = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.55, 'rgba(255,255,255,0.9)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, s, s);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function Cloud({ positions, colors, onHover, onPick, ghost, ghostOpacity }: Pick<PointCloudProps, 'positions' | 'colors' | 'onHover' | 'onPick'> & { ghost: boolean; ghostOpacity: number }) {
  const geomRef = useRef<THREE.BufferGeometry>(null);
  const matRef = useRef<THREE.PointsMaterial>(null);
  // Ease toward a faint ghost in close-up so the group reads clearly with context behind it.
  useFrame((_, dt) => {
    const m = matRef.current;
    if (!m) return;
    const target = ghost ? ghostOpacity : 0.9;
    if (Math.abs(m.opacity - target) > 0.002) m.opacity += (target - m.opacity) * Math.min(1, dt * 6);
  });
  const dot = useMemo(makeDotTexture, []);

  useEffect(() => {
    const g = geomRef.current;
    if (!g) return;
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    g.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    g.computeBoundingSphere();
  }, [positions, colors]);

  const idx = (e: ThreeEvent<PointerEvent | MouseEvent>) =>
    e.intersections.find((i) => i.object === e.object)?.index ?? e.index ?? null;

  return (
    <points
      onPointerMove={(e) => { if (ghost) return; e.stopPropagation(); onHover(idx(e), e.clientX, e.clientY); }}
      onPointerOut={() => onHover(null, 0, 0)}
      onClick={(e) => { if (ghost) return; e.stopPropagation(); onPick(idx(e)); }}
    >
      <bufferGeometry ref={geomRef} />
      <pointsMaterial
        ref={matRef}
        size={0.022}
        sizeAttenuation
        vertexColors
        map={dot}
        transparent
        alphaTest={0.05}
        depthWrite={false}
        opacity={0.9}
      />
    </points>
  );
}

function Highlight({ positions, indices, selected, focusColor, selectedColor }: { positions: Float32Array; indices: number[]; selected: number | null; focusColor: string; selectedColor: string }) {
  const pos = useMemo(() => {
    const a = new Float32Array(indices.length * 3);
    indices.forEach((p, i) => a.set(positions.subarray(p * 3, p * 3 + 3), i * 3));
    return a;
  }, [positions, indices]);
  const sel = useMemo(
    () => (selected == null ? null : new Float32Array(positions.subarray(selected * 3, selected * 3 + 3))),
    [positions, selected]
  );
  const dot = useMemo(makeDotTexture, []);
  return (
    <>
      {indices.length > 0 && (
        <points key={`h${indices.length}-${indices[0]}`}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[pos, 3]} />
          </bufferGeometry>
          <pointsMaterial size={0.05} sizeAttenuation color={focusColor} map={dot} transparent alphaTest={0.05} depthWrite={false} />
        </points>
      )}
      {sel && (
        <points key={`s${selected}`}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[sel, 3]} />
          </bufferGeometry>
          <pointsMaterial size={0.09} sizeAttenuation color={selectedColor} map={dot} transparent alphaTest={0.05} depthWrite={false} />
        </points>
      )}
    </>
  );
}

function Rays({ positions, selected, rays, dupColor, otherColor }: { positions: Float32Array; selected: number | null; rays: PointCloudProps['rays']; dupColor: string; otherColor: string }) {
  const [dup, other] = useMemo(() => {
    if (selected == null) return [new Float32Array(), new Float32Array()];
    const s = positions.subarray(selected * 3, selected * 3 + 3);
    const build = (rs: typeof rays) => {
      const a = new Float32Array(rs.length * 6);
      rs.forEach((r, i) => {
        a.set(s, i * 6);
        a.set(positions.subarray(r.to * 3, r.to * 3 + 3), i * 6 + 3);
      });
      return a;
    };
    return [build(rays.filter((r) => r.duplicate)), build(rays.filter((r) => !r.duplicate))];
  }, [positions, selected, rays]);
  return (
    <>
      {dup.length > 0 && (
        <lineSegments key={`d${dup.length}-${selected}`}>
          <bufferGeometry><bufferAttribute attach="attributes-position" args={[dup, 3]} /></bufferGeometry>
          <lineBasicMaterial color={dupColor} transparent opacity={0.95} />
        </lineSegments>
      )}
      {other.length > 0 && (
        <lineSegments key={`o${other.length}-${selected}`}>
          <bufferGeometry><bufferAttribute attach="attributes-position" args={[other, 3]} /></bufferGeometry>
          <lineBasicMaterial color={otherColor} transparent opacity={0.6} />
        </lineSegments>
      )}
    </>
  );
}

// Eases the camera + orbit target toward an external focus, then lets go so the user can orbit.
function CameraRig({ flyTo, shiftPx }: { flyTo: FlyTo | null; shiftPx: number }) {
  const { camera, controls, size } = useThree() as unknown as {
    camera: THREE.PerspectiveCamera;
    controls: { target: THREE.Vector3; update: () => void } | null;
    size: { width: number; height: number };
  };
  // Shift the rendered view left so the focus stays centered in the space left of a side panel.
  useEffect(() => {
    if (shiftPx > 0) camera.setViewOffset(size.width + shiftPx * 2, size.height, shiftPx * 2, 0, size.width, size.height);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }, [camera, shiftPx, size.width, size.height]);
  const anim = useRef<{ t: number; fromPos: THREE.Vector3; toPos: THREE.Vector3; fromTgt: THREE.Vector3; toTgt: THREE.Vector3 } | null>(null);

  useEffect(() => {
    if (!flyTo || !controls) return;
    const toTgt = new THREE.Vector3(...flyTo.center);
    let toPos: THREE.Vector3;
    if (flyTo.keepDist) {
      // Slide camera and target together: new pivot, same zoom and viewing angle.
      toPos = camera.position.clone().add(toTgt.clone().sub(controls.target));
    } else {
      // Keep the current viewing direction; move closer/further based on the focus size.
      const dir = camera.position.clone().sub(controls.target).normalize();
      if (dir.lengthSq() < 1e-6) dir.set(0, 0, 1);
      // Close-up: frame tightly, but back off when the visible area (left of the panel) is narrow.
      const avail = Math.max(320, size.width - shiftPx * 2);
      // Floor keeps a small group's neighborhood in frame instead of filling the screen with two dots.
      const dist = flyTo.fit ? flyTo.radius * 2.4 * Math.max(1, 820 / avail) : Math.min(2.8, Math.max(0.85, flyTo.radius * 3.2));
      toPos = toTgt.clone().add(dir.multiplyScalar(dist));
    }
    anim.current = {
      t: 0,
      fromPos: camera.position.clone(),
      toPos,
      fromTgt: controls.target.clone(),
      toTgt,
    };
  }, [flyTo?.nonce, controls]); // eslint-disable-line react-hooks/exhaustive-deps

  useFrame((_, dt) => {
    const a = anim.current;
    if (!a || !controls) return;
    a.t = Math.min(1, a.t + dt / 1.1);
    const e = 1 - Math.pow(1 - a.t, 3); // ease-out cubic
    camera.position.lerpVectors(a.fromPos, a.toPos, e);
    controls.target.lerpVectors(a.fromTgt, a.toTgt, e);
    controls.update();
    if (a.t >= 1) anim.current = null;
  });
  return null;
}

export default function R3FPointCloud(props: PointCloudProps) {
  return (
    <Canvas
      camera={{ position: [0, 0, 2.6], fov: 50, near: 0.01, far: 100 }}
      raycaster={{ params: { Points: { threshold: 0.012 } } as THREE.RaycasterParameters }}
      onPointerMissed={() => { if (!props.closeup) props.onPick(null); }}
      dpr={[1, 2]}
      resize={{ debounce: 120 }}
    >
      <color attach="background" args={[props.theme.bg]} />
      <Cloud positions={props.positions} colors={props.colors} onHover={props.onHover} onPick={props.onPick} ghost={!!props.closeup} ghostOpacity={props.theme.ghost} />
      {props.closeup ? (
        <CloseupLayer key={props.closeup.data.group_id} {...props.closeup} theme={props.theme} />
      ) : (
        <>
          <Highlight positions={props.positions} indices={props.highlighted} selected={props.selected} focusColor={props.theme.focus} selectedColor={props.theme.selected} />
          <Rays positions={props.positions} selected={props.selected} rays={props.rays} dupColor={props.theme.dupLine} otherColor={props.theme.otherLine} />
        </>
      )}
      <CameraRig flyTo={props.flyTo} shiftPx={props.closeup ? 190 : 0} />
      <OrbitControls makeDefault enableDamping dampingFactor={0.08} autoRotate={props.autoRotate} autoRotateSpeed={0.8} />
    </Canvas>
  );
}
