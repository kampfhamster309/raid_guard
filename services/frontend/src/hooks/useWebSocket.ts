import { useCallback, useEffect, useRef, useState } from "react";
import { createAlertWebSocket, getToken } from "../api";
import type { WsStatus } from "../types";

const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000];

interface UseWebSocketOptions {
  onMessage: (data: string) => void;
  enabled: boolean;
}

export function useWebSocket({ onMessage, enabled }: UseWebSocketOptions): WsStatus {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const onMessageRef = useRef(onMessage);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // keep onMessage ref up-to-date without forcing reconnect
  useEffect(() => {
    onMessageRef.current = onMessage;
  });

  const connect = useCallback(() => {
    const token = getToken();
    if (!token || !enabled) return;

    setStatus("connecting");
    const ws = createAlertWebSocket(token);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      attemptsRef.current = 0;
    };

    ws.onmessage = (event) => {
      onMessageRef.current(event.data as string);
    };

    ws.onclose = () => {
      setStatus("disconnected");
      wsRef.current = null;
      const delay =
        BACKOFF_MS[Math.min(attemptsRef.current, BACKOFF_MS.length - 1)];
      attemptsRef.current += 1;
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      wsRef.current?.close();
      return;
    }
    connect();
    return () => {
      if (timerRef.current != null) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect, enabled]);

  return status;
}
