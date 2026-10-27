FROM ghcr.io/home-assistant/base-python:3.13-alpine3.22

ARG BUILD_VERSION
ARG BUILD_ARCH

ENV GAARD_HA=1 \
    GAARD_DATA_DIR=/data \
    GAARD_PORT=8099 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

CMD ["python3", "run.py", "--port", "8099"]

LABEL \
    io.hass.name="Gårdopgaver" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="aarch64|amd64"
