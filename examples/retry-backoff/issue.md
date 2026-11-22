# Retry transient 503 errors with exponential backoff

## Acceptance criteria

- [ ] Retry HTTP 503 responses up to 3 times with exponential backoff, and never retry HTTP 400 responses.
- [ ] Add unit test coverage for the retry policy.
