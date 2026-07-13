"""
Clean position names across all CSV files.
Standardizes position names by removing location-specific suffixes like " of PROVINCE"
"""

import csv
import os
import re
from glob import glob

def clean_position_name(position):
    """
    Clean position name by removing location-specific suffixes.
    
    Examples:
    - "SENATOR of PHILIPPINES" -> "SENATOR"
    - "MAYOR of ILOCOS NORTE - ADAMS" -> "MAYOR"
    - "MEMBER, HOUSE OF REPRESENTATIVES of ILOCOS NORTE - FIRST LEGDIST" -> "MEMBER, HOUSE OF REPRESENTATIVES"
    """
    # Remove " of [LOCATION]" pattern
    cleaned = re.sub(r'\s+of\s+[A-Z\s\-,]+$', '', position)
    
    # Also remove district information like "- FIRST LEGDIST", "- LONE DIST", etc.
    cleaned = re.sub(r'\s+-\s+[A-Z\s\-]+$', '', cleaned)
    
    return cleaned.strip()

def process_csv_file(filepath):
    """Process a single CSV file and clean position names."""
    # Read the file
    rows = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Clean the position name
            row['position'] = clean_position_name(row['position'])
            rows.append(row)
    
    # Write back to the file
    if rows:
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['region', 'province', 'city', 'position', 'rank', 'candidate_name', 'party', 'votes', 'percentage']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        return len(rows)
    return 0

def main():
    """Main function to process all CSV files."""
    print("=" * 80)
    print("Position Name Cleaner")
    print("=" * 80)
    
    # Find all CSV files in the data directory
    csv_files = glob('data/**/*.csv', recursive=True)
    
    print(f"\nFound {len(csv_files)} CSV files to process\n")
    
    total_records = 0
    files_processed = 0
    
    for csv_file in csv_files:
        try:
            records = process_csv_file(csv_file)
            total_records += records
            files_processed += 1
            
            if files_processed % 50 == 0:
                print(f"Processed {files_processed}/{len(csv_files)} files...")
        except Exception as e:
            print(f"Error processing {csv_file}: {e}")
    
    print(f"\n" + "=" * 80)
    print(f"CLEANING COMPLETE")
    print("=" * 80)
    print(f"Files processed: {files_processed}")
    print(f"Total records cleaned: {total_records}")
    print("=" * 80)

if __name__ == "__main__":
    main()
