import asyncio
from playwright.async_api import async_playwright
import csv
import os
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import json # Added json import

async def scrape_property_links(agent_id):
    """
    Scrapes property links for a given agent ID and saves them to a CSV file.
    Returns the sanitized agent name used for the filename.
    """
    url = f'https://www.sothebysrealty.com/eng/sales/int/{agent_id}'

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Navigating to {url}")
        await page.goto(url, wait_until='networkidle')

        # Find the element with the data-item-name attribute to get the agent name dynamically.
        agent_name_element = await page.query_selector('[data-item-name]')
        agent_name = "unknown_agent" # Default name

        if agent_name_element:
            agent_name = await agent_name_element.get_attribute('data-item-name')
            if agent_name:
                agent_name = agent_name.strip()
                print(f"Scraped agent name: {agent_name}")
            else:
                agent_name = "unknown_agent"
                print("Found element with data-item-name attribute but it was empty. Using default name.")
        else:
            agent_name = "unknown_agent"
            print("Could not find element with data-item-name attribute. Using default name.")

        print("Scrolling to load all properties...")
        previous_height = -1
        while True:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == previous_height:
                break
            previous_height = current_height
        print("Finished scrolling.")

        print("Extracting property links and names...")
        property_data = await page.evaluate('''
            () => {
                const properties = [];
                const items = document.querySelectorAll('li.Search-results__item');
                items.forEach(item => {
                    const linkElement = item.querySelector('a.Results-card');
                    const nameElement = item.querySelector('.Results-card__body-address-wrapper h3.Results-card__body-address');
                    const fullAddressElement = item.querySelector('.Results-card__body-address-wrapper');

                    if (linkElement && nameElement && fullAddressElement) {
                        const name = nameElement.textContent.trim();
                        const fullText = fullAddressElement.textContent.trim();
                        let location = '';

                        if (fullText.startsWith(name)) {
                            location = fullText.substring(name.length).trim();
                            while (location.startsWith(',') || location.startsWith(' ')) {
                                location = location.substring(1).trim();
                            }
                        } else {
                            location = fullText;
                        }

                        properties.push({
                            name: name,
                            location: location,
                            link: linkElement.href
                        });
                    } else if (linkElement && nameElement) {
                         properties.push({
                            name: nameElement.textContent.trim(),
                            location: '',
                            link: linkElement.href
                        });
                    }
                });
                return properties;
            }
        ''')

        sanitized_agent_name = "".join(c for c in agent_name if c.isalnum() or c in (' ', '_')).rstrip()
        sanitized_agent_name = sanitized_agent_name.replace(' ', '_')
        if not sanitized_agent_name:
            sanitized_agent_name = "property"

        output_path = f'{sanitized_agent_name}_links.csv'

        print(f"Saving {len(property_data)} links to {output_path}")
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['name', 'location', 'link']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for data in property_data:
                writer.writerow(data)

        print("Finished scraping property links.")

        await browser.close()

        return sanitized_agent_name, agent_name

