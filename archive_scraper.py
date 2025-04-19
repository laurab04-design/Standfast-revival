import requests
from bs4 import BeautifulSoup

# Step 1: Fetch archived URLs from Wayback Machine
def fetch_archived_urls():
    # Wayback CDX API URL to fetch all StandfastData pages
    url = "https://web.archive.org/cdx/search/cdx"
    params = {
        "url": "standfastdata.co.uk/*",
        "output": "json",
        "collapse": "urlkey"
    }

    r = requests.get(url, params=params)
    data = r.json()
    
    # Headers and entries
    headers = data[0]
    entries = data[1:]

    # Extract the original URLs
    urls = [entry[headers.index("original")] for entry in entries]

    # Save the URLs to a text file for later scraping
    with open("standfast_urls.txt", "w") as f:
        for url in urls:
            f.write(url + "\n")

    print(f"Found {len(urls)} archived URLs.")
    return urls


# Step 2: Scrape show results from the archived URLs
def scrape_show_results(urls):
    # Iterate through each archived URL and scrape show results
    for url in urls:
        print(f"Scraping: {url}")
        
        # Get the archived page content
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find and extract show results (adjust based on actual HTML structure)
        show_data = {}

        # Example extraction based on common HTML tags - adapt this part as needed
        show_data['show_name'] = soup.find('h1').text if soup.find('h1') else "No title"
        show_data['date'] = soup.find('span', class_='date').text if soup.find('span', class_='date') else "No date"
        show_data['results'] = []

        # Assume the results are stored in a table with a class 'result-table'
        table = soup.find('table', class_='result-table')
        if table:
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > 1:  # If there are results in the row
                    result = {
                        "breed": cols[0].text.strip(),
                        "class": cols[1].text.strip(),
                        "judge": cols[2].text.strip(),
                        "cc": cols[3].text.strip() if len(cols) > 3 else "N/A",  # CC column
                        "rcc": cols[4].text.strip() if len(cols) > 4 else "N/A"  # RCC column
                    }
                    show_data['results'].append(result)

        # Save the data to a JSON or CSV file (you can adapt this as needed)
        with open("scraped_show_results.json", "a") as f:
            f.write(f"{show_data}\n")
        
        print(f"Scraped data for: {show_data['show_name']}")

# Main execution block
if __name__ == "__main__":
    # Step 1: Fetch archived URLs
    urls = fetch_archived_urls()

    # Step 2: Scrape the results from those URLs
    scrape_show_results(urls)
