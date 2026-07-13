"""
Reorganize data structure:
1. Move all data into a '2025' folder
2. Fix misplaced provinces (NIR provinces should be in Region VII, LAV needs investigation)
3. Verify all Philippine provinces are present
"""

import os
import shutil
from pathlib import Path

def reorganize_structure():
    """Reorganize the data directory structure."""
    
    base_path = Path('/Users/robertnelsonleung/ThePhilippineElectionProject')
    data_path = base_path / 'data'
    new_data_path = base_path / '2025'
    
    print("=" * 80)
    print("Data Structure Reorganization")
    print("=" * 80)
    
    # Create 2025 directory
    new_data_path.mkdir(exist_ok=True)
    print(f"\n✓ Created {new_data_path}")
    
    # Define the correct province mappings
    province_mapping = {
        # NIR provinces should be merged into their respective regions
        'NIR/NEGROS_OCCIDENTAL': 'REGION_VI/NEGROS_OCCIDENTAL',  # Region VI (Western Visayas)
        'NIR/NEGROS_ORIENTAL': 'REGION_VII/NEGROS_ORIENTAL',      # Region VII (Central Visayas)
        'NIR/SIQUIJOR': 'REGION_VII/SIQUIJOR',                     # Region VII (Central Visayas)
    }
    
    # First, handle NIR reorganization before moving
    print("\n" + "=" * 80)
    print("Fixing NIR province locations...")
    print("=" * 80)
    
    for old_path, new_path in province_mapping.items():
        old_full = data_path / old_path
        new_full = data_path / new_path
        
        if old_full.exists():
            print(f"\n  Moving {old_path} -> {new_path}")
            new_full.parent.mkdir(parents=True, exist_ok=True)
            
            # Move the directory
            if new_full.exists():
                # Merge if target exists
                print(f"    Target exists, merging contents...")
                for item in old_full.iterdir():
                    shutil.move(str(item), str(new_full / item.name))
                old_full.rmdir()
            else:
                shutil.move(str(old_full), str(new_full))
            
            print(f"    ✓ Moved successfully")
    
    # Remove empty NIR directory
    nir_path = data_path / 'NIR'
    if nir_path.exists() and not any(nir_path.iterdir()):
        nir_path.rmdir()
        print(f"\n  ✓ Removed empty NIR directory")
    
    # Handle LAV - check what it actually is
    lav_csv = data_path / 'LAV' / 'LAV' / 'LAV_LAV_LAV.csv'
    if lav_csv.exists():
        print("\n" + "=" * 80)
        print("Investigating LAV...")
        print("=" * 80)
        # Read first line to see what region it actually belongs to
        with open(lav_csv, 'r') as f:
            lines = f.readlines()[:3]
            print("  LAV file contents:")
            for line in lines:
                print(f"    {line.strip()}")
        
        # LAV seems to be a special voting district or erroneous entry
        # For now, keep it but flag it
        print("\n  ⚠️  LAV appears to be incomplete/special district - keeping as-is for manual review")
    
    # Now move everything to 2025 folder
    print("\n" + "=" * 80)
    print("Moving all data to 2025 folder...")
    print("=" * 80)
    
    for region_dir in data_path.iterdir():
        if region_dir.is_dir() and region_dir.name not in ['2025', '.DS_Store']:
            target = new_data_path / region_dir.name
            print(f"\n  Moving {region_dir.name} -> 2025/{region_dir.name}")
            shutil.move(str(region_dir), str(target))
            print(f"    ✓ Moved")
    
    print("\n" + "=" * 80)
    print("Reorganization Complete!")
    print("=" * 80)

