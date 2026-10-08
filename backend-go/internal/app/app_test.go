package app

import (
	"testing"

	"github.com/satomic/octofinance/backend-go/internal/jx"
)

func TestDeriveTitle(t *testing.T) {
	cases := map[string]string{
		"":                       DefaultSessionTitle,
		"  # Hello   world ":     "Hello world",
		"see `code` ```x\ny```!": "see code !",
		"当前有多少个organizations?":   "当前有多少个organizations?",
		"Find all users who haven't used Copilot in the last 30 days please": "Find all users who haven't used Copilot in the...",
	}
	for in, want := range cases {
		if got := DeriveTitle(in); got != want {
			t.Errorf("DeriveTitle(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestDescribeCron(t *testing.T) {
	cases := map[string]string{
		"*/30 * * * *": "Every 30 minutes",
		"0 */6 * * *":  "Every 6 hours",
		"0 0 * * *":    "Daily",
		"0 0 */2 * *":  "Every 2 days",
		"5 4 * * 1":    "",
	}
	for in, want := range cases {
		if got := DescribeCron(in); got != want {
			t.Errorf("DescribeCron(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestMergeUsageUsersReportKeepsHistory(t *testing.T) {
	old := jx.M{"records": jx.L{
		jx.M{"day": "2026-01-01", "user_login": "a", "v": 1.0},
		jx.M{"day": "2026-01-02", "user_login": "a", "v": 1.0},
	}}
	fresh := jx.M{"records": jx.L{
		jx.M{"day": "2026-01-02", "user_login": "a", "v": 2.0},
		jx.M{"day": "2026-01-03", "user_login": "a", "v": 3.0},
	}}
	got := jx.Map(mergeUsageUsersReport(old, fresh))
	recs := jx.GetMaps(got, "records")
	if len(recs) != 3 || jx.GetFloat(recs[1], "v") != 2 {
		t.Fatalf("merged records = %v", recs)
	}
	if got["report_start_day"] != "2026-01-01" || got["report_end_day"] != "2026-01-03" {
		t.Errorf("range = %v..%v", got["report_start_day"], got["report_end_day"])
	}
}

func TestSyntheticBillingPicksMajorityPlan(t *testing.T) {
	b := BuildSyntheticEnterpriseBilling(jx.M{"seats": jx.L{
		jx.M{"plan_type": "business"}, jx.M{"plan_type": "enterprise"}, jx.M{"plan_type": "business"},
	}})
	if b["plan_type"] != "business" || b["_detected_price_per_seat"] != 19.0 {
		t.Errorf("billing = %v", b)
	}
}

func TestToolsRegisteredInPythonOrder(t *testing.T) {
	names := ToolNames()
	if len(names) != 44 {
		t.Fatalf("expected 44 tools, got %d", len(names))
	}
	if names[0] != "get_all_seats" || names[len(names)-1] != "sync_data" {
		t.Errorf("unexpected order: first=%s last=%s", names[0], names[len(names)-1])
	}
}
