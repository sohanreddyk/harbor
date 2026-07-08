# ---- build stage ----
FROM golang:1.24-alpine AS build
WORKDIR /src
# Week 2 introduces the go-redis dependency. We run `go mod tidy` during the
# build so the repo doesn't need a committed go.sum to bootstrap; run
# `cd gateway && go mod tidy` locally and commit go.mod/go.sum for reproducible
# builds.
COPY . .
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /out/gateway ./cmd/gateway

# ---- runtime stage ----
FROM alpine:3.20
RUN adduser -D -u 10001 harbor
USER harbor
COPY --from=build /out/gateway /usr/local/bin/gateway
EXPOSE 8080
ENTRYPOINT ["gateway"]
