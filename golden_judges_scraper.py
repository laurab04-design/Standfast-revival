import asyncio
from playwright.async_api import async_playwright
import json
import csv
import os

JUDGE_LIST_URL = "https://www.thekennelclub.org.uk/search/find-a-judge/?Breed=Retriever+(Golden)"
BASE_URL = "https://www.thekennelclub.org.uk"

async def fetch_golden_judges():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("[INFO] Navigating to judge list...")
        await page.goto(JUDGE_LIST_URL, wait_until="networkidle")
        await page.wait_for_selector(".search-judge__item", timeout=10000)

        items = await page.query_selector_all(".search-judge__item")
        judges = []

        for item in items:
            name_el = await item.query_selector(".search-judge__title")
            region_el = await item.query_selector(".search-judge__subtitle")
            link_el = await item.query_selector("a")

            name = (await name_el.inner_text()).strip() if name_el else None
            location = (await region_el.inner_text()).strip() if region_el else None
            href = await link_el.get_attribute("href") if link_el else None
            profile_url = BASE_URL + href if href else None

            print(f"[INFO] Judge: {name} ({location}) — {profile_url}")
            judge_data = {
                "name": name,
                "location": location,
                "profile_url": profile_url,
                "breeds": []
            }

            if profile_url:
                judge_page = await context.new_page()
                try:
                    await judge_page.goto(profile_url, wait_until="networkidle")
                    await judge_page.wait_for_selector(".judging-sections__section", timeout=5000)
                    breed_items = await judge_page.query_selector_all(".judging-sections__section li")
                    for li in breed_items:
                        txt = await li.inner_text()
                        if txt and "level" not in txt.lower():
                            judge_data["breeds"].append(txt.strip())
                except Exception as e:
                    print(f"[WARN] Failed to parse {profile_url}: {e}")
                await judge_page.close()

            judges.append(judge_data)

        await browser.close()

        # Write JSON
        with open("golden_judges.json", "w") as jf:
            json.dump(judges, jf, indent=2)

        # Write CSV
        with open("golden_judges.csv", "w", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["Name", "Location", "Profile URL", "Breeds"])
            for j in judges:
                writer.writerow([
                    j["name"], j["location"], j["profile_url"], "; ".join(j["breeds"])
                ])

        print(f"[INFO] Saved {len(judges)} judges to golden_judges.json and golden_judges.csv")
