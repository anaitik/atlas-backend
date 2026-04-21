# Backend Codebase Context

## Role in system
The backend owns domain logic, data integrity, extraction orchestration, and API contracts consumed by the frontend.

## Important areas
- `app/agentic/extraction/`: extraction workflows and orchestration logic.
- `app/agentic/template/`: template generation logic.
- `app/...` other domain modules: auth, metrics, reporting, and integrations.
- `tests/`: backend test coverage.

## Contribution guidance
- Keep domain rules server-side.
- Add tests for logic-heavy workflow updates.
- Document new env vars in `docs/ENVIRONMENT.md` and `.env.example`.
