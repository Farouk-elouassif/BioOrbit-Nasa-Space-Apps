# Local backend + PostgreSQL

From the repository root, run:

```bash
docker compose up --build
```

Compose reads the root `.env` for configuration. A generated `.env` is provided locally and ignored by Git and Docker builds. `.env.example` documents the required variables without real credentials. For a fresh checkout, copy the example to `.env` and replace its secret placeholders before starting.

Services:

- `db`: PostgreSQL 17, persistent `postgres_data` volume, internal port 5432. No host database port is published.
- `backend`: built from the root Dockerfile, runs migrations after PostgreSQL is healthy, then starts Django's foreground development server at http://localhost:8000. The existing Django admin route is http://localhost:8000/admin/; no application API is implemented yet.

The backend is a development service, not a production deployment. Source code is copied into the image: rebuild after backend changes. `POSTGRES_HOST=db` is the Compose service name. Django receives variables from Compose; it does not load `.env` automatically outside Docker.

Validation commands to run yourself:

```bash
docker compose config --quiet
docker compose exec backend python manage.py check
docker compose exec backend python manage.py showmigrations
```

`docker compose down` stops the services and preserves the database volume. Changing PostgreSQL credentials in `.env` does not update an already-initialized database; coordinate credential changes with the existing database rather than deleting its volume.
