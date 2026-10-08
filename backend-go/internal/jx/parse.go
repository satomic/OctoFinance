package jx

import (
	"errors"
	"fmt"
	"strconv"
	"unicode/utf16"
	"unicode/utf8"
)

// Parse decodes JSON into the same values as encoding/json does for an `any`
// target (map[string]any, []any, float64, string, bool, nil), but interns
// object keys and short string values. Synced GitHub snapshots repeat the
// same keys and values (field names, dates, IDE and model names) hundreds of
// thousands of times; encoding/json allocates each one separately, which made
// cached snapshots several times larger than the file.
func Parse(data []byte) (any, error) {
	p := parser{data: data, intern: make(map[string]string, 1024)}
	p.skipWS()
	v, err := p.value()
	if err != nil {
		return nil, err
	}
	p.skipWS()
	if p.pos != len(p.data) {
		return nil, p.errorf("invalid character after top-level value")
	}
	return v, nil
}

// internMaxLen bounds which string values are interned; long values (free
// text, URLs) are rarely repeated.
const internMaxLen = 64

type parser struct {
	data   []byte
	pos    int
	intern map[string]string
}

func (p *parser) errorf(format string, args ...any) error {
	return fmt.Errorf("json: "+format+" at offset %d", append(args, p.pos)...)
}

func (p *parser) skipWS() {
	for p.pos < len(p.data) {
		switch p.data[p.pos] {
		case ' ', '\t', '\n', '\r':
			p.pos++
		default:
			return
		}
	}
}

func (p *parser) value() (any, error) {
	if p.pos >= len(p.data) {
		return nil, p.errorf("unexpected end of input")
	}
	switch c := p.data[p.pos]; {
	case c == '{':
		return p.object()
	case c == '[':
		return p.array()
	case c == '"':
		return p.str(false)
	case c == 't':
		return true, p.literal("true")
	case c == 'f':
		return false, p.literal("false")
	case c == 'n':
		return nil, p.literal("null")
	case c == '-' || (c >= '0' && c <= '9'):
		return p.number()
	}
	return nil, p.errorf("invalid character %q looking for beginning of value", p.data[p.pos])
}

func (p *parser) literal(word string) error {
	if len(p.data)-p.pos < len(word) || string(p.data[p.pos:p.pos+len(word)]) != word {
		return p.errorf("invalid literal")
	}
	p.pos += len(word)
	return nil
}

func (p *parser) object() (any, error) {
	p.pos++ // {
	m := map[string]any{}
	p.skipWS()
	if p.pos < len(p.data) && p.data[p.pos] == '}' {
		p.pos++
		return m, nil
	}
	for {
		p.skipWS()
		if p.pos >= len(p.data) || p.data[p.pos] != '"' {
			return nil, p.errorf("expected object key")
		}
		k, err := p.str(true)
		if err != nil {
			return nil, err
		}
		p.skipWS()
		if p.pos >= len(p.data) || p.data[p.pos] != ':' {
			return nil, p.errorf("expected ':' after object key")
		}
		p.pos++
		p.skipWS()
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		m[k.(string)] = v // a duplicate key keeps the last value, like encoding/json
		p.skipWS()
		if p.pos >= len(p.data) {
			return nil, p.errorf("unexpected end of object")
		}
		switch p.data[p.pos] {
		case ',':
			p.pos++
		case '}':
			p.pos++
			return m, nil
		default:
			return nil, p.errorf("expected ',' or '}' in object")
		}
	}
}

func (p *parser) array() (any, error) {
	p.pos++ // [
	a := []any{}
	p.skipWS()
	if p.pos < len(p.data) && p.data[p.pos] == ']' {
		p.pos++
		return a, nil
	}
	for {
		p.skipWS()
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		a = append(a, v)
		p.skipWS()
		if p.pos >= len(p.data) {
			return nil, p.errorf("unexpected end of array")
		}
		switch p.data[p.pos] {
		case ',':
			p.pos++
		case ']':
			p.pos++
			return a, nil
		default:
			return nil, p.errorf("expected ',' or ']' in array")
		}
	}
}

