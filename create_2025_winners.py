"""
Create 2025 winners dataset with proper aggregation levels:
1. Municipal level: Mayor (1), Vice Mayor (1), Councilors (variable per city)
2. Provincial level: Governor (1), Vice Governor (1), Provincial Board Members (variable per province)
3. District level: Representatives (1 per district)
"""

import pandas as pd
from pathlib import Path
import re

def load_2019_reference_counts():
    """
    Load 2019 data to determine number of provincial board members per province.
    """
    dynasty_df = pd.read_csv('data/Political Dynasty v8.5.csv')
    dynasty_2019 = dynasty_df[dynasty_df['Year'] == 2019].copy()
    
    # Board members per province (varies by province: 6-25)
    board_per_prov = dynasty_2019[dynasty_2019['Position'] == 'PROVINCIAL BOARD MEMBER'].groupby(
        'Province'
    ).size().to_dict()
    
    print(f"Loaded 2019 reference counts:")
    print(f"  Board members: {len(board_per_prov)} province records")
    print(f"  Board member range: {min(board_per_prov.values())}-{max(board_per_prov.values())}")
    print(f"  Using fixed default of 8 councilors per municipality (Philippine standard)")
    
    return board_per_prov


def extract_district(position_text):
    """
    Extract district information from position names.
    Returns: district identifier (e.g., 'FIRST LEGDIST', 'SECOND PROVDIST', 'LONE DIST')
    """
    # Look for district patterns
    district_match = re.search(r'(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|LONE)\s+(LEGDIST|PROVDIST|DIST)', position_text, re.IGNORECASE)
    if district_match:
        return district_match.group(0).upper()
    return 'UNKNOWN'


def standardize_position(raw_position):
    """
    Map raw position names to standard format used in dynasty dataset.
    Returns: (standard_position, district)
    """
    position = raw_position.strip().upper()
    district = extract_district(position)
    
    # Map to standard positions
    if 'SANGGUNIANG BAYAN' in position:
        return 'COUNCILOR', district
    elif 'SANGGUNIANG PANLUNGSOD' in position:
        return 'COUNCILOR', district
    elif 'SANGGUNIANG PANLALAWIGAN' in position:
        return 'PROVINCIAL BOARD MEMBER', district
    elif 'HOUSE OF REPRESENTATIVES' in position:
        return 'MEMBER, HOUSE OF REPRESENTATIVES', district
    elif 'PROVINCIAL GOVERNOR' in position:
        return 'GOVERNOR', None
    elif 'PROVINCIAL VICE-GOVERNOR' in position:
        return 'VICE GOVERNOR', None
    elif position.startswith('MAYOR'):
        return 'MAYOR', None
    elif position.startswith('VICE-MAYOR'):
        return 'VICE MAYOR', None
    
    return None, None


