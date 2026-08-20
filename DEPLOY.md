# Deploying the BRO Risk Oracle demonstrator to Render

## The problem you hit
Your build log showed:
    #8 [3/4] COPY . .            DONE 0.0s
    #9 Installing from: <none found>
`COPY . .` finishing instantly and finding no `requirements.txt` means **the build
context was empty** — only the Dockerfile reached Render. The application files were
never committed to the repository Render builds from. The Dockerfile cannot create
files that are not in the context, so this must be fixed at the repo level.

## Fix — put ALL files into the repo, then deploy

1. Unzip this package. Open a terminal **inside the unzipped folder**. Confirm you can
   see the project files side by side:
       ls
   You should see: `Dockerfile  requirements.txt  bro_demo.db  app/  render.yaml  ...`
   If you only see a Dockerfile, you are in the wrong folder.

2. Put everything into a Git repo (the `.gitignore` is already set so `bro_demo.db`
   IS included and only throwaway files are skipped):
       git init
       git add -A
       git commit -m "BRO Risk Oracle demonstrator"
       git branch -M main
       git remote add origin <YOUR_GITHUB_REPO_URL>
       git push -u origin main

3. **Verify the files are actually in the repo before deploying:**
       git ls-files | wc -l        # should be ~100+ files, NOT 1
       git ls-files | grep -E "requirements.txt|app/bro_app.py|bro_demo.db"
   All three must be listed. If only the Dockerfile is listed, step 2 didn't capture
   the files — make sure you ran the commands inside the unzipped project folder.

4. On Render: New → Web Service → connect this repo → Runtime: **Docker**.
   - If the project files are at the repo ROOT, leave Root Directory blank.
   - If you committed them inside a subfolder, set **Root Directory** to that folder.
   Deploy.

## Confirming success in the build log
A correct build now prints the context contents, e.g.:
    === build context contents (/app) ===
    ... requirements.txt, app, bro_demo.db ...
    Installing from: ./requirements.txt
If instead you see "BUILD CONTEXT IS EMPTY", the files still aren't in the repo —
return to step 2/3.

## Sign in
Once live, open the service URL and sign in with **admin / admin**.
The demonstrator (100 vendors, 275 engagements, 5 critical vendors, 7 critical
engagements) is already loaded via `BRO_DB_URL=sqlite:///bro_demo.db`.

## Local check (optional, needs Docker)
From inside the project folder:
    docker build -t bro .
    docker run -p 8000:8000 bro
Open http://localhost:8000  (admin / admin).

## Simplest path: native Python (no Docker)

The included `render.yaml` now uses Render's native Python runtime, which avoids the
Docker build-context problem altogether. After pushing the repo (steps above), choose
**New → Blueprint** in Render and point it at the repo — it will read `render.yaml`,
run `pip install -r requirements.txt`, and start with
`uvicorn app.bro_app:app --host 0.0.0.0 --port $PORT`. Sign in with `admin` / `admin`.

To use the live model, either set `ANTHROPIC_API_KEY` as an environment variable on the
Render service, or add the key in the app's **Settings → AI provider** screen.
