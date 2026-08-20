FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Copy whatever the build context contains.
COPY . .

# Install dependencies, with a clear diagnostic if the build context is empty.
# If you see "BUILD CONTEXT IS EMPTY" below, the app files were not included in
# the repo/context Render is building from (only the Dockerfile reached the build).
RUN set -e; \
    echo "=== build context contents (/app) ==="; ls -la; echo "======================================"; \
    REQ="$(find . -name requirements.txt | head -1)"; \
    if [ -z "$REQ" ]; then \
      echo "############################################################"; \
      echo "ERROR: BUILD CONTEXT IS EMPTY — no requirements.txt found."; \
      echo "Only the Dockerfile reached the build. The application files"; \
      echo "(app/, requirements.txt, bro_demo.db) are NOT in the context."; \
      echo "FIX: commit ALL project files to the repo Render builds from,"; \
      echo "or set the service Root Directory to the project folder."; \
      echo "############################################################"; \
      exit 1; \
    fi; \
    echo "Installing from: $REQ"; \
    pip install --upgrade pip && pip install -r "$REQ"

# Seeded demonstrator DB by default; override BRO_DB_URL (e.g. Postgres) for prod.
ENV BRO_DB_URL=sqlite:///bro_demo.db
ENV PORT=8000
EXPOSE 8000

# Locate the app package at runtime (tolerates nesting) and launch uvicorn from
# its parent directory so `app.bro_app:app` imports and bro_demo.db resolves.
CMD ["sh","-c","APP_DIR=\"$(dirname \"$(find . -path '*/app/bro_app.py' | head -1)\")\"; cd \"$APP_DIR/..\"; echo \"Launching from $(pwd)\"; exec uvicorn app.bro_app:app --host 0.0.0.0 --port ${PORT}"]
