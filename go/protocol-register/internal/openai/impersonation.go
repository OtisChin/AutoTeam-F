package openai

const defaultTransportUserAgent = "AutoToken-F protocol-registerd/go-http"

type TransportProfile struct {
	Name      string
	UserAgent string
}

func ResolveTransportProfile(_ string) TransportProfile {
	return TransportProfile{
		Name:      "go-http",
		UserAgent: defaultTransportUserAgent,
	}
}
