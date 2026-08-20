"""Run the unified BRO Risk Oracle API:  python run.py
Then open http://127.0.0.1:8000/docs for the interactive API.
Runs offline: SQLite + deterministic-local analysers, no API key needed.
Set BRO_DB_URL to a Postgres URL for production persistence.
Default login: admin / admin"""
import uvicorn
from app.bro_app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
