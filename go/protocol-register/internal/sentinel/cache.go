package sentinel

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
	"time"
)

const (
	latestCacheFile   = "latest.json"
	lastGoodCacheFile = "last-good.json"

	maxCacheRecordBytes = 64 * 1024
	maxFrameBytes       = 1024 * 1024
	maxSDKBytes         = 4 * 1024 * 1024
	maxCacheUnixSeconds = 253402300799
)

type cacheRecord struct {
	Version    string  `json:"version"`
	SDKURL     string  `json:"sdk_url"`
	ResolvedAt float64 `json:"resolved_at"`
}

type cachedSDK struct {
	SDK        SDK
	ResolvedAt time.Time
}

type sdkCache struct {
	dir string
	mu  *sync.RWMutex
}

var cacheDirectoryLocks sync.Map

func newSDKCache(dir string) *sdkCache {
	key, err := filepath.Abs(dir)
	if err != nil {
		key = filepath.Clean(dir)
	}
	lock, _ := cacheDirectoryLocks.LoadOrStore(key, &sync.RWMutex{})
	return &sdkCache{dir: dir, mu: lock.(*sync.RWMutex)}
}

func (c *sdkCache) readRecord(name string) (cachedSDK, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return readCacheRecord(filepath.Join(c.dir, name))
}

func readCacheRecord(path string) (cachedSDK, bool) {
	payload, err := readFileBounded(path, maxCacheRecordBytes)
	if err != nil {
		return cachedSDK{}, false
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var record cacheRecord
	if err := decoder.Decode(&record); err != nil {
		return cachedSDK{}, false
	}
	if err := requireJSONEOF(decoder); err != nil {
		return cachedSDK{}, false
	}
	if math.IsNaN(record.ResolvedAt) || math.IsInf(record.ResolvedAt, 0) || record.ResolvedAt < 0 || record.ResolvedAt > maxCacheUnixSeconds {
		return cachedSDK{}, false
	}
	sdk, err := parseSDKURL(record.SDKURL)
	if err != nil || sdk.Version != record.Version {
		return cachedSDK{}, false
	}
	seconds, fraction := math.Modf(record.ResolvedAt)
	return cachedSDK{
		SDK:        sdk,
		ResolvedAt: time.Unix(int64(seconds), int64(fraction*float64(time.Second))),
	}, true
}

func (c *sdkCache) writeRecord(name string, sdk SDK, resolvedAt time.Time) error {
	_, payload, err := encodeCacheRecord(sdk, resolvedAt)
	if err != nil {
		return err
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	return writeFileAtomic(filepath.Join(c.dir, name), payload)
}

func (c *sdkCache) writeRecordIfChanged(name string, sdk SDK, resolvedAt time.Time) error {
	normalized, payload, err := encodeCacheRecord(sdk, resolvedAt)
	if err != nil {
		return err
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	path := filepath.Join(c.dir, name)
	if current, ok := readCacheRecord(path); ok && current.SDK.Version == normalized.Version && current.SDK.URL == normalized.URL {
		return nil
	}
	return writeFileAtomic(path, payload)
}

func encodeCacheRecord(sdk SDK, resolvedAt time.Time) (SDK, []byte, error) {
	normalized, err := normalizeSDK(sdk)
	if err != nil {
		return SDK{}, nil, err
	}
	record := cacheRecord{
		Version:    normalized.Version,
		SDKURL:     normalized.URL,
		ResolvedAt: float64(resolvedAt.Unix()) + float64(resolvedAt.Nanosecond())/float64(time.Second),
	}
	payload, err := json.Marshal(record)
	if err != nil {
		return SDK{}, nil, err
	}
	return normalized, append(payload, '\n'), nil
}

func (c *sdkCache) readSource(version string) ([]byte, bool) {
	if err := validateSDKVersion(version); err != nil {
		return nil, false
	}
	c.mu.RLock()
	defer c.mu.RUnlock()

	payload, err := readFileBounded(filepath.Join(c.dir, version+".js"), maxSDKBytes)
	if err != nil || len(bytes.TrimSpace(payload)) == 0 {
		return nil, false
	}
	return append([]byte(nil), payload...), true
}

func (c *sdkCache) writeSource(version string, source []byte) error {
	if err := validateSDKVersion(version); err != nil {
		return err
	}
	if len(source) > maxSDKBytes {
		return ErrResponseTooLarge
	}
	if len(bytes.TrimSpace(source)) == 0 {
		return ErrEmptySDKSource
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	return writeFileAtomic(filepath.Join(c.dir, version+".js"), source)
}

func readFileBounded(path string, limit int64) ([]byte, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	if info, statErr := file.Stat(); statErr != nil {
		return nil, statErr
	} else if info.Size() > limit {
		return nil, ErrResponseTooLarge
	}
	payload, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(payload)) > limit {
		return nil, ErrResponseTooLarge
	}
	return payload, nil
}

func requireJSONEOF(decoder *json.Decoder) error {
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("unexpected trailing JSON value")
		}
		return err
	}
	return nil
}

func writeFileAtomic(path string, payload []byte) (returnErr error) {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	temporary, err := os.CreateTemp(dir, "."+filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer func() {
		if temporary != nil {
			_ = temporary.Close()
		}
		if returnErr != nil {
			_ = os.Remove(temporaryPath)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		return err
	}
	if _, err := temporary.Write(payload); err != nil {
		return err
	}
	if err := temporary.Sync(); err != nil {
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	temporary = nil
	if err := replaceFile(temporaryPath, path); err != nil {
		return err
	}
	return nil
}

func replaceFile(oldPath, newPath string) error {
	const maxRetries = 6
	for attempt := 0; ; attempt++ {
		err := os.Rename(oldPath, newPath)
		if err == nil {
			return nil
		}
		if attempt == maxRetries || !isTransientWindowsRenameError(err) {
			return err
		}
		time.Sleep(time.Millisecond << attempt)
	}
}

func isTransientWindowsRenameError(err error) bool {
	if runtime.GOOS != "windows" {
		return false
	}
	const (
		windowsErrorAccessDenied     syscall.Errno = 5
		windowsErrorSharingViolation syscall.Errno = 32
	)
	var errno syscall.Errno
	return errors.As(err, &errno) && (errno == windowsErrorAccessDenied || errno == windowsErrorSharingViolation)
}
