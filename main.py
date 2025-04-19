from fastapi import FastAPI
from standfast_revival import fetch_archived_urls, scrape_show_results

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
