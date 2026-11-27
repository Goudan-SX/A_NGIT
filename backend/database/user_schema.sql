-- ==========================================================================
-- 反诈卫士 · 用户中心数据库结构（SQL Server，可重复执行）
-- 数据库：[user]
-- 设计：共享表 + user_id 租户标识列；user_id 建索引；isdeleted 软删除可恢复。
-- ==========================================================================

IF OBJECT_ID('dbo.users', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.users (
        user_id          INT IDENTITY(1001,1) NOT NULL
            CONSTRAINT PK_users PRIMARY KEY,
        username         NVARCHAR(254) NOT NULL,              -- 邮箱 / root
        password_hash    NVARCHAR(256) NOT NULL,              -- pbkdf2_sha256$迭代$salt$hash
        password_salt    NVARCHAR(64) NOT NULL,
        role             NVARCHAR(16) NOT NULL
            CONSTRAINT DF_users_role DEFAULT N'user',         -- user / root
        api_base_url     NVARCHAR(500) NULL,
        api_key          NVARCHAR(512) NULL,
        api_model        NVARCHAR(120) NULL,
        api_vision_model NVARCHAR(120) NULL,
        api_status       NVARCHAR(16) NOT NULL
            CONSTRAINT DF_users_api_status DEFAULT N'unknown', -- unknown / ok / error
        api_checked_at   DATETIME2(0) NULL,
        isdeleted        BIT NOT NULL CONSTRAINT DF_users_deleted DEFAULT 0,
        created_at       DATETIME2(0) NOT NULL
            CONSTRAINT DF_users_created DEFAULT SYSDATETIME(),
        updated_at       DATETIME2(0) NOT NULL
            CONSTRAINT DF_users_updated DEFAULT SYSDATETIME(),
        last_login_at    DATETIME2(0) NULL
    );
END

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'IX_users_userid' AND object_id = OBJECT_ID('dbo.users'))
    CREATE INDEX IX_users_userid ON dbo.users(user_id)
        INCLUDE (username, role, isdeleted, api_status);

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'UX_users_username' AND object_id = OBJECT_ID('dbo.users'))
    CREATE UNIQUE INDEX UX_users_username ON dbo.users(username)
        WHERE isdeleted = 0;

-- 登录会话：token 只保存 sha256 摘要；按 user_id 隔离
IF OBJECT_ID('dbo.user_sessions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.user_sessions (
        session_id   BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_user_sessions PRIMARY KEY,
        user_id      INT NOT NULL,
        token_hash   CHAR(64) NOT NULL,
        created_at   DATETIME2(0) NOT NULL
            CONSTRAINT DF_sessions_created DEFAULT SYSDATETIME(),
        expires_at   DATETIME2(0) NOT NULL,
        isdeleted    BIT NOT NULL CONSTRAINT DF_sessions_deleted DEFAULT 0,
        CONSTRAINT FK_sessions_user FOREIGN KEY (user_id)
            REFERENCES dbo.users(user_id)
    );
END

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'IX_sessions_userid' AND object_id = OBJECT_ID('dbo.user_sessions'))
    CREATE INDEX IX_sessions_userid ON dbo.user_sessions(user_id, expires_at, isdeleted);

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'UX_sessions_token' AND object_id = OBJECT_ID('dbo.user_sessions'))
    CREATE UNIQUE INDEX UX_sessions_token ON dbo.user_sessions(token_hash);

-- 租户数据共享表：所有用户共用一张表，通过 user_id 划分
IF OBJECT_ID('dbo.user_data', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.user_data (
        data_id      BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_user_data PRIMARY KEY,
        user_id      INT NOT NULL,
        data_key     NVARCHAR(64) NOT NULL,
        data_value   NVARCHAR(MAX) NULL,
        isdeleted    BIT NOT NULL CONSTRAINT DF_user_data_deleted DEFAULT 0,
        created_at   DATETIME2(0) NOT NULL
            CONSTRAINT DF_user_data_created DEFAULT SYSDATETIME(),
        updated_at   DATETIME2(0) NOT NULL
            CONSTRAINT DF_user_data_updated DEFAULT SYSDATETIME(),
        CONSTRAINT FK_user_data_user FOREIGN KEY (user_id)
            REFERENCES dbo.users(user_id)
    );
END

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'IX_user_data_userid' AND object_id = OBJECT_ID('dbo.user_data'))
    CREATE INDEX IX_user_data_userid ON dbo.user_data(user_id, data_key, isdeleted);

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'UX_user_data_tenant_key' AND object_id = OBJECT_ID('dbo.user_data'))
    CREATE UNIQUE INDEX UX_user_data_tenant_key ON dbo.user_data(user_id, data_key)
        WHERE isdeleted = 0;


-- ==========================================================================
-- 统一租户键：u{user_id}:{username}（幂等）
-- ==========================================================================
IF COL_LENGTH('dbo.users', 'user_key') IS NULL
    ALTER TABLE dbo.users ADD user_key NVARCHAR(300) NULL;
IF COL_LENGTH('dbo.user_sessions', 'user_key') IS NULL
    ALTER TABLE dbo.user_sessions ADD user_key NVARCHAR(300) NULL;
IF COL_LENGTH('dbo.user_data', 'user_key') IS NULL
    ALTER TABLE dbo.user_data ADD user_key NVARCHAR(300) NULL;

GO

UPDATE dbo.users
SET user_key = CONCAT(N'u', user_id, N':', LOWER(username))
WHERE user_key IS NULL OR user_key = N'';

UPDATE dbo.user_sessions
SET user_key = (SELECT TOP 1 u.user_key FROM dbo.users u WHERE u.user_id = dbo.user_sessions.user_id)
WHERE user_key IS NULL OR user_key = N'';

UPDATE dbo.user_data
SET user_key = (SELECT TOP 1 u.user_key FROM dbo.users u WHERE u.user_id = dbo.user_data.user_id)
WHERE user_key IS NULL OR user_key = N'';

GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_users_userkey' AND object_id = OBJECT_ID('dbo.users'))
    CREATE INDEX IX_users_userkey ON dbo.users(user_key) INCLUDE (user_id, role, isdeleted);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_user_data_userkey' AND object_id = OBJECT_ID('dbo.user_data'))
    CREATE INDEX IX_user_data_userkey ON dbo.user_data(user_key, data_key, isdeleted);
