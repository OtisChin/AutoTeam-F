# Protocol Registration 2FA Design

## Goal

Make the existing “register then enable official 2FA/TOTP” option work for both Python and Go protocol registration without launching a browser.

## Architecture

Add a focused protocol executor beside the existing Security UI executor. It rebuilds a ChatGPT HTTP session from the protocol registration result, performs OpenAI password reauthentication with a fresh email OTP, enrolls a TOTP factor through the first-party ChatGPT MFA endpoints, activates the factor with a locally generated code, and persists the secret through the existing account storage API.

Python and Go registration continue to share the same post-registration manager path. The manager selects the browser executor when a live page exists and the protocol executor when registration produced only session credentials.

## Data Flow

1. Protocol registration returns `accessToken`, `sessionToken` or `cookie_header`, and `device_id` when available.
2. The account record and auth session are saved as they are today.
3. The protocol 2FA executor reconstructs a first-party HTTP session and requests a fresh CSRF token.
4. It starts password reauthentication using the ChatGPT callback `?action=enable&factor=totp`.
5. The existing mailbox adapter obtains a newly issued email OTP. Previously submitted codes are excluded on retry.
6. The executor validates the OTP, follows the callback, and fetches the refreshed ChatGPT access token containing recent password authentication.
7. It calls the official MFA enroll and activation endpoints.
8. The TOTP secret is normalized, used locally to generate the activation code, persisted through `accounts.save_totp_metadata`, and exposed only as masked metadata in the registration result.

## Error Handling

Registration remains successful if 2FA setup fails. The result receives a structured `two_factor` status and reason, while the account retains its saved auth session. Missing reusable session credentials, missing email OTP support, rejected OTPs, malformed enroll responses, and activation failures are reported without logging raw tokens or the full TOTP secret.

## Testing

Unit tests use a deterministic fake HTTP session to verify request order, refreshed-token usage, OTP retry/exclusion, metadata persistence, and failure behavior. Manager integration tests verify that a page-less protocol result selects the protocol executor and that a browser result still selects the existing UI executor.

