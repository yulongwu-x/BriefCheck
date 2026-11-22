# Expected Review: Multi-Hunk Diff, Compound Split & Stale Test Log

This fixture exercises:
1. Splitting a compound acceptance requirement into independent rows.
2. Tracking line numbers across multiple hunks in the same file.
3. Flagging a test log whose revision does not match the reviewed diff commit.

| Acceptance requirement | Judgment | Evidence | Follow-up |
| --- | --- | --- | --- |
| Retry HTTP 503 responses up to 3 times with exponential backoff. | Contradicted | `client/http.py:6–7` sets `MAX_RETRIES = 3` and `BASE_DELAY = 0.5`, but `client/http.py:45–50` iterates `range(MAX_RETRIES - 1)`, performing at most 2 retries (delays `0.5`, `1.0`) instead of 3. `tests/test_http.py:17–19` also asserts only two delays. | Change the retry loop to `range(MAX_RETRIES)` and update the test to expect 3 retries (`[0.5, 1.0, 2.0]`). |
| Never retry HTTP 400 responses. | Supported | `client/http.py:5` restricts `RETRYABLE_STATUSES = {503}` and `client/http.py:46–47` returns immediately when `status_code` is not retryable. `tests/test_http.py:12–15` defines a 400 test, but `test-run.log` is from an older revision (`111111122222`) so execution on the reviewed commit is unverified. | Re-run `tests/test_http.py` on commit `b2c3d4e5f6a7`. |
| Add unit test coverage for the retry policy. | Supported | `tests/test_http.py:6–19` adds `RetryPolicyTests.test_retries_503_and_skips_400` covering both 400 and 503 paths (execution on the reviewed commit remains unverified because `test-run.log` does not match revision `b2c3d4e5f6a7`). | Re-run unit tests on commit `b2c3d4e5f6a7` after fixing the retry count. |
