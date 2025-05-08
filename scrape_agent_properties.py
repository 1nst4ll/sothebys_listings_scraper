import asyncio
from playwright.async_api import async_playwright
import csv
import os
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

async def scrape_property_links(agent_id):
    """
    Scrapes property links for a given agent ID and saves them to a CSV file.
    Returns the sanitized agent name used for the filename.
    """
    url = f'https://www.sothebysrealty.com/turksandcaicossir/eng/sales/int/{agent_id}'

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print(f"Navigating to {url}")
        await page.goto(url, wait_until='networkidle')

        marketing_text_element = await page.query_selector('p:has-text("Showing listings marketed by")')
        agent_name = "unknown_agent"
        if marketing_text_element:
            full_text = await marketing_text_element.text_content()
            if "Showing listings marketed by" in full_text:
                name_part = full_text.split("Showing listings marketed by", 1)[1].strip()
                agent_name = name_part.split('.')[0].strip()
                print(f"Scraped agent name: {agent_name}")
            else:
                print("Found element with 'Showing listings marketed by' but text format is unexpected.")
        else:
            print("Could not find element containing the text 'Showing listings marketed by'. Using default name.")

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

        return sanitized_agent_name

async def scrape_details_from_links(input_csv_path, output_csv_path):
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
            fieldnames = ['Property Name', 'Property Link', 'Property ID', 'MLS#', 'Price', 'Bedrooms', 'Full Bathrooms', 'Partial Baths', 'Total Sqft', 'Lot Size Unit', 'Lot Size', 'Property Type', 'Status', 'Marketed By', 'Style', 'Cooling', 'Interior Features', 'Additional Features', 'Google Map Location', 'Property Description'] + [f'Image Link {i+1}' for i in range(60)]
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

                    property_id = 'N/A'
                    mls_number = 'N/A'
                    price = 'N/A'
                    bedrooms = 'N/A'
                    bathrooms = 'N/A'
                    partial_baths = 'N/A'
                    total_sqft = 'N/A'
                    lot_size_unit = 'N/A'
                    lot_size = 'N/A'
                    property_type = 'N/A'
                    status = 'N/A'
                    marketed_by = 'N/A'
                    style = 'N/A'
                    cooling = 'N/A'
                    interior_features = 'N/A'
                    additional_features = 'N/A'
                    googleMapLocation = 'N/A'
                    amenities_features = 'N/A'
                    listing_details = 'N/A'
                    property_description = 'N/A'

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
                                    elif column_title == 'Utilities & Building':
                                        if title == 'Style':
                                            style = content
                                        elif title == 'total sqft':
                                            total_sqft = content
                                        elif title == 'Lot Size Unit':
                                            lot_size_unit = content
                                        elif title == 'Lot Size':
                                            lot_size = content
                                        elif title == 'cooling':
                                            cooling = content
                                    elif column_title == 'Interior':
                                        if title == 'Features':
                                            interior_features = content
                                        elif title == 'Full Bathrooms':
                                            if bathrooms == 'N/A':
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

                    description_div = soup.select_one('div.description')
                    if description_div:
                        property_description = description_div.get_text(strip=True)
                    else:
                        property_description = 'N/A'

                    latitude_match = re.search(r'"latitude":{"_text":"(\d+\.?\d*)"', html_content)
                    longitude_match = re.search(r'"longitude":{"_text":"(-?\d+\.?\d*)"', html_content)

                    if latitude_match and longitude_match:
                        latitude = latitude_match.group(1)
                        longitude = longitude_match.group(1)
                        googleMapLocation = f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
                    else:
                        map_iframe_element = soup.select_one('iframe[src*="google.com/maps"]')
                        if map_iframe_element:
                            googleMapLocation = map_iframe_element['src']
                        else:
                            googleMapLocation = 'N/A'

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
                        'property_type': property_type,
                        'status': status,
                        'marketed_by': marketed_by,
                        'style': style,
                        'cooling': cooling,
                        'interior_features': interior_features,
                        'additional_features': additional_features,
                        'googleMapLocation': googleMapLocation,
                        'amenities_features': amenities_features,
                        'listing_details': listing_details,
                        'property_description': property_description,
                        'imageLinks': imageLinks
                    }

                    row_data = {
                        'Property Name': name,
                        'Property Link': link,
                        'Property ID': details['property_id'],
                        'MLS#': details['mls_number'],
                        'Price': details['price'],
                        'Bedrooms': details['bedrooms'],
                        'Full Bathrooms': details['full_bathrooms'],
                        'Partial Baths': details['partial_baths'],
                        'Total Sqft': details['total_sqft'],
                        'Lot Size Unit': details['lot_size_unit'],
                        'Lot Size': details['lot_size'],
                        'Property Type': details['property_type'],
                        'Status': details['status'],
                        'Marketed By': details['marketed_by'],
                        'Style': details['style'],
                        'Cooling': details['cooling'],
                        'Interior Features': details['interior_features'],
                        'Additional Features': details['additional_features'],
                        'Google Map Location': details['googleMapLocation'],
                        'Property Description': details['property_description'],
                    }

                    max_image_columns = 60
                    for i in range(max_image_columns):
                         row_data[f'Image Link {i+1}'] = details['imageLinks'][i] if i < len(details['imageLinks']) else ''

                    writer.writerow(row_data)
                    print(f"Scraped details for \"{name}\"")

                except Exception as e:
                    print(f"Error scraping {link}: {e}")
                    error_row_data = {
                        'Property Name': name,
                        'Property Link': link,
                        'Property ID': 'Error Scraping',
                        'MLS#': 'N/A',
                        'Price': 'Error Scraping',
                        'Bedrooms': 'N/A',
                        'Full Bathrooms': 'N/A',
                        'Partial Baths': 'N/A',
                        'Total Sqft': 'N/A',
                        'Lot Size Unit': 'N/A',
                        'Lot Size': 'N/A',
                        'Property Type': 'N/A',
                        'Status': 'N/A',
                        'Marketed By': 'N/A',
                        'Style': 'N/A',
                        'Cooling': 'N/A',
                        'Interior Features': 'N/A',
                        'Additional Features': 'N/A',
                        'Google Map Location': 'N/A',
                        'Amenities & Features': 'N/A',
                        'Property Description': 'Error Scraping',
                    }
                    writer.writerow(error_row_data)

        await browser.close()
        print(f"Finished scraping. Data saved to {output_csv_path}")

if __name__ == "__main__":
    agent_id_to_scrape = input("Please enter the agent ID to scrape: ")

    async def main_scrape_process(agent_id):
        # Scrape links first
        sanitized_agent_name = await scrape_property_links(agent_id)
        input_csv = f'{sanitized_agent_name}_links.csv'
        output_csv = f'{sanitized_agent_name}_properties.csv'

        # Then scrape details from the generated links CSV
        await scrape_details_from_links(input_csv, output_csv)

    asyncio.run(main_scrape_process(agent_id_to_scrape))

# Instructions to run this script:
# 1. Make sure you have Python installed.
# 2. Open your terminal in the directory where this file is saved.
# 3. Install the required packages:
#    pip install playwright beautifulsoup4
# 4. Install Playwright browsers:
#    playwright install
# 5. Run the script:
#    python scrape_agent_properties.py
#
# This script will scrape property links for the given agent ID, save them to a CSV,
# and then scrape details for each property from the links, saving the details to another CSV.
