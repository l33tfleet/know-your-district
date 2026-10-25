-- Published scalar facts only; built offline and opened with mode=ro at runtime.
CREATE TABLE facts (
    variable TEXT NOT NULL CHECK (length(trim(variable)) > 0),
    geography TEXT NOT NULL CHECK (length(trim(geography)) > 0),
    vintage TEXT NOT NULL CHECK (length(trim(vintage)) > 0),
    value REAL CHECK (value >= 0 AND value < 1e999),
    moe REAL CHECK (moe >= 0 AND moe < 1e999),
    cv REAL CHECK (cv >= 0 AND cv < 1e999),
    reliability TEXT NOT NULL CHECK (reliability IN ('reliable', 'moderate', 'caution', 'unavailable')),
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    table_id TEXT NOT NULL CHECK (length(trim(table_id)) > 0),
    method TEXT NOT NULL CHECK (length(trim(method)) > 0),
    endpoint TEXT NOT NULL CHECK (length(trim(endpoint)) > 0),
    label TEXT NOT NULL CHECK (length(trim(label)) > 0),
    estimate_annotation TEXT,
    moe_annotation TEXT,
    PRIMARY KEY (variable, geography, vintage),
    CHECK (
        ((value IS NULL OR value = 0 OR moe IS NULL) AND cv IS NULL)
        OR (value > 0 AND moe IS NOT NULL AND cv IS NOT NULL)
    ),
    CHECK (reliability = CASE
        WHEN value IS NULL THEN 'unavailable'
        WHEN value = 0 OR moe IS NULL THEN 'caution'
        WHEN cv <= 0.15 THEN 'reliable'
        WHEN cv <= 0.30 THEN 'moderate'
        ELSE 'caution' END)
) STRICT;
