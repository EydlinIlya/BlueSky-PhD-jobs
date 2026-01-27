-- Add country and position_type columns to phd_positions table
-- country: Standard country name (e.g., USA, UK, Germany) or NULL
-- position_type: Array of position types (e.g., {"PhD Student","Postdoc"}) or NULL

ALTER TABLE phd_positions ADD COLUMN country TEXT;
ALTER TABLE phd_positions ADD COLUMN position_type TEXT[];
