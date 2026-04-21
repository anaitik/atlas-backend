# Atlas Backend

Backend API service for Atlas Breakdown.

## Quick Start
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Configure env:
   - Copy `.env.example` to `.env`
   - Fill required values
3. Run API:
   - `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Docker
1. Build:
   - `docker build -t atlas-backend .`
2. Run:
   - `docker run --env-file .env -p 8000:8000 atlas-backend`

## Project Structure
- `app/`: API and business logic
- `tests/`: test suite
- `storage/`: local runtime storage
- `docs/`: backend docs

## Docs
- `docs/README.md`
- `docs/DEPLOYMENT.md`
- `docs/ENVIRONMENT.md`
- `docs/CODEBASE_CONTEXT.md`
- `docs/PRODUCT_CONTEXT.md`
- `docs/FUTURE_DEVELOPMENT.md`
- `docs/ARCHITECTURE.md`