def main():
    print("="*80)
    print("Creating 2025 Winners Dataset")
    print("="*80)
    
    # Load 2019 reference data
    board_per_prov = load_2019_reference_counts()
    
    # Standard number of councilors in Philippine municipalities (can be 8, 10, or 12 depending on class)
    # Using 8 as default for most municipalities
    DEFAULT_COUNCILORS = 8
    
    # Load all 2025_raw data
    print("\nLoading 2025_raw data...")
    all_data = []
    csv_files = list(Path('2025_raw').rglob('*.csv'))
    print(f"Found {len(csv_files)} CSV files")
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            all_data.append(df)
        except Exception as e:
            print(f"Error reading {csv_file}: {e}")
    
    df = pd.concat(all_data, ignore_index=True)
    print(f"Total records loaded: {len(df):,}")
    
    # Standardize positions and extract districts
    print("\nStandardizing positions...")
    df[['standard_position', 'district']] = df['position'].apply(
        lambda x: pd.Series(standardize_position(x))
    )
    
    # Filter to local positions only
    local_positions = [
        'MAYOR', 'VICE MAYOR', 'COUNCILOR',
        'GOVERNOR', 'VICE GOVERNOR', 'PROVINCIAL BOARD MEMBER',
        'MEMBER, HOUSE OF REPRESENTATIVES'
    ]
    
    df = df[df['standard_position'].isin(local_positions)].copy()
    print(f"Records after filtering to local positions: {len(df):,}")
    
    # Show position distribution
    print("\nPosition distribution:")
    print(df['standard_position'].value_counts())
    
    # Convert votes to numeric
    df['votes'] = pd.to_numeric(df['votes'], errors='coerce').fillna(0).astype(int)
    
    # Process winners by position type
    winners = []
    
    print("\n" + "="*80)
    print("STEP 1: Municipal Level Winners (Mayor, Vice Mayor, Councilors)")
    print("="*80)
    
    for position in ['MAYOR', 'VICE MAYOR', 'COUNCILOR']:
        position_df = df[df['standard_position'] == position].copy()
        
        for (province, city), group in position_df.groupby(['province', 'city']):
            # Sort by votes
            group = group.sort_values('votes', ascending=False)
            
            # Determine number of winners
            if position == 'COUNCILOR':
                # Use default 8 councilors per municipality (Philippine standard)
                num_winners = DEFAULT_COUNCILORS
            else:
                num_winners = 1  # Mayor and Vice Mayor
            
            # Take top N
            for idx, row in group.head(num_winners).iterrows():
                winners.append({
                    'region': row['region'],
                    'province': row['province'],
                    'city': row['city'],
                    'position': position,
                    'district': row['district'],
                    'candidate_name': row['candidate_name'],
                    'party': row['party'],
                    'votes': row['votes'],
                    'raw_position': row['position']
                })
    
    print(f"Municipal winners: {len([w for w in winners if w['position'] in ['MAYOR', 'VICE MAYOR', 'COUNCILOR']])}")
    
    print("\n" + "="*80)
    print("STEP 2: Provincial Level Winners (Governor, Vice Governor, Board Members)")
    print("="*80)
    
    for position in ['GOVERNOR', 'VICE GOVERNOR', 'PROVINCIAL BOARD MEMBER']:
        position_df = df[df['standard_position'] == position].copy()
        
        if position == 'PROVINCIAL BOARD MEMBER':
            # Board members are elected at province level (not by district)
            # Use 2019 counts to determine seats per province
            for province, group in position_df.groupby('province'):
                # Aggregate votes across ALL municipalities in province
                candidate_votes = group.groupby(['candidate_name', 'party']).agg({
                    'votes': 'sum',
                    'region': 'first',
                    'position': 'first',
                    'district': 'first'  # Keep for reference
                }).reset_index()
                
                candidate_votes = candidate_votes.sort_values('votes', ascending=False)
                
                # Use 2019 count for this province, default to 8 if not found
                num_seats = board_per_prov.get(province, 8)
                
                # Take top N for this province
                for _, row in candidate_votes.head(num_seats).iterrows():
                    winners.append({
                        'region': row['region'],
                        'province': province,
                        'city': None,
                        'position': position,
                        'district': row['district'],
                        'candidate_name': row['candidate_name'],
                        'party': row['party'],
                        'votes': row['votes'],
                        'raw_position': row['position']
                    })
        else:
            # Governor and Vice Governor: aggregate votes across entire province
            for province, group in position_df.groupby('province'):
                candidate_votes = group.groupby(['candidate_name', 'party']).agg({
                    'votes': 'sum',
                    'region': 'first',
                    'position': 'first'
                }).reset_index()
                
                candidate_votes = candidate_votes.sort_values('votes', ascending=False)
                
                # Take top 1
                if len(candidate_votes) > 0:
                    row = candidate_votes.iloc[0]
                    winners.append({
                        'region': row['region'],
                        'province': province,
                        'city': None,
                        'position': position,
                        'district': None,
                        'candidate_name': row['candidate_name'],
                        'party': row['party'],
                        'votes': row['votes'],
                        'raw_position': row['position']
                    })
    
    print(f"Provincial winners: {len([w for w in winners if w['position'] in ['GOVERNOR', 'VICE GOVERNOR', 'PROVINCIAL BOARD MEMBER']])}")
    
    print("\n" + "="*80)
    print("STEP 3: District Level Winners (Representatives)")
    print("="*80)
    
    rep_df = df[df['standard_position'] == 'MEMBER, HOUSE OF REPRESENTATIVES'].copy()
    
    for (province, district), group in rep_df.groupby(['province', 'district']):
        # Aggregate votes across municipalities in this district
        candidate_votes = group.groupby(['candidate_name', 'party']).agg({
            'votes': 'sum',
            'region': 'first',
            'position': 'first'
        }).reset_index()
        
        candidate_votes = candidate_votes.sort_values('votes', ascending=False)
        
        # Take top 1 (one representative per district)
        if len(candidate_votes) > 0:
            row = candidate_votes.iloc[0]
            winners.append({
                'region': row['region'],
                'province': province,
                'city': None,
                'position': 'MEMBER, HOUSE OF REPRESENTATIVES',
                'district': district,
                'candidate_name': row['candidate_name'],
                'party': row['party'],
                'votes': row['votes'],
                'raw_position': row['position']
            })
    
    print(f"Representative winners: {len([w for w in winners if w['position'] == 'MEMBER, HOUSE OF REPRESENTATIVES'])}")
    
    # Create winners dataframe
    winners_df = pd.DataFrame(winners)
    
    print("\n" + "="*80)
    print("Summary of 2025 Winners")
    print("="*80)
    print(f"\nTotal winners: {len(winners_df):,}")
    print("\nWinners by position:")
    print(winners_df['position'].value_counts())
    
    # Save to CSV
    output_file = 'winners_2025.csv'
    winners_df.to_csv(output_file, index=False)
    print(f"\n✓ Winners dataset saved to: {output_file}")
    
    return winners_df


if __name__ == '__main__':
    main()
