"""
Create winners dataset from 2025_raw data (preserving district information)
and compare counts with Political Dynasty dataset
"""

import pandas as pd
from pathlib import Path
import re

def load_2022_reference_counts():
    """Load 2022 reference data for number of winners per position"""
    dynasty_df = pd.read_csv('data/Political Dynasty v8.5.csv')
    dynasty_2022 = dynasty_df[dynasty_df['Year'] == 2022].copy()
    
    # Count councilors per city (should be consistent)
    councilors_per_city = dynasty_2022[dynasty_2022['Position'] == 'COUNCILOR'].groupby(
        ['Province', 'Community']
    ).size().median()
    
    # Count board members per province (varies by province class)
    board_per_prov = dynasty_2022[dynasty_2022['Position'] == 'PROVINCIAL BOARD MEMBER'].groupby(
        'Province'
    ).size().to_dict()
    
    print(f"Reference from 2022:")
    print(f"  Councilors per city (median): {councilors_per_city}")
    print(f"  Board members per province: varies by province (6-17)")
    
    return int(councilors_per_city), board_per_prov


def standardize_position(raw_position):
    """
    Standardize position names to match dynasty dataset format.
    Extracts district information for representatives before standardizing.
    
    Returns: (standard_position, district)
    """
    position = raw_position.strip().upper()
    district = None
    
    # Extract district information for representatives
    if 'HOUSE OF REPRESENTATIVES' in position or 'REPRESENTATIVE' in position:
        # Extract district like "FIFTH DISTRICT", "1ST DISTRICT", etc.
        district_match = re.search(r'(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|LONE|\d+(?:ST|ND|RD|TH))\s+DISTRICT', position, re.IGNORECASE)
        if district_match:
            district = district_match.group(0).upper()
        
        return 'MEMBER, HOUSE OF REPRESENTATIVES', district
    
    # Map other positions
    position_mapping = {
        'MAYOR': 'MAYOR',
        'VICE MAYOR': 'VICE MAYOR',
        'VICE-MAYOR': 'VICE MAYOR',
        'COUNCILOR': 'COUNCILOR',
        'SANGGUNIANG BAYAN': 'COUNCILOR',
        'SANGGUNIANG PANLUNGSOD': 'COUNCILOR',
        'GOVERNOR': 'GOVERNOR',
        'VICE GOVERNOR': 'VICE GOVERNOR',
        'VICE-GOVERNOR': 'VICE GOVERNOR',
        'PROVINCIAL BOARD MEMBER': 'PROVINCIAL BOARD MEMBER',
        'BOARD MEMBER': 'PROVINCIAL BOARD MEMBER',
    }
    
    for key, value in position_mapping.items():
        if key in position:
            return value, district
    
    return None, None


def get_aggregation_level(position):
    """Determine if position should be aggregated at provincial or municipal level"""
    provincial_positions = [
        'GOVERNOR',
        'VICE GOVERNOR', 
        'PROVINCIAL BOARD MEMBER',
        'MEMBER, HOUSE OF REPRESENTATIVES'
    ]
    return 'provincial' if position in provincial_positions else 'municipal'


def aggregate_and_find_winners(df, councilors_per_city, board_per_prov):
    """
    Aggregate votes and determine winners for each position.
    For representatives, aggregate by district within province.
    """
    winners = []
    
    # Group by position
    for position in df['standard_position'].unique():
        if pd.isna(position):
            continue
            
        position_df = df[df['standard_position'] == position].copy()
        agg_level = get_aggregation_level(position)
        
        if position == 'MEMBER, HOUSE OF REPRESENTATIVES':
            # Special handling: aggregate by province + district
            for (province, district), group in position_df.groupby(['province', 'district']):
                if pd.isna(district):
                    # If no district info, aggregate at province level
                    district = 'UNKNOWN'
                
                # Sum votes across municipalities for this district
                candidate_votes = group.groupby(['candidate_name', 'party'])['votes'].sum().reset_index()
                candidate_votes = candidate_votes.sort_values('votes', ascending=False)
                
                # Take top 1 (one representative per district)
                top_candidate = candidate_votes.iloc[0]
                
                winners.append({
                    'province': province,
                    'city': None,  # Provincial level
                    'position': position,
                    'district': district,
                    'candidate_name': top_candidate['candidate_name'],
                    'party': top_candidate['party'],
                    'votes': top_candidate['votes'],
                    'rank': 1
                })
        
        elif agg_level == 'provincial':
            # Aggregate at province level (Governor, Vice Governor, Provincial Board)
            for province, group in position_df.groupby('province'):
                # Sum votes across all municipalities in the province
                candidate_votes = group.groupby(['candidate_name', 'party'])['votes'].sum().reset_index()
                candidate_votes = candidate_votes.sort_values('votes', ascending=False)
                
                # Determine number of winners
                if position == 'PROVINCIAL BOARD MEMBER':
                    num_winners = board_per_prov.get(province, 8)  # Default to 8 if unknown
                else:
                    num_winners = 1  # Governor and Vice Governor
                
                # Take top N
                for idx, row in candidate_votes.head(num_winners).iterrows():
                    winners.append({
                        'province': province,
                        'city': None,
                        'position': position,
                        'district': None,
                        'candidate_name': row['candidate_name'],
                        'party': row['party'],
                        'votes': row['votes'],
                        'rank': idx + 1
                    })
        
        else:
            # Municipal level (Mayor, Vice Mayor, Councilor)
            for (province, city), group in position_df.groupby(['province', 'city']):
                candidate_votes = group.sort_values('votes', ascending=False)
                
                # Determine number of winners
                if position == 'COUNCILOR':
                    num_winners = councilors_per_city
                else:
                    num_winners = 1  # Mayor and Vice Mayor
                
                # Take top N
                for idx, row in candidate_votes.head(num_winners).iterrows():
                    winners.append({
                        'province': province,
                        'city': city,
                        'position': position,
                        'district': None,
                        'candidate_name': row['candidate_name'],
                        'party': row['party'],
                        'votes': row['votes'],
                        'rank': idx + 1
                    })
    
    return pd.DataFrame(winners)


