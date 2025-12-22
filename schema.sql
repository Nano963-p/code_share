/* =========================================================
   MINI_GITHUB - Schéma MySQL solide + triggers utiles
   (MySQL 8+ recommandé)
   ========================================================= */

CREATE DATABASE IF NOT EXISTS code_share
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE code_share;

-- Supprimer d'abord les tables dépendantes
DROP TABLE IF EXISTS project_activity;
DROP TABLE IF EXISTS project_tags;
DROP TABLE IF EXISTS tags;
DROP TABLE IF EXISTS followers;
DROP TABLE IF EXISTS stars;
DROP TABLE IF EXISTS comments;
DROP TABLE IF EXISTS files;
DROP TABLE IF EXISTS project_members;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS users;

/* =========================================================
   TABLE: users
   ========================================================= */
CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(30) NOT NULL,
  email VARCHAR(100) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  bio VARCHAR(500) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  -- Normalisation (évite Alice vs alice)
  username_norm VARCHAR(30)
    GENERATED ALWAYS AS (LOWER(TRIM(username))) STORED,
  email_norm VARCHAR(100)
    GENERATED ALWAYS AS (LOWER(TRIM(email))) STORED,

  CONSTRAINT uq_users_username_norm UNIQUE (username_norm),
  CONSTRAINT uq_users_email_norm UNIQUE (email_norm),

  CONSTRAINT chk_username_len CHECK (CHAR_LENGTH(username) BETWEEN 3 AND 30),
  CONSTRAINT chk_username_format CHECK (username REGEXP '^[a-zA-Z0-9_]+$'),
  CONSTRAINT chk_email_format CHECK (email REGEXP '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$')
) ENGINE=InnoDB;

CREATE INDEX idx_users_created_at ON users(created_at);

/* =========================================================
   TABLE: projects
   ========================================================= */
CREATE TABLE projects (
  id INT AUTO_INCREMENT PRIMARY KEY,
  owner_id INT NOT NULL,
  title VARCHAR(100) NOT NULL,
  description VARCHAR(2000) NULL,
  language VARCHAR(50) NULL,
  is_private BOOLEAN NOT NULL DEFAULT FALSE,
  status ENUM('active','archived') NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    ON UPDATE CURRENT_TIMESTAMP,

  CONSTRAINT fk_projects_owner
    FOREIGN KEY (owner_id) REFERENCES users(id)
    ON DELETE CASCADE,

  CONSTRAINT chk_project_title_len CHECK (CHAR_LENGTH(title) BETWEEN 3 AND 100)
) ENGINE=InnoDB;

CREATE INDEX idx_projects_owner ON projects(owner_id);
CREATE INDEX idx_projects_visibility ON projects(is_private);
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_created_at ON projects(created_at);

/* =========================================================
   TABLE: project_members
   ========================================================= */
CREATE TABLE project_members (
  project_id INT NOT NULL,
  user_id INT NOT NULL,
  role ENUM('owner','admin','member') NOT NULL DEFAULT 'member',
  joined_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (project_id, user_id),

  CONSTRAINT fk_pm_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE CASCADE,

  CONSTRAINT fk_pm_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_pm_user ON project_members(user_id);
CREATE INDEX idx_pm_role ON project_members(project_id, role);

/* =========================================================
   TABLE: files
   ========================================================= */
CREATE TABLE files (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  uploaded_by INT NOT NULL,
  filename VARCHAR(255) NOT NULL,
  filepath VARCHAR(500) NOT NULL,
  filesize BIGINT NOT NULL,
  sha256 CHAR(64) NULL,
  uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_files_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE CASCADE,

  CONSTRAINT fk_files_uploader
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
    ON DELETE CASCADE,

  CONSTRAINT uq_files_project_filepath UNIQUE (project_id, filepath),

  CONSTRAINT chk_filesize_positive CHECK (filesize > 0),
  CONSTRAINT chk_filesize_limit CHECK (filesize <= 10485760)
) ENGINE=InnoDB;

CREATE INDEX idx_files_project ON files(project_id);
CREATE INDEX idx_files_uploader ON files(uploaded_by);
CREATE INDEX idx_files_uploaded_at ON files(uploaded_at);
CREATE INDEX idx_files_sha256 ON files(sha256);

/* =========================================================
   TABLE: comments
   ========================================================= */
CREATE TABLE comments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  user_id INT NOT NULL,
  message VARCHAR(1000) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_comments_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE CASCADE,

  CONSTRAINT fk_comments_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE,

  CONSTRAINT chk_comment_len CHECK (CHAR_LENGTH(message) BETWEEN 1 AND 1000)
) ENGINE=InnoDB;

CREATE INDEX idx_comments_project_created ON comments(project_id, created_at);
CREATE INDEX idx_comments_user ON comments(user_id);

/* =========================================================
   TABLE: stars
   ========================================================= */
