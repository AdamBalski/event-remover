#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/AdamBalski/event-remover"

if [ -z "${PORT:-}" ]; then
    echo "ERROR: PORT environment variable not set."
    exit 1
fi
if [ -z "${ORIGIN:-}" ]; then
    echo "ERROR: ORIGIN environment variable not set."
    exit 1
fi

ssh "${REMOTE_USERNAME}@${REMOTE_HOST}" -p "$REMOTE_PORT" bash <<EOF
    set -euo pipefail
    echo "==> Killing previous app..."
    pkill -f 'EVENT_REMOVER' || true

    echo "==> Cloning/updating repo..."
    [ -d "event-remover" ] || git clone $REPO_URL event-remover
    cd event-remover
    git fetch --all && git reset --hard origin/main

    echo "==> Starting app..."
    # the last python3 parameter is not used by the app, 
    # but simplifies the above pkill command
    PORT='$PORT' \
        ORIGIN='$ORIGIN' \
        nohup python3 run.py EVENT_REMOVER > stdout 2>&1 &
    disown

    server_status=DOWN
    for i in \`seq 20\`; do
        echo "Waiting for /healthz endpoint to report the server is up..."
        if curl http://localhost:$PORT/healthz | grep UP; then
            server_status=UP
            break
        fi
        sleep 0.5
    done

    if [ "\$server_status" = "UP" ]; then
        echo "Deployment complete at \$(date)"
    else
        echo "Deployment failed at \$(date)"
        false
    fi
EOF

echo "Deployed successfully to ${REMOTE_HOST}"


