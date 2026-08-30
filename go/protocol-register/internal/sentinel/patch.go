package sentinel

import (
	"bytes"
	"errors"
	"fmt"
	"regexp"
)

var ErrUnsupportedSDK = errors.New("unsupported Sentinel SDK")

const identifierPattern = `[A-Za-z_$][A-Za-z0-9_$]*`

var (
	globalSDKPattern     = regexp.MustCompile(`\bvar\s+SentinelSDK\s*=`)
	proofInstancePattern = regexp.MustCompile(
		`\bvar\s+(` + identifierPattern + `)\s*=\s*new\s+(` + identifierPattern + `)\s*;`,
	)
	proofWeakMapPattern = regexp.MustCompile(
		`\bconst\s+(` + identifierPattern + `)\s*=\s*new\s+WeakMap\s*;`,
	)
	proofFunctionPattern = regexp.MustCompile(
		`function\s+(` + identifierPattern + `)\s*\((` + identifierPattern + `),(` + identifierPattern + `)\)\s*\{([^{}]{1,320})\}`,
	)
	turnstileSolverPattern = regexp.MustCompile(
		`\.dx\s*\?\s*await\s+(` + identifierPattern + `)\s*\(`,
	)
	publicExportPattern = regexp.MustCompile(
		`,\s*(` + identifierPattern + `)\.token\s*=\s*(` + identifierPattern + `)\s*,\s*(` + identifierPattern + `)\s*\}\s*\(\s*\{\s*\}\s*\)\s*;\s*$`,
	)
)

func PatchSDKSource(source []byte) ([]byte, error) {
	patched := append([]byte(nil), source...)

	globalMatch, err := requireUniqueMatch(patched, globalSDKPattern, "global export")
	if err != nil {
		return nil, err
	}
	patched = replaceMatch(patched, globalMatch, []byte("globalThis.SentinelSDK="))

	instanceMatch, err := requireUniqueMatch(patched, proofInstancePattern, "proof instance")
	if err != nil {
		return nil, err
	}
	instanceName := capture(patched, instanceMatch, 1)
	instanceExport := append(append([]byte(nil), patched[instanceMatch[0]:instanceMatch[1]]...), []byte("globalThis.__debugP="+instanceName+";")...)
	patched = replaceMatch(patched, instanceMatch, instanceExport)

	weakMapMatch, err := requireUniqueMatch(patched, proofWeakMapPattern, "proof WeakMap")
	if err != nil {
		return nil, err
	}
	weakMapName := capture(patched, weakMapMatch, 1)
	regionEnd := min(len(patched), weakMapMatch[0]+1600)
	region := patched[weakMapMatch[0]:regionEnd]
	bindProofName, err := findProofBinding(region, weakMapName)
	if err != nil {
		return nil, err
	}

	turnstileMatch, err := requireUniqueMatch(patched, turnstileSolverPattern, "turnstile solver")
	if err != nil {
		return nil, err
	}
	turnstileSolverName := capture(patched, turnstileMatch, 1)

	exportMatch, err := requireUniqueMatch(patched, publicExportPattern, "public export")
	if err != nil {
		return nil, err
	}
	sdkObjectName := capture(patched, exportMatch, 1)
	tokenFunctionName := capture(patched, exportMatch, 2)
	if sdkObjectName != capture(patched, exportMatch, 3) {
		return nil, unsupportedSDK("public export", 0)
	}
	exports := []byte(fmt.Sprintf(
		",%s.token=%s,%s.__debug_n=%s,%s.__debug_bindProof=%s,%s}({});",
		sdkObjectName,
		tokenFunctionName,
		sdkObjectName,
		turnstileSolverName,
		sdkObjectName,
		bindProofName,
		sdkObjectName,
	))
	return replaceMatch(patched, exportMatch, exports), nil
}

func findProofBinding(region []byte, weakMapName string) (string, error) {
	matches := proofFunctionPattern.FindAllSubmatchIndex(region, -1)
	candidates := make([]string, 0, 1)
	for _, match := range matches {
		firstArgument := capture(region, match, 2)
		secondArgument := capture(region, match, 3)
		body := region[match[8]:match[9]]
		mapAccess, err := regexp.Compile(
			regexp.QuoteMeta(weakMapName) + `\s*(\.set|\[[^]]+\])\s*\(\s*` +
				regexp.QuoteMeta(firstArgument) + `\s*,\s*` + regexp.QuoteMeta(secondArgument) + `\s*\)`,
		)
		if err != nil {
			return "", fmt.Errorf("%w: proof binding pattern", ErrUnsupportedSDK)
		}
		if mapAccess.Match(body) {
			candidates = append(candidates, capture(region, match, 1))
		}
	}
	if len(candidates) != 1 {
		return "", unsupportedSDK("proof binding", len(candidates))
	}
	return candidates[0], nil
}

func requireUniqueMatch(source []byte, pattern *regexp.Regexp, label string) ([]int, error) {
	matches := pattern.FindAllSubmatchIndex(source, -1)
	if len(matches) != 1 {
		return nil, unsupportedSDK(label, len(matches))
	}
	return matches[0], nil
}

func unsupportedSDK(label string, matches int) error {
	return fmt.Errorf("%w: %s matches=%d", ErrUnsupportedSDK, label, matches)
}

func capture(source []byte, match []int, group int) string {
	start := match[group*2]
	end := match[group*2+1]
	if start < 0 || end < start {
		return ""
	}
	return string(source[start:end])
}

func replaceMatch(source []byte, match []int, replacement []byte) []byte {
	var output bytes.Buffer
	output.Grow(len(source) - (match[1] - match[0]) + len(replacement))
	output.Write(source[:match[0]])
	output.Write(replacement)
	output.Write(source[match[1]:])
	return output.Bytes()
}
