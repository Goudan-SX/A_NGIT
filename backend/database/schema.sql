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
