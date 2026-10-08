package jx

import (
	"encoding/json"
	"reflect"
	"testing"
)

var parseCases = []string{
	`{}`, `[]`, `null`, `true`, `false`, `0`, `-0`, `12.5e-3`, `1E+2`, `-7`,
	`"plain"`, `"esc \" \\ \/ \b \f \n \r \t"`, `"é中"`, `"😀"`,
	`"\ud83d"`, `"\ud83dx"`, `"\udc00\ud83d"`, "\"bad \xff utf8\"", `"中文"`,
	` { "a" : [ 1 , 2 , {"b":null} ] , "a" : "dup" } `,
	`{"seats":[{"login":"u1","last_activity_at":"2026-01-01"},{"login":"u2","last_activity_at":"2026-01-01"}]}`,
	`1e400`, `{"a":1,}`, `[1 2]`, `01`, `1.`, `.5`, `-`, `"\x"`, `"abc`, `{"a"}`, `tru`, `nul`, "\"tab\tin\"", `{"a":1} x`, ``,
}

func TestParseMatchesEncodingJSON(t *testing.T) {
	for _, c := range parseCases {
		var want any
		wantErr := json.Unmarshal([]byte(c), &want)
		got, err := Parse([]byte(c))
		if (wantErr != nil) != (err != nil) {
			t.Errorf("%q: error mismatch: encoding/json=%v Parse=%v", c, wantErr, err)
			continue
		}
		if err == nil && !reflect.DeepEqual(want, got) {
			t.Errorf("%q: got %#v, want %#v", c, got, want)
		}
	}
}

func FuzzParse(f *testing.F) {
	for _, c := range parseCases {
		f.Add([]byte(c))
	}
	f.Fuzz(func(t *testing.T, b []byte) {
		var want any
		wantErr := json.Unmarshal(b, &want)
		got, err := Parse(b)
		if (wantErr != nil) != (err != nil) {
			t.Fatalf("%q: error mismatch: encoding/json=%v Parse=%v", b, wantErr, err)
		}
		if err == nil && !reflect.DeepEqual(want, got) {
			t.Fatalf("%q: got %#v, want %#v", b, got, want)
		}
	})
}
