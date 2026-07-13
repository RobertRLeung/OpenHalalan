"""
Full scraper for COMELEC 2025 election results.
Scrapes all regions -> provinces -> municipalities and saves to organized CSV files.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium_stealth import stealth
import time
import csv
import os
from pathlib import Path
from datetime import datetime

def setup_driver():
    """Initialize Chrome driver with stealth settings."""
    options = webdriver.ChromeOptions()
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="MacIntel",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )
    
    driver.maximize_window()
    return driver

def wait_for_page_load(driver, initial_load=False):
    """Wait for page to fully load."""
    if initial_load:
        print("  Waiting for page load...")
        time.sleep(10)  # Initial Cloudflare wait
    else:
        time.sleep(1)  # Much shorter for dropdowns
    
    WebDriverWait(driver, 20).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )
    if not initial_load:
        time.sleep(0.5)  # Minimal buffer

def click_autocomplete_field(driver, label_text):
    """Click on a Vuetify autocomplete field to activate it."""
    try:
        xpath_options = [
            f"//label[contains(text(), '{label_text}')]/following-sibling::div//input",
            f"//label[contains(text(), '{label_text}')]/..//input",
            f"//div[.//label[contains(text(), '{label_text}')]]//input",
        ]
        
        for xpath in xpath_options:
            try:
                input_field = driver.find_element(By.XPATH, xpath)
                driver.execute_script("arguments[0].scrollIntoView();", input_field)
                time.sleep(0.2)
                input_field.click()
                time.sleep(0.5)
                return True
            except:
                continue
        
        return False
    except Exception as e:
        print(f"Error clicking autocomplete for '{label_text}': {e}")
        return False

def get_autocomplete_options(driver):
    """Get options from the currently open autocomplete dropdown, scrolling to get all items."""
    try:
        time.sleep(2)
        menu = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".v-menu__content.menuable__content__active"))
        )
        
        options = []
        seen_texts = set()
        
        # Scroll through the dropdown to load all items
        last_count = 0
        scroll_attempts = 0
        max_scroll_attempts = 20
        
        while scroll_attempts < max_scroll_attempts:
            items = menu.find_elements(By.CSS_SELECTOR, ".v-list-item")
            
            # Collect visible items
            for item in items:
                try:
                    text = item.text.strip()
                    if text and text not in seen_texts:
                        options.append(text)
                        seen_texts.add(text)
                except:
                    pass
            
            # If no new items, we've reached the end
            if len(options) == last_count:
                break
            
            last_count = len(options)
            
            # Scroll to the last item to load more
            if items:
                try:
                    driver.execute_script("arguments[0].scrollIntoView();", items[-1])
                    time.sleep(0.3)
                except:
                    pass
            
            scroll_attempts += 1
        
        return options
    except Exception as e:
        print(f"Error getting autocomplete options: {e}")
        return []

def select_autocomplete_option(driver, option_text):
    """Select an option from the autocomplete dropdown by clicking it."""
    try:
        time.sleep(0.5)
        menu = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".v-menu__content.menuable__content__active"))
        )
        
        items = menu.find_elements(By.CSS_SELECTOR, ".v-list-item")
        for item in items:
            if option_text in item.text:
                driver.execute_script("arguments[0].scrollIntoView();", item)
                time.sleep(0.2)
                item.click()
                time.sleep(1)
                return True
        
        return False
    except Exception as e:
        print(f"Error selecting option '{option_text}': {e}")
        return False

def get_election_results(driver):
    """Extract election results from the current page, organized by position."""
    try:
        time.sleep(2)  # Wait for results to load
        
        results = []
        
        # First, expand all panels at once with JavaScript
        driver.execute_script("""
            document.querySelectorAll('.v-expansion-panel-header').forEach(header => {
                if (!header.classList.contains('v-expansion-panel-header--active')) {
                    header.click();
                }
            });
        """)
        time.sleep(1)  # Wait for all panels to expand
        
        panels = driver.find_elements(By.CSS_SELECTOR, ".v-expansion-panel")
        
        for panel in panels:
            try:
                header = panel.find_element(By.CSS_SELECTOR, ".v-expansion-panel-header")
                position_text = header.text.strip()
                
                # Skip category headers
                if "National Positions" in position_text or "Local Positions" in position_text:
                    continue
                
                content = panel.find_element(By.CSS_SELECTOR, ".v-expansion-panel-content")
                
                try:
                    table = content.find_element(By.CSS_SELECTOR, ".v-data-table")
                    rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
                    
                    for row in rows:
                        try:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if len(cells) >= 3:
                                first_cell = cells[0].text.strip()
                                votes = cells[1].text.strip().replace(',', '')
                                percentage = cells[2].text.strip()
                                
                                rank = ""
                                candidate_name = ""
                                party = ""
                                
                                if '. ' in first_cell:
                                    parts = first_cell.split('. ', 1)
                                    rank = parts[0]
                                    rest = parts[1] if len(parts) > 1 else ""
                                    
                                    if '(' in rest and ')' in rest:
                                        candidate_name = rest[:rest.rfind('(')].strip()
                                        party = rest[rest.rfind('(')+1:rest.rfind(')')].strip()
                                    else:
                                        candidate_name = rest
                                else:
                                    candidate_name = first_cell
                                
                                results.append({
                                    'position': position_text,
                                    'rank': rank,
                                    'candidate_name': candidate_name,
                                    'party': party,
                                    'votes': votes,
                                    'percentage': percentage
                                })
                        except:
                            continue
                            
                except:
                    continue
                    
            except:
                continue
        
        return results
        
    except Exception as e:
        print(f"Error getting results: {e}")
        return []

def save_to_csv(results, region, province, city, base_dir="2025_raw"):
    """Save results to a CSV file with organized folder structure."""
    try:
        # Clean names for folder/file names
        def clean_name(name):
            return name.replace('/', '-').replace(' ', '_').replace('\\', '-')
        
        region_clean = clean_name(region)
        province_clean = clean_name(province)
        city_clean = clean_name(city)
        
        # Create folder structure: 2025_raw/region/province/
        region_dir = os.path.join(base_dir, region_clean)
        province_dir = os.path.join(region_dir, province_clean)
        os.makedirs(province_dir, exist_ok=True)
        
        # Create filename: region_province_municipality.csv
        filename = f"{region_clean}_{province_clean}_{city_clean}.csv"
        filepath = os.path.join(province_dir, filename)
        
        # Write to CSV
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['region', 'province', 'city', 'position', 'rank', 'candidate_name', 'party', 'votes', 'percentage']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for result in results:
                writer.writerow({
                    'region': region,
                    'province': province,
                    'city': city,
                    'position': result['position'],
                    'rank': result['rank'],
                    'candidate_name': result['candidate_name'],
                    'party': result['party'],
                    'votes': result['votes'],
                    'percentage': result['percentage']
                })
        
        return filepath
        
    except Exception as e:
        print(f"  ✗ Error saving to CSV: {e}")
        import traceback
        traceback.print_exc()
        return None

def region_already_scraped(region, base_dir="2025_raw"):
    """Check if a region has been fully scraped by checking if its folder exists."""
    def clean_name(name):
        return name.replace('/', '-').replace(' ', '_').replace('\\', '-')
    
    region_clean = clean_name(region)
    region_dir = os.path.join(base_dir, region_clean)
    
    # If the region folder doesn't exist, it hasn't been scraped
    if not os.path.exists(region_dir):
        return False
    
    # If it exists and has CSV files, consider it scraped
    csv_count = sum(1 for _ in Path(region_dir).rglob('*.csv'))
    return csv_count > 0

def file_already_exists(region, province, city, base_dir="2025_raw"):
    """Check if a CSV file already exists for this location."""
    def clean_name(name):
        return name.replace('/', '-').replace(' ', '_').replace('\\', '-')
    
    region_clean = clean_name(region)
    province_clean = clean_name(province)
    city_clean = clean_name(city)
    
    region_dir = os.path.join(base_dir, region_clean)
    province_dir = os.path.join(region_dir, province_clean)
    filename = f"{region_clean}_{province_clean}_{city_clean}.csv"
    filepath = os.path.join(province_dir, filename)
    
    return os.path.exists(filepath)

def province_already_complete(region, province, cities, base_dir="2025_raw"):
    """Check if all cities in a province have been scraped."""
    missing = []
    for city in cities:
        if not file_already_exists(region, province, city, base_dir):
            missing.append(city)
    return len(missing) == 0, missing

def scrape_municipality(driver, region, province, city):
    """Scrape results for a specific municipality."""
    try:
        results = get_election_results(driver)
        
        if results:
            filepath = save_to_csv(results, region, province, city)
            print(f"    ✓ Saved {len(results)} records to {filepath}")
            return True
        else:
            print(f"    ✗ No results found")
            return False
            
    except Exception as e:
        print(f"    ✗ Error scraping {city}: {e}")
        return False

def main():
    """Main scraping function."""
    url = "https://2025electionresults.comelec.gov.ph/coc-result"
    
    print("=" * 80)
    print("COMELEC 2025 Election Results Scraper")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    driver = setup_driver()
    
    total_scraped = 0
    total_failed = 0
    cities_since_refresh = 0  # Track cities to force periodic restarts
    
    try:
        driver.get(url)
        wait_for_page_load(driver, initial_load=True)
        print("✓ Page loaded successfully\n")
        
        # Get all regions
        print("Fetching regions...")
        if not click_autocomplete_field(driver, "Region:"):
            print("✗ Failed to open region dropdown")
            return
        
        regions = get_autocomplete_options(driver)
        print(f"✓ Found {len(regions)} regions\n")
        
        # Close the dropdown
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1)
        
        # Loop through each region
        start_from_region = "REGION IV-A"  # Start from beginning to catch all missing municipalities
        skip_mode = True
        
        for region_idx, region in enumerate(regions, 1):
            # Skip until we reach the start_from_region
            if skip_mode:
                if start_from_region.upper() in region.upper():
                    skip_mode = False
                    print(f"\n[{region_idx}/{len(regions)}] Resuming from: {region}")
                else:
                    print(f"\n[{region_idx}/{len(regions)}] Skipping: {region}")
                    continue
            
            print(f"\n[{region_idx}/{len(regions)}] Processing region: {region}")
            print("-" * 80)
            
            # Check if region is complete (optional optimization - can remove if causing issues)
            # But still process the region to handle partial scrapes
            
            # Refresh page at the start of each region for clean state
            print("  Refreshing page for clean state...")
            driver.refresh()
            wait_for_page_load(driver, initial_load=True)
            print("  Page refreshed!")
            
            try:
                # Select region (after refresh) - with retries
                retry_count = 0
                max_retries = 3
                
                while retry_count < max_retries:
                    if click_autocomplete_field(driver, "Region:"):
                        if select_autocomplete_option(driver, region):
                            break
                        else:
                            print(f"  ⟳ Retry {retry_count + 1}/{max_retries}: Failed to select region")
                    else:
                        print(f"  ⟳ Retry {retry_count + 1}/{max_retries}: Failed to open region dropdown")
                    
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(3)
                        driver.refresh()
                        wait_for_page_load(driver, initial_load=True)
                
                if retry_count >= max_retries:
                    print(f"  ✗ Failed to select region after {max_retries} attempts: {region}")
                    continue
                
                wait_for_page_load(driver)
                
                # Get provinces for this region
                if not click_autocomplete_field(driver, "Province/District:"):
                    print(f"  ✗ Failed to open province dropdown")
                    continue
                
                provinces = get_autocomplete_options(driver)
                print(f"  → Found {len(provinces)} provinces/districts")
                
                # Close dropdown
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(1)
            except Exception as e:
                print(f"  ✗ Error processing region {region}: {e}")
                import traceback
                traceback.print_exc()
                continue
            
            # Loop through each province
            for province_idx, province in enumerate(provinces, 1):
                print(f"\n  [{province_idx}/{len(provinces)}] Processing: {province}")
                
                try:
                    # Select province
                    if not click_autocomplete_field(driver, "Province/District:"):
                        print(f"    ✗ Failed to open province dropdown")
                        continue
                    
                    if not select_autocomplete_option(driver, province):
                        print(f"    ✗ Failed to select province: {province}")
                        continue
                    
                    wait_for_page_load(driver)
                    
                    # Get cities for this province
                    if not click_autocomplete_field(driver, "City/Municipality:"):
                        print(f"    ✗ Failed to open city dropdown")
                        continue
                    
                    cities = get_autocomplete_options(driver)
                    print(f"    → Found {len(cities)} cities/municipalities")
                    
                    # Check if province is already complete
                    is_complete, missing_cities = province_already_complete(region, province, cities)
                    if is_complete:
                        print(f"    ⊙ Province complete - all {len(cities)} cities already scraped (skipping)")
                        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                        time.sleep(1)
                        continue
                    else:
                        print(f"    → Need to scrape {len(missing_cities)} missing cities")
                    
                    # Close dropdown
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(1)
                except Exception as e:
                    print(f"    ✗ Error processing province {province}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
                
                # Loop through each city
                for city_idx, city in enumerate(cities, 1):
                    # Force refresh every 20 cities to prevent element staleness
                    if cities_since_refresh >= 20:
                        print(f"\n    [Refreshing browser after {cities_since_refresh} cities for stability...]")
                        driver.refresh()
                        wait_for_page_load(driver, initial_load=True)
                        # Re-select region and province
                        if click_autocomplete_field(driver, "Region:") and select_autocomplete_option(driver, region):
                            wait_for_page_load(driver)
                            if click_autocomplete_field(driver, "Province/District:") and select_autocomplete_option(driver, province):
                                wait_for_page_load(driver)
                                if click_autocomplete_field(driver, "City/Municipality:"):
                                    cities = get_autocomplete_options(driver)
                                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                                    time.sleep(1)
                        cities_since_refresh = 0
                    
                    # Check if already scraped (resume capability)
                    if file_already_exists(region, province, city):
                        print(f"    [{city_idx}/{len(cities)}] {city}... ⊙ Already scraped (skipping)")
                        total_scraped += 1
                        cities_since_refresh += 1
                        continue
                    
                    print(f"    [{city_idx}/{len(cities)}] {city}...", end=" ")
                    
                    # Retry logic for each city
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            # Select city
                            if not click_autocomplete_field(driver, "City/Municipality:"):
                                if retry < max_retries - 1:
                                    print(f"⟳ Retry {retry + 1}/{max_retries}...", end=" ")
                                    time.sleep(2)
                                    continue
                                else:
                                    print("✗ Failed to open city dropdown")
                                    total_failed += 1
                                    break
                            
                            if not select_autocomplete_option(driver, city):
                                if retry < max_retries - 1:
                                    print(f"⟳ Retry {retry + 1}/{max_retries}...", end=" ")
                                    time.sleep(2)
                                    continue
                                else:
                                    print("✗ Failed to select")
                                    total_failed += 1
                                    break
                            
                            wait_for_page_load(driver)
                            
                            # Scrape results
                            if scrape_municipality(driver, region, province, city):
                                total_scraped += 1
                                cities_since_refresh += 1
                            else:
                                total_failed += 1
                            break  # Success, exit retry loop
                            
                        except Exception as e:
                            if retry < max_retries - 1:
                                print(f"⟳ Error, retry {retry + 1}/{max_retries}...", end=" ")
                                time.sleep(3)
                                # Try refreshing the page and re-selecting province
                                try:
                                    driver.refresh()
                                    wait_for_page_load(driver, initial_load=True)
                                    if click_autocomplete_field(driver, "Region:") and select_autocomplete_option(driver, region):
                                        wait_for_page_load(driver)
                                        if click_autocomplete_field(driver, "Province/District:") and select_autocomplete_option(driver, province):
                                            wait_for_page_load(driver)
                                            continue
                                except:
                                    pass
                            else:
                                print(f"✗ Error after {max_retries} retries: {e}")
                                total_failed += 1
                                break
        
        print("\n" + "=" * 80)
        print("SCRAPING COMPLETE")
        print("=" * 80)
        print(f"Total municipalities scraped: {total_scraped}")
        print(f"Total failures: {total_failed}")
        print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print("\n\n✗ Scraping interrupted by user")
        print(f"Scraped {total_scraped} municipalities before interruption")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()
        print("\nBrowser closed.")

if __name__ == "__main__":
    main()
