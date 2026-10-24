# notifier

Delivers the engine's alerts from the Kafka `alerts` topic to webhooks: each alert is POSTed as JSON (the `alert` schema) with an `Idempotency-Key: <alert id>` header.

```sh
KAFKA_BOOTSTRAP_SERVERS=localhost:19092 go run ./cmd/notifier -webhook http://localhost:9000
```

| Flag | Default | |
| --- | --- | --- |
| `-webhook URL` | (required, repeatable) | where to POST each alert |
| `-topic` | `alerts` | the topic to consume |
| `-max-age` | `5m` | give up on alerts older than this (by their Kafka timestamp); `0` retries forever |
| `-timeout` | `5s` | per request |
| `-v` | | debug logs |

Kafka settings come from `KAFKA_*` environment variables, mapped to librdkafka properties as in the simulator and engine (`KAFKA_SASL_USERNAME` → `sasl.username`).

- **At least once.** It consumes as the `notifier` group and stores an alert's offset only once it is done with it (delivered everywhere, given up on, or unreadable); stored offsets are committed in the background and on shutdown.
- **Repeats are dropped** by alert id (the last 10,000 ids), since the engine publishes a stretch's alerts again when a viewer rewatches it. Across a restart, the receiver can use the `Idempotency-Key`.
- **Retries.** Network errors, 5xx and 429 are retried with exponential backoff (0.5 s up to 30 s), only for the webhooks that haven't taken the alert yet; any other 4xx is logged and not retried.

| Path | What |
| --- | --- |
| `cmd/notifier` | Flags, wiring and shutdown |
| `internal/notify` | `Notifier`: the delivery loop over a `Source` (dedupe, staleness, retries) |
| `cmd/notifier` | Flags, or `NOTIFIER_WEBHOOKS` (comma-separated, for a secret store); logs only the webhooks' hosts, as their paths often hold a token |
| `internal/kafka` | The consumer (`Source` on confluent-kafka-go, passing on the trace context in each message's headers) and `ConfigFromEnv` |
| `internal/telemetry` | Text or JSON (`LOG_FORMAT=json`) logs with the span's ids, and OTLP tracing when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (shared with the simulator) |
| `internal/schema` | The `Alert` type, generated from `schema/jsonschema/` by `make gen`; do not edit it |
