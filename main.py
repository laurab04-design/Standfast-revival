from fossedata_core import upload_to_drive
from fastapi import FastAPI
from standfast_revival import fetch_archived_urls, scrape_show_results
from standfast_revival.golden_judges_scraper import fetch_golden_judges
import asyncio

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/scrape")
def scrape():
    urls = fetch_archived_urls()
    scrape_show_results(urls)
    return {"message": "Scraping completed!"}

@app.get("/run")
def run():
    urls = fetch_archived_urls()
    scrape_show_results(urls)
    return {"message": "Scrape run complete"}

@app.get("/judges")
def scrape_judges():
    asyncio.run(fetch_golden_judges())
    upload_to_drive("golden_judges.json", "application/json")
    upload_to_drive("golden_judges.csv", "text/csv")
    return {"message": "Golden Retriever judge list updated and uploaded!"}
