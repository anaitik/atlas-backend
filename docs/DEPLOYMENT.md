# Backend Deployment

## Local run
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Configure environment:
   - Copy `.env.example` to `.env` and fill values.
3. Start API:
   - `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Docker run
1. Build image:
   - `docker build -t atlas-backend .`
2. Start container:
   - `docker run --env-file .env -p 8000:8000 atlas-backend`

## Notes
- Container stores runtime files in `/app/storage`.
- Ensure database and external service credentials are provided in `.env`.
