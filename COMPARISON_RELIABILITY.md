# Comparison reliability fixes

An incomplete gzip previously raised EOFError outside the artifact rejection
handler and stopped all comparison output. The processor now records the rejected
artifact and continues with independent valid sources. Missing observations remain
UNAVAILABLE. An observer that exits without explicit finalization closes its file
with a failure marker; that file cannot become valid forward evidence.

The public dashboard authenticates comparison writes with RSA-SHA256 signatures.
The publisher includes its public key ID. The server first verifies the configured
key, then may verify another active Google-published key for that same server-pinned
service-account email. No caller-supplied issuer or lookup URL is accepted. Requests
still require a fresh signed timestamp; unknown keys and modified payloads fail.
A key mismatch is a possible cause of the prior GitHub 401; its exact reason was
not available in the previous generic error. New failures report a safe reason code
and public signing key ID without logging credentials or payloads.

Publication retries 429/5xx at most three times, retains signature requirements and
checks explicit storage acknowledgement. A failed publish does not claim success.
--publish-only republishes existing research Sheet rows with no market downloads
or baseline writes. It is exposed as an optional manual EOD-workflow input.

Validation: 13 existing comparison tests, two capture/failure tests, JS signature
and key-rotation tests, TypeScript checks, and production Python publisher against
the local Postman HTTP simulation. Live testing uses the existing account only;
next unattended GitHub completion still requires verification.


The publisher uses the verified canonical origin https://nifty-straddle-lab.samuel-putla.chatgpt.site directly; redirects are not followed for signed writes.
