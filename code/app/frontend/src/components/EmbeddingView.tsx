import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import * as THREE from 'three';
import R3FPointCloud from './viz/R3FPointCloud';
import type { BlockInfo, CloseupView, FlyTo, MapFocus, NeighborsResponse, ProjectionPayload, Ray } from './viz/types';
import { getBlocks, getProjection, getNeighbors, getCloseup, setDisposition } from '../api';
import { THEMES, type ThemeName } from './viz/theme';

type ColorBy = 'category' | 'plant' | 'group' | 'savings' | 'gt_label';

const MAX_OVERLAY = 2500; // above this, focus only dims the rest (no enlarged overlay)

const fmtMoney = (v: number) =>
  v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(0)}K` : `$${v.toFixed(0)}`;

// Write a color, faded toward the background by `f` (1 = full color). Blending toward the
// background (not toward black) keeps dimming correct on both dark and light themes.
const _c = new THREE.Color();
function writeRgb(col: THREE.Color, bg: THREE.Color, out: Float32Array, i: number, f = 1) {
  out[i * 3] = col.r * f + bg.r * (1 - f);
  out[i * 3 + 1] = col.g * f + bg.g * (1 - f);
  out[i * 3 + 2] = col.b * f + bg.b * (1 - f);
}
function hexRgb(hex: string, bg: THREE.Color, out: Float32Array, i: number, f = 1) {
  writeRgb(_c.set(hex), bg, out, i, f);
}

interface Props {
  onOpenGroup: (groupId: string) => void;
  focus: MapFocus | null; // set by filters, queue, group drawer or Genie
  onClearFocus: () => void;
  controlsEl: HTMLElement | null; // map controls render into the shared main toolbar
  onValidated: () => void; // a person approved a consolidation (refresh queue + decision strip)
  themeName: ThemeName; // app-wide light/dark theme
}

export default function EmbeddingView({ onOpenGroup, focus, onClearFocus, controlsEl, onValidated, themeName }: Props) {
  const [blocks, setBlocks] = useState<BlockInfo[]>([]);
  const [scope, setScope] = useState<string>('global'); // 'global' or a block_key
  const [method, setMethod] = useState<'umap' | 'pca'>('umap');
  const [colorBy, setColorBy] = useState<ColorBy>('category');
  const [data, setData] = useState<ProjectionPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [nbrs, setNbrs] = useState<NeighborsResponse | null>(null);
  const [nbrErr, setNbrErr] = useState<string | null>(null);
  const [autoRotate, setAutoRotate] = useState(true);
  const [flyTo, setFlyTo] = useState<FlyTo | null>(null);
  const handledFocus = useRef<number>(-1); // focus nonce already flown to / auto-selected
  const [closeup, setCloseup] = useState<CloseupView | null>(null);
  const [cuLoading, setCuLoading] = useState(false);
  const [approved, setApproved] = useState<Record<string, boolean>>({});
  const flyNonce = useRef(100000);
  const theme = THEMES[themeName] ?? THEMES.dark;
  const PALETTE = theme.palette, MUTED = theme.muted, GT_COLORS = theme.gt;

  useEffect(() => { getBlocks().then(setBlocks).catch((e) => setErr(String(e))); }, []);

  // An external focus picks the scope; the projection effect below loads it.
  useEffect(() => {
    if (!focus) return;
    setScope(focus.scope);
    setSelected(null); setNbrs(null);
    setAutoRotate(false);
  }, [focus?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const reqId = useRef(0);
  useEffect(() => {
    setLoading(true); setErr(null); setSelected(null); setNbrs(null);
    const isGlobal = scope === 'global';
    const id = ++reqId.current; // ignore stale responses if the scope changes mid-flight
    getProjection(isGlobal ? 'global' : 'block', isGlobal ? undefined : scope, method)
      .then((d) => {
        if (id !== reqId.current) return;
        setData(d);
        if (!isGlobal && colorBy === 'category') setColorBy('group');
        if (isGlobal && colorBy === 'group') setColorBy('category');
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, method]);

  const positions = useMemo(() => {
    if (!data) return new Float32Array();
    const { x, y, z } = data.columns;
    const a = new Float32Array(data.count * 3);
    for (let i = 0; i < data.count; i++) { a[i * 3] = x[i]; a[i * 3 + 1] = y[i]; a[i * 3 + 2] = z[i]; }
    return a;
  }, [data]);

  // "Home" pivot: the middle of the loaded points' bounding box, so auto-rotate and orbiting
  // spin around the visual center of the view (not the median, and not a stale focus point).
  const home = useMemo<[number, number, number]>(() => {
    if (!data || !data.count) return [0, 0, 0];
    // Middle of the 2nd-98th percentile on each axis: a few stray parts far from the main
    // islands shouldn't drag the pivot off the visual center.
    const out: number[] = [];
    for (let k = 0; k < 3; k++) {
      const v = new Float32Array(data.count);
      for (let i = 0; i < data.count; i++) v[i] = positions[i * 3 + k];
      v.sort();
      out.push((v[Math.floor(v.length * 0.02)] + v[Math.floor(v.length * 0.98)]) / 2);
    }
    return out as [number, number, number];
  }, [data, positions]);

  const goHome = useCallback((keepDist = false) => {
    flyNonce.current += 1;
    setFlyTo({ center: home, radius: 0.8, nonce: flyNonce.current, keepDist });
  }, [home]);

  // Pivot on a clicked point's group (or the point itself) without changing the zoom.
  const pivotOn = useCallback((i: number) => {
    if (!data) return;
    const g = data.columns.group[i];
    const idx: number[] = [];
    if (g >= 0) data.columns.group.forEach((gi, j) => { if (gi === g) idx.push(j); });
    else idx.push(i);
    const c = [0, 0, 0];
    idx.forEach((j) => { c[0] += positions[j * 3]; c[1] += positions[j * 3 + 1]; c[2] += positions[j * 3 + 2]; });
    flyNonce.current += 1;
    setFlyTo({ center: [c[0] / idx.length, c[1] / idx.length, c[2] / idx.length], radius: 0.8, nonce: flyNonce.current, keepDist: true });
  }, [data, positions]);

  // Every newly loaded view starts centered, unless a focus for this view will fly somewhere.
  useEffect(() => {
    if (!data) return;
    if (focus && focus.scope === data.block_key && handledFocus.current !== focus.nonce) return;
    goHome();
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const idOf = useMemo(() => {
    const m = new Map<string, number>();
    data?.columns.part_id.forEach((id, i) => m.set(id, i));
    return m;
  }, [data]);

  // Points the current focus refers to (only once the matching scope has loaded).
  const focusIdx = useMemo(() => {
    if (!data || !focus || data.block_key !== focus.scope) return null;
    const c = data.columns;
    const out: number[] = [];
    if (focus.partIds?.length) {
      for (const id of focus.partIds) { const i = idOf.get(id); if (i != null) out.push(i); }
    } else if (focus.blocks?.length) {
      const want = new Set(focus.blocks);
      for (let i = 0; i < data.count; i++)
        if (want.has(`${data.dicts.category[c.category[i]]}|${data.dicts.material[c.material[i]]}`)) out.push(i);
    } else if (focus.categories?.length) {
      const want = new Set(focus.categories);
      for (let i = 0; i < data.count; i++) if (want.has(data.dicts.category[c.category[i]])) out.push(i);
    } else {
      return null; // scope-only focus (e.g. filters picked a block): nothing to emphasize
    }
    return out;
  }, [data, focus, idOf]);

  const focusSet = useMemo(() => (focusIdx ? new Set(focusIdx) : null), [focusIdx]);

  // Fly to the focus once its data is in; auto-open the panel for a single group.
  useEffect(() => {
    if (!focus || !data || data.block_key !== focus.scope || handledFocus.current === focus.nonce) return;
    handledFocus.current = focus.nonce;
    const pts = focusIdx && focusIdx.length ? focusIdx : null;
    if (!pts) { setFlyTo({ center: home, radius: 0.8, nonce: focus.nonce }); return; }
    const ctr = [0, 0, 0];
    pts.forEach((i) => { ctr[0] += positions[i * 3]; ctr[1] += positions[i * 3 + 1]; ctr[2] += positions[i * 3 + 2]; });
    ctr.forEach((_, k) => (ctr[k] /= pts.length));
    let r = 0;
    pts.forEach((i) => {
      const d = Math.hypot(positions[i * 3] - ctr[0], positions[i * 3 + 1] - ctr[1], positions[i * 3 + 2] - ctr[2]);
      if (d > r) r = d;
    });
    // Spread across the whole view (e.g. many groups in many categories): just show the overview.
    if (r > 0.5) setFlyTo({ center: home, radius: 0.8, nonce: focus.nonce });
    else setFlyTo({ center: ctr as [number, number, number], radius: Math.max(r, 0.04), nonce: focus.nonce });
    if (focus.autoSelect && focus.groupIds?.length === 1) openCloseup(focus.groupIds[0], ctr as [number, number, number]);
    else if (focus.autoSelect && pts.length) pick(pts[0], false);
  }, [focus, data, focusIdx, positions]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- True-distance close-up of one match group ----
  const anchorOf = (groupId: string): [number, number, number] => {
    if (!data) return [0, 0, 0];
    const g = data.dicts.group.indexOf(groupId);
    const idx: number[] = [];
    if (g >= 0) data.columns.group.forEach((gi, i) => { if (gi === g) idx.push(i); });
    if (!idx.length && selected != null) idx.push(selected);
    if (!idx.length) return [0, 0, 0];
    const c = [0, 0, 0];
    idx.forEach((i) => { c[0] += positions[i * 3]; c[1] += positions[i * 3 + 1]; c[2] += positions[i * 3 + 2]; });
    return [c[0] / idx.length, c[1] / idx.length, c[2] / idx.length];
  };

  const openCloseup = (groupId: string, anchor?: [number, number, number]) => {
    const at = anchor ?? anchorOf(groupId);
    setCuLoading(true); setAutoRotate(false); setHover(null);
    getCloseup(groupId, 6)
      .then((d) => {
        // Size the layout so the threshold sphere and the nearest look-alikes are all in frame.
        // Frame the group plus its nearest look-alikes; farther ones may sit past the edge.
        let ext = d.threshold;
        d.members.forEach((p) => { ext = Math.max(ext, Math.hypot(...p.pos)); });
        const nbr = d.neighbors.map((p) => Math.hypot(...p.pos)).sort((a, b) => a - b);
        if (nbr.length) ext = Math.max(ext, nbr[Math.min(2, nbr.length - 1)]);
        const scale = 0.3 / ext;
        setCloseup({ data: d, anchor: at, scale });
        flyNonce.current += 1;
        setFlyTo({ center: at, radius: 0.3, nonce: flyNonce.current, fit: true });
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setCuLoading(false));
  };

  const closeCloseup = useCallback(() => {
    setCloseup(null);
    goHome();
  }, [goHome]);

  useEffect(() => {
    if (!closeup) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeCloseup(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [closeup, closeCloseup]);

  // A new scope or a cleared focus ends the close-up.
  useEffect(() => { setCloseup(null); }, [scope, method]);
  const hadFocus = useRef(false);
  useEffect(() => {
    if (focus) { hadFocus.current = true; return; }
    setCloseup(null);
    if (hadFocus.current) { hadFocus.current = false; goHome(); }
  }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps

  const approve = async (groupId: string) => {
    try {
      await setDisposition(groupId, 'consolidated', 'Approved from the Similarity Map close-up');
      setApproved((a) => ({ ...a, [groupId]: true }));
      onValidated();
    } catch (e) {
      setErr(String(e));
    }
  };

  // Enlarged overlay: the clicked point's group, otherwise a (small) focus set.
  const highlighted = useMemo(() => {
    if (!data) return [];
    if (selected != null) {
      const g = data.columns.group[selected];
      if (g < 0) return [];
      const out: number[] = [];
      data.columns.group.forEach((gi, i) => { if (gi === g) out.push(i); });
      return out;
    }
    return focusIdx && focusIdx.length <= MAX_OVERLAY ? focusIdx : [];
  }, [data, selected, focusIdx]);

  const { colors, legend } = useMemo(() => {
    const legend: { label: string; color: string }[] = [];
    if (!data) return { colors: new Float32Array(), legend };
    const n = data.count;
    const c = new Float32Array(n * 3);
    const col = data.columns;
    const bg = new THREE.Color(theme.bg);
    // Dim everything outside the focus (or everything when a point is selected).
    const dimOf = (i: number) => (selected != null ? 0.35 : focusSet && !focusSet.has(i) ? 0.22 : 1);
    if (colorBy === 'category' || colorBy === 'plant') {
      const key = colorBy === 'category' ? 'category' : 'plant';
      const names = data.dicts[key];
      names.forEach((nm, i) => legend.push({ label: nm, color: PALETTE[i % PALETTE.length] }));
      for (let i = 0; i < n; i++) { const k = col[key][i]; hexRgb(k < 0 ? MUTED : PALETTE[k % PALETTE.length], bg, c, i, dimOf(i)); }
    } else if (colorBy === 'group') {
      legend.push({ label: 'In a match group (one color per group)', color: PALETTE[0] }, { label: 'No duplicate found', color: MUTED });
      for (let i = 0; i < n; i++) { const g = col.group[i]; hexRgb(g < 0 ? MUTED : PALETTE[(g * 7) % PALETTE.length], bg, c, i, dimOf(i)); }
    } else if (colorBy === 'savings') {
      const sav = data.groups.map((g) => g.savings ?? 0);
      const max = Math.log10(Math.max(10, ...sav));
      const lo = new THREE.Color(theme.savLo), hi = new THREE.Color(theme.savHi), tmp = new THREE.Color();
      legend.push({ label: 'Low group savings', color: theme.savLo }, { label: 'High group savings', color: theme.savHi }, { label: 'No duplicate found', color: MUTED });
      for (let i = 0; i < n; i++) {
        const g = col.group[i];
        const dim = dimOf(i);
        if (g < 0) { hexRgb(MUTED, bg, c, i, dim); continue; }
        const t = Math.max(0, Math.log10(Math.max(1, sav[g])) / max);
        tmp.copy(lo).lerp(hi, t);
        writeRgb(tmp, bg, c, i, dim);
      }
    } else {
      Object.entries(GT_COLORS).forEach(([k, v]) => legend.push({ label: k.replace('_', ' '), color: v }));
      legend.push({ label: 'unlabeled', color: MUTED });
      for (let i = 0; i < n; i++) { const k = col.gt_label[i]; const nm = k < 0 ? '' : data.dicts.gt_label[k]; hexRgb(GT_COLORS[nm] ?? MUTED, bg, c, i, dimOf(i)); }
    }
    return { colors: c, legend };
  }, [data, colorBy, selected, focusSet, theme]); // eslint-disable-line react-hooks/exhaustive-deps

  const rays: Ray[] = useMemo(() => {
    if (!nbrs) return [];
    return nbrs.neighbors.flatMap((nb) => {
      const to = idOf.get(nb.part_id);
      return to == null ? [] : [{ to, duplicate: nb.is_duplicate }];
    });
  }, [nbrs, idOf]);

  const pick = useCallback((i: number | null, stopRotate = true) => {
    if (i == null && selected != null && !closeup) goHome(true); // deselect: pivot back on the whole set
    setSelected(i);
    setNbrs(null); setNbrErr(null);
    if (i == null || !data) return;
    if (stopRotate) setAutoRotate(false);
    pivotOn(i);
    getNeighbors(data.columns.part_id[i], 10).then(setNbrs).catch((e) => setNbrErr(String(e)));
  }, [data, pivotOn, goHome, closeup, selected]);

  const onHover = useCallback((i: number | null, x: number, y: number) => {
    setHover(i == null ? null : { i, x, y });
  }, []);

  const label = (i: number) => {
    if (!data) return null;
    const c = data.columns;
    const g = c.group[i];
    return {
      part: c.part_number[i],
      category: data.dicts.category[c.category[i]] ?? '',
      plant: data.dicts.plant[c.plant[i]] ?? '',
      machine: data.dicts.machine_type[c.machine_type[i]] ?? '',
      gt: c.gt_label[i] >= 0 ? data.dicts.gt_label[c.gt_label[i]] : null,
      group: g >= 0 ? data.groups[g] : null,
    };
  };

  const sel = selected != null ? label(selected) : null;
  const hov = hover ? label(hover.i) : null;
  const plantsInGroup = useMemo(() => {
    if (!data) return 0;
    return new Set(highlighted.map((i) => data.columns.plant[i])).size;
  }, [data, highlighted]);

  const controls = (
    <>
      <span className="sortsel">
        View
        <select value={scope} onChange={(e) => { onClearFocus(); setScope(e.target.value); }}>
          <option value="global">Whole catalog (sample)</option>
          {blocks.map((b) => (
            <option key={b.block_key} value={b.block_key}>
              {b.part_category} · {b.material} ({b.parts.toLocaleString()} parts, {fmtMoney(b.savings)})
            </option>
          ))}
        </select>
      </span>
      <span className="sortsel">
        Color by
        <select value={colorBy} onChange={(e) => setColorBy(e.target.value as ColorBy)}>
          <option value="category">Part category</option>
          <option value="plant">Plant</option>
          <option value="group">Match group</option>
          <option value="savings">Group savings</option>
          <option value="gt_label">Ground truth label</option>
        </select>
      </span>
      <span className="sortsel">
        Projection
        <select value={method} onChange={(e) => setMethod(e.target.value as 'umap' | 'pca')}>
          <option value="umap">UMAP</option>
          <option value="pca">PCA</option>
        </select>
      </span>
      <label className="sortsel chk">
        <input type="checkbox" checked={autoRotate} onChange={(e) => setAutoRotate(e.target.checked)} /> Rotate
      </label>
    </>
  );

  return (
    <div className={`viz ${theme.name}`}>
      {controlsEl && createPortal(controls, controlsEl)}

      <div className="viz-stage">
        {err && <div className="viz-msg err">{err}</div>}
        {data && data.count > 0 && (
          <R3FPointCloud
            positions={positions}
            colors={colors}
            highlighted={highlighted}
            selected={selected}
            rays={rays}
            autoRotate={autoRotate && !hover} // hold still while pointing at a part so it can be clicked
            flyTo={flyTo}
            closeup={closeup}
            theme={theme}
            onHover={onHover}
            onPick={pick}
          />
        )}

        <div className="viz-status">
          {loading ? 'Loading…' : data ? `${data.count.toLocaleString()} parts` : ''}
        </div>

        {focus && (
          <div className="viz-focus">
            <span className="viz-focus-dot" />
            <span>{focus.label}</span>
            {focusIdx && <span className="muted">· {focusIdx.length.toLocaleString()} on map</span>}
            <button className="x" onClick={onClearFocus} title="Clear focus">×</button>
          </div>
        )}

        <div className="viz-legend">
          {(closeup
            ? [...Object.entries(theme.plant).map(([k, v]) => ({ label: `Plant ${k}`, color: v })), { label: 'Look-alike (not a match)', color: theme.lookalike }, { label: `Green line = within match threshold (L2 ≤ ${closeup.data.threshold})`, color: theme.threshold }]
            : legend).map((l) => (
            <div key={l.label}><span className="sw" style={{ background: l.color }} />{l.label}</div>
          ))}
        </div>

        {hov && hover && (
          <div className="viz-tip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
            <strong>{hov.part}</strong>
            <div>{hov.category} · {hov.plant} · {hov.machine}</div>
            {hov.group ? <div>Group of {hov.group.size} · {fmtMoney(hov.group.savings ?? 0)}/yr</div> : <div className="muted">No duplicate found</div>}
          </div>
        )}

        {closeup && (() => {
          const d = closeup.data;
          const prices = d.members.map((m) => m.best_price ?? 0);
          const lo = Math.min(...prices), hi = Math.max(...prices);
          const plants = [...new Set(d.members.map((m) => m.plant_id))];
          const done = approved[d.group_id];
          return (
            <div className="viz-panel cu-panel">
              <div className="viz-panel-h">
                <strong>{d.part_category} · {d.material}</strong>
                <button className="x" onClick={closeCloseup} title="Back to map (Esc)">×</button>
              </div>
              <div className="cu-headline">
                <b>{d.members.length} part numbers</b>, one physical part, bought at <b>{plants.length} plant{plants.length === 1 ? '' : 's'}</b>
              </div>
              <table className="cu-members">
                <thead><tr><th>Part</th><th>Plant</th><th className="num">Best price</th><th className="num">Vol/yr</th></tr></thead>
                <tbody>
                  {d.members.map((m) => (
                    <tr key={m.part_id}>
                      <td><span className="sw" style={{ background: theme.plant[m.plant_id] ?? theme.plantFallback }} />{m.part_number}</td>
                      <td>{m.plant_id}</td>
                      <td className={`num ${m.best_price === lo ? 'best' : m.best_price === hi && hi > lo ? 'worst' : ''}`}>{m.best_price == null ? '' : `$${m.best_price.toLocaleString('en-US', { maximumFractionDigits: 2 })}`}</td>
                      <td className="num">{m.annual_volume?.toLocaleString() ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {hi > lo && <div className="cu-gap">Price gap {Math.round(((hi - lo) / lo) * 100)}% for the same part</div>}
              <div className="cu-value">
                <span>Annual savings if consolidated</span>
                <strong>{fmtMoney(d.savings ?? 0)}</strong>
              </div>
              <button className={`btn primary cu-approve ${done ? 'done' : ''}`} disabled={done} onClick={() => approve(d.group_id)}>
                {done ? '✓ Approved for consolidation' : 'Approve consolidation'}
              </button>
              <div className="viz-nbrs-h">Closest look-alikes (live Vector Search)</div>
              <table className="viz-nbrs">
                <tbody>
                  {d.neighbors.map((nb) => (
                    <tr key={nb.part_id}>
                      <td>{nb.part_number}</td>
                      <td className="muted">{nb.gt_label === 'hard_negative' ? <span className="cu-twin">near-twin · </span> : null}{nb.differs_on ? `differs on ${nb.differs_on}` : ''}</td>
                      <td className="num">L2 {nb.l2.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="muted small">Distances are true L2 across 21 physical attributes. Green lines join parts within the match threshold (L2 ≤ {d.threshold}). Illustrative, synthetic data.</div>
              <div className="viz-actions">
                <button className="btn ghost-dark" onClick={closeCloseup}>← Back to map</button>
                <button className="btn ghost-dark" onClick={() => onOpenGroup(d.group_id)}>Open group</button>
              </div>
            </div>
          );
        })()}

        {sel && !closeup && (
          <div className="viz-panel">
            <div className="viz-panel-h">
              <strong>{sel.part}</strong>
              <button className="x" onClick={() => pick(null)}>×</button>
            </div>
            <div className="muted">{sel.category} · {sel.plant} · {sel.machine}{sel.gt ? ` · GT: ${sel.gt.replace('_', ' ')}` : ''}</div>
            {sel.group ? (
              <div className="viz-group">
                <div><strong>{sel.group.size}</strong> parts in this group across <strong>{plantsInGroup}</strong> plant{plantsInGroup === 1 ? '' : 's'}</div>
                <div><strong>{fmtMoney(sel.group.savings ?? 0)}</strong> annual savings</div>
                <div className="viz-actions">
                  <button className="btn primary" onClick={() => openCloseup(sel.group!.group_id)} disabled={cuLoading}>
                    {cuLoading ? 'Loading…' : 'Close-up'}
                  </button>
                  <button className="btn ghost-dark" onClick={() => onOpenGroup(sel.group!.group_id)}>Open group</button>
                </div>
              </div>
            ) : <div className="viz-group muted">Not in a match group.</div>}
            <div className="viz-nbrs-h">Nearest neighbors (live Vector Search)</div>
            {nbrErr && <div className="err">{nbrErr}</div>}
            {!nbrs && !nbrErr && <div className="muted">Querying…</div>}
            {nbrs && (
              <table className="viz-nbrs">
                <tbody>
                  {nbrs.neighbors.map((nb) => (
                    <tr key={nb.part_id} className={nb.is_duplicate ? 'dup' : ''}>
                      <td>{nb.part_number}</td>
                      <td>{nb.plant_id}</td>
                      <td className="num">L2 {nb.l2.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {nbrs && <div className="muted small">Green = within the matcher's L2 ≤ {nbrs.threshold} threshold. Distances are measured in the full 21-dim space, not the projection.</div>}
          </div>
        )}
      </div>
    </div>
  );
}