def main():
    print("="*80)
    print("Creating 2025 Winners Dataset from Raw Data")
    print("="*80)
    
    # Load reference counts from 2022
    councilors_per_city, board_per_prov = load_2022_reference_counts()
    
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
    
    # Standardize positions and extract district information
    print("\nStandardizing positions and extracting districts...")
    df[['standard_position', 'district']] = df['position'].apply(
        lambda x: pd.Series(standardize_position(x))
    )
    
    # Filter to only local positions (exclude Senator, President, Vice President, Party-list)
    local_positions = [
        'MAYOR',
        'VICE MAYOR',
        'COUNCILOR',
        'GOVERNOR',
        'VICE GOVERNOR',
        'PROVINCIAL BOARD MEMBER',
        'MEMBER, HOUSE OF REPRESENTATIVES'
    ]
    
    df = df[df['standard_position'].isin(local_positions)].copy()
    print(f"Records after filtering to local positions: {len(df):,}")
    
    # Show position distribution
    print("\nPosition distribution in raw data:")
    print(df['standard_position'].value_counts())
    
    # Show district distribution for representatives
    print("\nDistrict distribution for Representatives:")
    rep_districts = df[df['standard_position'] == 'MEMBER, HOUSE OF REPRESENTATIVES']['district'].value_counts()
    print(rep_districts.head(20))
    print(f"Representatives with district info: {rep_districts[rep_districts.index != 'UNKNOWN'].sum()}")
    print(f"Representatives without district info: {rep_districts.get('UNKNOWN', 0)}")
    
    # Aggregate and find winners
    print("\nAggregating votes and determining winners...")
    winners_df = aggregate_and_find_winners(df, councilors_per_city, board_per_prov)
    print(f"Total winners identified: {len(winners_df):,}")
    
    # Show winner distribution by position
    print("\nWinner distribution by position:")
    print(winners_df['position'].value_counts())
    
    # Compare with Political Dynasty dataset
    print("\n" + "="*80)
    print("Comparison with Political Dynasty Dataset (2022)")
    print("="*80)
    
    dynasty_df = pd.read_csv('data/Political Dynasty v8.5.csv')
    dynasty_2022 = dynasty_df[dynasty_df['Year'] == 2022].copy()
    
    print(f"\n2022 Dynasty counts by position:")
    for pos in local_positions:
        count_2022 = len(dynasty_2022[dynasty_2022['Position'] == pos])
        count_2025 = len(winners_df[winners_df['position'] == pos])
        diff = count_2025 - count_2022
        diff_pct = (diff / count_2022 * 100) if count_2022 > 0 else 0
        print(f"  {pos:<40} 2022: {count_2022:>6}  2025: {count_2025:>6}  Diff: {diff:>6} ({diff_pct:>+6.1f}%)")
    
    # Compare by province for key positions
    print("\n" + "="*80)
    print("Province-level comparison for Governors:")
    print("="*80)
    
    gov_2022 = dynasty_2022[dynasty_2022['Position'] == 'GOVERNOR'].groupby('Province').size()
    gov_2025 = winners_df[winners_df['position'] == 'GOVERNOR'].groupby('province').size()
    
    all_provinces = sorted(set(gov_2022.index) | set(gov_2025.index))
    
    mismatches = []
    for prov in all_provinces:
        c2022 = gov_2022.get(prov, 0)
        c2025 = gov_2025.get(prov, 0)
        if c2022 != c2025:
            mismatches.append((prov, c2022, c2025))
    
    if mismatches:
        print(f"\nProvinces with different governor counts:")
        print(f"{'Province':<40} {'2022':>6} {'2025':>6}")
        print("-"*60)
        for prov, c2022, c2025 in mismatches:
            print(f"{prov:<40} {c2022:>6} {c2025:>6}")
    else:
        print("\n✓ All provinces have consistent governor counts!")
    
    # Save winners dataset
    output_file = 'winners_2025_raw.csv'
    winners_df.to_csv(output_file, index=False)
    print(f"\n✓ Winners dataset saved to: {output_file}")
    print(f"  Total records: {len(winners_df):,}")
    
    return winners_df


if __name__ == '__main__':
    main()
