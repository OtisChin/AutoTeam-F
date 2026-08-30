package fingerprint

import "testing"

func BenchmarkPoolSelectParallel(b *testing.B) {
	pool, err := ParsePool(DefaultPool)
	if err != nil {
		b.Fatal(err)
	}
	b.ReportAllocs()
	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			if _, err := pool.Select(CryptoDraw); err != nil {
				b.Fatal(err)
			}
		}
	})
}
