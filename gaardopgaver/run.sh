#!/usr/bin/with-contenv sh
# s6-overlay (Home Assistants basisimage) nulstiller miljøet for CMD; with-contenv giver
# containerens variabler tilbage, bl.a. SUPERVISOR_TOKEN til sensorerne og TZ.
export GAARD_HA=1 GAARD_DATA_DIR=/data GAARD_PORT=8099 PYTHONUNBUFFERED=1
cd /app
exec python3 run.py --port 8099
