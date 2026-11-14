# GLOBAL STORE Docker deployment

Nginx serves the storefront and proxies every current API route to the single
FastAPI process. MySQL, Redis and Chroma each use a new named volume. MySQL/Redis
and the app have no published host ports; the storefront binds 127.0.0.1:8080.
The existing local services and their data are independent and remain available.

Use a private env file outside the repository (see `.env.example`). Never print
`docker compose config` with resolved secrets; use `config --quiet` instead.
`constraints-py312.txt` keeps the working project's core package versions;
the same PyTorch version uses CPU wheels. `requirements.txt` is unchanged.
The existing Hugging Face cache is bind-mounted read-only and models load offline.

## First deployment: migrate before exposing the app

1. Record Git/file hashes and source MySQL/Chroma/Redis logical fingerprints.
2. Make a consistent full `mysqldump --single-transaction` backup of the project
   database, including all tables, indexes, routines, triggers and events.
3. Export Chroma IDs/documents/metadata/embeddings using the existing collection.
   Preserve its original FLOAT32 insertion vectors as well: cosine storage can
   normalize SDK-returned vectors again when imported. Do not copy live HNSW files.
4. Export Redis key types/TTLs/DUMP data. Preserve the document Bloom bitmaps,
   Bloom metadata and product cache version. Do not import active locks, expired
   cache data or unrelated legacy test keys. Never clear the source Redis.
5. Verify backup hashes, then build and start only the NEW MySQL/Redis services.
6. Require an empty target schema, import the full SQL dump once, then run the
   guarded one-time imports using the new app image and a read-only backup mount:

```powershell
docker compose --env-file $EnvFile -p $Project run --rm --no-deps -T -v "${BackupDirectory}:/migration:ro" app python -m deployment.data_transfer import-redis /migration
docker compose --env-file $EnvFile -p $Project run --rm --no-deps -T -v "${BackupDirectory}:/migration:ro" app python -m deployment.data_transfer import-chroma /migration
docker compose --env-file $EnvFile -p $Project run --rm --no-deps -T -v "${BackupDirectory}:/migration:ro" app python -m deployment.data_transfer verify /migration
```

The helper refuses host/source connections and refuses to overwrite collections
or Redis keys. Its expected backup files are recorded in the deployment report.
On any mismatch, preserve the target and backups; do not retry writes or switch
traffic. Only after verification create `migration_verified.json` next to the
private env file with `project` and `status: PASS`, then start the app and Nginx.
The supplied report records this deployment's exact paths and migration results.

## Existing verified deployment

Run from the project directory, substituting the private env path in the report:

```powershell
.\deployment\manage.ps1 -EnvFile $EnvFile -Action status
.\deployment\manage.ps1 -EnvFile $EnvFile -Action start
.\deployment\manage.ps1 -EnvFile $EnvFile -Action stop
```

`stop` preserves every volume. Do not use `down -v`, any prune command or an old
Compose project name. No upload/index update is necessary on restart.

Storefront: http://127.0.0.1:8080/

API documentation: http://127.0.0.1:8080/docs

Nginx returns the deployment runtime configuration at
`/static/js/runtime-config.js`; all API requests then use the same origin.
Local static hosting keeps the original 127.0.0.1:8001 fallback, including file
previews. Chat JSON, USER_ID, text/plain/getReader streaming and UI logic are
unchanged. Normal GET `/health` proxies the existing backend health route;
Nginx-only `/healthz` is a separate readiness check.
