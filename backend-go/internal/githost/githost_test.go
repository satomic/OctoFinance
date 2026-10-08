package githost

import "testing"

func TestNormalize(t *testing.T) {
	ok := map[string]string{
		"":                                   "github.com",
		"github.com":                         "github.com",
		"https://www.github.com/x":           "github.com",
		"ACME.ghe.com":                       "acme.ghe.com",
		"api.acme.ghe.com":                   "acme.ghe.com",
		"https://acme.ghe.com/enterprises/a": "acme.ghe.com",
	}
	for in, want := range ok {
		if got, err := Normalize(in); err != nil || got != want {
			t.Errorf("Normalize(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	for _, bad := range []string{"example.com", "ghe.com", "-x.ghe.com"} {
		if _, err := Normalize(bad); err == nil {
			t.Errorf("Normalize(%q) should fail", bad)
		}
	}
}

func TestBases(t *testing.T) {
	t.Setenv("OCTOFINANCE_GITHUB_API_BASE", "")
	if APIBase("github.com") != "https://api.github.com" || APIBase("acme.ghe.com") != "https://api.acme.ghe.com" {
		t.Error("APIBase")
	}
	if WebBase("") != "https://github.com" {
		t.Error("WebBase")
	}
	if FromAPIBase("https://api.acme.ghe.com") != "acme.ghe.com" || FromAPIBase("http://127.0.0.1:9") != "github.com" {
		t.Error("FromAPIBase")
	}
}

func TestParseEnterpriseURL(t *testing.T) {
	host, slug, ok, err := ParseEnterpriseURL("https://acme.ghe.com/enterprises/acme-corp")
	if err != nil || !ok || host != "acme.ghe.com" || slug != "acme-corp" {
		t.Errorf("got %q %q %v %v", host, slug, ok, err)
	}
	if _, _, ok, _ := ParseEnterpriseURL("acme-corp"); ok {
		t.Error("a plain slug is not a URL")
	}
}
