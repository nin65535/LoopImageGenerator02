-- LoopImageGenerator V2 - SQLite DDL
-- Version: 2026-10-10
-- All saved generations are complete, immutable snapshots.
-- Write a generation and *all* of its tagged images in one transaction.
-- PRAGMA foreign_keys=ON must be applied on every SQLite connection.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    initial_image_path TEXT NOT NULL,
    generation_config_json TEXT CHECK (
        generation_config_json IS NULL OR json_valid(generation_config_json)
    ),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS generations (
    id                 INTEGER PRIMARY KEY,
    project_id         INTEGER NOT NULL,
    parent_id          INTEGER,
    -- Selection of image IDs that belong to the parent generation:
    -- {"liked":[11,13], "disliked":[15]}; NULL only for root generations.
    -- This is an immutable snapshot of the choice that CAUSED this generation.
    selection_json     TEXT,
    -- Exact effective generation parameters, including prompt/negative, weights,
    -- model/workflow identifiers, image_count, width, height, inheritance_rate.
    parameters_json    TEXT NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id, parent_id)
        REFERENCES generations(project_id, id),
    UNIQUE (project_id, id),
    CHECK (parent_id IS NULL OR parent_id <> id),
    CHECK ((parent_id IS NULL AND selection_json IS NULL)
        OR (parent_id IS NOT NULL AND selection_json IS NOT NULL)),
    CHECK (json_valid(parameters_json)),
    CHECK (json_type(parameters_json) = 'object'),
    CHECK (json_type(parameters_json, '$.image_count') IS 'integer'),
    CHECK (json_extract(parameters_json, '$.image_count') >= 1),
    CHECK (
        selection_json IS NULL OR
        CASE WHEN json_valid(selection_json) THEN
            json_type(selection_json) = 'object'
            AND json_type(selection_json, '$.liked') IS 'array'
            AND json_type(selection_json, '$.disliked') IS 'array'
            AND (json_array_length(selection_json, '$.liked')
               + json_array_length(selection_json, '$.disliked')) >= 1
        ELSE 0 END
    )
);

CREATE INDEX IF NOT EXISTS idx_generations_project_parent
    ON generations(project_id, parent_id);

CREATE TABLE IF NOT EXISTS images (
    id                 INTEGER PRIMARY KEY,
    generation_id      INTEGER NOT NULL,
    position           INTEGER NOT NULL CHECK (position >= 0),
    file_path          TEXT NOT NULL,
    -- Actual seed for this individual image. Signed 64-bit SQLite INTEGER.
    seed               INTEGER NOT NULL,
    -- Snapshot of image tagging results: {"tag":null} initially;
    -- future versions may use {"tag":0.92} for confidence scores.
    tags_json          TEXT NOT NULL,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    FOREIGN KEY (generation_id) REFERENCES generations(id) ON DELETE CASCADE,
    UNIQUE (generation_id, position),
    UNIQUE (file_path),
    CHECK (json_valid(tags_json)),
    CHECK (json_type(tags_json) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_images_generation
    ON images(generation_id);

-- Transaction contract (FastAPI):
-- 1. Generate the configured number of images and tag EVERY image.
-- 2. Verify image count equals parameters_json.image_count.
-- 3. Validate liked/disliked IDs: from the SAME parent generation, distinct,
--    disjoint, at least one selected for non-root, and all JSON items integers.
-- 4. Save a generation + its image rows atomically in a single transaction.
-- 5. Only commit after all validations succeed. No pending/running/failed rows.
-- 6. Preserve old generations; branches are new child rows, not updates.
-- 7. Keep unsubmitted user ratings only in React's transient state.
-- 8. Use new random seeds for re-generation; record actual seed per image.
-- 9. Coordinate staged image files and DB commits; cleanup on failures.
-- 10. Root generation has parent_id=NULL and selection_json=NULL.
-- Note: SQLite row CHECK constraints cannot verify the number of child image
-- rows, and filesystem writes are not part of SQLite transactions.
