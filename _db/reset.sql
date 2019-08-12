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

DROP TABLE IF EXISTS break;
CREATE TABLE break (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    work_id INTEGER NOT NULL,
    beg_dt TEXT NOT NULL,
    end_dt TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task(id),
    FOREIGN KEY (work_id) REFERENCES work(id)
)

-- WARNING: This file cannot end with a trailing semi-colon. We use .split('<SEMICOLON>') to parse sentences out.
-- WARNING: You cannot use any semicolons in this file without breaking the parser UNLESS between two statements.




