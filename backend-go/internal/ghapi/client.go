// Package ghapi is the GitHub REST API client, one instance per PAT.
//
// It mirrors the Python backend's GitHubAPI: most getters swallow HTTP errors
// and return nil so one inaccessible org cannot abort a whole sync, recording
// the reason via ConsumeFailure for the caller to surface.
package ghapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/satomic/octofinance/backend-go/internal/githost"
	"github.com/satomic/octofinance/backend-go/internal/jx"
)

// DefaultAPIVersion is the REST API version sent on every request.
const DefaultAPIVersion = "2022-11-28"

// BillingAPIVersion is required by the billing (budgets / cost centers / AI credit) endpoints.
const BillingAPIVersion = "2026-03-10"

// Logger receives request logs (the api_requests.log handler is attached by the app).
var Logger = slog.Default()

// Response is a buffered HTTP response.
type Response struct {
	Status int
	Reason string
	Header http.Header
	Body   []byte
	URL    string
	Method string
}

// OK reports a 2xx status.
func (r *Response) OK() bool { return r.Status >= 200 && r.Status < 300 }

// JSON decodes the body (nil when empty or invalid).
func (r *Response) JSON() any {
	if len(bytes.TrimSpace(r.Body)) == 0 {
		return nil
	}
	var v any
	if err := json.Unmarshal(r.Body, &v); err != nil {
		return nil
	}
	return v
}

// Text returns the body as a string.
func (r *Response) Text() string { return string(r.Body) }

// HTTPError is a non-2xx response, the equivalent of httpx.HTTPStatusError.
type HTTPError struct {
	Resp *Response
}

func (e *HTTPError) Error() string {
	kind := "Server error"
	if e.Resp.Status < 500 {
		kind = "Client error"
	}
	return fmt.Sprintf("%s '%d %s' for url '%s'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/%d",
		kind, e.Resp.Status, e.Resp.Reason, e.Resp.URL, e.Resp.Status)
}

// Status returns the HTTP status code.
func (e *HTTPError) Status() int { return e.Resp.Status }

// TransportError is a failure to reach GitHub at all (httpx.TransportError).
type TransportError struct {
	Err error
}

func (e *TransportError) Error() string { return e.Err.Error() }
func (e *TransportError) Unwrap() error { return e.Err }

// RaiseForStatus returns an *HTTPError for non-2xx responses.
func RaiseForStatus(r *Response) error {
	if r.OK() {
		return nil
	}
	return &HTTPError{Resp: r}
}

// ErrorDetail extracts a human-readable reason from a GitHub error response.
func ErrorDetail(r *Response) string {
	body := r.JSON()
	if body == nil {
		return truncate(strings.TrimSpace(r.Text()), 300)
	}
	if m := jx.Map(body); m != nil {
		msg := jx.Str(m["message"])
		if errs, ok := m["errors"]; ok && jx.Truthy(errs) {
			msg = strings.TrimSpace(msg + " " + jx.Dumps(errs))
		}
		if msg == "" {
			return truncate(jx.Dumps(body), 300)
		}
		return truncate(msg, 300)
	}
	return truncate(jx.Dumps(body), 300)
}

func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

// Client is bound to one PAT.
type Client struct {
	token   string
	baseURL string
	http    *http.Client

	mu          sync.Mutex
	lastFailure jx.M
}

// New creates a client for the given token and API base URL.
func New(token, baseURL string) *Client {
	if baseURL == "" {
		baseURL = "https://api.github.com"
	}
	return &Client{
		token:   token,
		baseURL: strings.TrimRight(baseURL, "/"),
		http:    &http.Client{Timeout: 30 * time.Second},
	}
}

// BaseURL returns the API base URL.
func (c *Client) BaseURL() string { return c.baseURL }

// Host is the normalized GitHub host (github.com or <sub>.ghe.com).
func (c *Client) Host() string { return githost.FromAPIBase(c.baseURL) }

// WebBase is the web UI base URL for building profile links.
func (c *Client) WebBase() string { return githost.WebBase(c.Host()) }

// Close is a no-op kept for parity with the Python client.
func (c *Client) Close() {}

// TransientRetries is how many extra attempts a read request (GET/HEAD) gets
// after a transport failure (connection reset, EOF, timeout). HTTP error
// statuses are returned as-is and writes are never retried.
var TransientRetries = 2

// transientBackoff is the wait before each retry (index = retry number).
var transientBackoff = []time.Duration{500 * time.Millisecond, 1500 * time.Millisecond}

// Do performs an API request. Only transport failures return an error;
// HTTP error statuses come back as a Response. Read requests are retried on
// transient transport failures, so one dropped connection does not lose data.
func (c *Client) Do(ctx context.Context, method, path string, query url.Values, body any, headers map[string]string) (*Response, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	u := c.baseURL + path
	if len(query) > 0 {
		u += "?" + query.Encode()
	}
	var payload []byte
	if body != nil {
		b, err := jx.Marshal(body)
		if err != nil {
			return nil, err
		}
		payload = b
	}
	retries := 0
	if method == http.MethodGet || method == http.MethodHead {
		retries = TransientRetries
	}
	for attempt := 0; ; attempt++ {
		resp, err := c.doOnce(ctx, method, u, payload, headers)
		if err == nil || attempt >= retries || ctx.Err() != nil {
			return resp, err
		}
		wait := transientBackoff[len(transientBackoff)-1]
		if attempt < len(transientBackoff) {
			wait = transientBackoff[attempt]
		}
		Logger.Warn(fmt.Sprintf("%s %s failed (%v); retrying in %s", method, u, err, wait))
		select {
		case <-ctx.Done():
			return nil, err
		case <-time.After(wait):
		}
	}
}

