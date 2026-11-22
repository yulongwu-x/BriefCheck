# Add export audit logging without weakening access control

Exports must record who triggered the download while preserving existing access control.

## Acceptance criteria

- [ ] Non-admin callers are still rejected with an authorization error.
- [ ] Each export logs a `report_export` audit event with the caller's `user.id` and `report_id`.
