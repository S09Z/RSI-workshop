# Sourced by orch / orch-headless. Points Claude Code's built-in OpenTelemetry export at the
# local receiver (orch-dashboard --otlp). Set AGENT_DASHBOARD_OTEL=0 to turn it off.
# Values you already exported win (":=" only fills unset variables).
# If nothing listens on 127.0.0.1:4318 the export fails silently; the session is unaffected.
if [ "${AGENT_DASHBOARD_OTEL:-1}" = "1" ]; then
  export CLAUDE_CODE_ENABLE_TELEMETRY="${CLAUDE_CODE_ENABLE_TELEMETRY:-1}"
  : "${OTEL_METRICS_EXPORTER:=otlp}";  export OTEL_METRICS_EXPORTER
  : "${OTEL_LOGS_EXPORTER:=otlp}";     export OTEL_LOGS_EXPORTER
  : "${OTEL_EXPORTER_OTLP_PROTOCOL:=http/json}"; export OTEL_EXPORTER_OTLP_PROTOCOL
  : "${OTEL_EXPORTER_OTLP_ENDPOINT:=http://127.0.0.1:${AGENT_DASHBOARD_OTLP_PORT:-4318}}"; export OTEL_EXPORTER_OTLP_ENDPOINT
  : "${OTEL_METRIC_EXPORT_INTERVAL:=10000}"; export OTEL_METRIC_EXPORT_INTERVAL
  # Traces are BETA in Claude Code (span names may change). Turn off with AGENT_DASHBOARD_TRACES=0.
  if [ "${AGENT_DASHBOARD_TRACES:-1}" = "1" ]; then
    export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA="${CLAUDE_CODE_ENHANCED_TELEMETRY_BETA:-1}"
    : "${OTEL_TRACES_EXPORTER:=otlp}"; export OTEL_TRACES_EXPORTER
  fi
  # Content stays off: OTEL_LOG_USER_PROMPTS / OTEL_LOG_TOOL_DETAILS / OTEL_LOG_TOOL_CONTENT are not set here.
fi