func (p *parser) number() (any, error) {
	start := p.pos
	if p.data[p.pos] == '-' {
		p.pos++
	}
	digits := func() int {
		n := 0
		for p.pos < len(p.data) && p.data[p.pos] >= '0' && p.data[p.pos] <= '9' {
			p.pos++
			n++
		}
		return n
	}
	if p.pos < len(p.data) && p.data[p.pos] == '0' {
		p.pos++
	} else if digits() == 0 {
		return nil, p.errorf("invalid number")
	}
	if p.pos < len(p.data) && p.data[p.pos] == '.' {
		p.pos++
		if digits() == 0 {
			return nil, p.errorf("invalid number")
		}
	}
	if p.pos < len(p.data) && (p.data[p.pos] == 'e' || p.data[p.pos] == 'E') {
		p.pos++
		if p.pos < len(p.data) && (p.data[p.pos] == '+' || p.data[p.pos] == '-') {
			p.pos++
		}
		if digits() == 0 {
			return nil, p.errorf("invalid number")
		}
	}
	f, err := strconv.ParseFloat(string(p.data[start:p.pos]), 64)
	if err != nil {
		var ne *strconv.NumError
		if errors.As(err, &ne) && errors.Is(ne.Err, strconv.ErrRange) {
			return nil, p.errorf("number %s out of range", string(p.data[start:p.pos]))
		}
		return nil, p.errorf("invalid number")
	}
	return f, nil
}

// str parses a string; keys are always interned, values when short.
func (p *parser) str(key bool) (any, error) {
	p.pos++ // opening quote
	start := p.pos
	// fast path: no escapes
	for p.pos < len(p.data) {
		c := p.data[p.pos]
		if c == '"' {
			raw := p.data[start:p.pos]
			p.pos++
			if !utf8.Valid(raw) {
				return p.finish(string([]rune(string(raw))), key), nil // replace invalid UTF-8 like encoding/json
			}
			return p.internBytes(raw, key), nil
		}
		if c == '\\' {
			break
		}
		if c < 0x20 {
			return nil, p.errorf("invalid control character in string")
		}
		p.pos++
	}
	// slow path with escapes
	buf := make([]byte, 0, p.pos-start+16)
	buf = append(buf, p.data[start:p.pos]...)
	for p.pos < len(p.data) {
		c := p.data[p.pos]
		switch {
		case c == '"':
			p.pos++
			s := string(buf)
			if !utf8.ValidString(s) {
				s = string([]rune(s))
			}
			return p.finish(s, key), nil
		case c == '\\':
			p.pos++
			if p.pos >= len(p.data) {
				return nil, p.errorf("unexpected end of string escape")
			}
			e := p.data[p.pos]
			p.pos++
			switch e {
			case '"', '\\', '/':
				buf = append(buf, e)
			case 'b':
				buf = append(buf, '\b')
			case 'f':
				buf = append(buf, '\f')
			case 'n':
				buf = append(buf, '\n')
			case 'r':
				buf = append(buf, '\r')
			case 't':
				buf = append(buf, '\t')
			case 'u':
				r, ok := p.hex4()
				if !ok {
					return nil, p.errorf("invalid \\u escape")
				}
				if utf16.IsSurrogate(r) {
					r2 := utf8.RuneError
					if p.pos+1 < len(p.data) && p.data[p.pos] == '\\' && p.data[p.pos+1] == 'u' {
						save := p.pos
						p.pos += 2
						if lo, ok := p.hex4(); ok {
							if dec := utf16.DecodeRune(r, lo); dec != utf8.RuneError {
								r2 = dec
							} else {
								p.pos = save
							}
						} else {
							p.pos = save
						}
					}
					r = r2
				}
				buf = utf8.AppendRune(buf, r)
			default:
				return nil, p.errorf("invalid escape character %q", e)
			}
		case c < 0x20:
			return nil, p.errorf("invalid control character in string")
		default:
			buf = append(buf, c)
			p.pos++
		}
	}
	return nil, p.errorf("unexpected end of string")
}

func (p *parser) hex4() (rune, bool) {
	if p.pos+4 > len(p.data) {
		return 0, false
	}
	v, err := strconv.ParseUint(string(p.data[p.pos:p.pos+4]), 16, 32)
	if err != nil {
		return 0, false
	}
	p.pos += 4
	return rune(v), true
}

func (p *parser) internBytes(b []byte, key bool) string {
	if !key && len(b) > internMaxLen {
		return string(b)
	}
	if s, ok := p.intern[string(b)]; ok { // no allocation for the lookup
		return s
	}
	s := string(b)
	p.intern[s] = s
	return s
}

func (p *parser) finish(s string, key bool) string {
	if !key && len(s) > internMaxLen {
		return s
	}
	if v, ok := p.intern[s]; ok {
		return v
	}
	p.intern[s] = s
	return s
}
