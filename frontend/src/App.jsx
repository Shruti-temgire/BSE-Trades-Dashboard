import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';
import { useLiveEvents } from './hooks/useLiveEvents';
import { formatNumber } from './utils/format';
import Header from './components/Header';
import Notice from './components/Notice';
import StatsCards from './components/StatsCards';
import PullPanel from './components/PullPanel';
import TradesTable from './components/TradesTable';
import './App.css';

const PAGE_SIZE = 25;
const SEARCH_DEBOUNCE_MS = 300;
const ACTIVE = new Set(['queued', 'running']);
const EMPTY_TABLE = { items: [], total: 0, page: 1, totalPages: 1, search: '' };

const toTable = (data) => ({
  items: data.items,
  total: data.total,
  page: data.page,
  totalPages: data.total_pages,
  search: data.search,
});

export default function App() {
  const [stats, setStats] = useState(null);
  const [job, setJob] = useState(null);
  const [lastSuccessAt, setLastSuccessAt] = useState(null);
  const [table, setTable] = useState(EMPTY_TABLE);
  const [query, setQuery] = useState({ page: 1, search: '' });
  const [searchInput, setSearchInput] = useState('');
  const [initialLoading, setInitialLoading] = useState(true);
  const [tableLoading, setTableLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [starting, setStarting] = useState(false);
  const [freshIds, setFreshIds] = useState(() => new Set());
  const [pendingNew, setPendingNew] = useState(0);
  const [stream, setStream] = useState({ since: null, epoch: 0 });

  const queryRef = useRef(query);
  queryRef.current = query;
  const jobRef = useRef(job);
  const tableSeq = useRef(0);
  const prevQuery = useRef(query);

  // ---------------------------------------------------------------- job updates

  const applyJob = useCallback((next, lastSuccess) => {
    if (!next) return;
    const prev = jobRef.current;
    if (prev && next.id < prev.id) return; // ignore stale updates about an older job
    jobRef.current = next;
    setJob(next);
    if (lastSuccess !== undefined) setLastSuccessAt(lastSuccess);

    const wasActive = prev && prev.id === next.id && ACTIVE.has(prev.status);
    if (wasActive && next.status === 'succeeded') {
      setNotice({ type: 'success', text: `Pull #${next.id} completed — ${formatNumber(next.inserted_count)} new trades stored.` });
    } else if (wasActive && next.status === 'failed') {
      setNotice({ type: 'error', text: `Pull #${next.id} failed: ${next.error}` });
    }
  }, []);

  // ---------------------------------------------------------------- REST loading

  /** Full snapshot: stats + job + current table page + SSE starting point, in one consistent read. */
  const loadSnapshot = useCallback(async () => {
    const seq = ++tableSeq.current;
    setTableLoading(true);
    try {
      const q = queryRef.current;
      const snap = await api.dashboard({ page: q.page, pageSize: PAGE_SIZE, search: q.search });
      setStats(snap.stats);
      jobRef.current = snap.latest_job;
      setJob(snap.latest_job);
      setLastSuccessAt(snap.last_successful_pull_at);
      if (seq === tableSeq.current) setTable(toTable(snap.trades));
      setPendingNew(0);
      setLoadError(null);
      setStream((s) => ({ since: snap.last_event_id, epoch: s.epoch + 1 }));
    } catch (err) {
      setLoadError(err.message);
    } finally {
      if (seq === tableSeq.current) setTableLoading(false);
      setInitialLoading(false);
    }
  }, []);

  /** Just the table page (used for paging and searching). */
  const loadTrades = useCallback(async (q) => {
    const seq = ++tableSeq.current;
    setTableLoading(true);
    try {
      const data = await api.trades({ page: q.page, pageSize: PAGE_SIZE, search: q.search });
      if (seq !== tableSeq.current) return; // a newer request has been made
      setTable(toTable(data));
      setLoadError(null);
      if (q.page === 1 && !q.search) setPendingNew(0);
    } catch (err) {
      if (seq === tableSeq.current) setLoadError(err.message);
    } finally {
      if (seq === tableSeq.current) setTableLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSnapshot();
  }, [loadSnapshot]);

  useEffect(() => {
    if (prevQuery.current === query) return;
    prevQuery.current = query;
    loadTrades(query);
  }, [query, loadTrades]);

  // Debounce typing in the search box.
  useEffect(() => {
    const timer = setTimeout(() => {
      const search = searchInput.trim();
      setQuery((q) => (q.search === search ? q : { page: 1, search }));
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Success/info messages fade away by themselves; errors stay until dismissed.
  useEffect(() => {
    if (!notice || notice.type === 'error' || notice.type === 'warning') return undefined;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  // ---------------------------------------------------------------- live events (SSE)

  const handleEvent = useCallback((type, data) => {
    if (type === 'resync') {
      loadSnapshot(); // server history no longer covers our gap: reload everything
      return;
    }
    if (data.job) applyJob(data.job, data.last_successful_pull_at);
    if (data.stats) setStats(data.stats);
    if (type !== 'trades' || !data.trades?.length) return;

    const incoming = data.trades;
    const total = data.stats.total_trades;
    const q = queryRef.current;

    if (q.page === 1 && !q.search) {
      // Newest-first page: prepend rows that are newer than anything shown.
      // Rows are ordered by the database id, so `id > newest shown id` (plus the
      // trade_id check) guarantees a trade is never shown twice, even when events are replayed.
      setTable((prev) => {
        const newestShown = prev.items[0]?.id ?? 0;
        const shown = new Set(prev.items.map((t) => t.trade_id));
        const fresh = incoming
          .filter((t) => t.id > newestShown && !shown.has(t.trade_id))
          .sort((a, b) => b.id - a.id);
        if (fresh.length === 0) return prev;
        return {
          ...prev,
          items: [...fresh, ...prev.items].slice(0, PAGE_SIZE),
          total,
          totalPages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
        };
      });
      setFreshIds(new Set(incoming.map((t) => t.trade_id)));
    } else {
      // Don't shuffle the page the user is reading; offer to jump to the latest instead.
      setPendingNew((n) => n + incoming.length);
      if (!q.search) {
        setTable((prev) => ({ ...prev, total, totalPages: Math.max(1, Math.ceil(total / PAGE_SIZE)) }));
      }
    }
  }, [applyJob, loadSnapshot]);

  const connection = useLiveEvents(stream.since, stream.epoch, handleEvent);

  // ---------------------------------------------------------------- actions

  const startPull = async () => {
    setStarting(true);
    setNotice(null);
    try {
      const res = await api.startPull();
      applyJob(res.job);
      setNotice({ type: 'info', text: `Pull #${res.job_id} queued. New trades will appear below as each batch is stored.` });
    } catch (err) {
      if (err.status === 409 && err.body?.job) {
        applyJob(err.body.job);
        setNotice({ type: 'warning', text: err.message });
      } else {
        setNotice({ type: 'error', text: `Could not start pull: ${err.message}` });
      }
    } finally {
      setStarting(false);
    }
  };

  const showLatest = () => {
    setSearchInput('');
    setQuery({ page: 1, search: '' });
    setPendingNew(0);
  };

  const connectionStatus = stream.since == null && loadError ? 'offline' : connection;

  return (
    <div className="app">
      <Header connection={connectionStatus} />
      <main className="container">
        <Notice notice={notice} onDismiss={() => setNotice(null)} />
        <StatsCards stats={stats} loading={initialLoading} />
        <PullPanel
          job={job}
          lastSuccessAt={lastSuccessAt}
          starting={starting}
          onPull={startPull}
          loading={initialLoading}
        />
        <TradesTable
          table={table}
          searchInput={searchInput}
          onSearchChange={setSearchInput}
          onPageChange={(page) => setQuery((q) => ({ ...q, page }))}
          loading={tableLoading}
          error={loadError}
          onRetry={loadSnapshot}
          freshIds={freshIds}
          pendingNew={pendingNew}
          onShowLatest={showLatest}
        />
      </main>
      <footer className="footer">
        Mock BSE data for demonstration only · Live updates via Server-Sent Events
      </footer>
    </div>
  );
}
