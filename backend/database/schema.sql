-- ==========================================================================
-- 反诈卫士 · SQL Server 数据库结构（可重复执行）
-- 数据库：AntiFraudGuard
-- ==========================================================================

IF OBJECT_ID('dbo.analyses', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.analyses (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_analyses_created DEFAULT SYSDATETIME(),
        source          NVARCHAR(16) NOT NULL,
        input_text      NVARCHAR(MAX) NULL,
        note            NVARCHAR(500) NULL,
        risk_score      INT NOT NULL,
        risk_level      NVARCHAR(16) NOT NULL,
        scam_type       NVARCHAR(64) NULL,
        summary         NVARCHAR(1000) NULL,
        result_json     NVARCHAR(MAX) NOT NULL,
        engine          NVARCHAR(80) NULL,
        duration_ms     INT NULL,
        is_false_positive BIT NOT NULL CONSTRAINT DF_analyses_fp DEFAULT 0,
        feedback_note   NVARCHAR(500) NULL,
        report_count    INT NOT NULL CONSTRAINT DF_analyses_reports DEFAULT 0
    );
END

IF OBJECT_ID('dbo.images', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.images (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        analysis_id     INT NOT NULL,
        original_name   NVARCHAR(255) NOT NULL,
        stored_name     NVARCHAR(255) NOT NULL,
        thumb_name      NVARCHAR(255) NULL,
        media_type      NVARCHAR(16) NOT NULL,
        content_type    NVARCHAR(100) NULL,
        size_bytes      BIGINT NOT NULL,
        width           INT NULL,
        height          INT NULL,
        sha256          CHAR(64) NULL,
        risk_score      INT NULL,
        ocr_text        NVARCHAR(MAX) NULL,
        detail_json     NVARCHAR(MAX) NULL,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_images_created DEFAULT SYSDATETIME(),
        CONSTRAINT FK_images_analysis FOREIGN KEY (analysis_id)
            REFERENCES dbo.analyses(id) ON DELETE CASCADE
    );
END

IF OBJECT_ID('dbo.reports', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.reports (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        report_no       NVARCHAR(32) NOT NULL,
        analysis_id     INT NOT NULL,
        channel         NVARCHAR(32) NULL,
        title           NVARCHAR(200) NOT NULL,
        content         NVARCHAR(MAX) NOT NULL,
        status          NVARCHAR(16) NOT NULL CONSTRAINT DF_reports_status DEFAULT 'submitted',
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_reports_created DEFAULT SYSDATETIME(),
        CONSTRAINT UQ_reports_no UNIQUE (report_no),
        CONSTRAINT FK_reports_analysis FOREIGN KEY (analysis_id)
            REFERENCES dbo.analyses(id) ON DELETE CASCADE
    );
END

IF OBJECT_ID('dbo.logs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.logs (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_logs_created DEFAULT SYSDATETIME(),
        level           NVARCHAR(12) NOT NULL,
        event           NVARCHAR(40) NOT NULL,
        message         NVARCHAR(1000) NOT NULL,
        meta_json       NVARCHAR(MAX) NULL,
        duration_ms     INT NULL
    );
END

IF OBJECT_ID('dbo.knowledge', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.knowledge (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        category        NVARCHAR(32) NOT NULL,
        title           NVARCHAR(120) NOT NULL,
        content         NVARCHAR(MAX) NOT NULL,
        tags            NVARCHAR(200) NULL,
        sort_order      INT NOT NULL CONSTRAINT DF_knowledge_sort DEFAULT 0,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_knowledge_created DEFAULT SYSDATETIME()
    );
END

-- 文本案例库：从旧版 scam_cases 平滑迁移
IF OBJECT_ID('dbo.text_cases', 'U') IS NULL AND OBJECT_ID('dbo.scam_cases', 'U') IS NOT NULL
BEGIN
    EXEC sp_rename 'dbo.scam_cases', 'text_cases';
END

IF OBJECT_ID('dbo.text_cases', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.text_cases (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        title           NVARCHAR(200) NOT NULL,
        category        NVARCHAR(64) NOT NULL,
        content         NVARCHAR(MAX) NOT NULL,
        content_norm    NVARCHAR(MAX) NOT NULL,
        content_hash    CHAR(64) NOT NULL,
        risk_score      INT NOT NULL,
        risk_level      NVARCHAR(16) NOT NULL,
        scam_type       NVARCHAR(64) NULL,
        summary         NVARCHAR(1000) NULL,
        result_json     NVARCHAR(MAX) NOT NULL,
        source          NVARCHAR(32) NOT NULL CONSTRAINT DF_cases_source DEFAULT 'seed',
        hit_count       INT NOT NULL CONSTRAINT DF_cases_hits DEFAULT 0,
        is_active       BIT NOT NULL CONSTRAINT DF_cases_active DEFAULT 1,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_cases_created DEFAULT SYSDATETIME(),
        updated_at      DATETIME2(0) NOT NULL CONSTRAINT DF_cases_updated DEFAULT SYSDATETIME(),
        CONSTRAINT UQ_cases_hash UNIQUE (content_hash)
    );
END

IF COL_LENGTH('dbo.text_cases', 'review_json') IS NULL
    ALTER TABLE dbo.text_cases ADD review_json NVARCHAR(MAX) NULL;

IF COL_LENGTH('dbo.text_cases', 'reviewed_at') IS NULL
    ALTER TABLE dbo.text_cases ADD reviewed_at DATETIME2(0) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_cases_active' AND object_id = OBJECT_ID('dbo.text_cases'))
    CREATE INDEX IX_cases_active ON dbo.text_cases(is_active, risk_score DESC);

-- Guardian-AI 关键词规则库（来自反诈关键词汇总 CSV）
IF OBJECT_ID('dbo.guardian_keywords', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.guardian_keywords (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        keyword         NVARCHAR(80) NOT NULL,
        category        NVARCHAR(40) NOT NULL,
        weight          INT NOT NULL CONSTRAINT DF_guardian_kw_weight DEFAULT 8,
        source          NVARCHAR(64) NULL,
        hit_count       INT NOT NULL CONSTRAINT DF_guardian_kw_hits DEFAULT 0,
        is_active       BIT NOT NULL CONSTRAINT DF_guardian_kw_active DEFAULT 1,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_guardian_kw_created DEFAULT SYSDATETIME(),
        CONSTRAINT UQ_guardian_kw UNIQUE (keyword)
    );
END

-- Guardian-AI 分省案例示例
IF OBJECT_ID('dbo.guardian_cases', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.guardian_cases (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        code            NVARCHAR(20) NOT NULL,
        province        NVARCHAR(40) NOT NULL,
        region          NVARCHAR(80) NULL,
        age_group       NVARCHAR(40) NULL,
        category        NVARCHAR(80) NULL,
        subtype         NVARCHAR(120) NULL,
        scam_type       NVARCHAR(120) NULL,
        channel         NVARCHAR(120) NULL,
        method          NVARCHAR(MAX) NULL,
        keywords        NVARCHAR(500) NULL,
        loss            NVARCHAR(100) NULL,
        source          NVARCHAR(300) NULL,
        tips            NVARCHAR(1000) NULL,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_guardian_cases_created DEFAULT SYSDATETIME(),
        CONSTRAINT UQ_guardian_case_code UNIQUE (code)
    );
END

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_guardian_cases_province' AND object_id = OBJECT_ID('dbo.guardian_cases'))
    CREATE INDEX IX_guardian_cases_province ON dbo.guardian_cases(province, category);

-- 交易风控规则库：由金融欺诈数据集提炼，供表格模型/规则引擎使用
IF OBJECT_ID('dbo.transaction_rules', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.transaction_rules (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        code            NVARCHAR(64) NOT NULL,
        name            NVARCHAR(120) NOT NULL,
        description     NVARCHAR(500) NOT NULL,
        condition_json  NVARCHAR(MAX) NOT NULL,
        risk_weight     INT NOT NULL,
        support         DECIMAL(10, 4) NULL,
        fraud_rate      DECIMAL(10, 4) NULL,
        lift            DECIMAL(10, 2) NULL,
        source          NVARCHAR(64) NOT NULL CONSTRAINT DF_txn_rules_source DEFAULT 'indian_financial_fraud',
        is_active       BIT NOT NULL CONSTRAINT DF_txn_rules_active DEFAULT 1,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_txn_rules_created DEFAULT SYSDATETIME(),
        updated_at      DATETIME2(0) NOT NULL CONSTRAINT DF_txn_rules_updated DEFAULT SYSDATETIME(),
        CONSTRAINT UQ_txn_rules_code UNIQUE (code)
    );
END

-- 交易模型训练记录
IF OBJECT_ID('dbo.transaction_models', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.transaction_models (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        model_name      NVARCHAR(120) NOT NULL,
        trained_at      DATETIME2(0) NOT NULL CONSTRAINT DF_txn_models_trained DEFAULT SYSDATETIME(),
        rows_count      INT NOT NULL,
        fraud_count     INT NOT NULL,
        auc_roc         DECIMAL(8, 4) NULL,
        auc_pr          DECIMAL(8, 4) NULL,
        threshold       DECIMAL(8, 4) NULL,
        artifact_path   NVARCHAR(300) NULL,
        metrics_json    NVARCHAR(MAX) NULL
    );
END

-- 图片案例库：保存图片指纹、OCR 文本与视觉研判结果
IF OBJECT_ID('dbo.image_cases', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.image_cases (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        sha256          CHAR(64) NOT NULL,
        original_name   NVARCHAR(255) NOT NULL,
        stored_name     NVARCHAR(255) NOT NULL,
        content_type    NVARCHAR(100) NULL,
        size_bytes      BIGINT NOT NULL,
        width           INT NULL,
        height          INT NULL,
        ocr_text        NVARCHAR(MAX) NULL,
        risk_score      INT NOT NULL,
        risk_level      NVARCHAR(16) NOT NULL,
        scam_type       NVARCHAR(64) NULL,
        summary         NVARCHAR(1000) NULL,
        result_json     NVARCHAR(MAX) NULL,
        source          NVARCHAR(32) NOT NULL CONSTRAINT DF_image_cases_source DEFAULT 'upload',
        hit_count       INT NOT NULL CONSTRAINT DF_image_cases_hits DEFAULT 0,
        is_active       BIT NOT NULL CONSTRAINT DF_image_cases_active DEFAULT 1,
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_image_cases_created DEFAULT SYSDATETIME(),
        updated_at      DATETIME2(0) NOT NULL CONSTRAINT DF_image_cases_updated DEFAULT SYSDATETIME(),
        CONSTRAINT UQ_image_cases_hash UNIQUE (sha256)
    );
END

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_image_cases_active' AND object_id = OBJECT_ID('dbo.image_cases'))
    CREATE INDEX IX_image_cases_active ON dbo.image_cases(is_active, risk_score DESC);

-- 当前用户暂存库：所有输入/上传内容（文本、图片、语音）
IF OBJECT_ID('dbo.staging_contents', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.staging_contents (
        id              INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        user_key        NVARCHAR(64) NOT NULL,
        modality        NVARCHAR(16) NOT NULL,
        raw_text        NVARCHAR(MAX) NULL,
        stored_name     NVARCHAR(255) NULL,
        original_name   NVARCHAR(255) NULL,
        content_type    NVARCHAR(100) NULL,
        size_bytes      BIGINT NULL,
        width           INT NULL,
        height          INT NULL,
        sha256          CHAR(64) NULL,
        ocr_text        NVARCHAR(MAX) NULL,
        transcript      NVARCHAR(MAX) NULL,
        analysis_id     INT NULL,
        risk_score      INT NULL,
        risk_level      NVARCHAR(16) NULL,
        status          NVARCHAR(16) NOT NULL CONSTRAINT DF_staging_status DEFAULT 'analyzed',
        created_at      DATETIME2(0) NOT NULL CONSTRAINT DF_staging_created DEFAULT SYSDATETIME()
    );
END

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_staging_user_time' AND object_id = OBJECT_ID('dbo.staging_contents'))
    CREATE INDEX IX_staging_user_time ON dbo.staging_contents(user_key, created_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_staging_modality' AND object_id = OBJECT_ID('dbo.staging_contents'))
    CREATE INDEX IX_staging_modality ON dbo.staging_contents(modality, created_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_analyses_created' AND object_id = OBJECT_ID('dbo.analyses'))
    CREATE INDEX IX_analyses_created ON dbo.analyses(created_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_analyses_level' AND object_id = OBJECT_ID('dbo.analyses'))
    CREATE INDEX IX_analyses_level ON dbo.analyses(risk_level, risk_score DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_images_analysis' AND object_id = OBJECT_ID('dbo.images'))
    CREATE INDEX IX_images_analysis ON dbo.images(analysis_id);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_logs_created' AND object_id = OBJECT_ID('dbo.logs'))
    CREATE INDEX IX_logs_created ON dbo.logs(created_at DESC);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_reports_analysis' AND object_id = OBJECT_ID('dbo.reports'))
    CREATE INDEX IX_reports_analysis ON dbo.reports(analysis_id);

-- 科普内容种子数据 ---------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM dbo.knowledge)
BEGIN
    INSERT INTO dbo.knowledge (category, title, content, tags, sort_order) VALUES
    (N'刷单返利', N'所有“先垫付后返利”都是诈骗',
     N'刷单返利诈骗通常以“动动手指日赚几百”开场，先用小额返利建立信任，再以“连单任务”“操作失误”“账户冻结”为由要求持续垫付。记住：正规兼职不会要求你先垫钱，更不会让你向陌生账户转账。',
     N'刷单,返利,垫付,兼职', 10),
    (N'冒充客服', N'退款理赔不会让你开屏幕共享',
     N'冒充电商或物流客服，以“订单异常、商品质量问题、理赔退款”为由，诱导你下载会议软件并开启屏幕共享，进而窥屏获取验证码、银行卡密码。真正的客服不会要求屏幕共享，也不会索要验证码。',
     N'客服,退款,屏幕共享,验证码', 20),
    (N'冒充公检法', N'公检法不会电话办案，更没有“安全账户”',
     N'骗子冒充公安、检察院、法院，以“涉嫌洗钱、护照异常、涉案账户”制造恐惧，要求你保密、单独沟通，并把钱转入所谓“安全账户”自证清白。公检法绝不会通过电话、社交软件办案，也不存在安全账户。',
     N'公检法,安全账户,洗钱,恐吓', 30),
    (N'信息保护', N'验证码是你的最后一道门',
     N'短信验证码等于账户钥匙。任何人以任何理由索要验证码，都应立即拒绝。不要向陌生人发送身份证、银行卡正反面照片，不要开启屏幕共享，不要在陌生链接中输入账号密码。',
     N'验证码,身份证,银行卡,密码', 40),
    (N'虚假投资', N'稳赚不赔的投资，只存在于骗局里',
     N'虚假投资理财通过“导师带单、内部渠道、稳赚不赔”吸引你进入伪造平台，先让你小赚提现，再诱导加大投入。平台数据可随意修改，一旦大额入金便无法提现。投资请认准持牌机构官方 App。',
     N'投资,理财,导师,提现', 50),
    (N'网络贷款', N'放款前先收费的，一定是诈骗',
     N'正规贷款不会在放款前收取保证金、解冻费、工本费、认证费。凡是要求先转账“刷流水”“包装征信”的，都是诈骗。校园贷、注销校园贷同样高发，征信无法通过转账修复。',
     N'贷款,征信,保证金,校园贷', 60),
    (N'游戏交易', N'脱离官方平台的交易不受保护',
     N'游戏账号、装备交易应走官方或知名第三方平台。骗子常以“低价充值、客服解冻、保证金”为由，诱导私下转账或扫码。任何要求脱离平台、先交保证金的交易都应停止。',
     N'游戏,账号,装备,低价充值', 70),
    (N'举报指引', N'遇到诈骗，这样止损和举报',
     N'第一时间停止转账并联系银行客服冻结账户；保留聊天记录、转账凭证、对方账号和链接；拨打 110 或到就近派出所报案；通过国家反诈中心 App、12321 网络不良与垃圾信息举报受理中心举报。越早报警，止付成功率越高。',
     N'举报,110,12321,止付,证据', 80);
END


-- ==========================================================================
-- 多租户改造（幂等）：user_id + user_key + isdeleted
-- 统一用户键：u{user_id}:{username}；历史数据全部归属 root（u1001:root）
-- ==========================================================================
IF COL_LENGTH('dbo.analyses', 'user_id') IS NULL
    ALTER TABLE dbo.analyses ADD user_id INT NULL;
IF COL_LENGTH('dbo.analyses', 'user_key') IS NULL
    ALTER TABLE dbo.analyses ADD user_key NVARCHAR(300) NULL;
IF COL_LENGTH('dbo.analyses', 'isdeleted') IS NULL
    ALTER TABLE dbo.analyses ADD isdeleted BIT NOT NULL CONSTRAINT DF_analyses_deleted DEFAULT 0;
IF COL_LENGTH('dbo.analyses', 'deleted_at') IS NULL
    ALTER TABLE dbo.analyses ADD deleted_at DATETIME2(0) NULL;

IF COL_LENGTH('dbo.images', 'user_id') IS NULL
    ALTER TABLE dbo.images ADD user_id INT NULL;
IF COL_LENGTH('dbo.images', 'user_key') IS NULL
    ALTER TABLE dbo.images ADD user_key NVARCHAR(300) NULL;
IF COL_LENGTH('dbo.images', 'isdeleted') IS NULL
    ALTER TABLE dbo.images ADD isdeleted BIT NOT NULL CONSTRAINT DF_images_deleted DEFAULT 0;

IF COL_LENGTH('dbo.reports', 'user_id') IS NULL
    ALTER TABLE dbo.reports ADD user_id INT NULL;
IF COL_LENGTH('dbo.reports', 'user_key') IS NULL
    ALTER TABLE dbo.reports ADD user_key NVARCHAR(300) NULL;
IF COL_LENGTH('dbo.reports', 'isdeleted') IS NULL
    ALTER TABLE dbo.reports ADD isdeleted BIT NOT NULL CONSTRAINT DF_reports_deleted DEFAULT 0;

IF COL_LENGTH('dbo.logs', 'user_id') IS NULL
    ALTER TABLE dbo.logs ADD user_id INT NULL;
IF COL_LENGTH('dbo.logs', 'user_key') IS NULL
    ALTER TABLE dbo.logs ADD user_key NVARCHAR(300) NULL;
IF COL_LENGTH('dbo.logs', 'isdeleted') IS NULL
    ALTER TABLE dbo.logs ADD isdeleted BIT NOT NULL CONSTRAINT DF_logs_deleted DEFAULT 0;

IF COL_LENGTH('dbo.staging_contents', 'user_id') IS NULL
    ALTER TABLE dbo.staging_contents ADD user_id INT NULL;
IF COL_LENGTH('dbo.staging_contents', 'client_id') IS NULL
    ALTER TABLE dbo.staging_contents ADD client_id NVARCHAR(64) NULL;
IF COL_LENGTH('dbo.staging_contents', 'isdeleted') IS NULL
    ALTER TABLE dbo.staging_contents ADD isdeleted BIT NOT NULL CONSTRAINT DF_staging_deleted DEFAULT 0;
IF COL_LENGTH('dbo.staging_contents', 'expires_at') IS NULL
    ALTER TABLE dbo.staging_contents ADD expires_at DATETIME2(0) NULL;

IF COL_LENGTH('dbo.image_cases', 'user_id') IS NULL
    ALTER TABLE dbo.image_cases ADD user_id INT NULL;
IF COL_LENGTH('dbo.image_cases', 'user_key') IS NULL
    ALTER TABLE dbo.image_cases ADD user_key NVARCHAR(300) NULL;
IF COL_LENGTH('dbo.image_cases', 'isdeleted') IS NULL
    ALTER TABLE dbo.image_cases ADD isdeleted BIT NOT NULL CONSTRAINT DF_image_cases_deleted DEFAULT 0;

GO

-- staging.user_key 从 client_id 升级为统一用户键，先扩长度
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.staging_contents')
           AND name = 'user_key' AND max_length < 600)
BEGIN
    IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_staging_user_time' AND object_id = OBJECT_ID('dbo.staging_contents'))
        DROP INDEX IX_staging_user_time ON dbo.staging_contents;
    ALTER TABLE dbo.staging_contents ALTER COLUMN user_key NVARCHAR(300) NOT NULL;
END
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_staging_user_time' AND object_id = OBJECT_ID('dbo.staging_contents'))
    CREATE INDEX IX_staging_user_time ON dbo.staging_contents(user_id, created_at DESC);

GO

-- 回填 root 租户
UPDATE dbo.analyses SET user_id = 1001 WHERE user_id IS NULL;
UPDATE dbo.analyses SET user_key = N'u1001:root' WHERE user_key IS NULL OR user_key = N'';
UPDATE dbo.images SET user_id = 1001 WHERE user_id IS NULL;
UPDATE dbo.images SET user_key = N'u1001:root' WHERE user_key IS NULL OR user_key = N'';
UPDATE dbo.reports SET user_id = 1001 WHERE user_id IS NULL;
UPDATE dbo.reports SET user_key = N'u1001:root' WHERE user_key IS NULL OR user_key = N'';
UPDATE dbo.logs SET user_id = 1001 WHERE user_id IS NULL;
UPDATE dbo.logs SET user_key = N'u1001:root' WHERE user_key IS NULL OR user_key = N'';
UPDATE dbo.staging_contents SET user_id = 1001 WHERE user_id IS NULL;
UPDATE dbo.staging_contents SET user_key = N'u1001:root' WHERE user_key NOT LIKE N'u%:%';
UPDATE dbo.staging_contents SET expires_at = DATEADD(day, 7, created_at) WHERE expires_at IS NULL;
UPDATE dbo.image_cases SET user_id = 1001 WHERE user_id IS NULL;
UPDATE dbo.image_cases SET user_key = N'u1001:root' WHERE user_key IS NULL OR user_key = N'';

GO

-- 图片指纹唯一性从“全局”改为“按用户”
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'UQ_image_cases_hash'
           AND parent_object_id = OBJECT_ID('dbo.image_cases'))
    ALTER TABLE dbo.image_cases DROP CONSTRAINT UQ_image_cases_hash;
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_image_cases_user_hash'
               AND object_id = OBJECT_ID('dbo.image_cases'))
    CREATE UNIQUE INDEX UX_image_cases_user_hash ON dbo.image_cases(user_id, sha256);

GO

-- 租户索引
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_analyses_user' AND object_id = OBJECT_ID('dbo.analyses'))
    CREATE INDEX IX_analyses_user ON dbo.analyses(user_id, id DESC) INCLUDE (isdeleted, risk_level, risk_score);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_images_user' AND object_id = OBJECT_ID('dbo.images'))
    CREATE INDEX IX_images_user ON dbo.images(user_id, analysis_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_reports_user' AND object_id = OBJECT_ID('dbo.reports'))
    CREATE INDEX IX_reports_user ON dbo.reports(user_id, id DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_logs_user' AND object_id = OBJECT_ID('dbo.logs'))
    CREATE INDEX IX_logs_user ON dbo.logs(user_id, id DESC);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_image_cases_user' AND object_id = OBJECT_ID('dbo.image_cases'))
    CREATE INDEX IX_image_cases_user ON dbo.image_cases(user_id, is_active, risk_score DESC);
