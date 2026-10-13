# The simulator: a static Go binary on a distroless base.
# Build context: simulator/. Match data is mounted at run time, not baked in.
FROM golang:1.27 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/simulator ./cmd/simulator

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/simulator /simulator
EXPOSE 8080
ENTRYPOINT ["/simulator", "-addr", ":8080", "-data", "/data/statsbomb"]
