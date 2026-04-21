# Backend Environment Variables

Use `.env.example` as the baseline template.

## Common variables
- `ENVIRONMENT`: e.g. `development`, `staging`, `production`
- `DEBUG`: `true` or `false`
- `LOG_LEVEL`: e.g. `INFO`, `DEBUG`
- `MONGODB_CONNECTION_STRING`: database connection URI
- `MONGODB_DATABASE_NAME`: database name
- `JWT_SECRET_KEY`: signing key for auth tokens
- `DEEPSEEK_API_KEY`: LLM API key

## Storage and async
- `STORAGE_BACKEND`
- `LOCAL_STORAGE_PATH`
- `TASK_BACKEND`

## Blockchain (optional)
- `BLOCKCHAIN_ENABLED`
- `POLYGON_RPC_URL`
- `POLYGON_CHAIN_ID`
- `HASHSTORE_CONTRACT_ADDRESS`
- `HASHCHAIN_PRIVATE_KEY`
