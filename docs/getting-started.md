# Start and use RepoMedic

## Start

Requirements: OrbStack or Docker Desktop.

```bash
git clone git@github.com:kyc-software/repo-medic.git
cd repo-medic
cp .env.example .env
docker compose up --build
```

Open <http://localhost:3000>.

## Use

1. Enter an issue title and description.
2. Select **Run triage**.
3. Watch prediction, evidence, and resolution appear.
4. If RepoMedic requests review, approve, edit, or reject its draft.

Useful pages:

- API documentation: <http://localhost:8000/docs>
- MLflow traces: <http://localhost:5001>

Demo mode makes no GitHub or OpenAI API calls.

## Stop

```bash
docker compose down
```

Start again without rebuilding:

```bash
docker compose up
```
