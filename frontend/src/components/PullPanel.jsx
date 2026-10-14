import { formatDateTime, formatNumber } from '../utils/format';
import './PullPanel.css';

const STATUS_LABEL = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Completed',
  failed: 'Failed',
};

function describe(job) {
  if (!job) return 'No pull has been started yet.';
  switch (job.status) {
    case 'queued':
      return 'Waiting for the worker process to pick up this job. (Is the worker running?)';
    case 'running':
      return job.pages_total
        ? `Fetching batch ${Math.min(job.pages_done + 1, job.pages_total)} of ${job.pages_total} from BSE…`
        : 'Connecting to BSE…';
    case 'succeeded':
      return `Finished: ${formatNumber(job.inserted_count)} new trades stored` +
        (job.duplicate_count ? `, ${formatNumber(job.duplicate_count)} duplicates skipped.` : '.');
    case 'failed':
      return 'The pull stopped with an error. Trades already stored are kept; you can start a new pull.';
    default:
      return '';
  }
}

export default function PullPanel({ job, lastSuccessAt, starting, onPull, loading }) {
  const active = job && (job.status === 'queued' || job.status === 'running');
  const progress = job?.progress_percent ?? 0;
  const showWarning = job?.status === 'running' && job.error;

  return (
    <section className="panel pull-panel" aria-label="Trade pull">
      <div className="pull-panel__top">
        <div className="pull-panel__info">
          <div className="pull-panel__heading">
            <h2 className="panel__title">Trade pull</h2>
            {job && (
              <span className={`badge badge--${job.status}`}>
                {active && <span className="badge__spinner" aria-hidden="true" />}
                {STATUS_LABEL[job.status] ?? job.status}
                <span className="badge__id">#{job.id}</span>
              </span>
            )}
          </div>
          <p className="pull-panel__desc">{loading ? 'Loading status…' : describe(job)}</p>
        </div>
        <button
          type="button"
          className="button button--primary"
          onClick={onPull}
          disabled={loading || starting || active}
        >
          {starting ? 'Starting…' : active ? 'Pull in progress' : 'Pull Trades'}
        </button>
      </div>

      {job && job.status !== 'succeeded' && job.status !== 'failed' && (
        <div className="progress" aria-label="Pull progress">
          <div className="progress__track" role="progressbar" aria-valuemin={0} aria-valuemax={100}
            aria-valuenow={progress}>
            <div className={`progress__bar ${job.status === 'queued' ? 'progress__bar--waiting' : ''}`}
              style={{ width: `${job.status === 'queued' ? 100 : progress}%` }} />
          </div>
          <div className="progress__meta">
            <span>{progress.toFixed(0)}%</span>
            <span>
              {formatNumber(job.fetched_count)}
              {job.total_expected ? ` / ${formatNumber(job.total_expected)}` : ''} trades fetched
            </span>
          </div>
        </div>
      )}

      {showWarning && <div className="inline-alert inline-alert--warning">{job.error}</div>}
      {job?.status === 'failed' && job.error && (
        <div className="inline-alert inline-alert--error"><strong>Error:</strong> {job.error}</div>
      )}

      <dl className="pull-panel__facts">
        <div>
          <dt>Last successful pull</dt>
          <dd>{loading ? '…' : formatDateTime(lastSuccessAt)}</dd>
        </div>
        {job && (
          <div>
            <dt>Current / last job</dt>
            <dd>
              #{job.id} · {formatNumber(job.inserted_count)} new · {formatNumber(job.fetched_count)} fetched
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
