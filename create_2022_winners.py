"""
Create 2022 winners dataset from 2022_raw data.

Aggregation levels:
1. Municipal level: Mayor (1), Vice Mayor (1), Councilors (8 per municipality)
2. Provincial level: Governor (1), Vice Governor (1), Provincial Board Members (varies by province)
3. District level: Representatives (1 per legislative district)

Note: 2022 data already includes position names with province/city info, so we can use rank directly.
Provincial board member counts per province are based on 2019 reference data.
"""

import pandas as pd
from pathlib import Path
import re


def load_2019_board_member_counts():
    """
    Load 2019 data to determine number of provincial board members per province.
    Returns: dict mapping province name to number of board members
    """
    nle_df = pd.read_csv('NLE_Winners_2004_2025.csv', low_memory=False)
    board_2019 = nle_df[(nle_df['Year'] == 2019) & 
                        (nle_df['Position'] == 'PROVINCIAL BOARD MEMBER')]
    
    # Count board members per province
    board_counts = board_2019.groupby('Province').size().to_dict()
    
    print(f"\nLoaded 2019 reference counts:")
    print(f"  Provinces: {len(board_counts)}")
    print(f"  Board member range: {min(board_counts.values())}-{max(board_counts.values())} per province")
    
    return board_counts


def extract_district(position_text):
    """
    Extract district information from position names.
    Examples:
    - "MEMBER, HOUSE OF REPRESENTATIVES AGUSAN DEL NORTE - SECOND LEGDIST" -> "SECOND LEGDIST"
    - "MEMBER, SANGGUNIANG PANLALAWIGAN AGUSAN DEL NORTE - SECOND PROVDIST" -> "SECOND PROVDIST"
    - "MEMBER, SANGGUNIANG BAYAN AGUSAN DEL NORTE - BUENAVISTA - LONE DIST" -> "LONE DIST"
    """
    # Look for district patterns at the end of position name
    district_match = re.search(r'[-\s](FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|LONE)\s+(LEGDIST|PROVDIST|DIST)$', 
                              position_text, re.IGNORECASE)
    if district_match:
        return district_match.group(1).strip().upper()
    return None


