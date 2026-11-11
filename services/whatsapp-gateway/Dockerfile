FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /gateway .

# Static binary on a minimal, non-root base image.
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /gateway /gateway
ENV PORT=8090
EXPOSE 8090
USER nonroot:nonroot
ENTRYPOINT ["/gateway"]
