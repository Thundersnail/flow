DROP TABLE IF EXISTS task;
CREATE TABLE task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    cache_beg_dt TEXT,
    cache_status_code INTEGER DEFAULT 0
);

DROP TABLE IF EXISTS work;
CREATE TABLE work (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    cache_beg_dt TEXT,
    cache_end_dt TEXT,
    cache_duration_sec INTEGER DEFAULT 0,
    FOREIGN KEY(task_id) REFERENCES task(id)
);

DROP TABLE IF EXISTS note;
CREATE TABLE note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    task_id INTEGER NOT NULL,
    opt_work_id INTEGER DEFAULT NULL,
    user_text TEXT DEFAULT NULL,
    flow_text TEXT DEFAULT NULL,
    FOREIGN KEY(task_id) REFERENCES task(id),
    FOREIGN KEY (opt_work_id) REFERENCES work(id)
);