def standardize_position(raw_position):
    """
    Map raw position names to standard format.
    Returns: (standard_position, district)
    """
    position = raw_position.strip().upper()
    district = extract_district(position)
    
    # Map to standard positions
    if 'SANGGUNIANG BAYAN' in position or 'SANGGUNIANG PANLUNGSOD' in position:
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
    print("Creating 2022 Winners Dataset")
    print("="*80)
    
    # Load 2019 board member counts as reference
    board_counts_2019 = load_2019_board_member_counts()
    
    # Standard number of councilors in Philippine municipalities
    DEFAULT_COUNCILORS = 8
    
    # Load all 2022_raw data
    print("\nLoading 2022_raw data...")
    all_data = []
    csv_files = list(Path('2022_raw').rglob('*.csv'))
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
    
    # Filter to local positions only (exclude national positions)
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
    
    # Convert votes to numeric and rank to int
    df['votes'] = pd.to_numeric(df['votes'], errors='coerce').fillna(0).astype(int)
    df['rank'] = pd.to_numeric(df['rank'], errors='coerce').fillna(999).astype(int)
    
    # Process winners by position type
    winners = []
    
    print("\n" + "="*80)
    print("STEP 1: Municipal Level Winners (Mayor, Vice Mayor, Councilors)")
    print("="*80)
    
    # For municipal positions, we can use rank directly since data is already at municipal level
    for position in ['MAYOR', 'VICE MAYOR', 'COUNCILOR']:
        position_df = df[df['standard_position'] == position].copy()
        
        for (region, province, city), group in position_df.groupby(['region', 'province', 'city']):
            # Sort by rank (1 is the winner)
            group = group.sort_values(['rank', 'votes'], ascending=[True, False])
            
            # Determine number of winners
            if position == 'COUNCILOR':
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
                    'rank': row['rank'],
                    'raw_position': row['position']
                })
    
    print(f"Municipal winners: {len([w for w in winners if w['position'] in ['MAYOR', 'VICE MAYOR', 'COUNCILOR']])}")
    
    print("\n" + "="*80)
    print("STEP 2: Provincial Level Winners (Governor, Vice Governor, Board Members)")
    print("="*80)
    
    # For provincial positions, aggregate votes across all municipalities in province
    for position in ['GOVERNOR', 'VICE GOVERNOR', 'PROVINCIAL BOARD MEMBER']:
        position_df = df[df['standard_position'] == position].copy()
        
        if position == 'PROVINCIAL BOARD MEMBER':
            # Board members are elected at province level (not by district)
            # Number of seats varies by province (typically 8-25)
            # Use 2019 counts as reference for seat allocation
            for (region, province), group in position_df.groupby(['region', 'province']):
                # Aggregate votes by candidate across ALL municipalities
                candidate_votes = group.groupby(['candidate_name', 'party']).agg({
                    'votes': 'sum',
                    'district': 'first'  # Keep district info for reference
                }).reset_index()
                
                # Sort by total votes
                candidate_votes = candidate_votes.sort_values('votes', ascending=False)
                
                # Use 2019 count for this province, default to 8 if not found
                num_seats = board_counts_2019.get(province, 8)
                
                # Take top N for this province
                for idx, row in candidate_votes.head(num_seats).iterrows():
                    winners.append({
                        'region': region,
                        'province': province,
                        'city': None,
                        'position': position,
                        'district': row['district'],  # Keep for reference
                        'candidate_name': row['candidate_name'],
                        'party': row['party'],
                        'votes': row['votes'],
                        'rank': idx + 1,  # New rank based on aggregated votes
                        'raw_position': f"MEMBER, SANGGUNIANG PANLALAWIGAN {province}"
                    })
        else:
            # Governor and Vice Governor: aggregate votes across entire province
            for (region, province), group in position_df.groupby(['region', 'province']):
                # Aggregate votes by candidate across all municipalities
                candidate_votes = group.groupby(['candidate_name', 'party']).agg({
                    'votes': 'sum'
                }).reset_index()
                
                # Sort by total votes
                candidate_votes = candidate_votes.sort_values('votes', ascending=False)
                
                # Take top 1
                if len(candidate_votes) > 0:
                    row = candidate_votes.iloc[0]
                    winners.append({
                        'region': region,
                        'province': province,
                        'city': None,
                        'position': position,
                        'district': None,
                        'candidate_name': row['candidate_name'],
                        'party': row['party'],
                        'votes': row['votes'],
                        'rank': 1,
                        'raw_position': f"{position} {province}"
                    })
    
    print(f"Provincial winners: {len([w for w in winners if w['position'] in ['GOVERNOR', 'VICE GOVERNOR', 'PROVINCIAL BOARD MEMBER']])}")
    
    print("\n" + "="*80)
    print("STEP 3: District Level Winners (Representatives)")
    print("="*80)
    
    # Representatives are elected by legislative district
    # Aggregate votes across municipalities in same province+district
    rep_df = df[df['standard_position'] == 'MEMBER, HOUSE OF REPRESENTATIVES'].copy()
    
    for (region, province, district), group in rep_df.groupby(['region', 'province', 'district']):
        if pd.isna(district) or district is None:
            continue
        
        # Aggregate votes by candidate across all municipalities in this district
        candidate_votes = group.groupby(['candidate_name', 'party']).agg({
            'votes': 'sum'
        }).reset_index()
        
        # Sort by total votes
        candidate_votes = candidate_votes.sort_values('votes', ascending=False)
        
        # Take top 1 (one representative per district)
        if len(candidate_votes) > 0:
            row = candidate_votes.iloc[0]
            winners.append({
                'region': region,
                'province': province,
                'city': None,
                'position': 'MEMBER, HOUSE OF REPRESENTATIVES',
                'district': district,
                'candidate_name': row['candidate_name'],
                'party': row['party'],
                'votes': row['votes'],
                'rank': 1,
                'raw_position': f"MEMBER, HOUSE OF REPRESENTATIVES {province} - {district}"
            })
    
    print(f"Representative winners: {len([w for w in winners if w['position'] == 'MEMBER, HOUSE OF REPRESENTATIVES'])}")
    
    # Create winners dataframe
    winners_df = pd.DataFrame(winners)
    
    print("\n" + "="*80)
    print("Summary of 2022 Winners")
    print("="*80)
    print(f"\nTotal winners: {len(winners_df):,}")
    print("\nWinners by position:")
    print(winners_df['position'].value_counts())
    
    # Show sample of winners
    print("\nSample of winners:")
    print(winners_df.head(20))
    
    # Save to CSV
    output_file = 'winners_2022.csv'
    winners_df.to_csv(output_file, index=False)
    print(f"\n✓ Winners dataset saved to: {output_file}")
    
    return winners_df


if __name__ == '__main__':
    main()
