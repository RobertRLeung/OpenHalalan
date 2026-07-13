"""
Merge 2022 and 2025 scraped data into NLE_Winners_2004_2025.csv
Replaces existing 2022 and 2025 entries with our newly scraped data.
"""

import pandas as pd
from datetime import datetime

def standardize_name(full_name):
    """
    Parse full name into Last Name, First Name, Middle Name.
    Handles formats like "SURNAME, FIRSTNAME MIDDLENAME"
    """
    if pd.isna(full_name) or not full_name:
        return None, None, None
    
    name = str(full_name).strip()
    
    # Check if name has comma (LASTNAME, FIRSTNAME format)
    if ',' in name:
        parts = name.split(',', 1)
        last_name = parts[0].strip()
        rest = parts[1].strip() if len(parts) > 1 else ''
        
        # Split rest into first and middle
        rest_parts = rest.split()
        first_name = rest_parts[0] if rest_parts else ''
        middle_name = ' '.join(rest_parts[1:]) if len(rest_parts) > 1 else ''
    else:
        # No comma, assume FIRSTNAME MIDDLENAME LASTNAME format
        parts = name.split()
        if len(parts) >= 2:
            first_name = parts[0]
            last_name = parts[-1]
            middle_name = ' '.join(parts[1:-1]) if len(parts) > 2 else ''
        elif len(parts) == 1:
            first_name = parts[0]
            last_name = ''
            middle_name = ''
        else:
            first_name = ''
            last_name = ''
            middle_name = ''
    
    return last_name, first_name, middle_name


def convert_to_nle_format(df, year):
    """
    Convert our scraped data format to NLE format.
    
    Our format: region, province, city, position, district, candidate_name, party, votes, rank, raw_position
    NLE format: Last Name, First Name, Middle Name, Position, Party, Year, Province, Region, Position Weight, Full Name, Community
    """
    records = []
    
    for _, row in df.iterrows():
        last_name, first_name, middle_name = standardize_name(row['candidate_name'])
        
        # Position weight (importance): 
        # 1=National, 2=Provincial, 3=Municipal
        if row['position'] in ['MEMBER, HOUSE OF REPRESENTATIVES']:
            position_weight = 1.5  # Between national and provincial
        elif row['position'] in ['GOVERNOR', 'VICE GOVERNOR', 'PROVINCIAL BOARD MEMBER']:
            position_weight = 2.0
        else:  # MAYOR, VICE MAYOR, COUNCILOR
            position_weight = 3.0
        
        # Community is city for municipal positions, empty for provincial
        community = row.get('city', '') if pd.notna(row.get('city')) else ''
        
        records.append({
            'Last Name': last_name,
            'First Name': first_name,
            'Middle Name': middle_name,
            'Position': row['position'],
            'Party': row.get('party', ''),
            'Year': year,
            'Province': row.get('province', ''),
            'Region': row.get('region', ''),
            'Position Weight': position_weight,
            'Full Name': row['candidate_name'],
            'Community': community
        })
    
    return pd.DataFrame(records)


def main():
    print("="*80)
    print("Merging 2022 and 2025 Data into NLE Dataset")
    print("="*80)
    
    # Load existing NLE data
    print("\nLoading NLE_Winners_2004_2025.csv...")
    nle_df = pd.read_csv('NLE_Winners_2004_2025.csv', low_memory=False)
    print(f"Original NLE records: {len(nle_df):,}")
    
    # Show year distribution before
    print("\nRecords by year (before):")
    print(nle_df['Year'].value_counts().sort_index())
    
    # Load our scraped data
    print("\nLoading scraped 2022 data...")
    winners_2022 = pd.read_csv('winners_2022.csv')
    print(f"2022 records: {len(winners_2022):,}")
    
    print("\nLoading scraped 2025 data...")
    winners_2025 = pd.read_csv('winners_2025.csv')
    print(f"2025 records: {len(winners_2025):,}")
    
    # Convert to NLE format
    print("\nConverting 2022 to NLE format...")
    nle_2022 = convert_to_nle_format(winners_2022, 2022)
    
    print("Converting 2025 to NLE format...")
    nle_2025 = convert_to_nle_format(winners_2025, 2025)
    
    # Remove existing 2022 and 2025 entries from NLE
    print("\nRemoving old 2022 and 2025 entries from NLE...")
    old_2022_count = len(nle_df[nle_df['Year'] == 2022])
    old_2025_count = len(nle_df[nle_df['Year'] == 2025])
    print(f"Removing {old_2022_count:,} old 2022 records")
    print(f"Removing {old_2025_count:,} old 2025 records")
    
    nle_df = nle_df[~nle_df['Year'].isin([2022, 2025])]
    print(f"NLE records after removal: {len(nle_df):,}")
    
    # Append new data
    print("\nAppending new 2022 and 2025 data...")
    nle_df = pd.concat([nle_df, nle_2022, nle_2025], ignore_index=True)
    
    # Sort by year and position
    nle_df = nle_df.sort_values(['Year', 'Province', 'Position', 'Last Name'])
    
    print(f"Final NLE records: {len(nle_df):,}")
    print("\nRecords by year (after):")
    print(nle_df['Year'].value_counts().sort_index())
    
    # Save updated dataset
    output_file = 'NLE_Winners_2004_2025_updated.csv'
    print(f"\nSaving updated dataset to {output_file}...")
    nle_df.to_csv(output_file, index=False)
    
    print("\n" + "="*80)
    print("Merge Complete!")
    print("="*80)
    print(f"\n✓ Original file preserved: NLE_Winners_2004_2025.csv")
    print(f"✓ Updated file saved as: {output_file}")
    print(f"\nChanges:")
    print(f"  2022: {old_2022_count:,} → {len(nle_2022):,} ({len(nle_2022)-old_2022_count:+,})")
    print(f"  2025: {old_2025_count:,} → {len(nle_2025):,} ({len(nle_2025)-old_2025_count:+,})")
    print(f"  Total: {len(nle_df):,} records")
    
    return nle_df


if __name__ == '__main__':
    main()
