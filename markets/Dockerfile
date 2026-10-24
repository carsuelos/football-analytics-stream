# The markets service: a pure-Go binary (no cgo) on the static distroless base.
# Build context: markets/. It only reads the venues' public APIs: no data, no keys.
FROM golang:1.27 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/markets ./cmd/markets

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/markets /markets
EXPOSE 8090
ENTRYPOINT ["/markets", "-addr", ":8090"]
