FROM jasonish/suricata:latest

USER root

# Pre-create the rules directory with an empty rules file so that
# `suricata -T` (config validation) works before suricata-update runs.
RUN mkdir -p /var/lib/suricata/rules && \
    touch /var/lib/suricata/rules/suricata.rules

COPY suricata.yaml /etc/suricata/suricata.yaml
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/var/log/suricata", "/var/lib/suricata/rules"]

ENTRYPOINT ["/entrypoint.sh"]
