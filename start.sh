#!/bin/bash

# Start web server first (for health checks)
python app.py &

# Wait for web server to initialize
sleep 2

# Start Telegram bot with retry logic
while true; do
    python main.py
    status=$?
    if [ $status -eq 0 ]; then
        echo "Bot exited normally"
        break
    else
        echo "Bot crashed with status $status. Restarting..."
        sleep 5
    fi
done

wait
