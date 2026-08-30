package fingerprint

import (
	"errors"
	"reflect"
	"testing"
)

func TestParsePoolRejectsEmptyInput(t *testing.T) {
	for _, raw := range []string{"", "   ", ", ,"} {
		if _, err := ParsePool(raw); !errors.Is(err, ErrEmptyPool) {
			t.Fatalf("ParsePool(%q) error=%v", raw, err)
		}
	}
}

func TestParsePoolNormalizesWhitespaceAndDuplicates(t *testing.T) {
	pool, err := ParsePool(" chrome144,chrome146, chrome144 ,chrome150 ")
	if err != nil {
		t.Fatalf("ParsePool() error=%v", err)
	}
	if got := pool.Names(); !reflect.DeepEqual(got, []string{"chrome144", "chrome146", "chrome150"}) {
		t.Fatalf("pool names=%v", got)
	}
}

func TestParsePoolRejectsAnyUnsupportedName(t *testing.T) {
	for _, raw := range []string{
		"chrome144,chrome147,chrome150",
		"chrome147,chrome147",
	} {
		if _, err := ParsePool(raw); !errors.Is(err, ErrUnsupportedProfile) {
			t.Fatalf("ParsePool(%q) error=%v", raw, err)
		}
	}
}

func TestPoolNamesReturnsCopy(t *testing.T) {
	pool, err := ParsePool(DefaultPool)
	if err != nil {
		t.Fatal(err)
	}
	got := pool.Names()
	got[0] = "mutated"
	if pool.Names()[0] != "chrome144" {
		t.Fatalf("pool names were mutated: %v", pool.Names())
	}
}

func TestPoolSelectUsesInjectedDrawOnce(t *testing.T) {
	pool, err := ParsePool(DefaultPool)
	if err != nil {
		t.Fatal(err)
	}
	calls := 0
	got, err := pool.Select(func(max int) (int, error) {
		calls++
		if max != 3 {
			t.Fatalf("draw max=%d", max)
		}
		return 2, nil
	})
	if err != nil || got.Name != "chrome150" || calls != 1 {
		t.Fatalf("profile=%#v calls=%d err=%v", got, calls, err)
	}
}

func TestPoolSelectPropagatesDrawError(t *testing.T) {
	pool, err := ParsePool(DefaultPool)
	if err != nil {
		t.Fatal(err)
	}
	want := errors.New("entropy unavailable")
	if _, err := pool.Select(func(int) (int, error) { return 0, want }); !errors.Is(err, want) {
		t.Fatalf("Select() error=%v", err)
	}
}

func TestPoolSelectRejectsOutOfRangeDraw(t *testing.T) {
	pool, err := ParsePool(DefaultPool)
	if err != nil {
		t.Fatal(err)
	}
	for _, index := range []int{-1, 3} {
		if _, err := pool.Select(func(int) (int, error) { return index, nil }); !errors.Is(err, ErrDrawOutOfRange) {
			t.Fatalf("draw index=%d error=%v", index, err)
		}
	}
}

func TestCryptoDrawBoundsAndEmptyPool(t *testing.T) {
	if _, err := CryptoDraw(0); !errors.Is(err, ErrEmptyPool) {
		t.Fatalf("CryptoDraw(0) error=%v", err)
	}
	for range 100 {
		got, err := CryptoDraw(3)
		if err != nil || got < 0 || got >= 3 {
			t.Fatalf("CryptoDraw(3)=%d error=%v", got, err)
		}
	}
}
