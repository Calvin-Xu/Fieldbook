ALTER TABLE notes ADD COLUMN title TEXT
CHECK (title IS NULL OR (length(trim(title)) BETWEEN 1 AND 120));

ALTER TABLE notes ADD COLUMN body_format TEXT NOT NULL DEFAULT 'markdown'
CHECK (body_format IN ('markdown', 'plain'));
