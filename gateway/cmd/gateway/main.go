package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/sohanreddy/harbor/gateway/internal/config"
	"github.com/sohanreddy/harbor/gateway/internal/provider"
	"github.com/sohanreddy/harbor/gateway/internal/server"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	cfg := config.FromEnv()

	prov := buildProvider(cfg)
	log.Info("starting harbor gateway", "port", cfg.Port, "provider", prov.Name(), "model", cfg.PrimaryModel)

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           server.New(cfg, prov, log).Routes(),
		ReadHeaderTimeout: 10 * time.Second,
		// No write timeout: streaming responses are long-lived.
	}

	// Graceful shutdown on SIGINT/SIGTERM.
	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	log.Info("shutting down")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}

func buildProvider(cfg config.Config) provider.Provider {
	switch cfg.Provider {
	case "openai":
		client := &http.Client{Timeout: cfg.RequestTimeout}
		return provider.NewOpenAI(cfg.OpenAIBaseURL, cfg.OpenAIAPIKey, client)
	default:
		return provider.NewMock()
	}
}
