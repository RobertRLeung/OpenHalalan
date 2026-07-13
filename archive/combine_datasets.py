"""
Combine 2025 winners with Political Dynasty dataset (2004-2022) 
to create comprehensive NLE_Winners_2004_2025.csv
"""

import pandas as pd
import numpy as np

def main():
    print("="*80)
    print("Combining 2025 Winners with Political Dynasty Dataset (2004-2022)")
    print("="*80)
    
    # Load both datasets
    print("\nLoading datasets...")
    dynasty_df = pd.read_csv('data/Political Dynasty v8.5.csv')
    winners_2025 = pd.read_csv('winners_2025.csv')
    
    print(f"Political Dynasty (2004-2022): {len(dynasty_df):,} records")
    print(f"2025 Winners: {len(winners_2025):,} records")
    
    # Check dynasty dataset columns
    print(f"\nDynasty dataset columns: {dynasty_df.columns.tolist()}")
    print(f"2025 dataset columns: {winners_2025.columns.tolist()}")
    
    # Create 2025 dataframe matching dynasty format
    print("\nFormatting 2025 data to match dynasty dataset structure...")
    
    # Parse candidate names into Last, First, Middle
    # Assuming format is "LAST, FIRST MIDDLE" or similar
    def parse_name(name):
        if pd.isna(name):
            return '', '', ''
        
        name = str(name).strip()
        
        # Handle "LAST, FIRST MIDDLE" format
        if ',' in name:
            parts = name.split(',', 1)
            last = parts[0].strip()
            rest = parts[1].strip() if len(parts) > 1 else ''
            
            # Split rest into first and middle
            rest_parts = rest.split()
            first = rest_parts[0] if len(rest_parts) > 0 else ''
            middle = ' '.join(rest_parts[1:]) if len(rest_parts) > 1 else ''
            
            return last, first, middle
        else:
            # Just use as last name if no comma
            return name, '', ''
    
    names = winners_2025['candidate_name'].apply(parse_name)
    
    # Map 2025 data to dynasty format
    df_2025 = pd.DataFrame()
    df_2025['Last Name'] = names.apply(lambda x: x[0])
    df_2025['First Name'] = names.apply(lambda x: x[1])
    df_2025['Middle Name'] = names.apply(lambda x: x[2])
    df_2025['Position'] = winners_2025['position']
    df_2025['Party'] = winners_2025['party']
    df_2025['Year'] = 2025
    df_2025['Province'] = winners_2025['province']
    df_2025['Region'] = winners_2025['region']
    df_2025['Position Weight'] = None  # Not used
    df_2025['Full Name'] = winners_2025['candidate_name']
    df_2025['Community'] = winners_2025['city'].fillna('')  # Empty for provincial positions
    
    print(f"Formatted 2025 data: {len(df_2025):,} records")
    
    # Show sample of formatted data
    print("\nSample of formatted 2025 data:")
    print(df_2025[['Year', 'Province', 'Community', 'Position', 'Last Name', 'First Name']].head(10))
    
    # Combine datasets
    print("\nCombining datasets...")
    combined_df = pd.concat([dynasty_df, df_2025], ignore_index=True)
    print(f"Combined dataset: {len(combined_df):,} records")
    
    # Summary by year
    print("\n" + "="*80)
    print("Records by Year:")
    print("="*80)
    year_counts = combined_df['Year'].value_counts().sort_index()
    for year, count in year_counts.items():
        print(f"  {year}: {count:>6,} records")
    
    # Summary by position (2025 only)
    print("\n" + "="*80)
    print("2025 Winners by Position:")
    print("="*80)
    position_2025 = combined_df[combined_df['Year'] == 2025]['Position'].value_counts()
    for pos, count in position_2025.items():
        print(f"  {pos:<40} {count:>6,}")
    
    # Check for issues
    print("\n" + "="*80)
    print("Data Quality Checks:")
    print("="*80)
    
    # Missing names
    missing_names = combined_df[combined_df['Year'] == 2025][
        (combined_df['Last Name'].isna()) | (combined_df['Last Name'] == '')
    ]
    print(f"✓ Records with missing last names (2025): {len(missing_names)}")
    
    # Position consistency
    all_positions = combined_df['Position'].unique()
    print(f"\n✓ Total unique positions in dataset: {len(all_positions)}")
    print("  Positions:")
    for pos in sorted(all_positions):
        count = len(combined_df[combined_df['Position'] == pos])
        print(f"    {pos:<40} {count:>7,} total records")
    
    # Compare 2022 vs 2025 by province
    print("\n" + "="*80)
    print("Province Coverage Comparison (Mayors as proxy):")
    print("="*80)
    
    mayors_2022 = set(combined_df[(combined_df['Year'] == 2022) & (combined_df['Position'] == 'MAYOR')]['Province'].unique())
    mayors_2025 = set(combined_df[(combined_df['Year'] == 2025) & (combined_df['Position'] == 'MAYOR')]['Province'].unique())
    
    print(f"  Provinces with mayors in 2022: {len(mayors_2022)}")
    print(f"  Provinces with mayors in 2025: {len(mayors_2025)}")
    
    only_2022 = mayors_2022 - mayors_2025
    only_2025 = mayors_2025 - mayors_2022
    
    if only_2022:
        print(f"\n  ⚠️  Provinces in 2022 but not 2025 ({len(only_2022)}):")
        for prov in sorted(only_2022):
            print(f"    - {prov}")
    
    if only_2025:
        print(f"\n  ℹ️  New provinces in 2025 ({len(only_2025)}):")
        for prov in sorted(only_2025):
            print(f"    - {prov}")
    
    # Check representatives by province
    print("\n" + "="*80)
    print("Representatives by Province:")
    print("="*80)
    
    reps_2022 = combined_df[(combined_df['Year'] == 2022) & 
                            (combined_df['Position'] == 'MEMBER, HOUSE OF REPRESENTATIVES')].groupby('Province').size()
    reps_2025 = combined_df[(combined_df['Year'] == 2025) & 
                            (combined_df['Position'] == 'MEMBER, HOUSE OF REPRESENTATIVES')].groupby('Province').size()
    
    # Compare provinces with significant changes
    print(f"\nProvinces with different representative counts (showing differences > 1):")
    print(f"{'Province':<40} {'2022':>6} {'2025':>6} {'Diff':>6}")
    print("-"*70)
    
    all_prov_reps = set(reps_2022.index) | set(reps_2025.index)
    significant_changes = []
    
    for prov in sorted(all_prov_reps):
        count_2022 = reps_2022.get(prov, 0)
        count_2025 = reps_2025.get(prov, 0)
        diff = count_2025 - count_2022
        if abs(diff) > 1:
            significant_changes.append((prov, count_2022, count_2025, diff))
    
    for prov, c22, c25, diff in significant_changes:
        print(f"{prov:<40} {c22:>6} {c25:>6} {diff:>6}")
    
    if not significant_changes:
        print("  ✓ No significant differences (all within ±1)")
    
    # Save combined dataset
    output_file = 'NLE_Winners_2004_2025.csv'
    combined_df.to_csv(output_file, index=False)
    print(f"\n✓ Combined dataset saved to: {output_file}")
    print(f"  Total records: {len(combined_df):,}")
    print(f"  Years: {combined_df['Year'].min()}-{combined_df['Year'].max()}")
    print(f"  Positions: {len(combined_df['Position'].unique())}")
    
    return combined_df

if __name__ == '__main__':
    main()
