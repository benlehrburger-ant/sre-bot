-- Database initialization script for SRE Demo
-- Creates tables and sample data

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    total DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert sample users
INSERT INTO users (name, email) VALUES
    ('Alice Johnson', 'alice@example.com'),
    ('Bob Smith', 'bob@example.com'),
    ('Carol Williams', 'carol@example.com'),
    ('David Brown', 'david@example.com'),
    ('Eva Martinez', 'eva@example.com'),
    ('Frank Garcia', 'frank@example.com'),
    ('Grace Lee', 'grace@example.com'),
    ('Henry Wilson', 'henry@example.com'),
    ('Ivy Chen', 'ivy@example.com'),
    ('Jack Taylor', 'jack@example.com')
ON CONFLICT (email) DO NOTHING;

-- Insert sample orders
INSERT INTO orders (user_id, total, status) VALUES
    (1, 99.99, 'completed'),
    (1, 149.50, 'completed'),
    (2, 75.00, 'pending'),
    (3, 200.00, 'completed'),
    (4, 45.99, 'shipped'),
    (5, 320.00, 'completed'),
    (6, 89.99, 'pending'),
    (7, 175.50, 'completed'),
    (8, 55.00, 'cancelled'),
    (9, 450.00, 'completed'),
    (10, 125.00, 'shipped'),
    (1, 67.50, 'completed'),
    (2, 230.00, 'completed'),
    (3, 95.00, 'pending'),
    (4, 180.00, 'completed');
