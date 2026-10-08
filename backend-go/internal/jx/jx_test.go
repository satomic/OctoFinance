package jx

import "testing"

func TestRoundMatchesPython(t *testing.T) {
	cases := []struct {
		x    float64
		n    int
		want float64
	}{
		{2.675, 2, 2.67}, // binary value is below the tie, as in Python
		{0.125, 2, 0.12}, // exact tie rounds to even
		{0.375, 2, 0.38},
		{-1.5, 0, -2},
		{1234.56789, 1, 1234.6},
		{-0.0001, 2, 0},
	}
	for _, c := range cases {
		if got := Round(c.x, c.n); got != c.want {
			t.Errorf("Round(%v, %d) = %v, want %v", c.x, c.n, got, c.want)
		}
	}
}

func TestTruthy(t *testing.T) {
	falsy := []any{nil, false, "", 0.0, L{}, M{}}
	for _, v := range falsy {
		if Truthy(v) {
			t.Errorf("Truthy(%#v) = true", v)
		}
	}
	for _, v := range []any{true, "x", 1.0, L{1}, M{"a": 1}} {
		if !Truthy(v) {
			t.Errorf("Truthy(%#v) = false", v)
		}
	}
}

func TestGetOrVsOrStr(t *testing.T) {
	m := M{"null": nil, "empty": ""}
	if GetOr(m, "null", "d") != nil {
		t.Error("GetOr must return a present null like dict.get(k, d)")
	}
	if OrStr(m, "empty", "d") != "d" || OrStr(m, "missing", "d") != "d" {
		t.Error("OrStr must behave like dict.get(k) or d")
	}
}

func TestISOAndParse(t *testing.T) {
	ts, ok := ParseISO("2026-06-01T12:30:00Z")
	if !ok {
		t.Fatal("ParseISO failed")
	}
	if got := ISO(ts); got != "2026-06-01T12:30:00+00:00" {
		t.Errorf("ISO = %s", got)
	}
	if _, ok := ParseISO("2026-06-01"); !ok {
		t.Error("date-only values must parse")
	}
}

func TestDaysBetweenFloors(t *testing.T) {
	a, _ := ParseISO("2026-06-02T00:00:00Z")
	b, _ := ParseISO("2026-06-02T12:00:00Z")
	if d := DaysBetween(a, b); d != -1 { // Python: (a - b).days == -1
		t.Errorf("DaysBetween = %d, want -1", d)
	}
}
