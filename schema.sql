-- Create users table
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    name TEXT,
    display_name TEXT,
    tier TEXT DEFAULT 'Unranked',
    wins INT DEFAULT 0,
    total_games INT DEFAULT 0
);

-- Create matches table
CREATE TABLE matches (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    winning_team TEXT -- 'A' or 'B'
);

-- Create match_participants table
CREATE TABLE match_participants (
    id SERIAL PRIMARY KEY,
    match_id INT REFERENCES matches(id),
    user_id BIGINT REFERENCES users(id),
    team TEXT -- 'A' or 'B'
);
