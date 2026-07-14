# pplink

`pplink.exe` is the bundled Windows helper that turns a ChatGPT access token into a PayPal authorization URL. Its auditable Go source lives in `src/` and uses the neutral module name `autotoken-pplink`.

## Configuration

The optional JSON configuration has exactly two fields:

```json
{
  "proxy_jp": "socks5://user:password@jp.example:1080",
  "proxy_us": "socks5://user:password@us.example:1080"
}
```

Missing or invalid configuration does not block flag-only use. A non-empty proxy flag overrides the corresponding JSON value; an omitted flag keeps the configured value.

## Modes

| Mode | Checkout | Entity | Routing |
| --- | --- | --- | --- |
| `us` (default) | US / USD / hosted | `openai_llc` | ChatGPT checkout, warmup, approval, and geo use JP; Stripe PM, confirm, poll, and redirects use US |
| `eu` | FR / EUR / custom | `openai_ie` | All requests use JP |
| `br` | BR / BRL / custom | `openai_ie` | All requests use JP |

For `eu` and `br`, a configured US proxy is deliberately ignored. On every retry, JP and US sticky SIDs are rotated independently from their original proxy strings.

## CLI

The executable exposes nine flags:

- `-config`: JSON configuration path, default `config.json`.
- `-entity`: explicit `processor_entity` override.
- `-max-retry`: maximum total attempts; `0` retries indefinitely.
- `-mode`: `us`, `eu`, or `br`; default `us`.
- `-proxy`: JP proxy override.
- `-retry-wait`: seconds between attempts.
- `-stop-at-pm-redirects`: return the Stripe redirect without following it to PayPal.
- `-token`: ChatGPT access token. A positional token and `-` stdin input are also supported.
- `-us-proxy`: US Stripe proxy override for `us` mode.

Help is written to stderr and exits with code `0`. Business logs are also written to stderr. Success exits with code `0` and includes:

```text
Authorize URL: https://pm-redirects.stripe.com/authorize/...
```

Business-input failures and exhausted retries exit with code `1`.
Flag syntax errors exit with code `2`.

## Test and build

Run the source tests:

```powershell
Push-Location .\vendor\pplink\src
go test ./... -count=1
Pop-Location
```

Build the committed Windows executable:

```powershell
.\vendor\pplink\build.ps1
```

The build pins `CGO_ENABLED=0`, `GOOS=windows`, `GOARCH=amd64`, `GOAMD64=v1`, disables workspaces and VCS stamping, uses readonly modules and trim paths, clears the Go build ID, and writes `vendor/pplink/pplink.exe`. Repeated builds from the same source and Go toolchain must produce the same SHA-256 hash.
