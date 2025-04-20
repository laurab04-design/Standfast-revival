import asyncio
from playwright.async_api import async_playwright
import json

JUDGE_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)"

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

        with open("golden_judges.json", "w") as f:
            json.dump(judges, f, indent=2)

        print(f"[INFO] Extracted {len(judges)} Golden Retriever judges.")

if __name__ == "__main__":
    asyncio.run(fetch_golden_judges())
