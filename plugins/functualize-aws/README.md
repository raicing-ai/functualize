# functualize-aws

AWS Secrets Manager (`aws-sm`) and SSM Parameter Store (`aws-ssm`) providers
for functualize's remote configuration layer.

```toml
[database]
password = "aws-sm://prod/db-password"
replica  = "aws-sm://prod/db?account=123456789012&region=eu-west-1"
api_url  = "aws-ssm:///prod/api-url"
token    = "aws-ssm:///prod/api-token?role=arn:aws:iam::123456789012:role/Deploy"
```

Values are fetched by `func builtin vault sync` and stored in the project's
encrypted local vault. Job execution reads the vault, never the network
(ADR-016).

## Override keys

| Key | Meaning |
|---|---|
| `profile` | Named profile from the shared AWS config; replaces the ambient chain for this value. |
| `role` | IAM role ARN to assume. Composes with `profile`, which supplies the source identity. |
| `region` | Region the client is built for. |
| `account` | **Assertion**, not a selector: the resolved caller identity must match, or the fetch fails. |

An unknown key is an error, not a no-op — `?porfile=prod` must not resolve
quietly under the default identity.

Temporary credentials from `role` live in memory for the life of the process.
They are never written to disk and never enter the vault, which holds resolved
values, not credentials.

## Testing against a local emulator

Set `AWS_ENDPOINT_URL` and any LocalStack-compatible emulator works:

```
docker run -d --name floci -p 4566:4566 floci/floci:latest
AWS_ENDPOINT_URL=http://localhost:4566 uv run pytest plugins/functualize-aws
```

Without it the integration tests skip.
