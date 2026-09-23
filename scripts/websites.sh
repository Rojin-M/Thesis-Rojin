#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

# Manage the named HTTP servers independently of the watcher and model worker.
configure_site() {
  site_name="$1"
  case "$site_name" in
    academy)
      site_session=exoplanet-academy
      site_port=8765
      site_log=outputs/academy/server.log
      site_health=http://127.0.0.1:8765/
      site_url=http://127.0.0.1:8765/#dashboard
      site_command='exec .venv/bin/python -u academy/serve.py --host 127.0.0.1 --port 8765 >> outputs/academy/server.log 2>&1'
      ;;
    research)
      site_session=exoplanet-research
      site_port=8766
      site_log=outputs/research/server.log
      site_health=http://127.0.0.1:8766/api/health
      site_url=http://127.0.0.1:8766/#overview
      site_command='exec .venv/bin/python -u -m scripts.research serve --host 127.0.0.1 --port 8766 >> outputs/research/server.log 2>&1'
      ;;
    recovery)
      site_session=exoplanet-research-recovery
      site_port=8767
      site_log=outputs/research/recovery-server.log
      site_health=http://127.0.0.1:8767/api/health
      site_url=http://127.0.0.1:8767/#overview
      site_command='exec .venv/bin/python -u -m scripts.research serve --host 127.0.0.1 --port 8767 >> outputs/research/recovery-server.log 2>&1'
      ;;
    *) printf 'Unknown site: %s (use academy, research, all, or recovery)\n' "$site_name" >&2; return 2 ;;
  esac
}

site_session_exists() { tmux has-session -t "=$site_session" 2>/dev/null; }
site_healthy() { curl --noproxy '*' --max-time 2 -fsS "$site_health" >/dev/null 2>&1; }
site_port_busy() {
  .venv/bin/python - "$site_port" <<'PY'
import socket, sys
with socket.socket() as client:
    client.settimeout(0.3)
    sys.exit(0 if client.connect_ex(('127.0.0.1', int(sys.argv[1]))) == 0 else 1)
PY
}

start_site() {
  if site_session_exists; then
    if site_healthy; then
      printf '%s already running: %s\n' "$site_name" "$site_url"
      return 0
    fi
    printf '%s has a session but is not responding. Try: bash scripts/websites.sh restart %s\n' "$site_name" "$site_name" >&2
    return 1
  fi
  if site_port_busy; then
    printf 'Port %s is occupied outside the expected session. Inspect it with: ss -ltnp "sport = :%s"\n' "$site_port" "$site_port" >&2
    printf '%s\n' 'Stop that website in its original terminal with Ctrl+C; this helper does not kill an unidentified process.' >&2
    return 1
  fi
  mkdir -p "$(dirname -- "$site_log")"
  tmux new-session -d -s "$site_session" -c "$project_root" "$site_command"
  for attempt in {1..20}; do
    if site_healthy; then printf '%s ready: %s\n' "$site_name" "$site_url"; return 0; fi
    sleep 0.5
  done
  printf '%s did not become ready. Inspect: tail -n 60 %s\n' "$site_name" "$site_log" >&2
  return 1
}

stop_site() {
  if site_session_exists; then
    # Exact session targeting avoids confusing research with research-recovery.
    if [ "$(tmux display-message -p -t "=$site_session:0.0" '#{pane_dead}')" = 1 ]; then
      tmux kill-session -t "=$site_session"
    else
      tmux send-keys -t "=$site_session:0.0" C-c
    fi
    for attempt in {1..20}; do
      if ! site_session_exists; then break; fi
      sleep 0.5
    done
    if site_session_exists; then
      printf '%s has not exited; inspect: tmux attach -t =%s\n' "$site_name" "$site_session" >&2
      return 1
    fi
  fi
  if site_port_busy; then
    printf 'Port %s is still occupied. Inspect: ss -ltnp "sport = :%s"\n' "$site_port" "$site_port" >&2
    return 1
  fi
  printf '%s stopped; remote port %s is free.\n' "$site_name" "$site_port"
}

manage_sites() {
  local operation="${1:-status}" selected="${2:-all}" name
  case "$operation" in start|restart|stop|status|open|logs) ;; *) printf 'Use {start|restart|stop|status|open|logs} [all|academy|research|recovery]\n' >&2; return 2 ;; esac
  local names=("$selected")
  if [ "$selected" = all ]; then names=(academy research); fi
  for name in "${names[@]}"; do
    configure_site "$name"
    case "$operation" in
      start) start_site ;;
      restart) stop_site; start_site ;;
      stop) stop_site ;;
      status)
        if site_healthy; then
          if site_session_exists; then printf '%s: healthy in tmux · %s\n' "$site_name" "$site_url"
          else printf '%s: responding outside the expected tmux session · %s\n' "$site_name" "$site_url"; fi
        elif site_session_exists; then printf '%s: tmux session exists but HTTP is not healthy; inspect %s\n' "$site_name" "$site_log"
        else printf '%s: not responding on port %s\n' "$site_name" "$site_port"; fi
        ;;
      logs) if [ -f "$site_log" ]; then printf '\n%s log:\n' "$site_name"; tail -n 40 "$site_log"; else printf 'No log yet: %s\n' "$site_log"; fi ;;
      open)
        start_site
        if [ -n "${BROWSER:-}" ] && [ -x "$BROWSER" ]; then "$BROWSER" "$site_url"
        else printf 'Forward remote and local port %s in VS Code, then open %s\n' "$site_port" "$site_url"; fi
        ;;
    esac
  done
}

manage_sites "${1:-status}" "${2:-all}"
