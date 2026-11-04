# Sheets quota isolation

Rolling collectors read all twelve managed summary/log ranges in one startup batch.
Header validation and current-date duplicate detection use that same snapshot.
The concurrency-protected collector owns these twelve tabs during its session;
do not insert, sort, delete or manually append rows while it runs.

Checkpoints reserve stable cell addresses and use one deterministic batch update.
Retries after uncertain responses overwrite the same event rows. Dashboard payloads
reuse the cache, eliminating twelve Sheet reads per checkpoint. Local state is
atomically saved before network calls. Optional measurement failures do not stop
quote processing. Startup still fails closed if duplicate checks cannot finish.

The transport retries GET and deterministic values:batchUpdate on 429/5xx with
bounded exponential jitter. It never blindly retries non-idempotent append calls.
Other collectors share Google quotas; this reduces rolling traffic, not increases
Google limits. Concurrent manual Sheet edits are outside the single-writer contract.

Postman fixture models read 429 then 503 then success, deterministic write 429
then success, and append 429 without retry. These are synthetic HTTP failures.
Unit checks cover no extra read, same-row close updates, uncertain-write retries,
and current-day duplicate refusal. No live broker or Sheet writes are test targets.

