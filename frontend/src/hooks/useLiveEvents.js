import { useEffect, useRef, useState } from 'react';
import { streamUrl } from '../api';

const EVENT_TYPES = ['ready', 'trades', 'job', 'resync'];
const RECONNECT_GRACE_MS = 2500;
const HARD_RETRY_MS = 3000;

/**
 * Subscribes to the server's SSE stream (no polling).
 *
 * - `since` is the last_event_id from the REST snapshot, so nothing between the
 *   snapshot and the subscription is lost.
 * - On a dropped connection the browser's EventSource reconnects by itself and sends
 *   the `Last-Event-ID` header; the server replays everything after that id.
 * - The server deliberately closes each connection after ~25 s (the network kills
 *   connections at 30 s). The reconnect takes ~1 s, so a short grace period stops
 *   the status from flickering to "reconnecting" every time.
 * - If the server answers with an error (e.g. backend stopped), EventSource gives up
 *   for good. We then open a new one, resuming from the last event id we processed.
 *
 * Changing `epoch` forces a fresh subscription from `since` (used after a `resync`).
 *
 * Returns the connection status: 'connecting' | 'live' | 'reconnecting'.
 */
export function useLiveEvents(since, epoch, onEvent) {
  const [status, setStatus] = useState('connecting');
  const [attempt, setAttempt] = useState(0);
  const handlerRef = useRef(onEvent);
  const lastIdRef = useRef(null);
  handlerRef.current = onEvent;

  // A new snapshot means a new starting point.
  useEffect(() => {
    lastIdRef.current = null;
  }, [since, epoch]);

  useEffect(() => {
    if (since == null) return undefined;
    const source = new EventSource(streamUrl(lastIdRef.current ?? since));
    let graceTimer = null;
    let retryTimer = null;

    const markLive = () => {
      clearTimeout(graceTimer);
      setStatus('live');
    };

    const listeners = EVENT_TYPES.map((type) => {
      const listener = (message) => {
        markLive();
        const id = Number(message.lastEventId);
        if (Number.isFinite(id) && message.lastEventId !== '') lastIdRef.current = id;
        let data;
        try {
          data = JSON.parse(message.data);
        } catch {
          return;
        }
        handlerRef.current(type, data, id);
      };
      source.addEventListener(type, listener);
      return [type, listener];
    });

    source.onopen = markLive;
    source.onerror = () => {
      clearTimeout(graceTimer);
      if (source.readyState === EventSource.CLOSED) {
        setStatus('reconnecting');
        retryTimer = setTimeout(() => setAttempt((n) => n + 1), HARD_RETRY_MS);
      } else {
        graceTimer = setTimeout(() => setStatus('reconnecting'), RECONNECT_GRACE_MS);
      }
    };

    return () => {
      clearTimeout(graceTimer);
      clearTimeout(retryTimer);
      listeners.forEach(([type, listener]) => source.removeEventListener(type, listener));
      source.close();
    };
  }, [since, epoch, attempt]);

  return status;
}