func (c *Client) doOnce(ctx context.Context, method, u string, payload []byte, headers map[string]string) (*Response, error) {
	var reader io.Reader
	if payload != nil {
		reader = bytes.NewReader(payload)
	}
	req, err := http.NewRequestWithContext(ctx, method, u, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-GitHub-Api-Version", DefaultAPIVersion)
	req.Header.Set("User-Agent", "OctoFinance-Go")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, &TransportError{Err: err}
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, &TransportError{Err: err}
	}
	return &Response{
		Status: resp.StatusCode,
		Reason: http.StatusText(resp.StatusCode),
		Header: resp.Header,
		Body:   data,
		URL:    u,
		Method: method,
	}, nil
}

// Get is Do with GET.
func (c *Client) Get(ctx context.Context, path string, query url.Values, headers map[string]string) (*Response, error) {
	return c.Do(ctx, http.MethodGet, path, query, nil, headers)
}

func billing() map[string]string { return map[string]string{"X-GitHub-Api-Version": BillingAPIVersion} }

func pageQuery(page int, extra ...string) url.Values {
	q := url.Values{"per_page": {"100"}, "page": {fmt.Sprint(page)}}
	for i := 0; i+1 < len(extra); i += 2 {
		q.Set(extra[i], extra[i+1])
	}
	return q
}

// ---------------------------------------------------------------------------
// Failure reporting
// ---------------------------------------------------------------------------

func (c *Client) recordFailure(operation string, status int, detail, u string) {
	var st any
	if status != 0 {
		st = status
	}
	c.mu.Lock()
	c.lastFailure = jx.M{"operation": operation, "status": st, "detail": strings.TrimSpace(detail), "url": u}
	c.mu.Unlock()
	msg := fmt.Sprintf("[%s] returned no data", operation)
	if status != 0 {
		msg += fmt.Sprintf(" (HTTP %d)", status)
	}
	if u != "" {
		msg += " " + u
	}
	if d := strings.TrimSpace(detail); d != "" {
		msg += ": " + d
	}
	Logger.Warn(msg)
}

func (c *Client) recordResponseFailure(operation string, r *Response) {
	c.recordFailure(operation, r.Status, ErrorDetail(r), r.URL)
}

func (c *Client) recordErr(operation string, err error) {
	if he, ok := err.(*HTTPError); ok {
		c.recordResponseFailure(operation, he.Resp)
		return
	}
	c.recordFailure(operation, 0, err.Error(), "")
}

