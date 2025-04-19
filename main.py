from fastapi import FastAPI
from archive_scraper import fetch_archived_urls, scrape_show_results  # Import your scraping functions

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

@app.get("/scrape")
def scrape():
    # Step 1: Fetch archived URLs
    urls = fetch_archived_urls()

    # Step 2: Scrape the results from those URLs
    scrape_show_results(urls)
    
    return {"message": "Scraping completed!"}
