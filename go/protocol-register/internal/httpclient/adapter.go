package httpclient

import (
	"errors"
	"net/http"
	"strings"

	"autoteam-f/protocol-register/internal/fingerprint"

	fhttp "github.com/bogdanfinn/fhttp"
)

var errNilInnerResponse = errors.New("tls-client returned a nil response")

type fhttpDoer interface {
	Do(*fhttp.Request) (*fhttp.Response, error)
}

type roundTripper struct {
	doer    fhttpDoer
	profile fingerprint.Profile
}

func newRoundTripper(doer fhttpDoer, profile fingerprint.Profile) *roundTripper {
	return &roundTripper{doer: doer, profile: profile}
}

func (t *roundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	innerRequest, err := toFHTTPRequest(req, t.profile)
	if err != nil {
		return nil, err
	}
	innerResponse, err := t.doer.Do(innerRequest)
	if err != nil {
		if innerResponse != nil && innerResponse.Body != nil {
			_ = innerResponse.Body.Close()
		}
		return nil, err
	}
	if innerResponse == nil {
		return nil, errNilInnerResponse
	}
	return toHTTPResponse(innerResponse, req), nil
}

func (t *roundTripper) CloseIdleConnections() {
	if closer, ok := t.doer.(interface{ CloseIdleConnections() }); ok {
		closer.CloseIdleConnections()
	}
}

func toFHTTPRequest(req *http.Request, profile fingerprint.Profile) (*fhttp.Request, error) {
	inner, err := fhttp.NewRequestWithContext(req.Context(), req.Method, req.URL.String(), req.Body)
	if err != nil {
		return nil, err
	}
	urlCopy := *req.URL
	inner.URL = &urlCopy
	inner.Proto = req.Proto
	inner.ProtoMajor = req.ProtoMajor
	inner.ProtoMinor = req.ProtoMinor
	inner.Header = toFHTTPHeader(req.Header)
	inner.Header[fhttp.HeaderOrderKey] = append([]string(nil), profile.HeaderOrder...)
	inner.Header[fhttp.PHeaderOrderKey] = append([]string(nil), profile.PseudoHeaderOrder...)
	inner.GetBody = req.GetBody
	inner.ContentLength = req.ContentLength
	inner.TransferEncoding = append([]string(nil), req.TransferEncoding...)
	inner.Close = req.Close
	inner.Host = req.Host
	inner.Trailer = fhttp.Header(req.Trailer)
	inner.Cancel = req.Cancel
	return inner, nil
}

func toFHTTPHeader(source http.Header) fhttp.Header {
	if source == nil {
		return make(fhttp.Header)
	}
	cloned := source.Clone()
	return fhttp.Header(cloned)
}

func toHTTPResponse(source *fhttp.Response, request *http.Request) *http.Response {
	return &http.Response{
		Status:           source.Status,
		StatusCode:       source.StatusCode,
		Proto:            source.Proto,
		ProtoMajor:       source.ProtoMajor,
		ProtoMinor:       source.ProtoMinor,
		Header:           toHTTPHeader(source.Header),
		Body:             source.Body,
		ContentLength:    source.ContentLength,
		TransferEncoding: append([]string(nil), source.TransferEncoding...),
		Close:            source.Close,
		Uncompressed:     source.Uncompressed,
		Trailer:          http.Header(source.Trailer),
		Request:          request,
	}
}

func toHTTPHeader(source fhttp.Header) http.Header {
	if source == nil {
		return make(http.Header)
	}
	converted := make(http.Header, len(source))
	for name, values := range source {
		if strings.EqualFold(name, fhttp.HeaderOrderKey) || strings.EqualFold(name, fhttp.PHeaderOrderKey) {
			continue
		}
		converted[name] = append([]string(nil), values...)
	}
	return converted
}
