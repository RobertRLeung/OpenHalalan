"""
FAST scraper for COMELEC 2025 election results.
Optimizations:
- Headless mode
- Reduced wait times
- Skip already-scraped files
- Save to 2025_raw folder to preserve raw position names with district info
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse

from config import CONFIG, raw_dir

# Set from --region / --province. Empty = scrape everything.
ONLY_REGIONS = set()
ONLY_PROVINCES = set()

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium_stealth import stealth
import time
import csv
import os
from datetime import datetime

def setup_driver(headless=True):
    """Initialize Chrome driver with stealth settings."""
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument('--headless=new')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
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
    
    if not headless:
        driver.maximize_window()
    return driver

def wait_for_page_load(driver, initial_load=False):
    """Wait for page to fully load with optimized timing."""
    if initial_load:
        time.sleep(8)  # Reduced from 10
    else:
        time.sleep(0.3)  # Reduced from 1
    
    WebDriverWait(driver, 15).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )
    if not initial_load:
        time.sleep(0.2)  # Reduced from 0.5

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
                time.sleep(0.1)  # Reduced from 0.2
                input_field.click()
                time.sleep(0.3)  # Reduced from 0.5
                return True
            except:
                continue
        
        return False
    except Exception as e:
        return False

def get_autocomplete_options(driver):
    """Get options from the currently open autocomplete dropdown."""
    try:
        time.sleep(1)  # Reduced from 2
        menu = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".v-menu__content.menuable__content__active"))
        )
        
        # The dropdown lazy-renders: only the items currently in view exist in the DOM.
        # Reading it once silently TRUNCATES long lists - Samar's 26 municipalities came
        # back as 20, and the missing ones simply never got scraped. Scroll to the bottom,
        # re-reading until the count stops growing.
        options = []
        last_count = -1

        while len(options) != last_count:
            last_count = len(options)

            for item in menu.find_elements(By.CSS_SELECTOR, ".v-list-item"):
                try:
                    text = item.text.strip()
                    if text and text not in options:
                        options.append(text)
                except Exception:
                    pass

            try:
                driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight;", menu
                )
                time.sleep(0.4)
            except Exception:
                break
        
        return options
    except Exception as e:
        return []

def select_autocomplete_option(driver, option_text):
    """Select an option from the autocomplete dropdown by clicking it."""
    try:
        time.sleep(0.3)  # Reduced from 0.5
        menu = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".v-menu__content.menuable__content__active"))
        )
        
        items = menu.find_elements(By.CSS_SELECTOR, ".v-list-item")

        # EXACT match first. A substring match silently picks the wrong place whenever one
        # name contains another: asking for "SAMAR" matched "EASTERN SAMAR" (listed first),
        # so the 2025 scrape filed Eastern Samar's 23 municipalities under Samar and the
        # real Samar province went missing entirely. Same trap for LEYTE/SOUTHERN LEYTE,
        # COTABATO/SOUTH COTABATO, and city names like SAN JOSE / SAN JOSE DEL MONTE.
        target = option_text.strip().upper()

        for item in items:
            if item.text.strip().upper() == target:
                driver.execute_script("arguments[0].scrollIntoView();", item)
                time.sleep(0.1)
                item.click()
                time.sleep(0.5)
                return True

        # Only then fall back to a substring match.
        for item in items:
            if target in item.text.strip().upper():
                driver.execute_script("arguments[0].scrollIntoView();", item)
                time.sleep(0.1)
                item.click()
                time.sleep(0.5)
                return True

        return False
    except Exception as e:
        return False

def get_election_results(driver):
    """Extract election results from the current page - PRESERVE RAW POSITION NAMES."""
    try:
        time.sleep(1)  # Reduced from 2
        
        results = []
        
        # Expand all panels at once with JavaScript
        driver.execute_script("""
            document.querySelectorAll('.v-expansion-panel-header').forEach(header => {
                if (!header.classList.contains('v-expansion-panel-header--active')) {
                    header.click();
                }
            });
        """)
        time.sleep(0.5)  # Reduced from 1
        
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
                                    'position': position_text,  # Keep RAW position name with district info
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
        return []

def save_to_csv(results, region, province, city, base_dir=None):
    base_dir = Path(base_dir) if base_dir else raw_dir(2025)
    """Save results to a CSV file with organized folder structure."""
    try:
        def clean_name(name):
            return name.replace('/', '-').replace(' ', '_').replace('\\', '-')
        
        region_clean = clean_name(region)
        province_clean = clean_name(province)
        city_clean = clean_name(city)
        
        region_dir = os.path.join(base_dir, region_clean)
        province_dir = os.path.join(region_dir, province_clean)
        os.makedirs(province_dir, exist_ok=True)
        
        filename = f"{region_clean}_{province_clean}_{city_clean}.csv"
        filepath = os.path.join(province_dir, filename)
        
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
        return None

def file_already_exists(region, province, city, base_dir=None):
    base_dir = Path(base_dir) if base_dir else raw_dir(2025)
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

def main():
    """Main scraping function."""
    url = "https://2025electionresults.comelec.gov.ph/coc-result"
    
    print("=" * 80)
    print("COMELEC 2025 FAST Scraper - Saving RAW position names to 2025_raw/")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Headless triggers COMELEC's bot detection; config.yaml -> scraping.headless
    driver = setup_driver(headless=CONFIG['scraping']['headless'])
    
    total_scraped = 0
    total_skipped = 0
    total_failed = 0
    
    try:
        driver.get(url)
        wait_for_page_load(driver, initial_load=True)
        print("✓ Page loaded\n")
        
        # Get all regions
        if not click_autocomplete_field(driver, "Region:"):
            print("✗ Failed to open region dropdown")
            return
        
        regions = get_autocomplete_options(driver)
        if ONLY_REGIONS:
            regions = [r for r in regions if r.upper() in ONLY_REGIONS]
            print(f"--region filter: {regions}")
        print(f"✓ Found {len(regions)} regions\n")
        
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.5)
        
        for region_idx, region in enumerate(regions, 1):
            print(f"\n[{region_idx}/{len(regions)}] {region}")
            print("-" * 80)
            
            driver.refresh()
            wait_for_page_load(driver, initial_load=True)
            
            try:
                if not click_autocomplete_field(driver, "Region:") or not select_autocomplete_option(driver, region):
                    print(f"  ✗ Failed to select region")
                    continue
                
                wait_for_page_load(driver)
                
                if not click_autocomplete_field(driver, "Province/District:"):
                    print(f"  ✗ Failed to open province dropdown")
                    continue
                
                provinces = get_autocomplete_options(driver)
                if ONLY_PROVINCES:
                    provinces = [p for p in provinces if p.upper() in ONLY_PROVINCES]
                    print(f"  --province filter: {provinces}")
                print(f"  → {len(provinces)} provinces")
                
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(0.5)
            except Exception as e:
                print(f"  ✗ Error: {e}")
                continue
            
            for province_idx, province in enumerate(provinces, 1):
                try:
                    if not click_autocomplete_field(driver, "Province/District:") or not select_autocomplete_option(driver, province):
                        continue
                    
                    wait_for_page_load(driver)
                    
                    if not click_autocomplete_field(driver, "City/Municipality:"):
                        continue
                    
                    cities = get_autocomplete_options(driver)
                    
                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                    time.sleep(0.5)
                except Exception as e:
                    continue
                
                for city_idx, city in enumerate(cities, 1):
                    if file_already_exists(region, province, city):
                        print(f"  [{province_idx}/{len(provinces)}] {province} - {city_idx}/{len(cities)} ⊙", end="\r")
                        total_skipped += 1
                        continue
                    
                    try:
                        if not click_autocomplete_field(driver, "City/Municipality:") or not select_autocomplete_option(driver, city):
                            total_failed += 1
                            continue
                        
                        wait_for_page_load(driver)
                        
                        results = get_election_results(driver)
                        
                        if results:
                            save_to_csv(results, region, province, city)
                            print(f"  [{province_idx}/{len(provinces)}] {province} - {city_idx}/{len(cities)} ✓ {city}")
                            total_scraped += 1
                        else:
                            total_failed += 1
                    except Exception as e:
                        total_failed += 1
                        continue
        
        print("\n" + "=" * 80)
        print("COMPLETE")
        print("=" * 80)
        print(f"Scraped: {total_scraped} | Skipped: {total_skipped} | Failed: {total_failed}")
        print(f"End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
    except KeyboardInterrupt:
        print(f"\n\n✗ Interrupted - Scraped: {total_scraped}, Skipped: {total_skipped}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Scrape 2025 COMELEC results into data/raw_data/2025/. "
                    "--region/--province re-scrape one place, e.g. Samar, which the full "
                    "run captured as a duplicate of Eastern Samar: "
                    "--region 'REGION VIII' --province SAMAR")
    ap.add_argument("--region", action="append", default=[])
    ap.add_argument("--province", action="append", default=[])
    ap.add_argument("--headed", action="store_true",
                    help="run with a visible browser (COMELEC blocks headless)")
    args = ap.parse_args()

    ONLY_REGIONS = {r.upper() for r in args.region}
    ONLY_PROVINCES = {p.upper() for p in args.province}
    if args.headed:
        CONFIG['scraping']['headless'] = False

    main()