def verify_provinces():
    """Verify all Philippine provinces are present."""
    
    print("\n" + "=" * 80)
    print("Verifying Philippine Provinces")
    print("=" * 80)
    
    # All provinces in the Philippines organized by region
    expected_provinces = {
        'REGION_I': ['ILOCOS_NORTE', 'ILOCOS_SUR', 'LA_UNION', 'PANGASINAN'],
        'REGION_II': ['BATANES', 'CAGAYAN', 'ISABELA', 'NUEVA_VIZCAYA', 'QUIRINO'],
        'REGION_III': ['AURORA', 'BATAAN', 'BULACAN', 'NUEVA_ECIJA', 'PAMPANGA', 'TARLAC', 'ZAMBALES'],
        'REGION_IV-A': ['BATANGAS', 'CAVITE', 'LAGUNA', 'QUEZON', 'RIZAL'],
        'REGION_IV-B': ['MARINDUQUE', 'OCCIDENTAL_MINDORO', 'ORIENTAL_MINDORO', 'PALAWAN', 'ROMBLON'],
        'REGION_V': ['ALBAY', 'CAMARINES_NORTE', 'CAMARINES_SUR', 'CATANDUANES', 'MASBATE', 'SORSOGON'],
        'REGION_VI': ['AKLAN', 'ANTIQUE', 'CAPIZ', 'GUIMARAS', 'ILOILO', 'NEGROS_OCCIDENTAL'],
        'REGION_VII': ['BOHOL', 'CEBU', 'NEGROS_ORIENTAL', 'SIQUIJOR'],
        'REGION_VIII': ['BILIRAN', 'EASTERN_SAMAR', 'LEYTE', 'NORTHERN_SAMAR', 'SAMAR', 'SOUTHERN_LEYTE'],
        'REGION_IX': ['SULU', 'ZAMBOANGA_DEL_NORTE', 'ZAMBOANGA_DEL_SUR', 'ZAMBOANGA_SIBUGAY'],
        'REGION_X': ['BUKIDNON', 'CAMIGUIN', 'LANAO_DEL_NORTE', 'MISAMIS_OCCIDENTAL', 'MISAMIS_ORIENTAL'],
        'REGION_XI': ['DAVAO_DE_ORO', 'DAVAO_DEL_NORTE', 'DAVAO_DEL_SUR', 'DAVAO_OCCIDENTAL', 'DAVAO_ORIENTAL'],
        'REGION_XII': ['COTABATO', 'SARANGANI', 'SOUTH_COTABATO', 'SULTAN_KUDARAT'],
        'REGION_XIII': ['AGUSAN_DEL_NORTE', 'AGUSAN_DEL_SUR', 'DINAGAT_ISLANDS', 'SURIGAO_DEL_NORTE', 'SURIGAO_DEL_SUR'],
        'BARMM': ['BASILAN', 'LANAO_DEL_SUR', 'MAGUINDANAO_DEL_NORTE', 'MAGUINDANAO_DEL_SUR', 'TAWI-TAWI'],
        'CORDILLERA_ADMINISTRATIVE_REGION': ['ABRA', 'APAYAO', 'BENGUET', 'IFUGAO', 'KALINGA', 'MOUNTAIN_PROVINCE'],
        'NATIONAL_CAPITAL_REGION': ['NCR'],  # Metro Manila is special
    }
    
    base_path = Path('/Users/robertnelsonleung/ThePhilippineElectionProject/2025')
    
    print("\nChecking provinces by region:\n")
    
    all_present = True
    missing_provinces = []
    found_provinces = []
    
    for region, provinces in sorted(expected_provinces.items()):
        region_path = base_path / region
        print(f"\n{region}:")
        
        if not region_path.exists():
            print(f"  ⚠️  REGION DIRECTORY NOT FOUND")
            missing_provinces.extend([(region, p) for p in provinces])
            all_present = False
            continue
        
        for province in provinces:
            if province == 'NCR':
                # NCR has special structure
                if any(region_path.iterdir()):
                    print(f"  ✓ {province}")
                    found_provinces.append((region, province))
                else:
                    print(f"  ✗ {province} - MISSING")
                    missing_provinces.append((region, province))
                    all_present = False
            else:
                province_path = region_path / province
                if province_path.exists() and province_path.is_dir():
                    csv_count = len(list(province_path.glob('*.csv')))
                    print(f"  ✓ {province} ({csv_count} municipalities)")
                    found_provinces.append((region, province))
                else:
                    # Check for alternative naming
                    alternatives = list(region_path.glob(f"*{province.replace('_', '*')}*"))
                    if alternatives:
                        print(f"  ⚠️  {province} - found as {alternatives[0].name}")
                        found_provinces.append((region, province))
                    else:
                        print(f"  ✗ {province} - MISSING")
                        missing_provinces.append((region, province))
                        all_present = False
    
    print("\n" + "=" * 80)
    print("Summary:")
    print("=" * 80)
    print(f"Total expected provinces: {sum(len(p) for p in expected_provinces.values())}")
    print(f"Found: {len(found_provinces)}")
    print(f"Missing: {len(missing_provinces)}")
    
    if missing_provinces:
        print("\nMissing provinces:")
        for region, province in missing_provinces:
            print(f"  - {region}/{province}")
    
    if all_present:
        print("\n✓ All provinces accounted for!")
    else:
        print("\n⚠️  Some provinces are missing or need attention")
    
    return all_present

if __name__ == "__main__":
    reorganize_structure()
    verify_provinces()
