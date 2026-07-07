package config

import (
	"os"
	"strconv"
	"time"
)

// Config holds all runtime configuration for the Harbor gateway.
// Everything is sourced from the environment so the binary is 12-factor
// friendly and identical across docker-compose and Kubernetes.
type Config struct {
	Port           string
	Provider       string // "mock" | "openai"
	OpenAIBaseURL  string // e.g. https://api.openai.com/v1, http://localhost:11434/v1 (Ollama)
	OpenAIAPIKey   string
	PrimaryModel   string
	RequestTimeout time.Duration
}

// FromEnv builds a Config from environment variables with safe defaults so
// the gateway boots with zero configuration in mock mode.
func FromEnv() Config {
	return Config{
		Port:           getenv("GATEWAY_PORT", "8080"),
		Provider:       getenv("PROVIDER", "mock"),
		OpenAIBaseURL:  getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
		OpenAIAPIKey:   getenv("OPENAI_API_KEY", ""),
		PrimaryModel:   getenv("PRIMARY_MODEL", "gpt-4o-mini"),
		RequestTimeout: time.Duration(getenvInt("REQUEST_TIMEOUT_SECONDS", 60)) * time.Second,
	}
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getenvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}
