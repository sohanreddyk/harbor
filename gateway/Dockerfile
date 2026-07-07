# ---- build stage ----
FROM golang:1.24-alpine AS build
WORKDIR /src
# Copy module files first for layer caching. Week 1 has no external deps, so
# this stays fast and works fully offline.
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/gateway ./cmd/gateway

# ---- runtime stage ----
FROM alpine:3.20
RUN adduser -D -u 10001 harbor
USER harbor
COPY --from=build /out/gateway /usr/local/bin/gateway
EXPOSE 8080
ENTRYPOINT ["gateway"]
