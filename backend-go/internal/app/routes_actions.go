package app

import (
	"encoding/json"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// Actions router (Python routers/actions.py): execute or manage AI-recommended operations.

func init() { registerRoutes(registerActionRoutes) }

func registerActionRoutes(r *Router) {
	r.Handle("GET /api/actions/pending", func(c *Ctx) any {
		recs := OpsPendingRecommendations()
		return jx.M{"recommendations": recs, "count": len(recs)}
	})
	r.Handle("POST /api/actions/execute", func(c *Ctx) any {
		id, resp := actionsBindID(c)
		if resp != nil {
			return resp
		}
		return OpsExecuteRecommendation(c.R.Context(), id)
	})
	r.Handle("POST /api/actions/approve", func(c *Ctx) any {
		id, resp := actionsBindID(c)
		if resp != nil {
			return resp
		}
		return OpsApproveRecommendation(id)
	})
	r.Handle("POST /api/actions/reject", func(c *Ctx) any {
		id, resp := actionsBindID(c)
		if resp != nil {
			return resp
		}
		return OpsRejectRecommendation(id)
	})
}

// actionsBindID decodes ExecuteRequest{recommendation_id: str}.
func actionsBindID(c *Ctx) (string, *Resp) {
	var raw map[string]json.RawMessage
	if r := c.Bind(&raw); r != nil {
		return "", r
	}
	id, present, ok := dataStrField(raw, "recommendation_id")
	if !ok {
		return "", dataTypeError("recommendation_id", "string_type")
	}
	if !present {
		return "", dataMissing(c, "recommendation_id")
	}
	return id, nil
}
