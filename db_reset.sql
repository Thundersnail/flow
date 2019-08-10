DROP TABLE IF EXISTS project;
CREATE TABLE project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    description TEXT,
    create_dt TEXT
)

DROP TABLE IF EXISTS work;
CREATE TABLE work (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    start_dt TEXT,
    end_dt TEXT,
    duration_sec INTEGER,
    note TEXT,
    info_json TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES project(id)
)
