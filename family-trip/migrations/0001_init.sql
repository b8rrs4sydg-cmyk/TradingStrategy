CREATE TABLE trips (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  days INTEGER NOT NULL DEFAULT 3,
  tips TEXT NOT NULL DEFAULT '{}',   -- AI 每日提示 JSON
  version INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE TABLE items (
  id TEXT PRIMARY KEY,
  trip_id TEXT NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
  day INTEGER NOT NULL DEFAULT 0,      -- 0 = 尚未安排
  position INTEGER NOT NULL DEFAULT 0,
  name TEXT NOT NULL,
  lat REAL,
  lng REAL,
  url TEXT,
  note TEXT NOT NULL DEFAULT '',
  added_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX items_trip ON items(trip_id, day, position);
