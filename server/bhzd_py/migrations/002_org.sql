CREATE TABLE schools ( id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL );
CREATE TABLE classes (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, school_id TEXT REFERENCES schools(id),
  invite_code TEXT UNIQUE, archived_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE class_teachers (
  class_id TEXT NOT NULL REFERENCES classes(id),
  teacher_id TEXT NOT NULL REFERENCES users(id),
  PRIMARY KEY (class_id, teacher_id)
);
CREATE TABLE class_enrollments (
  class_id TEXT NOT NULL REFERENCES classes(id),
  student_id TEXT NOT NULL REFERENCES users(id),
  joined_at TEXT NOT NULL, left_at TEXT,
  PRIMARY KEY (class_id, student_id)
);
