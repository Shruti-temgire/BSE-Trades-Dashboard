import './Header.css';

const LABELS = {
  live: 'Live',
  connecting: 'Connecting…',
  reconnecting: 'Reconnecting…',
  offline: 'Offline',
};

export default function Header({ connection }) {
  return (
    <header className="header">
      <div className="header__inner">
        <div className="header__brand">
          <span className="header__logo" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="22" height="22">
              <path d="M6 22l6-7 5 4 9-10" fill="none" stroke="currentColor" strokeWidth="3"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <div>
            <h1 className="header__title">BSE Trades Dashboard</h1>
            <p className="header__subtitle">Equity trade pulls · Bombay Stock Exchange (mock feed)</p>
          </div>
        </div>
        <div className={`connection connection--${connection}`} role="status" aria-live="polite">
          <span className="connection__dot" />
          {LABELS[connection] ?? connection}
        </div>
      </div>
    </header>
  );
}
