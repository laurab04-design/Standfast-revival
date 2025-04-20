from fastapi import FastAPI
from golden_judges_scraper import fetch_golden_judges
import asyncio

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/judges")
def scrape_judges():
    asyncio.run(fetch_golden_judges())
    upload_to_drive("golden_judges.json", "application/json")
    upload_to_drive("golden_judges.csv", "text/csv")
    return {"message": "Golden Retriever judge list updated and uploaded!"}
