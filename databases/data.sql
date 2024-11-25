-- Drop and recreate Users table (for oncologists and researchers)
DROP TABLE IF EXISTS Users;
CREATE TABLE Users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('Oncologist', 'Researcher') NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Drop and recreate Patients table
DROP TABLE IF EXISTS Patients;
CREATE TABLE Patients (
    patient_id VARCHAR(20) UNIQUE NOT NULL,
    mutation_type VARCHAR(255),
    cancer_type VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Import data from mutationalData.csv file
LOAD DATA INFILE '/BIOM9450/databases/mutationalData.csv' 
INTO TABLE Patients
FIELDS TERMINATED BY ',' 
LINES TERMINATED BY '\n' 
IGNORE 1 LINES
(
    patient_id, mutation_type, cancer_type
);

-- Insert sample oncologists into Users table
INSERT INTO Users (first_name, last_name, username, password_hash, role) VALUES
('John', 'Doe', 'jdoe_oncologist', SHA2('password123', 256), 'Oncologist'),
('Jane', 'Smith', 'jsmith_oncologist', SHA2('securepass', 256), 'Oncologist');

-- Insert sample researchers into Users table
INSERT INTO Users (first_name, last_name, username, password_hash, role) VALUES
('Emily', 'Brown', 'ebrown_researcher', SHA2('researcherpass', 256), 'Researcher'),
('Michael', 'Clark', 'mclark_researcher', SHA2('data4life', 256), 'Researcher');

-- Insert data into Patient table
INSERT INTO Patients (specimen_id, mutation_type, cancer_type) VALUES
('SP112909', 'single base substitution', 'Brain'),
('SP112909', 'insertion of <=200bp', 'Brain'),
('SP192770', 'single base substitution', 'Breast'),
('SP195936', 'single base substitution', 'Brain'),
('SP195938', 'single base substitution', 'Breast'),
('SP195941', 'single base substitution', 'Blood'),
('SP195947', 'single base substitution', 'Prostate'),
('SP195961', 'single base substitution', 'Liver'),
('SP195965', 'single base substitution', 'Breast');

-- Verify initial data
SELECT * FROM Users;
SELECT * FROM Patients;
