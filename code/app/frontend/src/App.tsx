import { useEffect, useState, useCallback, useRef } from 'react';
import type { Filters, FilterOptions, QueueRow } from './types';
import { getFilters, getQueue, getMe, locateOnMap, getSummary } from './api';
import type { Summary } from './api';
import FiltersPanel from './components/Filters';
import MatchQueue from './components/MatchQueue';
import GroupDetail from './components/GroupDetail';
import ChatPanel from './components/ChatPanel';
import type { MapRequest } from './components/ChatPanel';
import type { MapFocus } from './components/viz/types';
import type { ThemeName } from './components/viz/theme';
import EmbeddingView from './components/EmbeddingView';
import DecisionStrip from './components/DecisionStrip';

// Default view: status=new AND spans > 1 model, sorted by savings desc.
const DEFAULT_FILTERS: Filters = {
  part_category: '',
  material: '',
  machine_type: '',
  spans_models: true,
  spans_machine_types: false,
  spans_plants: false,
  model: '',
  plant: '',
  supplier: '',
  min_savings: '',
  min_similarity: '',
  status: 'new',
  normalized: '',
  min_group_size: '',
};

export default function App() {
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [sort, setSort] = useState('savings_potential');
  const [direction, setDirection] = useState('desc');
  const [rows, setRows] = useState<QueueRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState('');
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [view, setView] = useState<'queue' | 'map'>('queue');
  const [mapMounted, setMapMounted] = useState(false); // keep the map alive once opened
  // Drawer: `chatOpen` slides it in (transform, cheap); `chatDocked` reserves its width once the
  // slide finishes, so the 3D canvas resizes once instead of on every animation frame.
  const [chatOpen, setChatOpen] = useState(() => localStorage.getItem('apw.chatOpen') === '1');
  const [chatDocked, setChatDocked] = useState(chatOpen);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [reached, setReached] = useState(-1); // decision strip progress
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [mapCtl, setMapCtl] = useState<HTMLElement | null>(null);
  const nonce = useRef(0);
  // App-wide light/dark theme (the map follows it). Applied to <html> so the page background matches.
  const [theme, setTheme] = useState<ThemeName>(
    () => ((localStorage.getItem('apw.theme') || localStorage.getItem('apw.mapTheme')) as ThemeName) || 'dark'
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('apw.theme', theme);
  }, [theme]);

  useEffect(() => {
    getFilters().then(setOptions).catch((e) => setErr(String(e)));
    getMe().then((m) => setReviewer(m.reviewer)).catch(() => {});
  }, []);

  useEffect(() => { if (view === 'map') setMapMounted(true); }, [view]);

  const loadSummary = useCallback(() => { getSummary().then(setSummary).catch(() => {}); }, []);
  useEffect(() => { loadSummary(); }, [loadSummary]);
  const reach = (n: number) => setReached((r) => Math.max(r, n));

  const toggleChat = (open?: boolean) => {
    const next = open ?? !chatOpen;
    localStorage.setItem('apw.chatOpen', next ? '1' : '0');
    setChatOpen(next);
    if (!next) setChatDocked(false); // free the space right away; the drawer slides out over it
  };

  const loadQueue = useCallback(() => {
    setLoading(true);
    setErr(null);
    getQueue(filters, sort, direction, 200, 0)
      .then((r) => {
        setRows(r.rows);
        setTotal(r.total);
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [filters, sort, direction]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  const toast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg(null), 2500);
  };

  const focusMap = (f: Omit<MapFocus, 'nonce'>) => {
    reach(1);
    nonce.current += 1;
    setFocus({ ...f, nonce: nonce.current });
    setView('map');
  };

  // Filters drive the map too: category + material opens that block, category alone
  // highlights the category in the whole-catalog view.
  const prevCatMat = useRef(`${filters.part_category}|${filters.material}`);
  useEffect(() => {
    const key = `${filters.part_category}|${filters.material}`;
    if (key === prevCatMat.current) return;
    prevCatMat.current = key;
    const { part_category: cat, material: mat } = filters;
    nonce.current += 1;
    if (cat && mat) setFocus({ nonce: nonce.current, scope: `${cat}|${mat}`, label: `Filter: ${cat} · ${mat}` });
    else if (cat) setFocus({ nonce: nonce.current, scope: 'global', categories: [cat], label: `Filter: ${cat}` });
    else setFocus(null);
  }, [filters]);

  // One entry point for the queue, group drawer and Genie to point the map at something.
  const showOnMap = async (req: MapRequest) => {
    if (req.blocks?.length || req.categories?.length) {
      focusMap({ scope: 'global', label: req.label, blocks: req.blocks, categories: req.categories });
      return;
    }
    try {
      const loc = await locateOnMap({
        group_ids: req.groupIds, part_ids: req.partIds, part_numbers: req.partNumbers,
      });
      if (!loc.part_ids.length) { toast('Nothing from that result is on the map'); return; }
      const oneBlock = loc.blocks.length === 1 ? loc.blocks[0].block_key : null;
      setOpenGroup(null);
      focusMap({
        scope: oneBlock ?? 'global',
        label: req.label,
        partIds: loc.part_ids,
        groupIds: loc.group_ids,
        autoSelect: loc.group_ids.length === 1,
      });
    } catch (e) {
      toast(`Could not locate on map: ${e}`);
    }
  };

  const showGroup = (groupId: string, label?: string) =>
    showOnMap({ label: label ?? `Group ${groupId.slice(0, 8)}…`, groupIds: [groupId] });

  const money = (n: number) => '$' + Math.round(n).toLocaleString('en-US');

  return (
    <div className="app">
      <header className="header">
        <span className="logo-dot" />
        <h1>AI Parts Wizard</h1>
        <span className="sub">Part rationalization review</span>
        <span className="spacer" />
        {reviewer && <span className="user">Reviewer: {reviewer}</span>}
        <button
          className="theme-toggle"
          onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label="Toggle light / dark mode"
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>
        <button
          className={`genie-toggle ${chatOpen ? 'on' : ''}`}
          onClick={() => toggleChat()}
          title="Ask Genie"
        >
          <span className="genie-spark">✦</span> Ask Genie
        </button>
      </header>

      <DecisionStrip summary={summary} lastQuestion={lastQuestion} reached={reached} />

      <div className="body">
        <FiltersPanel
          options={options}
          filters={filters}
          onChange={setFilters}
          onReset={() => setFilters(DEFAULT_FILTERS)}
        />

        <main className="main" style={chatDocked ? { marginRight: 420 } : undefined}>
          <div className="toolbar">
            <div className="seg">
              <button className={view === 'queue' ? 'on' : ''} onClick={() => setView('queue')}>Match Queue</button>
              <button className={view === 'map' ? 'on' : ''} onClick={() => setView('map')}>Similarity Map</button>
            </div>
            <span className="count">
              <strong>{total.toLocaleString()}</strong> match groups
              {rows.length < total ? ` (showing ${rows.length})` : ''}
            </span>
            <span className="spacer" style={{ flex: 1 }} />
            {view === 'queue' ? (
              <span className="sortsel">
                Sort by
                <select value={sort} onChange={(e) => setSort(e.target.value)}>
                  <option value="savings_potential">Annual savings</option>
                  <option value="avg_similarity">Avg similarity</option>
                  <option value="member_count">Member count</option>
                  <option value="models_spanned">Models spanned</option>
                  <option value="total_current_spend">Annual spend</option>
                </select>
                <select value={direction} onChange={(e) => setDirection(e.target.value)}>
                  <option value="desc">Desc</option>
                  <option value="asc">Asc</option>
                </select>
              </span>
            ) : (
              <button
                className="btn"
                disabled={!rows.length}
                title="Highlight the groups currently in the queue (filters + sort)"
                onClick={() => showOnMap({
                  label: `Top ${rows.length} queue groups (${money(rows.reduce((a, r) => a + (r.savings_potential || 0), 0))}/yr)`,
                  groupIds: rows.map((r) => r.group_id),
                })}
              >
                ◎ Queue on map
              </button>
            )}
            <div ref={setMapCtl} className="map-ctl" style={view === 'map' ? undefined : { display: 'none' }} />
          </div>

          {err && <div className="err" style={{ padding: '8px 20px' }}>{err}</div>}

          {view === 'queue' && (
            <MatchQueue
              rows={rows}
              loading={loading}
              onOpen={setOpenGroup}
              onShowOnMap={(r) => showGroup(r.group_id, `${r.part_category} · ${r.material} group · ${r.member_count} parts · ${money(r.savings_potential)}/yr`)}
            />
          )}
          {mapMounted && (
            <div className="map-wrap" style={view === 'map' ? undefined : { display: 'none' }}>
              <EmbeddingView
                onOpenGroup={setOpenGroup}
                focus={focus}
                onClearFocus={() => setFocus(null)}
                controlsEl={mapCtl}
                onValidated={() => { loadQueue(); loadSummary(); reach(3); }}
                themeName={theme}
              />
            </div>
          )}
        </main>

        <ChatPanel
          open={chatOpen}
          onClose={() => toggleChat(false)}
          onShowOnMap={showOnMap}
          onAsk={(q) => { setLastQuestion(q); reach(0); }}
          onOpened={() => setChatDocked(true)}
        />
      </div>

      {openGroup && (
        <GroupDetail
          groupId={openGroup}
          onClose={() => setOpenGroup(null)}
          onChanged={() => { loadQueue(); loadSummary(); }}
          toast={toast}
          onShowOnMap={(gid) => showGroup(gid)}
        />
      )}

      {toastMsg && <div className="toast">{toastMsg}</div>}
    </div>
  );
}