CREATE TABLE stars (
  user_id INT NOT NULL,
  project_id INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (user_id, project_id),

  CONSTRAINT fk_stars_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE,

  CONSTRAINT fk_stars_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_stars_project ON stars(project_id);
CREATE INDEX idx_stars_user_created ON stars(user_id, created_at);

/* =========================================================
   TABLE: followers
   ========================================================= */
CREATE TABLE followers (
  follower_id INT NOT NULL,
  following_id INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (follower_id, following_id),

  CONSTRAINT fk_followers_follower
    FOREIGN KEY (follower_id) REFERENCES users(id)
    ON DELETE CASCADE,

  CONSTRAINT fk_followers_following
    FOREIGN KEY (following_id) REFERENCES users(id)
    ON DELETE CASCADE,

  CONSTRAINT chk_no_self_follow CHECK (follower_id <> following_id)
) ENGINE=InnoDB;

CREATE INDEX idx_followers_following ON followers(following_id);
CREATE INDEX idx_followers_follower ON followers(follower_id);

/* =========================================================
   TABLE: tags + project_tags (tags normalisés)
   ========================================================= */
CREATE TABLE tags (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(50) NOT NULL,

  name_norm VARCHAR(50)
    GENERATED ALWAYS AS (LOWER(TRIM(name))) STORED,

  CONSTRAINT uq_tags_name_norm UNIQUE (name_norm),
  CONSTRAINT chk_tag_len CHECK (CHAR_LENGTH(name) BETWEEN 1 AND 50),
  CONSTRAINT chk_tag_format CHECK (name REGEXP '^[a-zA-Z0-9_\\-]+$')
) ENGINE=InnoDB;

CREATE TABLE project_tags (
  project_id INT NOT NULL,
  tag_id INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (project_id, tag_id),

  CONSTRAINT fk_pt_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE CASCADE,

  CONSTRAINT fk_pt_tag
    FOREIGN KEY (tag_id) REFERENCES tags(id)
    ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_project_tags_tag ON project_tags(tag_id);

/* =========================================================
   TABLE: project_activity (journal d’activité)
   ========================================================= */
CREATE TABLE project_activity (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL,
  user_id INT NULL,
  action ENUM(
    'created_project',
    'joined_project',
    'left_project',
    'uploaded_file',
    'commented',
    'starred'
  ) NOT NULL,
  entity_type ENUM('project','member','file','comment','star') NOT NULL,
  entity_id BIGINT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CONSTRAINT fk_activity_project
    FOREIGN KEY (project_id) REFERENCES projects(id)
    ON DELETE CASCADE,

  CONSTRAINT fk_activity_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE INDEX idx_activity_project_created ON project_activity(project_id, created_at);
CREATE INDEX idx_activity_user_created ON project_activity(user_id, created_at);

USE code_share;

-- Helpful indexes (safe to add)
CREATE INDEX idx_pm_project_role ON project_members(project_id, role);
CREATE INDEX idx_pm_user ON project_members(user_id);

-- If you re-run this script, drop triggers/procedure first
DROP TRIGGER IF EXISTS trg_projects_ai_add_owner_member;
DROP TRIGGER IF EXISTS trg_projects_au_sync_owner_member;
DROP TRIGGER IF EXISTS trg_pm_bi_enforce_owner_rules;
DROP TRIGGER IF EXISTS trg_pm_bu_enforce_owner_rules;
DROP TRIGGER IF EXISTS trg_pm_bd_block_owner_delete;

DROP PROCEDURE IF EXISTS transfer_project_ownership;

DELIMITER $$

/* ---------------------------------------------------------
   1) When a project is created, auto-create owner membership
   --------------------------------------------------------- */
CREATE TRIGGER trg_projects_ai_add_owner_member
AFTER INSERT ON projects
FOR EACH ROW
BEGIN
  INSERT INTO project_members(project_id, user_id, role)
  VALUES (NEW.id, NEW.owner_id, 'owner')
  ON DUPLICATE KEY UPDATE role = 'owner';
END$$

/* ---------------------------------------------------------
   2) When project owner_id changes, sync project_members:
      - old owner -> admin
      - new owner -> owner
   --------------------------------------------------------- */
CREATE TRIGGER trg_projects_au_sync_owner_member
AFTER UPDATE ON projects
FOR EACH ROW
BEGIN
  IF NEW.owner_id <> OLD.owner_id THEN

    -- Demote old owner first (now old owner is NOT the current owner)
    UPDATE project_members
      SET role = 'admin'
    WHERE project_id = NEW.id
      AND user_id = OLD.owner_id
      AND role = 'owner';

    -- Promote new owner (must be the only owner)
    INSERT INTO project_members(project_id, user_id, role)
    VALUES (NEW.id, NEW.owner_id, 'owner')
    ON DUPLICATE KEY UPDATE role = 'owner';

  END IF;
END$$

/* ---------------------------------------------------------
   3) Enforce "single owner" + "owner must match projects.owner_id"
      on INSERT into project_members
   --------------------------------------------------------- */
CREATE TRIGGER trg_pm_bi_enforce_owner_rules
BEFORE INSERT ON project_members
FOR EACH ROW
BEGIN
  DECLARE proj_owner INT;

  SELECT owner_id INTO proj_owner
  FROM projects
  WHERE id = NEW.project_id;

  IF proj_owner IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Project does not exist.';
  END IF;

  -- If the row is for the project owner, role must be owner
  IF NEW.user_id = proj_owner AND NEW.role <> 'owner' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The project owner must have role=owner.';
  END IF;

  -- If inserting an owner row, it must match projects.owner_id
  IF NEW.role = 'owner' THEN

    IF NEW.user_id <> proj_owner THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only projects.owner_id can be role=owner.';
    END IF;

    IF EXISTS (
      SELECT 1 FROM project_members
      WHERE project_id = NEW.project_id
        AND role = 'owner'
    ) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A project can have only one owner.';
    END IF;

  END IF;
END$$

/* ---------------------------------------------------------
   4) Enforce the same rules on UPDATE project_members
      - cannot demote current owner
      - cannot create a second owner
      - owner must match projects.owner_id
   --------------------------------------------------------- */
CREATE TRIGGER trg_pm_bu_enforce_owner_rules
BEFORE UPDATE ON project_members
FOR EACH ROW
BEGIN
  DECLARE proj_owner INT;

  SELECT owner_id INTO proj_owner
  FROM projects
  WHERE id = NEW.project_id;

  IF proj_owner IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Project does not exist.';
  END IF;

  -- If the row is for the project owner, role must remain owner
  IF NEW.user_id = proj_owner AND NEW.role <> 'owner' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot demote the project owner. Transfer ownership first.';
  END IF;

  -- If trying to set role to owner, must match projects.owner_id
  IF NEW.role = 'owner' THEN

    IF NEW.user_id <> proj_owner THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only projects.owner_id can be role=owner.';
    END IF;

    IF EXISTS (
      SELECT 1 FROM project_members
      WHERE project_id = NEW.project_id
        AND role = 'owner'
        AND user_id <> NEW.user_id
    ) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A project can have only one owner.';
    END IF;

  END IF;

  -- Block demoting the current owner row (even if user_id not changing)
  IF OLD.role = 'owner' AND NEW.role <> 'owner' THEN
    IF OLD.user_id = proj_owner THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot demote current owner. Transfer ownership first.';
    END IF;
  END IF;

END$$

/* ---------------------------------------------------------
   5) Block deleting the owner membership row
   --------------------------------------------------------- */
CREATE TRIGGER trg_pm_bd_block_owner_delete
BEFORE DELETE ON project_members
FOR EACH ROW
BEGIN
  IF OLD.role = 'owner' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot delete the owner membership.';
  END IF;
END$$

/* ---------------------------------------------------------
   OPTIONAL: Safe ownership transfer procedure
   (The triggers will do the role syncing.)
   --------------------------------------------------------- */
CREATE PROCEDURE transfer_project_ownership(
  IN p_project_id INT,
  IN p_new_owner_id INT
)
BEGIN
  -- Update the source of truth; triggers sync membership roles
  UPDATE projects
    SET owner_id = p_new_owner_id
  WHERE id = p_project_id;
END$$

DELIMITER ;

-- Role permission matrix (optional)
DROP TABLE IF EXISTS role_permissions;

CREATE TABLE role_permissions (
  role ENUM('owner','admin','member') NOT NULL,
  permission ENUM(
    'project_view_private',
    'project_edit',
    'project_delete',
    'members_manage',
    'files_upload',
    'files_delete',
    'comments_create',
    'stars_toggle'
  ) NOT NULL,
  allowed BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (role, permission)
) ENGINE=InnoDB;

-- Seed defaults
INSERT INTO role_permissions(role, permission, allowed) VALUES
-- owner: everything
('owner','project_view_private',1),
('owner','project_edit',1),
('owner','project_delete',1),
('owner','members_manage',1),
('owner','files_upload',1),
('owner','files_delete',1),
('owner','comments_create',1),
('owner','stars_toggle',1),

-- admin
('admin','project_view_private',1),
('admin','project_edit',0),
('admin','project_delete',0),
('admin','members_manage',0),
('admin','files_upload',1),
('admin','files_delete',0),
('admin','comments_create',1),
('admin','stars_toggle',1),

-- member
('member','project_view_private',1),
('member','project_edit',0),
('member','project_delete',0),
('member','members_manage',0),
('member','files_upload',1),
('member','files_delete',0),
('member','comments_create',1),
('member','stars_toggle',1);

SELECT project_id, role, COUNT(*)
FROM project_members
WHERE role = 'owner'
GROUP BY project_id
HAVING COUNT(*) > 1;
