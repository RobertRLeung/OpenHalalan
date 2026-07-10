"""
Scraper for 2022 COMELEC election results
URL: https://2022electionresults.comelec.gov.ph/#/coc/0
Uses AngularJS framework with autocomplete suggestions
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
    """Set up Chrome driver with stealth mode."""
    options = webdriver.ChromeOptions()
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

def wait_for_page_load(driver, initial_load=False):
    """Wait for page to load and be interactive."""
    if initial_load:
        time.sleep(5)
    else:
        time.sleep(2)
    
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

def find_input_by_placeholder(driver, placeholder_keyword):
    """Find input element by placeholder text keyword."""
    inputs = driver.find_elements(By.TAG_NAME, "input")
    for inp in inputs:
        placeholder = inp.get_attribute("placeholder") or ""
        if placeholder_keyword.lower() in placeholder.lower():
            return inp
    return None

def get_suggestions(driver, input_field, search_text=""):
    """
    Get autocomplete suggestions from an input field.
    Returns list of suggestion texts.
    """
    # Clear the field first
    input_field.clear()
    time.sleep(0.5)
    
    # Click to focus
    input_field.click()
    time.sleep(0.5)
    
    # Type minimal text to trigger dropdown showing all options
    # Empty string or space often shows all items
    input_field.send_keys("")
    time.sleep(2)
    
    # Check if suggestions appeared
    suggestions = driver.find_elements(By.CSS_SELECTOR, "li[class*='suggestion']")
    
    if not suggestions or len(suggestions) == 0:
        # Try typing a common character
        input_field.send_keys("a")
        time.sleep(2)
        suggestions = driver.find_elements(By.CSS_SELECTOR, "li[class*='suggestion']")
    
    # If still none, clear and try clicking again
    if not suggestions or len(suggestions) == 0:
        input_field.clear()
        time.sleep(0.5)
        input_field.click()
        time.sleep(2)
        suggestions = driver.find_elements(By.CSS_SELECTOR, "li[class*='suggestion']")
    
    suggestion_texts = []
    for sug in suggestions:
        try:
            if sug.is_displayed():
                text = sug.text.strip()
                if text:
                    suggestion_texts.append(text)
        except:
            pass
    
    # Remove duplicates while preserving order
    seen = set()
    unique_suggestions = []
    for s in suggestion_texts:
        if s not in seen:
            seen.add(s)
            unique_suggestions.append(s)
    
    return unique_suggestions

def select_option(driver, placeholder_keyword, option_text):
    """
    Select an option from autocomplete suggestions.
    Find input field fresh each time using placeholder keyword.
    """
    try:
        # Find input field fresh
        input_field = None
        for inp in driver.find_elements(By.CSS_SELECTOR, "input"):
            try:
                placeholder = inp.get_attribute("placeholder") or ""
                if placeholder and placeholder_keyword.lower() in placeholder.lower():
                    input_field = inp
                    break
            except:
                continue
        
        if not input_field:
            print(f"      Error: Could not find input with placeholder containing '{placeholder_keyword}'")
            return False
        
        # Scroll to input field
        driver.execute_script("arguments[0].scrollIntoView(true);", input_field)
        time.sleep(0.5)
        
        # Clear and type to trigger suggestions
        input_field.clear()
        time.sleep(0.5)
        
        # Type the full text
        input_field.send_keys(option_text)
        time.sleep(3)
        
        # Find and click the matching suggestion
        suggestions = driver.find_elements(By.CSS_SELECTOR, "li[class*='suggestion']")
        
        for sug in suggestions:
            try:
                if sug.is_displayed() and sug.text.strip().upper() == option_text.upper():
                    driver.execute_script("arguments[0].scrollIntoView(true);", sug)
                    time.sleep(0.3)
                    driver.execute_script("arguments[0].click();", sug)
                    time.sleep(2)
                    return True
            except Exception as e:
                continue
        
        # If exact match not found, try partial match
        for sug in suggestions:
            try:
                if sug.is_displayed() and option_text.upper() in sug.text.strip().upper():
                    driver.execute_script("arguments[0].scrollIntoView(true);", sug)
                    time.sleep(0.3)
                    driver.execute_script("arguments[0].click();", sug)
                    time.sleep(2)
                    return True
            except:
                continue
        
        print(f"      Error selecting option {option_text}: No matching suggestion found")
        return False
        
    except Exception as e:
        print(f"      Error selecting option {option_text}: {e}")
        return False

def get_results_data(driver, region, province, city):
    """
    Extract election results data from the current page.
    2022 site uses div-based layout with ng-binding classes.
    Returns list of result dictionaries with candidate data.
    """
    try:
        time.sleep(5)  # Wait for results to load
        
        results = []
        current_position = ""
        
        # Get all text content to parse positions and candidates
        body = driver.find_element(By.TAG_NAME, "body")
        page_text = body.text
        lines = [line.strip() for line in page_text.split('\n') if line.strip()]
        
        # Find position headers (they contain keywords like PRESIDENT, GOVERNOR, MAYOR, etc.)
        # Position headers should NOT contain parentheses (those are candidate names)
        position_keywords = ['PRESIDENT', 'VICE-PRESIDENT', 'SENATOR', 'REPRESENTATIVE', 
                            'GOVERNOR', 'VICE GOVERNOR', 'MAYOR', 'VICE MAYOR', 
                            'MEMBER, SANGGUNIANG', 'MEMBER, HOUSE OF REPRESENTATIVES']
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check if this line is a position header
            # Must contain keyword AND not have parentheses (which indicate candidate names)
            is_position = any(keyword in line.upper() for keyword in position_keywords) and '(' not in line
            
            if is_position:
                current_position = line
                i += 1
                
                # Skip header rows (Candidate, Votes, Percentage)
                while i < len(lines) and lines[i] in ['Candidate', 'Votes', 'Percentage', '']:
                    i += 1
                
                # Now parse candidates until we hit the next position or section
                rank = 1
                while i < len(lines):
                    candidate_line = lines[i]
                    
                    # Check if we've hit the next position or section
                    if any(keyword in candidate_line.upper() for keyword in position_keywords):
                        break
                    if candidate_line in ['National Positions', 'Local Positions', 'Total COCs Received from BOC']:
                        break
                    
                    # Try to parse candidate data
                    # Format: candidate name with party in parentheses
                    # Next line: votes
                    # Next line: percentage
                    
                    if '(' in candidate_line and ')' in candidate_line and i + 2 < len(lines):
                        # Extract candidate name and party
                        candidate_name = candidate_line[:candidate_line.rfind('(')].strip()
                        party = candidate_line[candidate_line.rfind('(')+1:candidate_line.rfind(')')].strip()
                        
                        # Get votes and percentage from next lines
                        votes_line = lines[i + 1]
                        percentage_line = lines[i + 2]
                        
                        # Check if these look like votes and percentage
                        if votes_line.replace(',', '').replace('.', '').isdigit() and '%' in percentage_line:
                            votes = votes_line.replace(',', '')
                            percentage = percentage_line
                            
                            results.append({
                                'region': region,
                                'province': province,
                                'city': city,
                                'position': current_position,
                                'rank': str(rank),
                                'candidate_name': candidate_name,
                                'party': party,
                                'votes': votes,
                                'percentage': percentage
                            })
                            
                            rank += 1
                            i += 3  # Skip past this candidate's data
                            continue
                    
                    i += 1
            else:
                i += 1
        
        return results
        
    except Exception as e:
        print(f"    Error extracting results: {e}")
        import traceback
        traceback.print_exc()
        return []

def file_already_exists(region, province, city, base_dir="2022_raw"):
    """Check if city CSV file already exists."""
    safe_region = region.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
    safe_province = province.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
    safe_city = city.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
    
    region_dir = Path(base_dir) / safe_region
    province_dir = region_dir / safe_province
    filename = f"{safe_region}_{safe_province}_{safe_city}.csv"
    filepath = province_dir / filename
    
    return filepath.exists()

def save_to_csv(results, region, province, city, base_dir="2022_raw"):
    """Save results to a CSV file with organized folder structure."""
    try:
        # Clean names for folder/file names
        safe_region = region.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
        safe_province = province.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
        safe_city = city.upper().replace(' ', '_').replace('-', '_').replace('/', '_')
        
        # Create directory structure
        region_dir = Path(base_dir) / safe_region
        province_dir = region_dir / safe_province
        province_dir.mkdir(parents=True, exist_ok=True)
        
        # Create filename and path
        filename = f"{safe_region}_{safe_province}_{safe_city}.csv"
        filepath = province_dir / filename
        
        # Write to CSV
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['region', 'province', 'city', 'position', 'rank', 'candidate_name', 'party', 'votes', 'percentage'])
            
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
        print(f"Error saving CSV: {e}")
        return False, None

def main():
    """Main scraping function."""
    url = "https://2022electionresults.comelec.gov.ph/#/coc/0"
    output_base = Path("2022_raw")
    output_base.mkdir(exist_ok=True)
    
    print("=" * 80)
    print("COMELEC 2022 Election Results Scraper")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    driver = setup_driver()
    
    total_cities = 0
    successful_scrapes = 0
    failed_scrapes = 0
    
    try:
        driver.get(url)
        wait_for_page_load(driver, initial_load=True)
        print("✓ Page loaded successfully\n")
        
        # Find input fields
        region_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[contains(@placeholder, 'Region')]"))
        )
        print("✓ Found region input field")
        
        # Get all regions
        print("\nFetching regions...")
        regions = get_suggestions(driver, region_input)
        print(f"✓ Found {len(regions)} regions\n")
        
        # Loop through all regions
        for region_idx, region in enumerate(regions, 1):
            print(f"\n{'='*80}")
            print(f"Region {region_idx}/{len(regions)}: {region}")
            print(f"{'='*80}")
            
            # Select region (find_input fresh each time)
            if not select_option(driver, "region", region):
                print(f"✗ Failed to select region: {region}")
                continue
            
            time.sleep(2)
            
            # Find province input
            try:
                province_inputs = driver.find_elements(By.TAG_NAME, "input")
                province_input = None
                
                for inp in province_inputs:
                    placeholder = inp.get_attribute("placeholder") or ""
                    if "province" in placeholder.lower() or "district" in placeholder.lower():
                        province_input = inp
                        break
                
                if not province_input:
                    print("✗ Could not find province input field")
                    continue
                
                # Get all provinces
                provinces = get_suggestions(driver, province_input)
                print(f"Found {len(provinces)} provinces\n")
                
                # Loop through provinces
                for province_idx, province in enumerate(provinces, 1):
                    print(f"\n  Province {province_idx}/{len(provinces)}: {province}")
                    
                    # Select province (find input fresh each time)
                    if not select_option(driver, "province", province):
                        print(f"  ✗ Failed to select province: {province}")
                        continue
                    
                    time.sleep(2)
                    
                    # Find municipality input
                    try:
                        city_inputs = driver.find_elements(By.TAG_NAME, "input")
                        city_input = None
                        
                        for inp in city_inputs:
                            placeholder = inp.get_attribute("placeholder") or ""
                            if "city" in placeholder.lower() or "municipality" in placeholder.lower():
                                city_input = inp
                                break
                        
                        if not city_input:
                            print("  ✗ Could not find city/municipality input field")
                            continue
                        
                        # Get all cities/municipalities
                        cities = get_suggestions(driver, city_input)
                        print(f"  Found {len(cities)} cities/municipalities")
                        
                        # Loop through cities
                        for city_idx, city in enumerate(cities, 1):
                            total_cities += 1
                            
                            # Check if already scraped
                            if file_already_exists(region, province, city):
                                print(f"    {city_idx}/{len(cities)}. {city} - Already scraped ✓")
                                successful_scrapes += 1
                                continue
                            
                            print(f"    {city_idx}/{len(cities)}. Scraping {city}...")
                            
                            # Reload page for clean state
                            driver.get(url)
                            wait_for_page_load(driver)
                            
                            # Re-select region
                            if not select_option(driver, "region", region):
                                print(f"      ✗ Failed to reselect region")
                                failed_scrapes += 1
                                continue
                            
                            # Re-select province
                            if not select_option(driver, "province", province):
                                print(f"      ✗ Failed to reselect province")
                                failed_scrapes += 1
                                continue
                            
                            # Select city
                            if not select_option(driver, "city", city) and not select_option(driver, "municipality", city):
                                print(f"      ✗ Failed to select city")
                                failed_scrapes += 1
                                continue
                            
                            # Get results
                            results = get_results_data(driver, region, province, city)
                            
                            if results:
                                success, filepath = save_to_csv(results, region, province, city)
                                if success:
                                    print(f"      ✓ Saved {len(results)} results")
                                    successful_scrapes += 1
                                else:
                                    print(f"      ✗ Failed to save results")
                                    failed_scrapes += 1
                            else:
                                print(f"      ✗ No results found - NOT saving empty file")
                                failed_scrapes += 1
                        
                    except Exception as e:
                        print(f"  ✗ Error processing cities for {province}: {e}")
                        continue
                        
            except Exception as e:
                print(f"✗ Error processing provinces for {region}: {e}")
                continue
        
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
