import './Notice.css';

// A dismissible message bar for success / info / warning / error feedback.
export default function Notice({ notice, onDismiss }) {
  if (!notice) return null;
  return (
    <div className={`notice notice--${notice.type}`} role={notice.type === 'error' ? 'alert' : 'status'}>
      <span>{notice.text}</span>
      <button type="button" className="notice__close" onClick={onDismiss} aria-label="Dismiss">×</button>
    </div>
  );
}
