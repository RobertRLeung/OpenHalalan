#!/usr/bin/env python3
"""
Check which 2022 municipalities are missing by comparing 2025 folder structure with 2022_raw
"""

from pathlib import Path
import sys

def normalize_name(name):
    """Normalize a region/province/city name for comparison."""
    return name.upper().replace(' ', '_').replace('-', '_').replace('/', '_')

def get_2025_structure():
    """Get the complete structure from 2025 folder."""
    base_2025 = Path('/Users/robertnelsonleung/ThePhilippineElectionProject/2025')
    structure = {}
    
    if not base_2025.exists():
        print(f"Error: 2025 folder not found at {base_2025}")
        return structure
    
    for region_dir in sorted(base_2025.iterdir()):
        if not region_dir.is_dir():
            continue
        
        region_name = region_dir.name
        structure[region_name] = {}
        
        for province_dir in sorted(region_dir.iterdir()):
            if not province_dir.is_dir():
                continue
            
            province_name = province_dir.name
            
            # Get all CSV files (municipalities)
            csv_files = list(province_dir.glob('*.csv'))
            municipalities = []
            
            for csv_file in csv_files:
                # Extract municipality name from filename
                # Format: REGION_PROVINCE_MUNICIPALITY.csv
                filename = csv_file.stem
                parts = filename.split('_')
                
                # Find where municipality starts (after region and province parts)
                # This is tricky because region and province can have multiple words
                muni_name = '_'.join(parts[2:]) if len(parts) > 2 else ''
                
                if muni_name:
                    municipalities.append(muni_name)
            
            structure[region_name][province_name] = sorted(municipalities)
    
    return structure

def get_2022_structure():
    """Get the complete structure from 2022_raw folder."""
    base_2022 = Path('/Users/robertnelsonleung/ThePhilippineElectionProject/2022_raw')
    structure = {}
    
    if not base_2022.exists():
        print(f"Error: 2022_raw folder not found at {base_2022}")
        return structure
    
    for region_dir in sorted(base_2022.iterdir()):
        if not region_dir.is_dir():
            continue
        
        region_name = region_dir.name
        structure[region_name] = {}
        
        for province_dir in sorted(region_dir.iterdir()):
            if not province_dir.is_dir():
                continue
            
            province_name = province_dir.name
            
            # Get all CSV files (municipalities)
            csv_files = list(province_dir.glob('*.csv'))
            municipalities = []
            
            for csv_file in csv_files:
                # Extract municipality name from filename
                filename = csv_file.stem
                parts = filename.split('_')
                
                # Find where municipality starts (after region and province parts)
                muni_name = '_'.join(parts[2:]) if len(parts) > 2 else ''
                
                if muni_name:
                    municipalities.append(muni_name)
            
            structure[region_name][province_name] = sorted(municipalities)
    
    return structure

def main():
    print("=" * 80)
    print("CHECKING FOR MISSING 2022 MUNICIPALITIES")
    print("=" * 80)
    print()
    
    print("Loading 2025 structure...")
    structure_2025 = get_2025_structure()
    print(f"✓ Found {len(structure_2025)} regions in 2025 folder")
    
    print("Loading 2022_raw structure...")
    structure_2022 = get_2022_structure()
    print(f"✓ Found {len(structure_2022)} regions in 2022_raw folder")
    print()
    
    total_missing = 0
    total_expected = 0
    total_scraped = 0
    regions_with_missing = []
    
    # Compare structures
    for region_name, provinces_2025 in sorted(structure_2025.items()):
        region_missing = 0
        region_expected = 0
        region_scraped = 0
        
        provinces_2022 = structure_2022.get(region_name, {})
        
        for province_name, munis_2025 in sorted(provinces_2025.items()):
            munis_2022 = provinces_2022.get(province_name, [])
            
            expected = len(munis_2025)
            scraped = len(munis_2022)
            missing = set(munis_2025) - set(munis_2022)
            
            region_expected += expected
            region_scraped += scraped
            
            if missing:
                if region_missing == 0:
                    print(f"{'='*80}")
                    print(f"REGION: {region_name}")
                    print(f"{'='*80}")
                
                region_missing += len(missing)
                print(f"\n  Province: {province_name}")
                print(f"  Expected: {expected} | Scraped: {scraped} | Missing: {len(missing)}")
                print(f"  Missing municipalities:")
                for muni in sorted(missing):
                    print(f"    - {muni}")
        
        if region_missing > 0:
            regions_with_missing.append(region_name)
            print(f"\n  {region_name} TOTAL: {region_scraped}/{region_expected} municipalities")
            print(f"  Missing: {region_missing} municipalities")
            print()
        
        total_expected += region_expected
        total_scraped += region_scraped
        total_missing += region_missing
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total municipalities expected: {total_expected}")
    print(f"Total municipalities scraped: {total_scraped}")
    print(f"Total municipalities missing: {total_missing}")
    print(f"Completion: {total_scraped}/{total_expected} ({100*total_scraped/total_expected:.1f}%)")
    print()
    
    if regions_with_missing:
        print(f"Regions with missing data ({len(regions_with_missing)}):")
        for region in regions_with_missing:
            print(f"  - {region}")
    else:
        print("✓ All regions complete!")
    
    print("=" * 80)

if __name__ == '__main__':
    main()
