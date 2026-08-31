-- Corré esto una sola vez como root de MySQL:
--   sudo mysql < deploy/setup_mysql.sql
-- Cambiá la contraseña antes de correrlo (o después con ALTER USER).

CREATE DATABASE IF NOT EXISTS napsis_portal
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'napsis'@'localhost' IDENTIFIED BY 'CAMBIAR-ESTA-PASSWORD';
GRANT ALL PRIVILEGES ON napsis_portal.* TO 'napsis'@'localhost';
FLUSH PRIVILEGES;
