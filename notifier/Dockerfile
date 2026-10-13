# The notifier: a Go binary on a distroless base. It links librdkafka (bundled
# by confluent-kafka-go) through cgo, so the base needs glibc: distroless/base.
# Build context: notifier/.
FROM golang:1.27 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=1 go build -trimpath -ldflags="-s -w" -o /out/notifier ./cmd/notifier

FROM gcr.io/distroless/base-debian12:nonroot
COPY --from=build /out/notifier /notifier
ENTRYPOINT ["/notifier"]
