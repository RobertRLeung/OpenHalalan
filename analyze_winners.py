import pandas as pd

w2022 = pd.read_csv('winners_2022.csv')
w2025 = pd.read_csv('winners_2025.csv')

print('winners_2022.csv:')
print(f'  Total records: {len(w2022):,}')
print(f'  Positions: {w2022["position"].value_counts().to_dict()}')
print(f'  Unique provinces: {w2022["province"].nunique()}')
print(f'  Unique cities: {w2022["city"].nunique()}')

print('\nwinners_2025.csv:')
print(f'  Total records: {len(w2025):,}')
print(f'  Positions: {w2025["position"].value_counts().to_dict()}')
print(f'  Unique provinces: {w2025["province"].nunique()}')
print(f'  Unique cities: {w2025["city"].nunique()}')

print('\n2022 Low vote counts (votes < 100):')
print(f'  Mayor: {len(w2022[(w2022["position"] == "MAYOR") & (w2022["votes"] < 100)])}')
print(f'  Governor: {len(w2022[(w2022["position"] == "GOVERNOR") & (w2022["votes"] < 100)])}')

print('\n2025 Low vote counts (votes < 100):')
print(f'  Mayor: {len(w2025[(w2025["position"] == "MAYOR") & (w2025["votes"] < 100)])}')
print(f'  Governor: {len(w2025[(w2025["position"] == "GOVERNOR") & (w2025["votes"] < 100)])}')

# Check for missing BARMM data
print('\n2022 BARMM municipalities:')
barmm_2022 = w2022[w2022['region'] == 'BARMM']
print(f'  Total BARMM records: {len(barmm_2022)}')
print(f'  Provinces: {barmm_2022["province"].unique()}')
print(f'  Cities: {barmm_2022["city"].nunique()}')

print('\n2025 BARMM municipalities:')
barmm_2025 = w2025[w2025['region'] == 'CORDILLERA ADMINISTRATIVE REGION']
print(f'  Example region check for CAR: {len(barmm_2025)} records')
