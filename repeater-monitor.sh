#!/bin/bash
# repeater-monitor.sh — start/stop/restart the repeater monitor app

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$APP_DIR/.app.pid"
LOGFILE="$APP_DIR/backend.log"
VENV="$APP_DIR/venv"

start() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "Already running (PID $(cat "$PIDFILE"))"
        return 1
    fi

    echo "Starting repeater-monitor..."
    source "$VENV/bin/activate"
    cd "$APP_DIR"
    nohup python3 backend/app.py >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Started (PID $!), logging to $LOGFILE"
}

stop() {
    if [ ! -f "$PIDFILE" ]; then
        echo "Not running (no pidfile)"
        return 1
    fi

    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping repeater-monitor (PID $PID)..."
        kill "$PID"
        sleep 1
        # Force kill if still alive
        kill -0 "$PID" 2>/dev/null && kill -9 "$PID"
        echo "Stopped."
    else
        echo "Process $PID not running."
    fi
    rm -f "$PIDFILE"
}

restart() {
    stop
    sleep 1
    start
}

status() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "Running (PID $(cat "$PIDFILE"))"
    else
        echo "Not running"
        [ -f "$PIDFILE" ] && rm -f "$PIDFILE"
    fi
}

case "${1:-}" in
    start)   start   ;;
    stop)    stop    ;;
    restart) restart ;;
    status)  status  ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
