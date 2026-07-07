package provider

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

// OpenAI is an OpenAI-compatible upstream provider. Because the wire format is
// the de-facto standard, the same code talks to OpenAI, Azure OpenAI, Ollama
// (http://localhost:11434/v1), vLLM, or any compatible server just by changing
// the base URL.
type OpenAI struct {
	BaseURL string
	APIKey  string
	client  *http.Client
}

func NewOpenAI(baseURL, apiKey string, client *http.Client) *OpenAI {
	return &OpenAI{
		BaseURL: strings.TrimRight(baseURL, "/"),
		APIKey:  apiKey,
		client:  client,
	}
}

func (o *OpenAI) Name() string { return "openai" }

type upstreamChunk struct {
	Choices []struct {
		Delta struct {
			Content string `json:"content"`
		} `json:"delta"`
		FinishReason *string `json:"finish_reason"`
	} `json:"choices"`
}

func (o *OpenAI) Stream(ctx context.Context, req *ChatRequest, onDelta DeltaFunc) (string, error) {
	// Force streaming upstream regardless of what the caller asked for; the
	// gateway handler is responsible for re-framing to the client.
	body := *req
	body.Stream = true
	payload, err := json.Marshal(body)
	if err != nil {
		return "", fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost,
		o.BaseURL+"/chat/completions", bytes.NewReader(payload))
	if err != nil {
		return "", fmt.Errorf("build request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")
	if o.APIKey != "" {
		httpReq.Header.Set("Authorization", "Bearer "+o.APIKey)
	}

	resp, err := o.client.Do(httpReq)
	if err != nil {
		return "", fmt.Errorf("upstream request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		snippet := make([]byte, 512)
		n, _ := resp.Body.Read(snippet)
		return "", fmt.Errorf("upstream status %d: %s", resp.StatusCode, string(snippet[:n]))
	}

	finish := "stop"
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			break
		}
		var chunk upstreamChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue // tolerate keep-alive/comment lines
		}
		for _, c := range chunk.Choices {
			if c.Delta.Content != "" {
				if err := onDelta(c.Delta.Content); err != nil {
					return finish, err
				}
			}
			if c.FinishReason != nil && *c.FinishReason != "" {
				finish = *c.FinishReason
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return finish, fmt.Errorf("read upstream stream: %w", err)
	}
	return finish, nil
}
