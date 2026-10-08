package app

import (
	"strings"
	"sync"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Credentials for the AI chat engine (Copilot CLI), managed from Settings and
// stored in data/copilot_chat.json, apart from the data-sync PATs.

var chatAuthMu sync.Mutex

func chatAuthFile() string { return dataPath("copilot_chat.json") }

// MaskToken shows only the first and last 4 characters.
func MaskToken(token string) string {
	if len(token) > 8 {
		return token[:4] + "***" + token[len(token)-4:]
	}
	return "***"
}

// ChatAuthGet returns (token, host); an empty host means detect automatically.
func ChatAuthGet() (string, string) {
	raw := jx.Map(jx.ReadJSONOr(chatAuthFile(), jx.M{}))
	return jx.Str(raw["token"]), jx.Str(raw["host"])
}

// ChatAuthSave updates the stored values. nil keeps a field.
func ChatAuthSave(token, host *string, clearToken bool) (string, string, error) {
	chatAuthMu.Lock()
	defer chatAuthMu.Unlock()
	curToken, curHost := ChatAuthGet()
	if clearToken {
		curToken = ""
	} else if token != nil && strings.TrimSpace(*token) != "" {
		curToken = strings.TrimSpace(*token)
	}
	if host != nil {
		if strings.TrimSpace(*host) == "" {
			curHost = ""
		} else {
			h, err := githost.Normalize(*host)
			if err != nil {
				return "", "", err
			}
			curHost = h
		}
	}
	if err := jx.WriteJSON(chatAuthFile(), jx.M{"token": curToken, "host": curHost}); err != nil {
		return "", "", err
	}
	return curToken, curHost, nil
}
