CREATE DATABASE IF NOT EXISTS mini_github;
USE mini_github;

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE,
    email VARCHAR(100) UNIQUE,
    password VARCHAR(255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(100),
    description TEXT,
    owner_id INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES users(id)
);

CREATE TABLE project_members (
    project_id INT,
    user_id INT,
    role VARCHAR(50) DEFAULT 'member',
    PRIMARY KEY (project_id, user_id)
);

CREATE TABLE files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT,
    filename VARCHAR(100),
    filepath VARCHAR(255),
    uploaded_by INT,
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE comments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT,
    user_id INT,
    message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE likes (
    user_id INT,
    project_id INT,
    PRIMARY KEY (user_id, project_id)
);

