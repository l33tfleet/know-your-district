-- Synthetic population observations for CI only; never deploy as public data.
INSERT INTO facts
    (variable, geography, vintage, value, moe, cv, reliability,
     source, table_id, method, endpoint, label)
SELECT 'B01003_001E', geography, '2020–2024', 12345, 100, 0.005, 'reliable',
       'Synthetic Census ACS fixture', 'B01003',
       'published estimate and 90% margin of error',
       'https://api.census.gov/data/2024/acs/acs5', 'Total population'
FROM (
    SELECT 'house:15:022:2022' AS geography
    UNION ALL SELECT 'senate:15:001:2022'
    UNION ALL SELECT 'state:15'
);
