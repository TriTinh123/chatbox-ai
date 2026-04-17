import pathlib
import pandas as pd

base = pathlib.Path('data')
base.mkdir(exist_ok=True)

# Retail business sample
retail_rows = [
    ('2026-02-05', 'ElectroWidget', 'Online', 'North', 120, 250000, 120 * 250000),
    ('2026-02-10', 'ElectroWidget', 'Retail', 'North', 85, 250000, 85 * 250000),
    ('2026-02-15', 'HomeComfort', 'Online', 'Central', 140, 180000, 140 * 180000),
    ('2026-02-20', 'HomeComfort', 'Retail', 'South', 90, 180000, 90 * 180000),
    ('2026-02-25', 'WorkPro', 'Distributor', 'South', 65, 320000, 65 * 320000),
    ('2026-02-28', 'WorkPro', 'Online', 'Central', 70, 320000, 70 * 320000),
    ('2026-03-03', 'ElectroWidget', 'Online', 'North', 95, 250000, 95 * 250000),
    ('2026-03-08', 'ElectroWidget', 'Retail', 'North', 60, 250000, 60 * 250000),
    ('2026-03-12', 'HomeComfort', 'Online', 'Central', 110, 180000, 110 * 180000),
    ('2026-03-17', 'HomeComfort', 'Retail', 'South', 55, 180000, 55 * 180000),
    ('2026-03-21', 'WorkPro', 'Distributor', 'South', 40, 320000, 40 * 320000),
    ('2026-03-26', 'WorkPro', 'Online', 'Central', 38, 320000, 38 * 320000),
]
retail_df = pd.DataFrame(retail_rows, columns=['date','product','channel','region','quantity','unit_price','revenue'])
retail_df.to_excel(base / 'sample_retail_march2026.xlsx', index=False)

# Wholesale business sample
wholesale_rows = [
    ('2026-02-02', 'Industrial Coil', 'Distributor', 'East', 220, 550000, 220 * 550000),
    ('2026-02-09', 'Industrial Coil', 'Distributor', 'West', 150, 550000, 150 * 550000),
    ('2026-02-14', 'OfficeSuite', 'Corporate', 'North', 85, 420000, 85 * 420000),
    ('2026-02-19', 'OfficeSuite', 'Corporate', 'Central', 100, 420000, 100 * 420000),
    ('2026-02-24', 'SmartRack', 'Distributor', 'South', 60, 780000, 60 * 780000),
    ('2026-02-27', 'SmartRack', 'Online', 'East', 45, 780000, 45 * 780000),
    ('2026-03-03', 'Industrial Coil', 'Distributor', 'East', 140, 550000, 140 * 550000),
    ('2026-03-10', 'Industrial Coil', 'Distributor', 'West', 90, 550000, 90 * 550000),
    ('2026-03-15', 'OfficeSuite', 'Corporate', 'North', 60, 420000, 60 * 420000),
    ('2026-03-18', 'OfficeSuite', 'Corporate', 'Central', 70, 420000, 70 * 420000),
    ('2026-03-22', 'SmartRack', 'Distributor', 'South', 30, 780000, 30 * 780000),
    ('2026-03-28', 'SmartRack', 'Online', 'East', 25, 780000, 25 * 780000),
]
wholesale_df = pd.DataFrame(wholesale_rows, columns=['date','product','channel','region','quantity','unit_price','revenue'])
wholesale_df.to_excel(base / 'sample_wholesale_march2026.xlsx', index=False)

# Tech startup business sample
tech_rows = [
    ('2026-02-04', 'CloudSuite', 'Online', 'Central', 22, 3400000, 22 * 3400000),
    ('2026-02-11', 'CloudSuite', 'Online', 'North', 18, 3400000, 18 * 3400000),
    ('2026-02-13', 'AI Pack', 'Direct', 'Central', 14, 5200000, 14 * 5200000),
    ('2026-02-20', 'AI Pack', 'Direct', 'South', 10, 5200000, 10 * 5200000),
    ('2026-02-25', 'SupportPlus', 'Partnership', 'North', 26, 900000, 26 * 900000),
    ('2026-02-28', 'SupportPlus', 'Online', 'South', 24, 900000, 24 * 900000),
    ('2026-03-02', 'CloudSuite', 'Online', 'Central', 12, 3400000, 12 * 3400000),
    ('2026-03-09', 'CloudSuite', 'Online', 'North', 8, 3400000, 8 * 3400000),
    ('2026-03-14', 'AI Pack', 'Direct', 'Central', 6, 5200000, 6 * 5200000),
    ('2026-03-19', 'AI Pack', 'Direct', 'South', 4, 5200000, 4 * 5200000),
    ('2026-03-23', 'SupportPlus', 'Partnership', 'North', 16, 900000, 16 * 900000),
    ('2026-03-29', 'SupportPlus', 'Online', 'South', 14, 900000, 14 * 900000),
]
tech_df = pd.DataFrame(tech_rows, columns=['date','product','channel','region','quantity','unit_price','revenue'])
tech_df.to_excel(base / 'sample_tech_march2026.xlsx', index=False)

print('Created sample Excel files in', base.resolve())
