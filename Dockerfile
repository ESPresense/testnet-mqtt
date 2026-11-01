FROM eclipse-mosquitto:2
RUN apk add --no-cache python3 py3-pip && pip install --no-cache-dir --break-system-packages paho-mqtt==2.1.0 && apk del py3-pip
COPY mosquitto.conf /etc/testnet-mqtt/mosquitto.conf
COPY relay.py /app/relay.py
RUN mkdir -p /data && chown mosquitto:mosquitto /data
USER mosquitto
VOLUME /data
EXPOSE 1883
HEALTHCHECK --interval=5s --timeout=5s --retries=5 \
  CMD mosquitto_sub -t '$SYS/broker/uptime' -C 1 -W 3 >/dev/null
ENTRYPOINT ["python3", "/app/relay.py"]
