FROM ghcr.io/home-assistant/base-python:3.13-alpine3.22

ARG BUILD_VERSION
ARG BUILD_ARCH

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]

LABEL \
    io.hass.name="Gårdopgaver" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="aarch64|amd64"
