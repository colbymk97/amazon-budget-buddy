#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/.run_logs"
API_PID_FILE="$RUN_DIR/api.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"

API_HOST="127.0.0.1"
API_PORT="8000"
WEB_HOST="127.0.0.1"
WEB_PORT="5173"

mkdir -p "$RUN_DIR" "$LOG_DIR"

PY="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

is_pid_running() {
  local pid="$1"
  if [[ -z "${pid:-}" ]]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

port_pid() {
  local port="$1"
  lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

start_api() {
  local running_pid
  running_pid="$(port_pid "$API_PORT")"
  if [[ -n "$running_pid" ]]; then
    echo "API already running on :$API_PORT (pid $running_pid)"
    echo "$running_pid" >"$API_PID_FILE"
    return
  fi
  (
    cd "$ROOT_DIR"
    nohup "$PY" -m uvicorn amazon_spending.api:app --host "$API_HOST" --port "$API_PORT" \
      >"$LOG_DIR/api.log" 2>&1 &
    echo $! >"$API_PID_FILE"
  )
  sleep 1
  echo "API started on http://$API_HOST:$API_PORT (pid $(cat "$API_PID_FILE"))"
}

start_web() {
  local running_pid
  running_pid="$(port_pid "$WEB_PORT")"
  if [[ -n "$running_pid" ]]; then
    echo "Web already running on :$WEB_PORT (pid $running_pid)"
    echo "$running_pid" >"$WEB_PID_FILE"
    return
  fi
  (
    cd "$ROOT_DIR/frontend"
    nohup npm run dev -- --host "$WEB_HOST" --port "$WEB_PORT" \
      >"$LOG_DIR/web.log" 2>&1 &
    echo $! >"$WEB_PID_FILE"
  )
  sleep 1
  echo "Web started on http://$WEB_HOST:$WEB_PORT (pid $(cat "$WEB_PID_FILE"))"
}

stop_pid_file() {
  local pid_file="$1"
  local name="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" || true)"
    if is_pid_running "$pid"; then
      kill "$pid" >/dev/null 2>&1 || true
      sleep 1
      if is_pid_running "$pid"; then
        kill -9 "$pid" >/dev/null 2>&1 || true
      fi
      echo "Stopped $name (pid $pid)"
    fi
    rm -f "$pid_file"
  fi
}

stop_port() {
  local port="$1"
  local name="$2"
  local pid
  pid="$(port_pid "$port")"
  if [[ -n "$pid" ]]; then
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
    if is_pid_running "$pid"; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    echo "Stopped $name on :$port (pid $pid)"
  fi
}

stop_all() {
  stop_pid_file "$API_PID_FILE" "API"
  stop_pid_file "$WEB_PID_FILE" "Web"
  stop_port "$API_PORT" "API"
  stop_port "$WEB_PORT" "Web"
}

status_all() {
  local api_pid web_pid
  api_pid="$(port_pid "$API_PORT")"
  web_pid="$(port_pid "$WEB_PORT")"
  if [[ -n "$api_pid" ]]; then
    echo "API: running (pid $api_pid) -> http://$API_HOST:$API_PORT"
  else
    echo "API: stopped"
  fi
  if [[ -n "$web_pid" ]]; then
    echo "Web: running (pid $web_pid) -> http://$WEB_HOST:$WEB_PORT"
  else
    echo "Web: stopped"
  fi
}

cmd="${1:-}"
case "$cmd" in
  start)
    start_api
    start_web
    status_all
    ;;
  stop)
    stop_all
    status_all
    ;;
  restart)
    stop_all
    start_api
    start_web
    status_all
    ;;
  status)
    status_all
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
