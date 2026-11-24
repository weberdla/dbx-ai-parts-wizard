import { useState, useRef, useEffect } from 'react';
import { askGenie } from '../api';
import type { ChatResponse } from '../api';

const EXAMPLES = [
  'Show me the highest-value part standardization opportunities across the company',
  'Total annual savings by part category',
  'Top 10 match groups by savings that span both harvesters and tractors',
];

// What a Genie answer can point the map at. Detected from the result's column names.
export interface MapRequest {
  label: string;
  groupIds?: string[];
  partIds?: string[];
  partNumbers?: string[];
  categories?: string[];
  blocks?: string[];
}

function mapRequestFrom(question: string, columns: string[] = [], rows: (string | number | null)[][] = []): MapRequest | null {
  if (!columns.length || !rows.length) return null;
  const find = (re: RegExp) => columns.findIndex((c) => re.test(c.toLowerCase()));
  const vals = (i: number) => [...new Set(rows.map((r) => r[i]).filter((v) => v != null).map(String))];
  const label = question.length > 60 ? question.slice(0, 57) + '…' : question;
  const g = find(/(^|_)group_id$/), p = find(/(^|_)part_id$/), n = find(/part_number$/);
  if (g >= 0) return { label, groupIds: vals(g) };
  if (p >= 0) return { label, partIds: vals(p) };
  if (n >= 0) return { label, partNumbers: vals(n) };
  const cat = find(/(^|_)(part_)?category$/), mat = find(/(^|_)material$/);
  if (cat >= 0 && mat >= 0) return { label, blocks: [...new Set(rows.map((r) => `${r[cat]}|${r[mat]}`))] };
  if (cat >= 0) return { label, categories: vals(cat) };
  return null;
}

interface Turn {
  role: 'user' | 'genie';
  text: string;
  sql?: string | null;
  columns?: string[];
  rows?: (string | number | null)[][];
  error?: string | null;
  mapReq?: MapRequest | null;
}

// Genie answers use light markdown; render **bold** instead of showing the asterisks.
function Answer({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <div className="genie-answer">
      {parts.map((p, i) => (p.startsWith('**') && p.endsWith('**') ? <strong key={i}>{p.slice(2, -2)}</strong> : p))}
    </div>
  );
}

function SqlBlock({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="sqlblock">
      <button className="sqltoggle" onClick={() => setOpen((o) => !o)}>
        {open ? '▾' : '▸'} Generated SQL
      </button>
      {open && <pre className="sqlcode">{sql}</pre>}
    </div>
  );
}

// Id columns (long hashes) drive the map but are noise in the table, so hide them.
const HIDDEN = /(^|_)(group_id|part_id)$/i;

function ResultTable({ columns: allCols, rows: allRows }: { columns: string[]; rows: (string | number | null)[][] }) {
  if (!allCols.length || !allRows.length) return null;
  const keep = allCols.map((c, i) => (HIDDEN.test(c) ? -1 : i)).filter((i) => i >= 0);
  if (!keep.length) return null;
  const columns = keep.map((i) => allCols[i]);
  const rows = allRows.map((r) => keep.map((i) => r[i]));
  return (
    <div className="chat-result">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j}>{v == null ? '' : String(v)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface Props {
  open: boolean;
  onClose: () => void;
  onShowOnMap: (req: MapRequest) => void;
  onAsk?: (question: string) => void;
  onOpened?: () => void; // slide-in finished
}

export default function ChatPanel({ open, onClose, onShowOnMap, onAsk, onOpened }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns, busy]);

  const send = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setInput('');
    setTurns((t) => [...t, { role: 'user', text: q }]);
    onAsk?.(q);
    setBusy(true);
    try {
      const res: ChatResponse = await askGenie(q, conversationId);
      if (res.conversation_id) setConversationId(res.conversation_id);
      setTurns((t) => [
        ...t,
        {
          role: 'genie',
          text: res.answer || res.error || 'No answer returned.',
          sql: res.sql,
          columns: res.columns,
          rows: res.rows,
          error: res.error,
          mapReq: mapRequestFrom(q, res.columns, res.rows),
        },
      ]);
    } catch (e) {
      setTurns((t) => [...t, { role: 'genie', text: '', error: String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside
      className={`genie-drawer ${open ? 'open' : ''}`}
      aria-hidden={!open}
      onTransitionEnd={(e) => {
        if (e.target !== e.currentTarget || e.propertyName !== 'transform' || !open) return;
        onOpened?.();
        inputRef.current?.focus();
      }}
    >
      <div className="genie-bar">
        <span className="genie-title">
          <span className="genie-spark">✦</span> Ask Genie
        </span>
        <span className="spacer" style={{ flex: 1 }} />
        {conversationId && (
          <button
            className="genie-newchat"
            onClick={() => {
              setTurns([]);
              setConversationId(null);
            }}
          >
            New chat
          </button>
        )}
        <button className="genie-close" onClick={onClose} title="Close">×</button>
      </div>
      <div className="genie-sub-row">Natural-language Q&amp;A across the full catalog. Answers that name groups, parts or categories can drive the Similarity Map.</div>

        <div className="genie-body">
          <div className="genie-messages" ref={scrollRef}>
            {turns.length === 0 && (
              <div className="genie-empty">
                <div className="genie-empty-note">
                  Ask about savings, duplication spans, suppliers or plants across all match
                  groups. Try:
                </div>
                <div className="genie-chips">
                  {EXAMPLES.map((ex) => (
                    <button key={ex} className="genie-chip" onClick={() => send(ex)}>
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {turns.map((t, i) => (
              <div key={i} className={`genie-msg ${t.role}`}>
                {t.role === 'user' ? (
                  <div className="bubble user">{t.text}</div>
                ) : (
                  <div className="bubble genie">
                    {t.error && !t.text ? (
                      <div className="genie-err">{t.error}</div>
                    ) : (
                      <Answer text={t.text} />
                    )}
                    {t.columns && t.rows && <ResultTable columns={t.columns} rows={t.rows} />}
                    {t.mapReq && (
                      <button className="genie-map" onClick={() => onShowOnMap(t.mapReq!)}>
                        ◎ Show on map
                      </button>
                    )}
                    {t.sql && <SqlBlock sql={t.sql} />}
                  </div>
                )}
              </div>
            ))}
            {busy && (
              <div className="genie-msg genie">
                <div className="bubble genie thinking">
                  <span className="dot" /> <span className="dot" /> <span className="dot" />
                  &nbsp;Genie is thinking…
                </div>
              </div>
            )}
          </div>

          <form
            className="genie-input"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input
              ref={inputRef}
              type="text"
              placeholder="Ask a question about the match catalog…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={busy}
            />
            <button type="submit" className="btn primary" disabled={busy || !input.trim()}>
              {busy ? '…' : 'Ask'}
            </button>
          </form>
        </div>
    </aside>
  );
}
