"""
Create ElectionWinners2004_2025.csv by:
1. Only including LOCAL positions (no national positions like Senator, President)
2. Aggregating votes at appropriate levels for each position
3. Determining winners
4. Merging with dynasty dataset
5. Standardizing position names to match dynasty format
"""

import pandas as pd
import os
from pathlib import Path
import re
from collections import defaultdict

# Valid local positions from dynasty dataset
VALID_POSITIONS = [
    'COUNCILOR',
    'MAYOR', 
    'VICE MAYOR',
    'PROVINCIAL BOARD MEMBER',
    'MEMBER, HOUSE OF REPRESENTATIVES',
    'GOVERNOR',
    'VICE GOVERNOR'
]

def standardize_position(position):
    """Standardize position names to match dynasty dataset format."""
    position = position.upper().strip()
    
    # Remove location-specific suffixes (already cleaned in previous step)
    # Map to standard names
    if 'GOVERNOR' in position and 'VICE' not in position:
        return 'GOVERNOR'
    elif 'VICE GOVERNOR' in position or 'VICE-GOVERNOR' in position:
        return 'VICE GOVERNOR'
    elif 'MAYOR' in position and 'VICE' not in position:
        return 'MAYOR'
    elif 'VICE MAYOR' in position or 'VICE-MAYOR' in position:
        return 'VICE MAYOR'
    elif 'COUNCILOR' in position or 'COUNCILLOR' in position or 'SANGGUNIANG' in position:
        # All council members map to COUNCILOR
        if 'SANGGUNIANG PANLALAWIGAN' in position:
            return 'PROVINCIAL BOARD MEMBER'
        else:
            return 'COUNCILOR'
    elif 'REPRESENTATIVE' in position or 'HOUSE OF REPRESENTATIVES' in position:
        return 'MEMBER, HOUSE OF REPRESENTATIVES'
    
    return None  # Filter out positions we don't want

def parse_candidate_name(candidate_name):
    """Parse candidate name into Last Name, First Name, Middle Name."""
    name = candidate_name.strip()
    
    # Expected format: "LAST NAME, FIRST NAME MIDDLE NAME"
    if ',' in name:
        parts = name.split(',', 1)
        last_name = parts[0].strip()
        rest = parts[1].strip() if len(parts) > 1 else ""
        
        # Split rest into first and middle names
        name_parts = rest.split()
        first_name = name_parts[0] if len(name_parts) > 0 else ""
        middle_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ""
        
        return last_name, first_name, middle_name
    else:
        # If no comma, try to split by spaces
        parts = name.split()
        if len(parts) >= 2:
            last_name = parts[-1]
            first_name = parts[0]
            middle_name = ' '.join(parts[1:-1]) if len(parts) > 2 else ""
            return last_name, first_name, middle_name
        elif len(parts) == 1:
            return parts[0], "", ""
        else:
            return name, "", ""

def get_aggregation_level(position_std):
    """Determine aggregation level for position."""
    if position_std in ['GOVERNOR', 'VICE GOVERNOR', 'PROVINCIAL BOARD MEMBER', 'MEMBER, HOUSE OF REPRESENTATIVES']:
        return 'provincial'
    elif position_std in ['MAYOR', 'VICE MAYOR', 'COUNCILOR']:
        return 'municipal'
    return None

def load_2025_data():
    """Load all 2025 election data from CSV files."""
    print("Loading 2025 election data...")
    
    data_path = Path('2025')
    all_data = []
    
    csv_files = list(data_path.rglob('*.csv'))
    print(f"Found {len(csv_files)} CSV files")
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            all_data.append(df)
        except Exception as e:
            print(f"Error reading {csv_file}: {e}")
    
    combined_df = pd.concat(all_data, ignore_index=True)
    print(f"Loaded {len(combined_df)} total records")
    
    return combined_df

def load_2022_reference_counts():
    """Load 2022 data to get reference counts for multi-winner positions."""
    print("\nLoading 2022 reference data...")
    dynasty_df = pd.read_csv('data/Political Dynasty v8.5.csv')
    df_2022 = dynasty_df[dynasty_df['Year'] == 2022]
    
    # Get councilor counts per city in 2022 (typically 8)
    councilors_2022 = df_2022[df_2022['Position'] == 'COUNCILOR']
    # Most cities have 8, use 8 as default
    councilors_per_city = 8
    
    # Get board member counts per province in 2022
    board_2022 = df_2022[df_2022['Position'] == 'PROVINCIAL BOARD MEMBER']
    board_per_prov = board_2022.groupby('Province').size().to_dict()
    
    print(f"  Councilors per city: {councilors_per_city}")
    print(f"  Board members per province: {len(board_per_prov)} provinces with counts")
    
    return councilors_per_city, board_per_prov

