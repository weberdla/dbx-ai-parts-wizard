import { useEffect, useState, useCallback } from 'react';
import type { Filters, FilterOptions, QueueRow } from './types';
import { getFilters, getQueue, getMe } from './api';
import FiltersPanel from './components/Filters';
import MatchQueue from './components/MatchQueue';
import GroupDetail from './components/GroupDetail';
import ChatPanel from './components/ChatPanel';

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

  useEffect(() => {
    getFilters().then(setOptions).catch((e) => setErr(String(e)));
    getMe().then((m) => setReviewer(m.reviewer)).catch(() => {});
  }, []);

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

  return (
    <div className="app">
      <header className="header">
        <span className="logo-dot" />
        <h1>AI Parts Wizard</h1>
        <span className="sub">Part rationalization review</span>
        <span className="spacer" />
        {reviewer && <span className="user">Reviewer: {reviewer}</span>}
      </header>

      <div className="body">
        <FiltersPanel
          options={options}
          filters={filters}
          onChange={setFilters}
          onReset={() => setFilters(DEFAULT_FILTERS)}
        />

        <main className="main">
          <div className="toolbar">
            <span className="count">
              <strong>{total.toLocaleString()}</strong> match groups
              {rows.length < total ? ` (showing ${rows.length})` : ''}
            </span>
            <span className="spacer" style={{ flex: 1 }} />
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
          </div>

          {err && <div className="err" style={{ padding: '8px 20px' }}>{err}</div>}

          <MatchQueue rows={rows} loading={loading} onOpen={setOpenGroup} />

          <ChatPanel />
        </main>
      </div>

      {openGroup && (
        <GroupDetail
          groupId={openGroup}
          onClose={() => setOpenGroup(null)}
          onChanged={loadQueue}
          toast={toast}
        />
      )}

      {toastMsg && <div className="toast">{toastMsg}</div>}
    </div>
  );
}
