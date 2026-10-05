import { useState, useRef, useEffect } from 'react';
import { askGenie } from '../api';
import type { ChatResponse } from '../api';

const EXAMPLES = [
  'Total annual savings by part category',
  'Which groups span both harvesters and tractors?',
  'How many parts have a duplicate in a different plant?',
];

interface Turn {
  role: 'user' | 'genie';
  text: string;
  sql?: string | null;
  columns?: string[];
  rows?: (string | number | null)[][];
  error?: string | null;
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

function ResultTable({ columns, rows }: { columns: string[]; rows: (string | number | null)[][] }) {
  if (!columns.length || !rows.length) return null;
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

export default function ChatPanel() {
  const [collapsed, setCollapsed] = useState(false);
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
        },
      ]);
    } catch (e) {
      setTurns((t) => [...t, { role: 'genie', text: '', error: String(e) }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`genie-dock ${collapsed ? 'collapsed' : ''}`}>
      <div className="genie-bar" onClick={() => setCollapsed((c) => !c)}>
        <span className="genie-title">
          <span className="genie-spark">✦</span> Ask Genie
        </span>
        <span className="genie-sub">Natural-language Q&amp;A across the full catalog</span>
        <span className="spacer" style={{ flex: 1 }} />
        {conversationId && !collapsed && (
          <button
            className="genie-newchat"
            onClick={(e) => {
              e.stopPropagation();
              setTurns([]);
              setConversationId(null);
            }}
          >
            New chat
          </button>
        )}
        <span className="genie-caret">{collapsed ? '▴' : '▾'}</span>
      </div>

      {!collapsed && (
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
                      <div className="genie-answer">{t.text}</div>
                    )}
                    {t.columns && t.rows && <ResultTable columns={t.columns} rows={t.rows} />}
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
      )}
    </div>
  );
}