// ConsumeFailure pops the last recorded failure (nil when none).
func (c *Client) ConsumeFailure() jx.M {
	c.mu.Lock()
	defer c.mu.Unlock()
	f := c.lastFailure
	c.lastFailure = nil
	return f
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// getJSON GETs path and raises for status.
func (c *Client) getJSON(ctx context.Context, path string, query url.Values, headers map[string]string) (any, error) {
	r, err := c.Get(ctx, path, query, headers)
	if err != nil {
		return nil, err
	}
	if err := RaiseForStatus(r); err != nil {
		return nil, err
	}
	return r.JSON(), nil
}

// paginate collects a paged array endpoint. When skip403404 is set, a 403/404
// records a failure and returns what was collected so far as empty.
func (c *Client) paginateSoft(ctx context.Context, op, path string) []jx.M {
	var out []jx.M
	page := 1
	for {
		r, err := c.Get(ctx, path, pageQuery(page), nil)
		if err != nil {
			c.recordErr(op, err)
			return []jx.M{}
		}
		if r.Status == 404 || r.Status == 403 {
			c.recordResponseFailure(op, r)
			return []jx.M{}
		}
		if err := RaiseForStatus(r); err != nil {
			c.recordErr(op, err)
			return []jx.M{}
		}
		batch := jx.Maps(r.JSON())
		if len(batch) == 0 {
			break
		}
		out = append(out, batch...)
		if len(batch) < 100 {
			break
		}
		page++
	}
	if out == nil {
		out = []jx.M{}
	}
	return out
}

// ---------------------------------------------------------------------------
// Auto-Discovery
// ---------------------------------------------------------------------------

// DiscoverUser returns the authenticated user (raises on error).
func (c *Client) DiscoverUser(ctx context.Context) (jx.M, error) {
	v, err := c.getJSON(ctx, "/user", nil, nil)
	if err != nil {
		return nil, err
	}
	m := jx.Map(v)
	if m == nil {
		m = jx.M{}
	}
	return m, nil
}

// DiscoverOrgs lists the user's organizations (raises on error).
func (c *Client) DiscoverOrgs(ctx context.Context) ([]jx.M, error) {
	var out []jx.M
	page := 1
	for {
		v, err := c.getJSON(ctx, "/user/orgs", pageQuery(page), nil)
		if err != nil {
			return nil, err
		}
		batch := jx.Maps(v)
		if len(batch) == 0 {
			break
		}
		out = append(out, batch...)
		page++
	}
	return out, nil
}

// GetOrgMemberships returns the authenticated user's role in each organization
// as {org_lower: "admin"|"member"} (GET /user/memberships/orgs). It returns nil
// when the roles cannot be read, e.g. a fine-grained token without the permission.
func (c *Client) GetOrgMemberships(ctx context.Context) map[string]string {
	roles := map[string]string{}
	for page := 1; ; page++ {
		r, err := c.Get(ctx, "/user/memberships/orgs", pageQuery(page, "state", "active"), nil)
		if err != nil {
			c.recordFailure("org_memberships", 0, err.Error(), "")
			return nil
		}
		if r.Status != 200 {
			c.recordResponseFailure("org_memberships", r)
			return nil
		}
		batch := jx.Maps(r.JSON())
		for _, m := range batch {
			login := jx.Str(jx.GetMap(m, "organization")["login"])
			if role := jx.Str(m["role"]); login != "" && role != "" {
				roles[strings.ToLower(login)] = role
			}
		}
		if len(batch) < 100 {
			return roles
		}
	}
}

// GetOrgDetail returns /orgs/{org} (raises on error).
func (c *Client) GetOrgDetail(ctx context.Context, org string) (jx.M, error) {
	v, err := c.getJSON(ctx, "/orgs/"+org, nil, nil)
	if err != nil {
		return nil, err
	}
	return jx.Map(v), nil
}

// DiscoverEnterprises lists enterprise memberships as {slug, name, id, role}.
func (c *Client) DiscoverEnterprises(ctx context.Context) []jx.M {
	var memberships []jx.M
	page := 1
	for {
		r, err := c.Get(ctx, "/user/enterprise-memberships", pageQuery(page), nil)
		if err != nil {
			c.recordFailure("enterprise_memberships", 0, err.Error(), "")
			return []jx.M{}
		}
		if r.Status == 404 || r.Status == 403 {
			c.recordResponseFailure("enterprise_memberships", r)
			return []jx.M{}
		}
		if err := RaiseForStatus(r); err != nil {
			c.recordFailure("enterprise_memberships", 0, err.Error(), "")
			return []jx.M{}
		}
		batch := jx.Maps(r.JSON())
		if len(batch) == 0 {
			break
		}
		memberships = append(memberships, batch...)
		if len(batch) < 100 {
			break
		}
		page++
	}
	out := []jx.M{}
	for _, m := range memberships {
		ent := jx.GetMap(m, "enterprise")
		slug := jx.GetStr(ent, "slug")
		if slug == "" {
			continue
		}
		out = append(out, jx.M{
			"slug": slug,
			"name": jx.GetStr(ent, "name"),
			"id":   ent["id"],
			"role": jx.GetStr(m, "role"),
		})
	}
	return out
}

// GetOrgMembers lists members of an organization.
func (c *Client) GetOrgMembers(ctx context.Context, org string) []jx.M {
	return c.paginateSoft(ctx, "org_members "+org, "/orgs/"+org+"/members")
}

// GetTeamMembers lists members of an org team.
func (c *Client) GetTeamMembers(ctx context.Context, org, teamSlug string) []jx.M {
	return c.paginateSoft(ctx, "team_members "+org+"/"+teamSlug, "/orgs/"+org+"/teams/"+teamSlug+"/members")
}

// GetEnterpriseCostCenters lists active + archived cost centers.
func (c *Client) GetEnterpriseCostCenters(ctx context.Context, enterprise string) ([]jx.M, error) {
	results := []jx.M{}
	seen := map[string]bool{}
	for _, state := range []string{"active", "archived"} {
		page := 1
		for {
			r, err := c.Get(ctx, "/enterprises/"+enterprise+"/settings/billing/cost-centers",
				pageQuery(page, "state", state), billing())
			if err != nil {
				return nil, err
			}
			if r.Status == 404 || r.Status == 403 || r.Status == 400 {
				if r.Status != 404 {
					c.recordResponseFailure("enterprise_cost_centers "+enterprise, r)
				}
				break
			}
			if err := RaiseForStatus(r); err != nil {
				return nil, err
			}
			data := r.JSON()
			var batch []jx.M
			if l := jx.List(data); l != nil {
				batch = jx.Maps(l)
			} else {
				m := jx.Map(data)
				if v := jx.Get(m, "costCenters"); jx.Truthy(v) {
					batch = jx.Maps(v)
				} else {
					batch = jx.Maps(jx.Get(m, "cost_centers"))
				}
			}
			if len(batch) == 0 {
				break
			}
			for _, item := range batch {
				id := jx.Str(item["id"])
				if !seen[id] {
					seen[id] = true
					results = append(results, item)
				}
			}
			if len(batch) < 100 {
				break
			}
			page++
		}
	}
	return results, nil
}

// GetEnterpriseOrgs lists organizations owned by an enterprise.
func (c *Client) GetEnterpriseOrgs(ctx context.Context, enterprise string) []jx.M {
	return c.paginateSoft(ctx, "enterprise_orgs "+enterprise, "/enterprises/"+enterprise+"/organizations")
}

// GetEnterpriseTeams lists enterprise teams.
func (c *Client) GetEnterpriseTeams(ctx context.Context, enterprise string) []jx.M {
	return c.paginateSoft(ctx, "enterprise_teams "+enterprise, "/enterprises/"+enterprise+"/teams")
}

// GetEnterpriseTeamMembers lists members of an enterprise team.
func (c *Client) GetEnterpriseTeamMembers(ctx context.Context, enterprise, teamSlug string) []jx.M {
	return c.paginateSoft(ctx, "enterprise_team_members "+teamSlug, "/enterprises/"+enterprise+"/teams/"+teamSlug+"/memberships")
}

// GetEnterpriseTeamOrganizations lists orgs an enterprise team is assigned to.
func (c *Client) GetEnterpriseTeamOrganizations(ctx context.Context, enterprise, teamSlug string) []jx.M {
	return c.paginateSoft(ctx, "enterprise_team_orgs "+teamSlug, "/enterprises/"+enterprise+"/teams/"+teamSlug+"/organizations")
}

func jsonOrSuccess(r *Response) jx.M {
	if len(r.Body) > 0 {
		if m := jx.Map(r.JSON()); m != nil {
			return m
		}
		if v := r.JSON(); v != nil {
			return jx.M{"result": v}
		}
	}
	return jx.M{"success": true}
}

// GetCostCenter returns one cost center (raises on error).
func (c *Client) GetCostCenter(ctx context.Context, enterprise, id string) (jx.M, error) {
	v, err := c.getJSON(ctx, "/enterprises/"+enterprise+"/settings/billing/cost-centers/"+id, nil, billing())
	if err != nil {
		return nil, err
	}
	return jx.Map(v), nil
}

// CreateCostCenter creates a cost center (raises on error).
func (c *Client) CreateCostCenter(ctx context.Context, enterprise string, body jx.M) (jx.M, error) {
	r, err := c.Do(ctx, http.MethodPost, "/enterprises/"+enterprise+"/settings/billing/cost-centers", nil, body, billing())
	if err != nil {
		return nil, err
	}
	if err := RaiseForStatus(r); err != nil {
		return nil, err
	}
	return jsonOrSuccess(r), nil
}

// DeleteCostCenter deletes (archives) a cost center (raises on error).
func (c *Client) DeleteCostCenter(ctx context.Context, enterprise, id string) (jx.M, error) {
	r, err := c.Do(ctx, http.MethodDelete, "/enterprises/"+enterprise+"/settings/billing/cost-centers/"+id, nil, nil, billing())
	if err != nil {
		return nil, err
	}
	if err := RaiseForStatus(r); err != nil {
		return nil, err
	}
	return jsonOrSuccess(r), nil
}

// UpdateCostCenter renames and/or toggles the AI credit included usage cap.
func (c *Client) UpdateCostCenter(ctx context.Context, enterprise, id string, name *string, aiCreditPoolEnabled *bool) (jx.M, error) {
	body := jx.M{}
	if name != nil {
		body["name"] = *name
	}
	if aiCreditPoolEnabled != nil {
		body["ai_credit_pool_enabled"] = *aiCreditPoolEnabled
	}
	r, err := c.Do(ctx, http.MethodPatch, "/enterprises/"+enterprise+"/settings/billing/cost-centers/"+id, nil, body, billing())
	if err != nil {
		return nil, err
	}
	if err := RaiseForStatus(r); err != nil {
		return nil, err
	}
	return jsonOrSuccess(r), nil
}

func resourceBody(users, orgs, repos []string) jx.M {
	body := jx.M{}
	if len(users) > 0 {
		body["users"] = users
	}
	if len(orgs) > 0 {
		body["organizations"] = orgs
	}
	if len(repos) > 0 {
		body["repositories"] = repos
	}
	return body
}

// AddCostCenterResources adds users / orgs / repos to a cost center.
func (c *Client) AddCostCenterResources(ctx context.Context, enterprise, id string, users, orgs, repos []string) (jx.M, error) {
	r, err := c.Do(ctx, http.MethodPost, "/enterprises/"+enterprise+"/settings/billing/cost-centers/"+id+"/resource",
		nil, resourceBody(users, orgs, repos), billing())
	if err != nil {
		return nil, err
	}
	if err := RaiseForStatus(r); err != nil {
		return nil, err
	}
	return jsonOrSuccess(r), nil
}

// RemoveCostCenterResources removes users / orgs / repos from a cost center.
func (c *Client) RemoveCostCenterResources(ctx context.Context, enterprise, id string, users, orgs, repos []string) (jx.M, error) {
	r, err := c.Do(ctx, http.MethodDelete, "/enterprises/"+enterprise+"/settings/billing/cost-centers/"+id+"/resource",
		nil, resourceBody(users, orgs, repos), billing())
	if err != nil {
		return nil, err
	}
	if err := RaiseForStatus(r); err != nil {
		return nil, err
	}
	return jsonOrSuccess(r), nil
}

// ---------------------------------------------------------------------------
// Copilot billing / seats / metrics
// ---------------------------------------------------------------------------

// CopilotPricing is the USD/month/user price per plan.
var CopilotPricing = map[string]float64{
	"business":   19.0,
	"enterprise": 39.0,
}

// GetCopilotBilling returns org Copilot billing info with detected plan pricing, or nil.
func (c *Client) GetCopilotBilling(ctx context.Context, org string) (jx.M, error) {
	r, err := c.Get(ctx, "/orgs/"+org+"/copilot/billing", nil, nil)
	if err != nil {
		return nil, err
	}
	if !r.OK() {
		c.recordResponseFailure("copilot_billing", r)
		return nil, nil
	}
	billing := jx.Map(r.JSON())
	if billing == nil {
		return nil, nil
	}
	planType := jx.GetStr(billing, "plan_type", "business")
	if _, ok := billing["plan_type"]; !ok {
		planType = "business"
	}
	if p, ok := CopilotPricing[planType]; ok {
		billing["_detected_price_per_seat"] = p
	} else {
		billing["_detected_price_per_seat"] = CopilotPricing["business"]
	}
	billing["_detected_plan_type"] = billing["plan_type"]
	if _, ok := billing["plan_type"]; !ok {
		billing["_detected_plan_type"] = "business"
	}
	return billing, nil
}

func (c *Client) seats(ctx context.Context, op, path string, soft403 bool) (jx.M, error) {
	all := jx.L{}
	page := 1
	var total any = 0
	for {
		r, err := c.Get(ctx, path, pageQuery(page), nil)
		if err != nil {
			return nil, err
		}
		if r.Status == 404 || (soft403 && r.Status == 403) {
			c.recordResponseFailure(op, r)
			return nil, nil
		}
		if !r.OK() {
			c.recordResponseFailure(op, r)
			return nil, nil
		}
		data := jx.Map(r.JSON())
		total = jx.GetOr(data, "total_seats", 0)
		batch := jx.GetList(data, "seats")
		if len(batch) == 0 {
			break
		}
		all = append(all, batch...)
		page++
	}
	return jx.M{"total_seats": total, "seats": all}, nil
}

// GetCopilotSeats returns all org seat assignments, or nil.
func (c *Client) GetCopilotSeats(ctx context.Context, org string) (jx.M, error) {
	return c.seats(ctx, "copilot_seats", "/orgs/"+org+"/copilot/billing/seats", false)
}

// GetEnterpriseBillingSeats returns all enterprise seat assignments, or nil.
func (c *Client) GetEnterpriseBillingSeats(ctx context.Context, enterprise string) (jx.M, error) {
	return c.seats(ctx, "enterprise_billing_seats", "/enterprises/"+enterprise+"/copilot/billing/seats", true)
}

// GetCopilotMetrics returns the legacy metrics list, or nil.
func (c *Client) GetCopilotMetrics(ctx context.Context, org, since, until string) (jx.L, error) {
	q := url.Values{}
	if since != "" {
		q.Set("since", since)
	}
	if until != "" {
		q.Set("until", until)
	}
	r, err := c.Get(ctx, "/orgs/"+org+"/copilot/metrics", q, nil)
	if err != nil {
		return nil, err
	}
	if !r.OK() {
		c.recordResponseFailure("copilot_metrics", r)
		return nil, nil
	}
	return jx.List(r.JSON()), nil
}

func dateQuery(year, month, day int) url.Values {
	q := url.Values{}
	if year != 0 {
		q.Set("year", fmt.Sprint(year))
	}
	if month != 0 {
		q.Set("month", fmt.Sprint(month))
	}
	if day != 0 {
		q.Set("day", fmt.Sprint(day))
	}
	return q
}

func (c *Client) aiCredit(ctx context.Context, op, path string, year, month, day int) (jx.M, error) {
	r, err := c.Get(ctx, path, dateQuery(year, month, day), billing())
	if err != nil {
		return nil, err
	}
	if !r.OK() {
		c.recordResponseFailure(op, r)
		return nil, nil
	}
	return jx.Map(r.JSON()), nil
}

// GetAICreditUsage returns org AI credit usage (UBB), or nil. Zero year/month/day are omitted.
func (c *Client) GetAICreditUsage(ctx context.Context, org string, year, month, day int) (jx.M, error) {
	return c.aiCredit(ctx, "ai_credit_usage", "/organizations/"+org+"/settings/billing/ai_credit/usage", year, month, day)
}

// GetEnterpriseAICreditUsage returns enterprise AI credit usage (UBB), or nil.
func (c *Client) GetEnterpriseAICreditUsage(ctx context.Context, enterprise string, year, month, day int) (jx.M, error) {
	return c.aiCredit(ctx, "enterprise_ai_credit_usage", "/enterprises/"+enterprise+"/settings/billing/ai_credit/usage", year, month, day)
}

// ---------------------------------------------------------------------------
// Billing usage report CSV exports
// ---------------------------------------------------------------------------

// CreateBillingReport requests a CSV export; errors come back as {"error", "status_code"}.
func (c *Client) CreateBillingReport(ctx context.Context, enterprise, reportType, startDate, endDate string) jx.M {
	payload := jx.M{"report_type": reportType, "start_date": startDate}
	if endDate != "" {
		payload["end_date"] = endDate
	}
	r, err := c.Do(ctx, http.MethodPost, "/enterprises/"+enterprise+"/settings/billing/reports", nil, payload, nil)
	if err != nil {
		c.recordFailure("create_billing_report", 0, err.Error(), "")
		return jx.M{"error": err.Error(), "status_code": nil}
	}
	if !r.OK() {
		c.recordResponseFailure("create_billing_report", r)
		return jx.M{"error": ErrorDetail(r), "status_code": r.Status}
	}
	if m := jx.Map(r.JSON()); m != nil {
		return m
	}
	return jx.M{}
}

// GetBillingReport returns one export (with download_urls once completed), or nil.
func (c *Client) GetBillingReport(ctx context.Context, enterprise, reportID string) jx.M {
	r, err := c.Get(ctx, "/enterprises/"+enterprise+"/settings/billing/reports/"+reportID, nil, nil)
	if err != nil {
		c.recordFailure("get_billing_report", 0, err.Error(), "")
		return nil
	}
	if !r.OK() {
		c.recordResponseFailure("get_billing_report", r)
		return nil
	}
	return jx.Map(r.JSON())
}

// ListBillingReports lists the enterprise's exports.
func (c *Client) ListBillingReports(ctx context.Context, enterprise string) []jx.M {
	r, err := c.Get(ctx, "/enterprises/"+enterprise+"/settings/billing/reports", nil, nil)
	if err != nil {
		c.recordFailure("list_billing_reports", 0, err.Error(), "")
		return []jx.M{}
	}
	if !r.OK() {
		c.recordResponseFailure("list_billing_reports", r)
		return []jx.M{}
	}
	body := r.JSON()
	if l := jx.List(body); l != nil {
		return jx.Maps(l)
	}
	if m := jx.Map(body); m != nil {
		if v := m["usage_report_exports"]; jx.Truthy(v) {
			return jx.Maps(v)
		}
		return jx.Maps(m["reports"])
	}
	return []jx.M{}
}

var downloadClient = &http.Client{Timeout: 120 * time.Second}

// DownloadBillingReportCSV fetches each signed URL (no auth header) and returns the CSV texts.
func DownloadBillingReportCSV(ctx context.Context, urls []string) []string {
	parts := []string{}
	for _, u := range urls {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
		if err != nil {
			continue
		}
		resp, err := downloadClient.Do(req)
		if err != nil {
			Logger.Warn("Failed to download billing report part", "error", err)
			continue
		}
		b, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil || resp.StatusCode >= 300 {
			Logger.Warn("Failed to download billing report part", "status", resp.StatusCode)
			continue
		}
		if t := strings.TrimSpace(string(b)); t != "" {
			parts = append(parts, t)
		}
	}
	return parts
}

// ---------------------------------------------------------------------------
// Copilot usage metrics reports (download_links)
// ---------------------------------------------------------------------------

var reportDownloadClient = &http.Client{Timeout: 60 * time.Second}

func (c *Client) fetchReportLinks(ctx context.Context, path string, q url.Values) jx.M {
	r, err := c.Get(ctx, path, q, nil)
	if err != nil {
		c.recordFailure("usage_report "+path, 0, err.Error(), "")
		return nil
	}
	if !r.OK() {
		c.recordResponseFailure("usage_report "+path, r)
		return nil
	}
	return jx.Map(r.JSON())
}

func downloadAndMerge(ctx context.Context, links []string) jx.L {
	records := jx.L{}
	for _, u := range links {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
		if err != nil {
			continue
		}
		resp, err := reportDownloadClient.Do(req)
		if err != nil {
			continue
		}
		b, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil || resp.StatusCode >= 300 {
			continue
		}
		text := strings.TrimSpace(string(b))
		if text == "" {
			continue
		}
		if strings.HasPrefix(text, "[") {
			var arr []any
			if json.Unmarshal([]byte(text), &arr) == nil {
				records = append(records, arr...)
			}
			continue
		}
		for _, line := range strings.Split(text, "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var v any
			if json.Unmarshal([]byte(line), &v) != nil {
				continue
			}
			switch t := v.(type) {
			case map[string]any:
				records = append(records, t)
			case []any:
				records = append(records, t...)
			}
		}
	}
	return records
}

func (c *Client) fetchUsageReport(ctx context.Context, path string, q url.Values) jx.M {
	meta := c.fetchReportLinks(ctx, path, q)
	links := jx.Strings(jx.Get(meta, "download_links"))
	if meta == nil || len(jx.GetList(meta, "download_links")) == 0 {
		return nil
	}
	records := downloadAndMerge(ctx, links)
	result := jx.M{
		"records":              records,
		"total_records":        len(records),
		"download_links_count": len(jx.GetList(meta, "download_links")),
	}
	for _, k := range []string{"report_day", "report_start_day", "report_end_day"} {
		if v, ok := meta[k]; ok {
			result[k] = v
		}
	}
	return result
}

// GetOrgUsageReport28Day returns the latest 28-day org usage report, or nil.
func (c *Client) GetOrgUsageReport28Day(ctx context.Context, org string) jx.M {
	return c.fetchUsageReport(ctx, "/orgs/"+org+"/copilot/metrics/reports/organization-28-day/latest", nil)
}

// GetOrgUsageReport1Day returns a one-day org usage report, or nil.
func (c *Client) GetOrgUsageReport1Day(ctx context.Context, org, day string) jx.M {
	return c.fetchUsageReport(ctx, "/orgs/"+org+"/copilot/metrics/reports/organization-1-day", url.Values{"day": {day}})
}

// GetOrgUsersUsageReport28Day returns the latest 28-day user-level org report, or nil.
func (c *Client) GetOrgUsersUsageReport28Day(ctx context.Context, org string) jx.M {
	return c.fetchUsageReport(ctx, "/orgs/"+org+"/copilot/metrics/reports/users-28-day/latest", nil)
}

// GetOrgUsersUsageReport1Day returns a one-day user-level org report, or nil.
func (c *Client) GetOrgUsersUsageReport1Day(ctx context.Context, org, day string) jx.M {
	return c.fetchUsageReport(ctx, "/orgs/"+org+"/copilot/metrics/reports/users-1-day", url.Values{"day": {day}})
}

// GetEnterpriseUsageReport28Day returns the latest 28-day enterprise report, or nil.
func (c *Client) GetEnterpriseUsageReport28Day(ctx context.Context, enterprise string) jx.M {
	return c.fetchUsageReport(ctx, "/enterprises/"+enterprise+"/copilot/metrics/reports/enterprise-28-day/latest", nil)
}

// GetEnterpriseUsageReport1Day returns a one-day enterprise report, or nil.
func (c *Client) GetEnterpriseUsageReport1Day(ctx context.Context, enterprise, day string) jx.M {
	return c.fetchUsageReport(ctx, "/enterprises/"+enterprise+"/copilot/metrics/reports/enterprise-1-day", url.Values{"day": {day}})
}

// GetEnterpriseUsersUsageReport28Day returns the latest 28-day enterprise user report, or nil.
func (c *Client) GetEnterpriseUsersUsageReport28Day(ctx context.Context, enterprise string) jx.M {
	return c.fetchUsageReport(ctx, "/enterprises/"+enterprise+"/copilot/metrics/reports/users-28-day/latest", nil)
}

// GetEnterpriseUsersUsageReport1Day returns a one-day enterprise user report, or nil.
func (c *Client) GetEnterpriseUsersUsageReport1Day(ctx context.Context, enterprise, day string) jx.M {
	return c.fetchUsageReport(ctx, "/enterprises/"+enterprise+"/copilot/metrics/reports/users-1-day", url.Values{"day": {day}})
}

// ---------------------------------------------------------------------------
// Seat management operations
// ---------------------------------------------------------------------------

func errorResult(r *Response, withBody bool) jx.M {
	out := jx.M{"error": (&HTTPError{Resp: r}).Error(), "status_code": r.Status}
	if withBody {
		if v := r.JSON(); v != nil {
			out["response"] = v
		} else {
			out["response"] = jx.M{"text": r.Text()}
		}
	}
	return out
}

func transportResult(err error) jx.M {
	return jx.M{"error": err.Error(), "status_code": nil}
}

// AddCopilotSeats adds org-level seats.
func (c *Client) AddCopilotSeats(ctx context.Context, org string, usernames []string) jx.M {
	r, err := c.Do(ctx, http.MethodPost, "/orgs/"+org+"/copilot/billing/selected_users", nil, jx.M{"selected_usernames": usernames}, nil)
	if err != nil {
		return transportResult(err)
	}
	if !r.OK() {
		return errorResult(r, false)
	}
	return jx.Map(r.JSON())
}

// RemoveCopilotSeats removes org-level seats.
func (c *Client) RemoveCopilotSeats(ctx context.Context, org string, usernames []string) jx.M {
	r, err := c.Do(ctx, http.MethodDelete, "/orgs/"+org+"/copilot/billing/selected_users", nil, jx.M{"selected_usernames": usernames}, nil)
	if err != nil {
		return transportResult(err)
	}
	if !r.OK() {
		return errorResult(r, true)
	}
	return jx.Map(r.JSON())
}

// AddTeamMembership adds or updates a team membership.
func (c *Client) AddTeamMembership(ctx context.Context, org, teamSlug, username, role string) jx.M {
	if role == "" {
		role = "member"
	}
	r, err := c.Do(ctx, http.MethodPut, "/orgs/"+org+"/teams/"+teamSlug+"/memberships/"+username, nil, jx.M{"role": role}, nil)
	if err != nil {
		return transportResult(err)
	}
	if !r.OK() {
		return errorResult(r, true)
	}
	return jx.Map(r.JSON())
}

// RemoveTeamMembership removes a team membership (revoking its team-assigned seat).
func (c *Client) RemoveTeamMembership(ctx context.Context, org, teamSlug, username string) jx.M {
	r, err := c.Do(ctx, http.MethodDelete, "/orgs/"+org+"/teams/"+teamSlug+"/memberships/"+username, nil, nil, nil)
	if err != nil {
		return transportResult(err)
	}
	if !r.OK() {
		return errorResult(r, true)
	}
	return jx.M{"success": true, "username": username, "team": teamSlug}
}

// ---------------------------------------------------------------------------
// Budgets (UBB)
// ---------------------------------------------------------------------------

func budgetsPath(entityType, entityName string) string {
	if entityType == "enterprise" {
		return "/enterprises/" + entityName + "/settings/billing/budgets"
	}
	return "/organizations/" + entityName + "/settings/billing/budgets"
}

// GetBudgets returns one page of budgets, nil on 403/404, or {"error",...}.
func (c *Client) GetBudgets(ctx context.Context, entityType, entityName, scope string, page, perPage int) jx.M {
	path := budgetsPath(entityType, entityName)
	q := url.Values{}
	if scope != "" {
		q.Set("scope", scope)
	}
	if page > 0 {
		q.Set("page", fmt.Sprint(page))
	}
	if perPage > 0 {
		q.Set("per_page", fmt.Sprint(perPage))
	}
	Logger.Info(fmt.Sprintf("[GET_BUDGETS] REQUEST: GET %s%s", c.baseURL, path))
	r, err := c.Get(ctx, path, q, billing())
	if err != nil {
		Logger.Error(fmt.Sprintf("[GET_BUDGETS] Request error: %v", err))
		return jx.M{"error": err.Error(), "status_code": nil}
	}
	Logger.Info(fmt.Sprintf("[GET_BUDGETS] RESPONSE: %d %s", r.Status, r.Reason))
	if r.Status == 404 || r.Status == 403 {
		Logger.Warn(fmt.Sprintf("[GET_BUDGETS] Failed with %d, returning None", r.Status))
		return nil
	}
	if !r.OK() {
		return errorResult(r, false)
	}
	return jx.Map(r.JSON())
}

// GetAllBudgetsPaginated fetches every page. With strict, incomplete reads return an error.
func (c *Client) GetAllBudgetsPaginated(ctx context.Context, entityType, entityName, scope string, strict bool) ([]jx.M, error) {
	all := []jx.M{}
	page := 1
	for {
		result := c.GetBudgets(ctx, entityType, entityName, scope, page, 100)
		if result == nil || jx.Truthy(result["error"]) || jx.List(result["budgets"]) == nil {
			if strict {
				return nil, fmt.Errorf("Unable to read complete budget data from GitHub")
			}
			break
		}
		batch := jx.GetMaps(result, "budgets")
		all = append(all, batch...)
		if strict && jx.Truthy(result["has_next_page"]) && len(batch) == 0 {
			return nil, fmt.Errorf("Incomplete budget pagination from GitHub")
		}
		if !jx.Truthy(result["has_next_page"]) || len(batch) == 0 {
			break
		}
		page++
	}
	return all, nil
}

// GetBudget returns one budget, nil on 403/404, or {"error",...}.
func (c *Client) GetBudget(ctx context.Context, entityType, entityName, budgetID string) jx.M {
	path := budgetsPath(entityType, entityName) + "/" + budgetID
	r, err := c.Get(ctx, path, nil, billing())
	if err != nil {
		return jx.M{"error": err.Error(), "status_code": nil}
	}
	if r.Status == 404 || r.Status == 403 {
		return nil
	}
	if !r.OK() {
		return errorResult(r, false)
	}
	return jx.Map(r.JSON())
}

// CreateBudget creates a budget; errors come back as {"error","status_code","response"}.
func (c *Client) CreateBudget(ctx context.Context, entityType, entityName string, data jx.M) jx.M {
	path := budgetsPath(entityType, entityName)
	Logger.Info(fmt.Sprintf("[CREATE_BUDGET] REQUEST: POST %s%s", c.baseURL, path))
	r, err := c.Do(ctx, http.MethodPost, path, nil, data, billing())
	if err != nil {
		return jx.M{"error": err.Error(), "status_code": nil, "response": jx.M{"message": err.Error()}}
	}
	Logger.Info(fmt.Sprintf("[CREATE_BUDGET] RESPONSE: %d %s", r.Status, r.Reason))
	if !r.OK() {
		Logger.Error(fmt.Sprintf("[CREATE_BUDGET] Error: %s", r.Text()))
		return errorResult(r, true)
	}
	if m := jx.Map(r.JSON()); m != nil {
		return m
	}
	return jx.M{}
}

// UpdateBudget patches a budget; errors come back as {"error","status_code","response"}.
func (c *Client) UpdateBudget(ctx context.Context, entityType, entityName, budgetID string, data jx.M) jx.M {
	path := budgetsPath(entityType, entityName) + "/" + budgetID
	Logger.Info(fmt.Sprintf("[UPDATE_BUDGET] REQUEST: PATCH %s%s", c.baseURL, path))
	r, err := c.Do(ctx, http.MethodPatch, path, nil, data, billing())
	if err != nil {
		return jx.M{"error": err.Error(), "status_code": nil, "response": jx.M{"message": err.Error()}}
	}
	Logger.Info(fmt.Sprintf("[UPDATE_BUDGET] RESPONSE: %d %s", r.Status, r.Reason))
	if !r.OK() {
		Logger.Error(fmt.Sprintf("[UPDATE_BUDGET] Error: %s", r.Text()))
		return errorResult(r, true)
	}
	if m := jx.Map(r.JSON()); m != nil {
		return m
	}
	return jx.M{}
}

// DeleteBudget deletes a budget.
func (c *Client) DeleteBudget(ctx context.Context, entityType, entityName, budgetID string) jx.M {
	path := budgetsPath(entityType, entityName) + "/" + budgetID
	Logger.Info(fmt.Sprintf("[DELETE_BUDGET] DELETE %s%s", c.baseURL, path))
	r, err := c.Do(ctx, http.MethodDelete, path, nil, nil, billing())
	if err != nil {
		return jx.M{
			"error":        fmt.Sprintf("Request error while deleting budget: %T", err),
			"status_code":  nil,
			"response":     jx.M{"message": err.Error()},
			"request_path": path,
		}
	}
	Logger.Info(fmt.Sprintf("[DELETE_BUDGET] Status Code: %d", r.Status))
	if !r.OK() {
		var body any = r.JSON()
		if body == nil {
			t := r.Text()
			if t == "" {
				t = "No error details"
			}
			body = jx.M{"text": t}
		}
		return jx.M{
			"error":        fmt.Sprintf("HTTP %d: %s", r.Status, r.Reason),
			"status_code":  r.Status,
			"response":     body,
			"request_path": path,
		}
	}
	result := jx.Map(r.JSON())
	msg := jx.GetStr(result, "message", fmt.Sprintf("Budget %s deleted successfully", budgetID))
	id := jx.GetOr(result, "id", budgetID)
	return jx.M{
		"success":     true,
		"budget_id":   budgetID,
		"status_code": r.Status,
		"message":     msg,
		"id":          id,
	}
}