def aggregate_and_find_winners(df, councilors_per_city, board_per_prov):
    """Aggregate votes and determine winners at each level."""
    print("\nAggregating votes and determining winners...")
    
    # Convert votes to numeric, removing commas
    df['votes_numeric'] = pd.to_numeric(df['votes'].astype(str).str.replace(',', ''), errors='coerce')
    
    # Standardize positions
    df['position_std'] = df['position'].apply(standardize_position)
    
    # Filter to only valid positions
    df = df[df['position_std'].isin(VALID_POSITIONS)].copy()
    print(f"After filtering to local positions: {len(df)} records")
    
    # Add aggregation level
    df['agg_level'] = df['position_std'].apply(get_aggregation_level)
    
    winners = []
    
    # Process provincial-level positions (Governor, Vice Governor, Board Member, Representative)
    print("\nProcessing provincial-level positions...")
    prov_df = df[df['agg_level'] == 'provincial'].copy()
    
    if len(prov_df) > 0:
        # Aggregate votes by province
        prov_agg = prov_df.groupby(['position_std', 'province', 'candidate_name', 'party'], as_index=False).agg({
            'votes_numeric': 'sum',
            'region': 'first',
            'city': 'first',  # Keep one city for reference
            'agg_level': 'first'
        })
        
        # Find winners for each position in each province
        for (position, province), group in prov_agg.groupby(['position_std', 'province']):
            # Sort by votes
            group_sorted = group.sort_values('votes_numeric', ascending=False)
            
            if position == 'PROVINCIAL BOARD MEMBER':
                # Multiple winners - use 2022 count as reference
                num_winners = board_per_prov.get(province, 8)  # Default to 8 if province not in 2022 data
                for idx, row in group_sorted.head(num_winners).iterrows():
                    winners.append(row)
            else:
                # Single winner (Governor, Vice Governor, Representative)
                winners.append(group_sorted.iloc[0])
        
        prov_count = len([w for w in winners])
        print(f"  Found {prov_count} provincial-level winners")
    
    # Process municipal-level positions (Mayor, Vice Mayor, Councilor)
    print("\nProcessing municipal-level positions...")
    muni_df = df[df['agg_level'] == 'municipal'].copy()
    
    if len(muni_df) > 0:
        muni_count = 0
        for (position, province, city), group in muni_df.groupby(['position_std', 'province', 'city']):
            # Sort by votes
            group_sorted = group.sort_values('votes_numeric', ascending=False)
            
            if position == 'COUNCILOR':
                # Take top N councilors (typically 8)
                for idx, row in group_sorted.head(councilors_per_city).iterrows():
                    winners.append(row)
                    muni_count += 1
            else:
                # Mayor and Vice Mayor - single winner
                winners.append(group_sorted.iloc[0])
                muni_count += 1
        
        print(f"  Found {muni_count} municipal-level winners")
    
    winners_df = pd.DataFrame(winners)
    print(f"\nTotal winners identified: {len(winners_df)}")
    
    # Show breakdown by position
    print("\nWinners by position:")
    print(winners_df['position_std'].value_counts())
    
    return winners_df

def create_final_dataset(winners_df, dynasty_df):
    """Create final dataset matching dynasty format."""
    print("\nCreating final dataset...")
    
    # Parse candidate names
    names = winners_df['candidate_name'].apply(parse_candidate_name)
    winners_df['Last Name'] = names.apply(lambda x: x[0])
    winners_df['First Name'] = names.apply(lambda x: x[1])
    winners_df['Middle Name'] = names.apply(lambda x: x[2])
    
    # Create final dataframe matching dynasty format (without Community and Position Weight)
    final_df = pd.DataFrame({
        'Last Name': winners_df['Last Name'],
        'First Name': winners_df['First Name'],
        'Middle Name': winners_df['Middle Name'],
        'Position': winners_df['position_std'],
        'Party': winners_df['party'],
        'Year': 2025,
        'Province': winners_df['province'],
        'Region': winners_df['region'],
        'Full Name': winners_df['candidate_name']
    })
    
    # Remove Community and Position Weight from dynasty dataset too
    dynasty_clean = dynasty_df[['Last Name', 'First Name', 'Middle Name', 'Position', 
                                  'Party', 'Year', 'Province', 'Region', 'Full Name']].copy()
    
    # Combine with dynasty dataset
    combined_df = pd.concat([dynasty_clean, final_df], ignore_index=True)
    
    # Sort by Year, Province, Position
    combined_df = combined_df.sort_values(['Year', 'Province', 'Position'])
    
    return combined_df

def main():
    print("=" * 80)
    print("Creating Election Winners Dataset (2004-2025)")
    print("=" * 80)
    
    # Load dynasty dataset
    print("\nLoading dynasty dataset...")
    dynasty_df = pd.read_csv('data/Political Dynasty v8.5.csv')
    print(f"Dynasty dataset: {len(dynasty_df)} records (2004-2022)")
    print(f"Positions in dynasty data: {dynasty_df['Position'].unique()}")
    
    # Load 2022 reference counts for multi-winner positions
    councilors_per_city, board_per_prov = load_2022_reference_counts()
    
    # Load 2025 data
    df_2025 = load_2025_data()
    
    # Find winners
    winners_df = aggregate_and_find_winners(df_2025, councilors_per_city, board_per_prov)
    
    # Create final dataset
    final_df = create_final_dataset(winners_df, dynasty_df)
    
    # Save to CSV
    output_file = 'LocalElectionWinners2004_2025.csv'
    final_df.to_csv(output_file, index=False)
    
    print("\n" + "=" * 80)
    print("COMPLETE")
    print("=" * 80)
    print(f"Output file: {output_file}")
    print(f"Total records: {len(final_df)}")
    print(f"  - 2004-2022: {len(dynasty_df)}")
    print(f"  - 2025: {len(winners_df)}")
    print("\nColumns: {', '.join(final_df.columns.tolist())}")
    print("=" * 80)

if __name__ == "__main__":
    main()
