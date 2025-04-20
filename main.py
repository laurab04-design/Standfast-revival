from fastapi import FastAPI
import json
import asyncio
from playwright.async_api import async_playwright

# FastAPI application
app = FastAPI()

# ———————————————————————————————————————————
# Judge scraping logic directly in main.py
# ———————————————————————————————————————————
JUDGE_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)"

# Function to fetch Golden Retriever judges
async def fetch_golden_judges():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(JUDGE_URL, wait_until="networkidle")

        await page.wait_for_selector(".search-judge__item", timeout=10000)

        items = await page.query_selector_all(".search-judge__item")
        judges = []

        for item in items:
            name = await item.query_selector(".search-judge__title")
            region = await item.query_selector(".search-judge__subtitle")
            judges.append({
                "name": (await name.inner_text()).strip() if name else None,
                "location": (await region.inner_text()).strip() if region else None,
            })

        await browser.close()

        # Save results to file
        with open("golden_judges.json", "w") as f:
            json.dump(judges, f, indent=2)

        print(f"[INFO] Extracted {len(judges)} Golden Retriever judges.")

# Main page route
@app.get("/")
def root():
    return {"message": "Welcome to the Standfast Revival API"}

# Route to trigger scraping of Golden Retriever judges
@app.get("/run")
async def run():
    # Call the judge scraping function here
    await fetch_golden_judges()  # Run the function
    return {"message": "Scrape run complete"}
