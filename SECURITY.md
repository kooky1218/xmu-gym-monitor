# Security

## Sensitive data

This project must never contain or publish:

- WeChat Cookie or Token values;
- passwords;
- Bark device keys;
- browser profiles;
- authentication state files;
- runtime SQLite databases;
- application logs containing user activity.

Bark keys are stored through Windows Credential Manager and are intentionally
excluded from this repository.

## Reporting

If you believe sensitive information was committed, rotate the affected
credential immediately and use GitHub's secret-removal guidance. Do not open a
public issue containing the secret.
