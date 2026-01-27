-- Migration: Convert discipline TEXT to disciplines TEXT[]
-- This migrates existing single-discipline data to a multi-discipline array column.
-- Run in Supabase SQL Editor.

-- Step 1: Add new array column
ALTER TABLE phd_positions ADD COLUMN disciplines TEXT[];

-- Step 2: Migrate existing data (single text -> array with one element)
UPDATE phd_positions
SET disciplines = ARRAY[discipline]
WHERE discipline IS NOT NULL;

-- Step 3: Drop the old column
ALTER TABLE phd_positions DROP COLUMN discipline;
