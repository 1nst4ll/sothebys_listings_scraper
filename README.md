# MangoScraper

This repository contains a Python script (`scrape_agent_properties.py`) designed to scrape property listings and their details for a specific real estate agent from the Sotheby's International Realty website for Turks and Caicos.

The script takes an agent ID as input, scrapes the links to all properties listed by that agent, and then visits each property link to extract detailed information, including property features and image links.

## Features

*   Scrapes property links for a given agent ID.
*   Includes the agent's name (dynamically scraped) and a fixed 'Real Estate' category in the output.
*   Extracts detailed information for each property, including: Property ID, MLS#, Status, Marketed By, Property Type, Style, Price, Year Built, Bedrooms, Full Bathrooms, Partial Baths, Total Sqft, Lot Size, Lot Size Unit, Parking, Cooling, Interior Features, Additional Features, Latitude, Longitude, Property Description Title, and Property Description.
*   Scrapes up to 60 image links per property.
*   Saves the scraped data into two separate CSV files: one for links and one for detailed property information.

## Prerequisites

*   Python 3.7 or higher
*   `playwright` library
*   `beautifulsoup4` library

## Installation

1.  Clone this repository to your local machine.
2.  Navigate to the project directory in your terminal.
3.  Install the required Python packages:

    ```bash
    pip install playwright beautifulsoup4
    ```

4.  Install the Playwright browsers:

    ```bash
    playwright install
    ```

## Usage

1.  Create an `agents.json` file in the project directory. This file should contain a JSON array of agent IDs you want to scrape, like this:

    ```json
    [
      "agent_id_1",
      "agent_id_2",
      "agent_id_3"
    ]
    ```

2.  Open your terminal and navigate to the project directory.
3.  Run the script using the following command:

    ```bash
    python scrape_agent_properties.py
    ```

4.  The script will read the agent IDs from `agents.json` and process each one sequentially.

## Output

The script will generate two CSV files in the project directory:

1.  `[sanitized_agent_name]_links.csv`: Contains the list of property names, locations, and links for the specified agent.
2.  `[sanitized_agent_name]_properties.csv`: Contains the agent name, category ('Real Estate'), and detailed information scraped for each property, including up to 60 image links.

Replace `[sanitized_agent_name]` with the actual name of the agent, sanitized for use in a filename (e.g., spaces replaced with underscores).

## Contributing

Feel free to contribute to this project by submitting issues or pull requests.

## License

MIT