async def scrape_details_from_links(original_agent_name, input_csv_path, output_csv_path):
    """
    Scrapes property details from links in an input CSV and saves them to an output CSV.
    """
    property_links = []

    if not os.path.exists(input_csv_path):
        print(f"Error: Input CSV file not found at {input_csv_path}")
        return

    with open(input_csv_path, mode='r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            link_key = None
            if 'link' in row and row['link'].startswith('http'):
                link_key = 'link'
            elif 'Property Link' in row and row['Property Link'].startswith('http'):
                link_key = 'Property Link'

            if link_key:
                property_links.append({
                    'name': row.get('name', row.get('Property Name', 'N/A')),
                    'link': row[link_key]
                })
            else:
                print(f"Skipping row due to missing or invalid link: {row}")

    if not property_links:
        print('No property links found in the input CSV.')
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        with open(output_csv_path, 'w', newline='', encoding='utf-8') as outfile:
            fieldnames = ['Property ID', 'MLS#', 'Status', 'Agent Name', 'Marketed By', 'Category', 'Property Type', 'Style', 'Property Name', 'Property Link', 'Price', 'Year Built', 'Bedrooms', 'Full Bathrooms', 'Partial Baths', 'Total Sqft', 'Lot Size', 'Lot Size Unit', 'Parking', 'Cooling', 'Interior Features', 'Additional Features', 'Latitude', 'Longitude', 'Property Description Title', 'Property Description'] + [f'Image Link {i+1}' for i in range(60)]
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()

            print(f"Starting to scrape details for {len(property_links)} properties.")

            for property_data in property_links:
                link = property_data['link']
                name = property_data['name']
                print(f"Navigating to {link}")
                try:
                    await page.goto(link, wait_until='domcontentloaded')

                    await page.wait_for_selector('.c-ldp-hero-carousel__wrapper', state='visible', timeout=30000)

                    next_button = await page.query_selector('.c-ldp-hero-carousel__nav-btn--next')
                    pagination_span = await page.query_selector('.c-ldp-hero-carousel__pagination')

                    imageLinks = []
                    total_images = 0

                    if pagination_span:
                        pagination_text = await pagination_span.inner_text()
                        match = re.search(r'(\d+)/(\d+)', pagination_text)
                        if match:
                            current_image_str, total_images_str = match.groups()
                            total_images = int(total_images_str)

                            first_image_element = await page.query_selector('.c-ldp-hero-slide--current .c-ldp-hero-slide__image')
                            if first_image_element:
                                src = await first_image_element.get_attribute('src')
                                if src and src.startswith('http'):
                                    try:
                                        parsed_url = urlparse(src)
                                        query_params = parse_qs(parsed_url.query)
                                        imageUrlParam = query_params.get('url', [None])[0]
                                        if imageUrlParam:
                                            imageLinks.append(imageUrlParam)
                                        else:
                                            imageLinks.append(src.split('&')[0])
                                    except Exception as url_e:
                                        print(f"Error processing initial image URL {src}: {url_e}")
                                        imageLinks.append(src.split('&')[0])

                            if next_button:
                                for i in range(1, total_images):
                                    await next_button.click()
                                    await page.wait_for_function(f"document.querySelector('.c-ldp-hero-carousel__pagination').innerText.includes('{i + 1}/{total_images}')", timeout=10000)
                                    await asyncio.sleep(0.5)

                                    current_image_element = await page.query_selector('.c-ldp-hero-slide--current .c-ldp-hero-slide__image')
                                    if current_image_element:
                                        src = await current_image_element.get_attribute('src')
                                        if src and src.startswith('http'):
                                            try:
                                                parsed_url = urlparse(src)
                                                query_params = parse_qs(parsed_url.query)
                                                imageUrlParam = query_params.get('url', [None])[0]
                                                if imageUrlParam:
                                                    imageLinks.append(imageUrlParam)
                                                else:
                                                    imageLinks.append(src.split('&')[0])
                                            except Exception as url_e:
                                                print(f"Error processing image URL after click {src}: {url_e}")
                                                imageLinks.append(src.split('&')[0])

                            print(f"Finished clicking through {len(imageLinks)} images for {name}.")
                        else:
                            print("Could not parse total images from pagination text.")
                    else:
                        print("Pagination element not found. Cannot determine total images.")
                        image_elements = await page.query_selector_all('.c-ldp-hero-slide__image')
                        imageLinks = [img.get_attribute('src') for img in image_elements if img.get_attribute('src') and img.get_attribute('src').startswith('http')]
                        cleanedImageLinks = []
                        for src in imageLinks:
                             try:
                                parsed_url = urlparse(src)
                                query_params = parse_qs(parsed_url.query)
                                imageUrlParam = query_params.get('url', [None])[0]
                                if imageUrlParam:
                                    cleanedImageLinks.append(imageUrlParam)
                                else:
                                    cleanedImageLinks.append(src.split('&')[0])
                             except Exception as url_e:
                                print(f"Error processing fallback image URL {src}: {url_e}")
                                cleanedImageLinks.append(src.split('&')[0])
                        imageLinks = cleanedImageLinks
                        print(f"Found {len(imageLinks)} images using fallback selector for {name}.")

                    html_content = await page.content()
                    soup = BeautifulSoup(html_content, 'html.parser')

                    property_id = ''
                    mls_number = ''
                    price = ''
                    bedrooms = ''
                    bathrooms = ''
                    partial_baths = ''
                    total_sqft = ''
                    lot_size_unit = ''
                    lot_size = ''
                    property_type = ''
                    status = ''
                    marketed_by = ''
                    style = ''
                    cooling = ''
                    interior_features = ''
                    additional_features = ''
                    latitude = ''
                    longitude = ''
                    amenities_features = ''
                    listing_details = ''
                    property_description = ''
                    property_description_title = '' # Added property description title variable
                    year_built = ''
                    parking = '' # Added parking variable

                    column_divs = soup.select('.m-property-details-listing-info__column')
                    for column_div in column_divs:
                        column_title_element = column_div.select_one('.m-property-details-listing-info__column-title')
                        if column_title_element:
                            column_title = column_title_element.get_text(strip=True)

                            item_elements = column_div.select('.m-listing-info__item')
                            for item in item_elements:
                                title_element = item.select_one('.m-listing-info__item-title')
                                content_element = item.select_one('.m-listing-info__item-content')

                                if title_element and content_element:
                                    title = title_element.get_text(strip=True)
                                    content = content_element.get_text(strip=True)

                                    if column_title == 'Listing Details':
                                        if title == 'Property ID':
                                            property_id = content
                                        elif title == 'MLS#':
                                            mls_number = content
                                        elif title == 'Price':
                                            price = content
                                        elif title == 'Property type':
                                            property_type = content
                                        elif title == 'Marketed By':
                                            marketed_by = content
                                        elif title == 'Status':
                                            status = content
                                        elif title == 'Year Built':
                                            year_built = content
                                    elif column_title == 'Utilities & Building':
                                        if title == 'Style':
                                            style = content
                                        elif title == 'total sqft':
                                            total_sqft = content
                                        elif title == 'Lot Size Unit':
                                            lot_size_unit = content
                                        elif title == 'Lot Size':
                                            lot_size = content
                                        elif title == 'Parking': # Added scraping for Parking
                                            parking = content
                                        elif title == 'cooling':
                                            cooling = content
                                        elif title == 'Year Built': # Added scraping for Year Built under Utilities & Building
                                            year_built = content
                                    elif column_title == 'Interior':
                                        if title == 'Features':
                                            interior_features = content
                                        elif title == 'Full Bathrooms':
                                            bathrooms = content
                                        elif title == 'partial baths':
                                            partial_baths = content
                                        elif title == 'Bedrooms':
                                            bedrooms = content
                                    elif column_title == 'Additional Features':
                                        if title == 'Features':
                                            additional_features = content

                    amenities_section_title = soup.find('h3', string='Amenities & Features')
                    if amenities_section_title:
                         amenities_features_content = amenities_section_title.find_next_sibling('.property-details-accordion-content')
                    if amenities_features_content:
                        amenities_features = amenities_features_content.get_text(separator=' ', strip=True)

                    description_title_element = soup.select_one('div.c-listing-description h2.title') # Scrape description title
                    if description_title_element:
                        property_description_title = description_title_element.get_text(strip=True)

                    description_div = soup.select_one('div.c-listing-description div.description') # Select the description div within c-listing-description
                    if description_div:
                        property_description = description_div.get_text(strip=True)
                    else:
                        property_description = 'N/A'

                    latitude_match = re.search(r'"latitude":{"_text":"(\d+\.?\d*)"', html_content)
                    longitude_match = re.search(r'"longitude":{"_text":"(-?\d+\.?\d*)"', html_content)

                    if latitude_match and longitude_match:
                        latitude = latitude_match.group(1)
                        longitude = longitude_match.group(1)

                    details = {
                        'property_id': property_id,
                        'mls_number': mls_number,
                        'price': price,
                        'bedrooms': bedrooms,
                        'full_bathrooms': bathrooms,
                        'partial_baths': partial_baths,
                        'total_sqft': total_sqft,
                        'lot_size_unit': lot_size_unit,
                        'lot_size': lot_size,
                        'parking': parking, # Added parking to details
                        'property_type': property_type,
                        'status': status,
                        'marketed_by': marketed_by,
                        'style': style,
                        'cooling': cooling,
                        'interior_features': interior_features,
                        'additional_features': additional_features,
                        'latitude': latitude,
                        'longitude': longitude,
                        'amenities_features': amenities_features,
                        'listing_details': listing_details,
                        'property_description_title': property_description_title, # Added description title to details
                        'property_description': property_description,
                        'year_built': year_built,
                        'imageLinks': imageLinks
                    }


                    row_data = {
                        'Property ID': details['property_id'],
                        'MLS#': details['mls_number'],
                        'Status': details['status'],
                        'Agent Name': original_agent_name,
                        'Marketed By': details['marketed_by'],
                        'Category': 'Real Estate',
                        'Property Type': details['property_type'],
                        'Style': details['style'],
                        'Property Name': name,
                        'Property Link': link,
                        'Price': details['price'],
                        'Bedrooms': details['bedrooms'],
                        'Full Bathrooms': details['full_bathrooms'],
                        'Partial Baths': details['partial_baths'],
                        'Total Sqft': details['total_sqft'],
                        'Lot Size': details['lot_size'],
                        'Lot Size Unit': details['lot_size_unit'],
                        'Parking': details['parking'], # Added Parking to row_data
                        'Cooling': details['cooling'],
                        'Interior Features': details['interior_features'],
                        'Additional Features': details['additional_features'],
                        'Latitude': details['latitude'],
                        'Longitude': details['longitude'],
                        'Property Description Title': details['property_description_title'], # Added description title to row_data
                        'Property Description': details['property_description'],
                        'Year Built': details['year_built'],
                    }

                    max_image_columns = 60
                    for i in range(max_image_columns):
                         row_data[f'Image Link {i+1}'] = details['imageLinks'][i] if i < len(details['imageLinks']) else ''

                    writer.writerow(row_data)
                    print(f"Scraped details for \"{name}\"")

                except Exception as e:
                    print(f"Error scraping {link}: {e}")
                    error_row_data = {
                        'Property ID': 'Error Scraping',
                        'MLS#': '',
                        'Status': '',
                        'Agent Name': original_agent_name,
                        'Marketed By': '',
                        'Category': 'Real Estate',
                        'Property Type': '',
                        'Style': '',
                        'Property Name': name,
                        'Property Link': link,
                        'Price': 'Error Scraping',
                        'Bedrooms': '',
                        'Full Bathrooms': '',
                        'Partial Baths': '',
                        'Total Sqft': '',
                        'Lot Size': '',
                        'Lot Size Unit': '',
                        'Cooling': '',
                        'Interior Features': '',
                        'Additional Features': '',
                        'Latitude': 'Error Scraping',
                        'Longitude': 'Error Scraping',
                        'Property Description Title': 'Error Scraping', # Added description title to error data
                        'Property Description': 'Error Scraping',
                        'Year Built': 'Error Scraping',
                    }
                    writer.writerow(error_row_data)

        await browser.close()
        print(f"Finished scraping. Data saved to {output_csv_path}")

if __name__ == "__main__":
    # Read agent IDs from agents.json
    agents_file_path = 'agents.json'
    if not os.path.exists(agents_file_path):
        print(f"Error: agents.json not found at {agents_file_path}")
    else:
        with open(agents_file_path, 'r') as f:
            agent_ids = json.load(f)

        async def main_scrape_process(agent_id):
            # Scrape links first
            sanitized_agent_name, original_agent_name = await scrape_property_links(agent_id)
            input_csv = f'{sanitized_agent_name}_links.csv'
            output_csv = f'{sanitized_agent_name}_properties.csv'

            # Then scrape details from the generated links CSV
            await scrape_details_from_links(original_agent_name, input_csv, output_csv)

        # Loop through agent IDs and scrape
        for agent_id_to_scrape in agent_ids:
            asyncio.run(main_scrape_process(agent_id_to_scrape))


# Instructions to run this script:
# 1. Make sure you have Python installed.
# 2. Open your terminal in the directory where this file is saved.
# 3. Install the required packages:
#    pip install playwright beautifulsoup4
# 4. Install Playwright browsers:
#    playwright install
# 5. Create an 'agents.json' file in the same directory with a list of agent IDs, e.g., ["agent_id_1", "agent_id_2"].
# 6. Run the script:
#    python scrape_agent_properties.py
#
# This script will read agent IDs from agents.json, scrape property links for each agent, save them to a CSV,
# and then scrape details for each property from the links, saving the details to another CSV.
