"""
Scraper for 2022 COMELEC election results - Version 4
Properly interacts with dropdowns and buttons on the page.
URL: https://2022electionresults.comelec.gov.ph/#/coc/0
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium_stealth import stealth
import time
import csv
from pathlib import Path
from datetime import datetime

def setup_driver():
    """Set up Chrome driver with stealth mode."""
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="MacIntel",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True)
    
    driver.maximize_window()
    return driver

def wait_and_clear_input(input_element):
    """Clear input field and wait."""
    try:
        input_element.clear()
        time.sleep(0.3)
    except:
        pass

def click_dropdown_and_get_options(driver, input_element):
    """
    Click on a dropdown input to open it and get all available options.
    Returns list of option texts.
    """
    try:
        # Scroll to element
        driver.execute_script("arguments[0].scrollIntoView(true);", input_element)
        time.sleep(0.3)
        
        # Clear and focus
        wait_and_clear_input(input_element)
        input_element.click()
        time.sleep(0.5)
        
        # Click again to ensure dropdown opens
        input_element.click()
        time.sleep(1)
        
        # Find the dropdown menu container
        dropdown_containers = driver.find_elements(By.CSS_SELECTOR, "ul.ui-autocomplete, ul.ui-menu, ul[role='listbox']")
        visible_container = None
        for container in dropdown_containers:
            if container.is_displayed():
                visible_container = container
                break
        
        options = []
        
        if visible_container:
            # Scroll within the dropdown to load all options
            last_count = 0
            for _ in range(5):  # Try scrolling a few times
                all_lis = visible_container.find_elements(By.TAG_NAME, "li")
                
                for li in all_lis:
                    try:
                        if li.is_displayed():
                            text = li.text.strip()
                            if text and '\n' not in text and len(text) < 100:
                                if text not in options:
                                    options.append(text)
                    except:
                        pass
                
                # If no new options found, we're done
                if len(options) == last_count:
                    break
                last_count = len(options)
                
                # Scroll down in the dropdown
                try:
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", visible_container)
                    time.sleep(0.3)
                except:
                    pass
        else:
            # Fallback: get all visible li elements
            all_lis = driver.find_elements(By.TAG_NAME, "li")
            for li in all_lis:
                try:
                    if li.is_displayed() and li.size['height'] > 0:
                        text = li.text.strip()
                        if text and '\n' not in text and len(text) < 100:
                            if text not in options:
                                options.append(text)
                except:
                    pass
        
        return options
        
    except Exception as e:
        print(f"      Error getting options: {e}")
        return []

def select_from_dropdown(driver, input_element, option_text):
    """
    Select a specific option from a dropdown.
    """
    try:
        # Scroll to element and wait for it to be ready
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", input_element)
        time.sleep(0.5)
        
        # Wait for element to be clickable
        try:
            WebDriverWait(driver, 10).until(
                lambda d: input_element.is_enabled() and input_element.is_displayed()
            )
        except:
            pass
        
        # Clear field
        wait_and_clear_input(input_element)
        time.sleep(0.3)
        
        # Click to focus using JavaScript (more reliable)
        driver.execute_script("arguments[0].focus();", input_element)
        driver.execute_script("arguments[0].click();", input_element)
        time.sleep(0.5)
        
        # Type the full option text
        for char in option_text:
            input_element.send_keys(char)
            time.sleep(0.02)  # Faster typing
        
        time.sleep(1)  # Reduced wait for dropdown to populate
        
        # Find matching suggestion - look for exact match first
        all_lis = driver.find_elements(By.TAG_NAME, "li")
        
        # Try exact match first
        for li in all_lis:
            try:
                if li.is_displayed() and li.text.strip().upper() == option_text.upper():
                    print(f"      Found exact match: {li.text.strip()}")
                    driver.execute_script("arguments[0].click();", li)
                    time.sleep(1)
                    return True
            except:
                continue
        
        # Try partial match
        for li in all_lis:
            try:
                if li.is_displayed() and option_text.upper() in li.text.strip().upper():
                    print(f"      Found partial match: {li.text.strip()}")
                    driver.execute_script("arguments[0].click();", li)
                    time.sleep(1)
                    return True
            except:
                continue
        
        # Last resort: press Enter
        print(f"      No match found, pressing Enter")
        input_element.send_keys(Keys.ENTER)
        time.sleep(1)
        return True
        
    except Exception as e:
        print(f"      Error selecting option '{option_text}': {e}")
        return False

def find_input_by_placeholder(driver, keyword):
    """Find input field by placeholder text."""
    inputs = driver.find_elements(By.TAG_NAME, "input")
    for inp in inputs:
        try:
            placeholder = inp.get_attribute("placeholder") or ""
            if keyword.lower() in placeholder.lower():
                return inp
        except:
            pass
    return None

def extract_results(driver, region, province, city):
    """Extract election results from the current page."""
    try:
        # Wait for results to appear - increase wait time
        time.sleep(3)
        
        # Get page text
        body_text = driver.find_element(By.TAG_NAME, "body").text
        lines = [line.strip() for line in body_text.split('\n') if line.strip()]
        
        # Check if no results
        if "No COCs received" in body_text:
            return []
        
        results = []
        position_keywords = ['PRESIDENT', 'VICE-PRESIDENT', 'SENATOR', 'REPRESENTATIVE', 
                            'GOVERNOR', 'VICE GOVERNOR', 'MAYOR', 'VICE MAYOR', 
                            'MEMBER, SANGGUNIANG', 'HOUSE OF REPRESENTATIVES']
        
        current_position = ""
        rank = 1
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this is a position header
            is_position = any(keyword in line.upper() for keyword in position_keywords) and '(' not in line
            
            if is_position:
                current_position = line
                rank = 1
                i += 1
                
                # Skip column headers
                while i < len(lines) and lines[i] in ['Candidate', 'Votes', 'Percentage', '']:
                    i += 1
                
                # Parse candidates for this position
                while i < len(lines):
                    candidate_line = lines[i]
                    
                    # Check if we hit next position
                    if any(keyword in candidate_line.upper() for keyword in position_keywords):
                        break
                    if candidate_line in ['National Positions', 'Local Positions', 'Total COCs Received', 'Total COCs Received from BOC']:
                        break
                    
                    # Parse candidate (name with party in parentheses)
                    if '(' in candidate_line and ')' in candidate_line and i + 2 < len(lines):
                        candidate_name = candidate_line[:candidate_line.rfind('(')].strip()
                        party = candidate_line[candidate_line.rfind('(')+1:candidate_line.rfind(')')].strip()
                        
                        votes_line = lines[i + 1]
                        percentage_line = lines[i + 2]
                        
                        # Validate this looks like votes and percentage
                        if votes_line.replace(',', '').replace('.', '').isdigit() and '%' in percentage_line:
                            results.append({
                                'region': region,
                                'province': province,
                                'city': city,
                                'position': current_position,
                                'rank': str(rank),
                                'candidate_name': candidate_name,
                                'party': party,
                                'votes': votes_line.replace(',', ''),
                                'percentage': percentage_line
                            })
                            
                            rank += 1
                            i += 3
                            continue
                    
                    i += 1
            else:
                i += 1
        
        return results
        
    except Exception as e:
        print(f"      Error extracting results: {e}")
        import traceback
        traceback.print_exc()
        return []

def file_already_exists(region, province, city, base_dir="2022_raw"):
    """Check if CSV file already exists."""
    safe_region = region.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
    safe_province = province.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
    safe_city = city.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
    
    region_dir = Path(base_dir) / safe_region
    province_dir = region_dir / safe_province
    filename = f"{safe_region}_{safe_province}_{safe_city}.csv"
    filepath = province_dir / filename
    
    return filepath.exists()

def save_to_csv(results, region, province, city, base_dir="2022_raw"):
    """Save results to CSV file."""
    try:
        safe_region = region.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
        safe_province = province.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
        safe_city = city.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
        
        region_dir = Path(base_dir) / safe_region
        province_dir = region_dir / safe_province
        province_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{safe_region}_{safe_province}_{safe_city}.csv"
        filepath = province_dir / filename
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['region', 'province', 'city', 'position', 'rank', 
                           'candidate_name', 'party', 'votes', 'percentage'])
            
            for result in results:
                writer.writerow([
                    result.get('region', ''),
                    result.get('province', ''),
                    result.get('city', ''),
                    result.get('position', ''),
                    result.get('rank', ''),
                    result.get('candidate_name', ''),
                    result.get('party', ''),
                    result.get('votes', ''),
                    result.get('percentage', '')
                ])
        
        return True, str(filepath)
        
    except Exception as e:
        print(f"      Error saving CSV: {e}")
        return False, None

def main():
    """Main scraping function - scrapes all regions."""
    print("=" * 80)
    print("COMELEC 2022 Election Results Scraper v4 - ALL REGIONS")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    driver = setup_driver()
    url = "https://2022electionresults.comelec.gov.ph/#/coc/0"
    
    total_cities = 0
    successful_scrapes = 0
    failed_scrapes = 0
    
    try:
        print("Loading main page...")
        driver.get(url)
        time.sleep(3)
        print("✓ Page loaded\n")
        
        # Click "Local" button/tab if it exists
        try:
            # Look for Local button or link
            local_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Local')]")
            for elem in local_elements:
                if elem.is_displayed() and elem.tag_name in ['button', 'a', 'div']:
                    print("Clicking 'Local' option...")
                    driver.execute_script("arguments[0].click();", elem)
                    time.sleep(2)
                    print("✓ Selected Local results\n")
                    break
        except Exception as e:
            print(f"Note: Could not find/click Local button: {e}")
        
        # Find region input
        region_input = find_input_by_placeholder(driver, "region")
        if not region_input:
            print("✗ Could not find region input")
            return
        
        print("Getting list of regions...")
        regions = click_dropdown_and_get_options(driver, region_input)
        
        # Filter out non-region items like "Local", "Overseas", etc.
        regions = [r for r in regions if r and len(r) > 2 and r.upper() not in ['LOCAL', 'OVERSEAS']]
        
        print(f"✓ Found {len(regions)} regions")
        if regions:
            print(f"Available regions: {regions}")
        
        # Scrape all remaining regions
        # Prioritize regions with most missing data
        priority_order = [
            'REGION IV-A',      # 0/114 - completely missing
            'REGION IV-B',      # 0/69 - completely missing
            'NATIONAL CAPITAL REGION',  # 0/17 - completely missing
            'REGION IX',        # Missing Sulu province (18 munis)
            'REGION XIII',      # Almost done
            'REGION VIII',      # Some missing
            'REGION VII',       # Some missing
            'REGION VI',        # Some missing
            'BARMM',           # Missing several provinces
            'REGION V',         # Few missing
            'REGION X',         # Few missing
        ]
        
        # Reorder regions by priority
        ordered_regions = []
        for priority in priority_order:
            if priority in regions:
                ordered_regions.append(priority)
        
        # Add any remaining regions not in priority list
        for region in regions:
            if region not in ordered_regions:
                ordered_regions.append(region)
        
        regions = ordered_regions
        
        print(f"\nResuming - {len(regions)} regions remaining to scrape")
        print(f"Regions to scrape: {regions}")
        
        # Process all regions (not just BARMM)
        print(f"\nWill process {len(regions)} regions")
        
        for region_idx, region_name in enumerate(regions, 1):
            print(f"\n{'='*80}")
            print(f"REGION {region_idx}/{len(regions)}: {region_name}")
            print(f"{'='*80}")
            
            # Select region - this should enable the province dropdown
            region_input = find_input_by_placeholder(driver, "region")
            print(f"Selecting region: {region_name}...", flush=True)
            if not select_from_dropdown(driver, region_input, region_name):
                print("✗ Failed to select region")
                continue
            
            print("✓ Selected region, waiting for province dropdown to populate...")
            time.sleep(1)  # Wait for province dropdown to become active and populate
            
            # Now find and get provinces
            province_input = find_input_by_placeholder(driver, "province")
            if not province_input:
                province_input = find_input_by_placeholder(driver, "district")
            
            if not province_input:
                print("✗ Could not find province input")
                continue
            
            # Check if province input is enabled
            is_enabled = province_input.is_enabled()
            is_readonly = province_input.get_attribute("readonly")
            is_disabled = province_input.get_attribute("disabled")
            print(f"Province input - enabled: {is_enabled}, readonly: {is_readonly}, disabled: {is_disabled}")
            
            if not is_enabled or is_readonly or is_disabled:
                print("✗ Province input not ready after selecting region")
                continue
            
            print("Getting list of provinces...")
            provinces = click_dropdown_and_get_options(driver, province_input)
            
            # Filter out invalid items
            provinces = [p for p in provinces if p and len(p) > 2 and p.upper() not in ['LOCAL', 'OVERSEAS', 'SELECT', 'CHOOSE']]
            
            print(f"✓ Found {len(provinces)} provinces")
            if provinces:
                print(f"Provinces: {provinces}")
            else:
                print("✗ No valid provinces found")
                continue
            
            # Process each province
            for prov_idx, province_name in enumerate(provinces, 1):
                print(f"\nProvince {prov_idx}/{len(provinces)}: {province_name}")
                print("-" * 80)
                
                # Only reload and reselect region if NOT the first province
                if prov_idx > 1:
                    # Need to reload and reselect region for subsequent provinces
                    driver.get(url)
                    time.sleep(1.2)
                    
                    region_input = find_input_by_placeholder(driver, "region")
                    select_from_dropdown(driver, region_input, region_name)
                    time.sleep(0.5)
                
                # Select province
                province_input = find_input_by_placeholder(driver, "province")
                if not province_input:
                    province_input = find_input_by_placeholder(driver, "district")
                
                if not select_from_dropdown(driver, province_input, province_name):
                    print(f"  ✗ Failed to select province")
                    continue
                
                print("  ✓ Selected province, waiting for city dropdown...")
                time.sleep(0.8)  # Wait for city dropdown to become active
                
                # Find city input
                city_input = find_input_by_placeholder(driver, "city")
                if not city_input:
                    city_input = find_input_by_placeholder(driver, "municipality")
                
                if not city_input:
                    print(f"  ✗ Could not find city input")
                    continue
                
                # Check if city input is enabled
                is_enabled = city_input.is_enabled()
                print(f"  City input enabled: {is_enabled}")
                
                if not is_enabled:
                    print(f"  ✗ City input not enabled after selecting province")
                    continue
                
                cities = click_dropdown_and_get_options(driver, city_input)
                
                # Filter out invalid items
                cities = [c for c in cities if c and len(c) > 2 and c.upper() not in ['LOCAL', 'OVERSEAS', 'SELECT', 'CHOOSE']]
                
                print(f"  Found {len(cities)} cities/municipalities")
                if cities:
                    print(f"  Cities: {cities[:5]}...")  # Show first 5
                
                # Process each city
                for city_idx, city_name in enumerate(cities, 1):
                    total_cities += 1
                    
                    # Check if already scraped
                    if file_already_exists(region_name, province_name, city_name):
                        print(f"    {city_idx}/{len(cities)}. {city_name} - ✓ Skipped (already exists)")
                        successful_scrapes += 1
                        continue
                    
                    print(f"    {city_idx}/{len(cities)}. Scraping {city_name}...", flush=True)
                    
                    # For first city, region/province already selected from above
                    # For subsequent cities, just change the city dropdown - no reload needed
                    
                    # Select city
                    city_input = find_input_by_placeholder(driver, "city")
                    if not city_input:
                        city_input = find_input_by_placeholder(driver, "municipality")
                    if not select_from_dropdown(driver, city_input, city_name):
                        print(f"      ✗ Failed to select city")
                        failed_scrapes += 1
                        continue
                    
                    # Wait for results page to fully load
                    time.sleep(1)
                    
                    # Extract results
                    results = extract_results(driver, region_name, province_name, city_name)
                    
                    if len(results) == 0:
                        print(f"      ⚠ No results found (page may not have loaded)", flush=True)
                        failed_scrapes += 1
                    else:
                        success, filepath = save_to_csv(results, region_name, province_name, city_name)
                        if success:
                            print(f"      ✓ Saved {len(results)} results")
                            successful_scrapes += 1
                        else:
                            print(f"      ✗ Failed to save")
                            failed_scrapes += 1
    
    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()
        print("\n" + "=" * 80)
        print("SCRAPING COMPLETE")
        print("=" * 80)
        print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total cities: {total_cities}")
        print(f"Successful: {successful_scrapes}")
        print(f"Failed: {failed_scrapes}")
        print("=" * 80)

if __name__ == '__main__':
    main()
