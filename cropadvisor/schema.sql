-- Relational schema derived from the ER diagram in SRS Lab 9 (section 6).
-- Columns beyond the SRS mapping are marked "ext" and support the
-- application workflow (authentication, status, audit).

PRAGMA foreign_keys = ON;

-- FARMERS (Farmer_ID, Name, Location, Contact_No)
CREATE TABLE IF NOT EXISTS farmers (
    farmer_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    location      TEXT    NOT NULL,
    contact_no    TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,                      -- ext
    status        TEXT    NOT NULL DEFAULT 'active'      -- ext
                  CHECK (status IN ('active', 'disabled')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))  -- ext
);

-- Administrator accounts (actor in the use case diagrams).
CREATE TABLE IF NOT EXISTS admins (
    admin_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    password_hash TEXT    NOT NULL
);

-- FARM_DETAILS (Farmer_ID*, Plot_No, Land_Area, Season, Soil_Type, N, P, K, pH)
-- Weak entity: composite key, cascades with its owning farmer.
CREATE TABLE IF NOT EXISTS farm_details (
    farmer_id   INTEGER NOT NULL REFERENCES farmers(farmer_id) ON DELETE CASCADE,
    plot_no     INTEGER NOT NULL,
    plot_name   TEXT,                                    -- ext
    location    TEXT    NOT NULL,                        -- ext: plot may differ from home location
    land_area   REAL    NOT NULL CHECK (land_area > 0),
    season      TEXT    NOT NULL CHECK (season IN ('Kharif', 'Rabi', 'Zaid')),
    soil_type   TEXT,
    n           REAL CHECK (n  IS NULL OR n  BETWEEN 0 AND 300),
    p           REAL CHECK (p  IS NULL OR p  BETWEEN 0 AND 300),
    k           REAL CHECK (k  IS NULL OR k  BETWEEN 0 AND 300),
    ph          REAL CHECK (ph IS NULL OR ph BETWEEN 0 AND 14),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')), -- ext
    PRIMARY KEY (farmer_id, plot_no)
);

-- WEATHER_DATA (Weather_ID, Location, Temperature, Rainfall, Humidity, Recorded_Date)
CREATE TABLE IF NOT EXISTS weather_data (
    weather_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    location      TEXT NOT NULL,
    temperature   REAL NOT NULL,
    rainfall      REAL NOT NULL,          -- mean monthly rainfall over the season window, mm
    humidity      REAL NOT NULL,
    recorded_date TEXT NOT NULL DEFAULT (datetime('now')),
    season        TEXT,                   -- ext
    source        TEXT NOT NULL,          -- ext: 'open-meteo' or 'seasonal-estimate'
    period        TEXT,                   -- ext: date window the figures describe
    latitude      REAL,                   -- ext
    longitude     REAL                    -- ext
);

-- CROPS (Crop_ID, Crop_Name, Optimal_Temp, Min_Rainfall, Soil_Category)
CREATE TABLE IF NOT EXISTS crops (
    crop_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
    optimal_temp  REAL NOT NULL,
    min_rainfall  REAL NOT NULL CHECK (min_rainfall >= 0),
    soil_category TEXT NOT NULL,          -- comma-separated soil type names
    -- ext: agronomic ranges used to train the model
    category      TEXT NOT NULL DEFAULT 'Other',
    seasons       TEXT NOT NULL DEFAULT 'Kharif,Rabi,Zaid',
    temp_tolerance REAL NOT NULL DEFAULT 6,
    max_rainfall  REAL NOT NULL DEFAULT 250,
    humidity_min  REAL NOT NULL DEFAULT 30,
    humidity_max  REAL NOT NULL DEFAULT 85,
    n_min REAL NOT NULL DEFAULT 20,  n_max REAL NOT NULL DEFAULT 120,
    p_min REAL NOT NULL DEFAULT 15,  p_max REAL NOT NULL DEFAULT 80,
    k_min REAL NOT NULL DEFAULT 15,  k_max REAL NOT NULL DEFAULT 80,
    ph_min REAL NOT NULL DEFAULT 5.5, ph_max REAL NOT NULL DEFAULT 7.8,
    water_need    TEXT NOT NULL DEFAULT 'Medium',
    duration_days INTEGER,
    guidance      TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1
);

-- Soil reference data maintained by the administrator (Manage Soil Data).
CREATE TABLE IF NOT EXISTS soil_types (
    soil_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    typical_n   REAL NOT NULL,
    typical_p   REAL NOT NULL,
    typical_k   REAL NOT NULL,
    typical_ph  REAL NOT NULL,
    drainage    TEXT NOT NULL DEFAULT 'Moderate'
);

-- RECOMMENDATIONS (Rec_ID, Generated_Date, Confidence_Score, Status, Farmer_ID*, Weather_ID*)
CREATE TABLE IF NOT EXISTS recommendations (
    rec_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_date   TEXT NOT NULL DEFAULT (datetime('now')),
    confidence_score REAL NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    status           TEXT NOT NULL CHECK (status IN ('confident', 'low-confidence')),
    farmer_id        INTEGER NOT NULL REFERENCES farmers(farmer_id) ON DELETE CASCADE,
    weather_id       INTEGER NOT NULL REFERENCES weather_data(weather_id),
    plot_no          INTEGER,             -- ext: plot the request came from (may be deleted later)
    model_version    TEXT,                -- ext
    -- ext: snapshot of the inputs, so history stays accurate after a plot is edited or removed
    input_snapshot   TEXT NOT NULL
);

-- RECOMMENDATION_CROPS (Rec_ID*, Crop_ID*, Rank_Order, Suitability_Score)
-- Crops referenced here cannot be deleted, only deactivated (TC-35).
CREATE TABLE IF NOT EXISTS recommendation_crops (
    rec_id            INTEGER NOT NULL REFERENCES recommendations(rec_id) ON DELETE CASCADE,
    crop_id           INTEGER NOT NULL REFERENCES crops(crop_id) ON DELETE RESTRICT,
    rank_order        INTEGER NOT NULL CHECK (rank_order >= 1),
    suitability_score REAL NOT NULL CHECK (suitability_score BETWEEN 0 AND 1),
    PRIMARY KEY (rec_id, crop_id)
);

-- System activity, shown under View System Reports.
CREATE TABLE IF NOT EXISTS activity_log (
    log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT
);

CREATE INDEX IF NOT EXISTS idx_rec_farmer  ON recommendations(farmer_id, generated_date);
CREATE INDEX IF NOT EXISTS idx_weather_loc ON weather_data(location, season, recorded_date);
