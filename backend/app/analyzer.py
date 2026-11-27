"""反诈卫士 · 本地规则分析引擎（规则引擎 v1）。

设计目标：
1. 不依赖外部 API 也能完成文本诈骗识别、个人信息暴露检测、链接风险分析；
2. 输出五个可解释评分维度，方便比赛演示“为什么是高风险”；
3. 为 Qwen 多模态结果预留统一的合并入口。
"""
from __future__ import annotations

import re
import time
from typing import Any

from .text_normalize import preprocess_text

# --------------------------------------------------------------------------
# 一、评分维度（总分 100）
# --------------------------------------------------------------------------
DIMENSIONS: dict[str, dict[str, Any]] = {
    "script": {
        "name": "话术操控",
        "max": 20,
        "desc": "制造紧迫感、恐惧、高收益承诺或情感操控",
    },
    "financial": {
        "name": "资金诱导",
        "max": 30,
        "desc": "要求转账、垫付、充值、投资、贷款或刷单返利",
    },
    "info": {
        "name": "信息窃取",
        "max": 25,
        "desc": "索要验证码、密码、证件，或要求屏幕共享、人脸识别",
    },
    "channel": {
        "name": "渠道异常",
        "max": 15,
        "desc": "陌生链接、二维码、非官方 App、会议软件或跨平台引流",
    },
    "identity": {
        "name": "身份伪装",
        "max": 10,
        "desc": "冒充客服、公检法、熟人领导或平台官方",
    },
}

SCAM_TYPES = [
    "刷单返利",
    "冒充客服退款",
    "冒充公检法",
    "虚假投资理财",
    "网络贷款",
    "杀猪盘/情感诈骗",
    "游戏账号交易",
    "冒充熟人/领导",
    "钓鱼链接/木马",
    "屏幕共享/远程控制",
    "信息窃取",
    "暂无明确诈骗类型",
]

LEVELS = {
    "low": {"label": "低风险", "hint": "暂未发现明显诈骗特征，仍需保持警惕"},
    "medium": {"label": "中风险", "hint": "存在可疑信号，建议核实对方身份"},
    "high": {"label": "高风险", "hint": "建议立即停止沟通，不要转账"},
    "critical": {"label": "极高风险", "hint": "请立即停止沟通、止损并报警"},
}

# --------------------------------------------------------------------------
# 二、话术特征库
# 每条信号：id / 名称 / 维度 / 权重 / 严重度 / 适用诈骗类型 / 正则
# --------------------------------------------------------------------------
SIGNALS: list[dict[str, Any]] = [
    # ---------------- 话术操控 ----------------
    {
        "id": "urgency",
        "label": "制造紧迫感",
        "dim": "script",
        "weight": 6,
        "severity": "medium",
        "scam_types": ["冒充公检法", "冒充客服退款"],
        "patterns": [r"(立即|马上|赶快|限时|最后\s*\d+\s*(小时|分钟)|今日内|逾期|否则|后果自负|不处理就|抓紧)"],
    },
    {
        "id": "authority_pressure",
        "label": "冒充权威施压",
        "dim": "script",
        "weight": 10,
        "severity": "high",
        "scam_types": ["冒充公检法"],
        "patterns": [r"(公安|警察|检察院|法院|反诈中心|银保监|工信部|海关|税务).{0,14}(调查|办案|冻结|传唤|通缉|涉嫌|洗钱)"],
    },
    {
        "id": "isolation",
        "label": "要求保密/孤立",
        "dim": "script",
        "weight": 8,
        "severity": "high",
        "scam_types": ["冒充公检法"],
        "patterns": [r"(不要告诉|别告诉|不能告诉|要保密|单独沟通|不要挂断|保持通话|找个安静|不要声张)"],
    },
    {
        "id": "high_return",
        "label": "高收益承诺",
        "dim": "script",
        "weight": 7,
        "severity": "high",
        "scam_types": ["刷单返利", "虚假投资理财"],
        "patterns": [r"(日赚|日入|月入|轻松赚|稳赚|保本|高回报|零风险|躺赚|动动手指|足不出户)"],
    },
    {
        "id": "emotion",
        "label": "情感拉拢",
        "dim": "script",
        "weight": 4,
        "severity": "low",
        "scam_types": ["杀猪盘/情感诈骗"],
        "patterns": [r"(宝贝|亲爱的|老公|老婆|想你了|处对象|网恋|奔现)"],
    },
    {
        "id": "threat_expose",
        "label": "威胁曝光隐私",
        "dim": "script",
        "weight": 10,
        "severity": "high",
        "scam_types": ["杀猪盘/情感诈骗", "信息窃取"],
        "patterns": [r"(曝光|群发|发给你通讯录|发给家人|裸照|不雅视频|不雅照)"],
    },
    {
        "id": "limited_quota",
        "label": "制造稀缺名额",
        "dim": "script",
        "weight": 4,
        "severity": "low",
        "scam_types": ["虚假投资理财", "刷单返利"],
        "patterns": [r"(名额有限|最后\s*\d+\s*个|仅限今天|限时抢购|先到先得)"],
    },

    # ---------------- 资金诱导 ----------------
    {
        "id": "brushing",
        "label": "刷单返利",
        "dim": "financial",
        "weight": 18,
        "severity": "critical",
        "scam_types": ["刷单返利"],
        "patterns": [r"(刷单|刷信誉|刷流水|做任务返利|点赞返利|关注返利|助力返利)"],
    },
    {
        "id": "advance_payment",
        "label": "要求垫付资金",
        "dim": "financial",
        "weight": 15,
        "severity": "critical",
        "scam_types": ["刷单返利", "网络贷款", "游戏账号交易"],
        "patterns": [r"(垫付|先付|先交|先充值|保证金|押金|解冻费|手续费|工本费|认证费|验资|帮我垫|垫\s*\d+|垫钱|先帮我垫|代付|帮我付)"],
    },
    {
        "id": "transfer",
        "label": "要求转账汇款",
        "dim": "financial",
        "weight": 12,
        "severity": "high",
        "scam_types": ["冒充客服退款", "冒充公检法", "杀猪盘/情感诈骗"],
        "patterns": [r"(转账|汇款|打款|打钱|转钱|转我|给我转|给我打|卡里.{0,8}(打|转|存|充)|向.*账户.*(转|汇|打)|扫码支付|扫码付款|账号.{0,8}发你|卡号.{0,8}发你)"],
    },
    {
        "id": "emergency_money",
        "label": "紧急借钱/垫付话术",
        "dim": "script",
        "weight": 12,
        "severity": "high",
        "scam_types": ["冒充熟人/领导", "紧急求助诈骗"],
        "patterns": [r"(手机快没电|手机没电了|长话短说|在医院|住院费|急着用钱|急用钱|明天一早还|明天还你|先帮我垫|微信限额|转不出去|账号我发你)"],
    },
    {
        "id": "investment",
        "label": "投资理财诱导",
        "dim": "financial",
        "weight": 12,
        "severity": "high",
        "scam_types": ["虚假投资理财"],
        "patterns": [r"(投资|理财|炒股|基金|期货|外汇|虚拟币|USDT|数字货币|博彩|投注|带单|导师)"],
    },
    {
        "id": "loan",
        "label": "贷款代办诱导",
        "dim": "financial",
        "weight": 10,
        "severity": "high",
        "scam_types": ["网络贷款"],
        "patterns": [r"(贷款|借款|提额度|征信修复|包装征信|代办信用卡|刷流水)"],
    },
    {
        "id": "rebate",
        "label": "返利/提现诱导",
        "dim": "financial",
        "weight": 6,
        "severity": "medium",
        "scam_types": ["刷单返利", "虚假投资理财"],
        "patterns": [r"(返利|佣金|收益|提现|到账|返还)"],
    },
    {
        "id": "game_trade",
        "label": "游戏交易诱导",
        "dim": "financial",
        "weight": 8,
        "severity": "medium",
        "scam_types": ["游戏账号交易"],
        "patterns": [r"(游戏账号|装备|代练|点券|皮肤|低价充值|游戏币)"],
    },
    {
        "id": "red_packet",
        "label": "红包返利",
        "dim": "financial",
        "weight": 8,
        "severity": "high",
        "scam_types": ["刷单返利"],
        "patterns": [r"(发红包|返红包|十倍返还|红包返利|转账返利)"],
    },

    # ---------------- 信息窃取 ----------------
    {
        "id": "verification_code",
        "label": "索要验证码",
        "dim": "info",
        "weight": 20,
        "severity": "critical",
        "scam_types": ["信息窃取", "冒充客服退款", "屏幕共享/远程控制"],
        "patterns": [
            r"(验证码|动态码|短信码|校验码).{0,10}(发|给|告诉|提供|报|念)",
            r"(发|给|告诉|提供|报|念).{0,10}(验证码|动态码|短信码|校验码)",
        ],
    },
    {
        "id": "password",
        "label": "索要密码",
        "dim": "info",
        "weight": 16,
        "severity": "critical",
        "scam_types": ["信息窃取", "钓鱼链接/木马"],
        "patterns": [
            r"(密码|支付密码|登录密码).{0,10}(发|给|告诉|提供|输入|填写)",
            r"(发|给|告诉|提供|输入|填写).{0,10}(密码)",
        ],
    },
    {
        "id": "screen_share",
        "label": "要求屏幕共享/远程控制",
        "dim": "info",
        "weight": 20,
        "severity": "critical",
        "scam_types": ["屏幕共享/远程控制", "冒充客服退款"],
        "patterns": [r"(屏幕共享|共享屏幕|远程控制|远程协助|远程操作|远程指导|TeamViewer|向日葵|ToDesk|AnyDesk)"],
    },
    {
        "id": "id_bank_photo",
        "label": "索要证件/银行卡",
        "dim": "info",
        "weight": 14,
        "severity": "high",
        "scam_types": ["信息窃取", "网络贷款"],
        "patterns": [r"(身份证|证件|银行卡|卡号|CVV|有效期).{0,12}(照片|正反面|拍照|上传|发|提供|填写)"],
    },
    {
        "id": "face_auth",
        "label": "要求人脸识别",
        "dim": "info",
        "weight": 14,
        "severity": "high",
        "scam_types": ["信息窃取", "网络贷款"],
        "patterns": [r"(人脸|刷脸|活体|视频认证|录屏).{0,10}(认证|识别|验证|录制|采集)"],
    },
    {
        "id": "personal_collect",
        "label": "套取个人信息",
        "dim": "info",
        "weight": 8,
        "severity": "medium",
        "scam_types": ["信息窃取"],
        "patterns": [r"(姓名|手机号|住址|家庭|学校|学号|工作单位|家庭成员).{0,10}(发|填|提供|告诉|登记)"],
    },

    # ---------------- 渠道异常 ----------------
    {
        "id": "download_app",
        "label": "诱导下载 App",
        "dim": "channel",
        "weight": 8,
        "severity": "medium",
        "scam_types": ["虚假投资理财", "屏幕共享/远程控制"],
        "patterns": [r"(下载|安装).{0,12}(App|APP|app|软件|插件|客户端|会议)"],
    },
    {
        "id": "qr_code",
        "label": "诱导扫码",
        "dim": "channel",
        "weight": 8,
        "severity": "medium",
        "scam_types": ["钓鱼链接/木马", "刷单返利"],
        "patterns": [r"(扫码|二维码|扫一扫)"],
    },
    {
        "id": "meeting_app",
        "label": "引导使用会议软件",
        "dim": "channel",
        "weight": 8,
        "severity": "high",
        "scam_types": ["屏幕共享/远程控制", "冒充客服退款"],
        "patterns": [r"(腾讯会议|钉钉会议|Zoom|会议号|会议\s*App|会议\s*APP)"],
    },
    {
        "id": "cross_platform",
        "label": "跨平台引流",
        "dim": "channel",
        "weight": 6,
        "severity": "medium",
        "scam_types": ["杀猪盘/情感诈骗", "虚假投资理财"],
        "patterns": [r"(加微信|加QQ|加群|私聊|私信|转移到|换个平台|下载后联系)"],
    },
    {
        "id": "apk",
        "label": "非官方安装包",
        "dim": "channel",
        "weight": 10,
        "severity": "high",
        "scam_types": ["钓鱼链接/木马"],
        "patterns": [r"(安装包|\.apk|企业版|内测版|破解版)"],
    },

    # ---------------- 身份伪装 ----------------
    {
        "id": "fake_customer",
        "label": "冒充客服",
        "dim": "identity",
        "weight": 12,
        "severity": "high",
        "scam_types": ["冒充客服退款"],
        "patterns": [r"(客服|官方客服|平台客服|售后).{0,14}(退款|理赔|订单|账户|冻结|解冻|注销|异常)"],
    },
    {
        "id": "fake_police",
        "label": "冒充公检法",
        "dim": "identity",
        "weight": 14,
        "severity": "critical",
        "scam_types": ["冒充公检法"],
        "patterns": [r"(公安|警察|检察院|法院|反诈中心).{0,14}(办案|调查|涉嫌|洗钱|通缉|传唤)"],
    },
    {
        "id": "fake_acquaintance",
        "label": "冒充熟人/领导",
        "dim": "identity",
        "weight": 8,
        "severity": "high",
        "scam_types": ["冒充熟人/领导"],
        "patterns": [r"(我是|你).{0,6}(领导|老板|老师|同学|亲戚)|(换号|新号|手机丢了)"],
    },
    {
        "id": "account_frozen",
        "label": "账户冻结/异常",
        "dim": "identity",
        "weight": 8,
        "severity": "high",
        "scam_types": ["冒充客服退款", "冒充公检法"],
        "patterns": [r"(账户|账号|银行卡).{0,10}(冻结|异常|风险|涉案|注销|解冻)"],
    },
    {
        "id": "cancel_loan",
        "label": "注销校园贷/征信",
        "dim": "identity",
        "weight": 12,
        "severity": "high",
        "scam_types": ["网络贷款", "冒充客服退款"],
        "patterns": [r"(注销|清除|修复).{0,8}(校园贷|网贷|征信|账号)"],
    },
]

# 预编译正则
for _sig in SIGNALS:
    _sig["compiled"] = [re.compile(p, re.IGNORECASE) for p in _sig["patterns"]]

# --------------------------------------------------------------------------
# 三、个人信息与链接检测
# --------------------------------------------------------------------------
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID18_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
ID15_RE = re.compile(r"(?<!\d)(\d{15})(?!\d)")
BANK_RE = re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CODE_RE = re.compile(r"(?:验证码|校验码|动态码|短信码)[^\d]{0,6}(\d{4,6})(?!\d)")
SOCIAL_RE = re.compile(r"(?:QQ|qq|微信|wechat|WeChat|vx|VX|V信)[号：:\s]*([A-Za-z0-9_-]{5,20})")
URL_RE = re.compile(r"https?://[^\s<>\"'，。；、）】]+", re.IGNORECASE)
BARE_DOMAIN_RE = re.compile(
    r"(?<!@)(?<![\w.-])(?:[A-Za-z0-9-]+\.)+(?:com|cn|net|org|top|xyz|vip|cc|tk|work|icu|buzz|loan|shop|site|online|info|club)(?:/[^\s，。；、）】]*)?",
    re.IGNORECASE,
)

SHORT_DOMAINS = {"t.cn", "bit.ly", "dwz.cn", "url.cn", "tinyurl.com", "suo.im", "s.id", "rb.gy"}
SUSPICIOUS_TLDS = {"top", "xyz", "vip", "cc", "tk", "work", "icu", "buzz", "loan", "shop", "site", "online"}
SENSITIVE_URL_WORDS = {"login", "verify", "auth", "pay", "safe", "support", "update", "account", "bank", "wallet"}

PII_WEIGHTS = {
    "phone": 6,
    "id_card": 15,
    "bank_card": 15,
    "email": 3,
    "verification_code": 20,
    "social_account": 2,
}


def _is_protective(text: str, start: int) -> bool:
    window = text[max(0, start - 12):start]
    return bool(re.search(r"(不要|别|切勿|谨防|警惕|勿|禁止|防范|提醒|不可|不能)", window))


def _mask_phone(value: str) -> str:
    return value[:3] + "****" + value[-4:]


def _mask_id(value: str) -> str:
    return value[:6] + "********" + value[-4:]


def _mask_bank(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return "**** **** **** " + digits[-4:]


def _mask_email(value: str) -> str:
    name, _, domain = value.partition("@")
    return (name[:1] + "***@" + domain) if name else "***@" + domain


def _mask_code(value: str) -> str:
    return value[:2] + "**" + value[-2:] if len(value) > 4 else "****"


def _mask_social(value: str) -> str:
    return value[:2] + "****" + value[-2:]


def _valid_id18(value: str) -> bool:
    if not re.fullmatch(r"\d{17}[\dXx]", value):
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_codes = "10X98765432"
    total = sum(int(value[i]) * weights[i] for i in range(17))
    return value[-1].upper() == check_codes[total % 11]


def _valid_luhn(value: str) -> bool:
    digits = [int(ch) for ch in re.sub(r"\D", "", value)]
    if not 16 <= len(digits) <= 19:
        return False
    checksum = 0
    reverse = digits[::-1]
    for index, digit in enumerate(reverse):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _add_pii(bucket: dict[str, dict[str, Any]], pii_type: str, label: str, raw: str,
             masked: str, start: int, end: int, advice: str) -> None:
    key = f"{pii_type}:{masked}"
    if key not in bucket:
        bucket[key] = {
            "type": pii_type,
            "label": label,
            "value": masked,
            "count": 0,
            "positions": [],
            "advice": advice,
            "source": "text",
        }
    bucket[key]["count"] += 1
    bucket[key]["positions"].append({"start": start, "end": end})


def detect_pii(text: str) -> list[dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = {}

    for match in PHONE_RE.finditer(text):
        raw = match.group()
        _add_pii(bucket, "phone", "手机号", raw, _mask_phone(raw), match.start(), match.end(),
                 "手机号可用于精准诈骗，建议打码后再发送，并开启运营商防骚扰服务。")

    for match in ID18_RE.finditer(text):
        raw = match.group(1)
        nearby = text[max(0, match.start(1) - 8):match.start(1)]
        if _valid_id18(raw) or "身份证" in nearby:
            _add_pii(bucket, "id_card", "身份证号", raw, _mask_id(raw), match.start(1), match.end(1),
                     "身份证号属于敏感个人信息，切勿发给陌生人；如已泄露，警惕被用于贷款或注册账号。")

    for match in ID15_RE.finditer(text):
        raw = match.group(1)
        _add_pii(bucket, "id_card", "身份证号（旧版）", raw, _mask_id(raw), match.start(1), match.end(1),
                 "身份证号属于敏感个人信息，切勿发给陌生人。")

    for match in BANK_RE.finditer(text):
        raw = match.group()
        digits = re.sub(r"\D", "", raw)
        nearby = text[max(0, match.start() - 8):match.start()]
        looks_like_card = _valid_luhn(digits) or ("银行卡" in nearby) or ("卡号" in nearby)
        if looks_like_card and not PHONE_RE.fullmatch(digits) and not ID18_RE.fullmatch(digits):
            _add_pii(bucket, "bank_card", "银行卡号", raw, _mask_bank(raw), match.start(), match.end(),
                     "银行卡号+验证码足以盗刷，建议立即联系银行挂失或冻结。")

    for match in EMAIL_RE.finditer(text):
        raw = match.group()
        _add_pii(bucket, "email", "电子邮箱", raw, _mask_email(raw), match.start(), match.end(),
                 "邮箱可能被用于撞库，建议开启二次验证并修改相同密码。")

    for match in CODE_RE.finditer(text):
        raw = match.group(1)
        if raw and 4 <= len(raw) <= 6:
            start, end = match.span(1)
            _add_pii(bucket, "verification_code", "短信验证码", raw, _mask_code(raw), start, end,
                     "验证码等于账户钥匙，任何人索要都应拒绝；如已泄露，立即修改密码并冻结账户。")

    for match in SOCIAL_RE.finditer(text):
        raw = match.group(1)
        _add_pii(bucket, "social_account", "社交账号", raw, _mask_social(raw), match.start(1), match.end(1),
                 "社交账号可能被用于冒充熟人，建议检查登录设备并开启设备锁。")

    return sorted(bucket.values(), key=lambda item: PII_WEIGHTS.get(item["type"], 0), reverse=True)


def analyze_links(text: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    candidates: list[tuple[str, int, int]] = []
    for match in URL_RE.finditer(text):
        candidates.append((match.group().rstrip(".,;)]}"), match.start(), match.end()))
    for match in BARE_DOMAIN_RE.finditer(text):
        raw = match.group().rstrip(".,;)]}")
        if "@" in raw or raw.lower().startswith("http"):
            continue
        candidates.append((raw, match.start(), match.end()))

    for raw, start, end in candidates:
        normalized = raw if re.match(r"https?://", raw, re.I) else "http://" + raw
        if normalized in seen:
            continue
        seen.add(normalized)
        host_match = re.match(r"https?://([^/:]+)", normalized, re.I)
        host = (host_match.group(1) if host_match else "").lower()
        reasons: list[str] = []
        risk = 10
        if normalized.lower().startswith("http://"):
            risk += 20
            reasons.append("未使用 HTTPS 加密")
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
            risk += 30
            reasons.append("直接使用 IP 地址访问")
        if host in SHORT_DOMAINS or any(host.endswith("." + item) for item in SHORT_DOMAINS):
            risk += 25
            reasons.append("短链接，真实跳转地址不可见")
        tld = host.rsplit(".", 1)[-1] if "." in host else ""
        if tld in SUSPICIOUS_TLDS:
            risk += 20
            reasons.append(f"使用高风险后缀 .{tld}")
        if "xn--" in host:
            risk += 25
            reasons.append("包含 Punycode，可能是仿冒域名")
        if raw.lower().count("-") >= 3:
            risk += 10
            reasons.append("域名包含大量连字符")
        path_text = normalized.lower()
        hit_words = sorted(word for word in SENSITIVE_URL_WORDS if word in path_text)
        if hit_words:
            risk += min(15, 5 * len(hit_words))
            reasons.append("链接包含敏感词：" + "、".join(hit_words[:3]))
        if len(host) > 32:
            risk += 8
            reasons.append("域名异常冗长")
        risk = max(0, min(100, risk))
        results.append({
            "url": raw,
            "host": host,
            "risk": risk,
            "reasons": reasons or ["未发现明显异常，但仍需核实域名是否为官方"],
            "start": start,
            "end": end,
        })
    return sorted(results, key=lambda item: item["risk"], reverse=True)


# --------------------------------------------------------------------------
# 四、分析主流程
# --------------------------------------------------------------------------
def _empty_dimensions() -> dict[str, int]:
    return {key: 0 for key in DIMENSIONS}


def _dimension_payload(scores: dict[str, int]) -> list[dict[str, Any]]:
    payload = []
    for key, meta in DIMENSIONS.items():
        score = max(0, min(int(round(scores.get(key, 0))), meta["max"]))
        payload.append({
            "key": key,
            "name": meta["name"],
            "score": score,
            "max": meta["max"],
            "percent": round(score / meta["max"] * 100) if meta["max"] else 0,
            "desc": meta["desc"],
        })
    return payload


def _pii_risk_floor(score: int, pii: list[dict[str, Any]]) -> int:
    """证件/银行卡/验证码组合泄露时，即使话术证据少，也应至少判为中高风险。"""
    types = {item.get("type") for item in pii}
    if "verification_code" in types and ({"id_card", "bank_card"} & types):
        return max(score, 70)
    if "id_card" in types and "bank_card" in types:
        return max(score, 55)
    if "verification_code" in types and "phone" in types:
        return max(score, 50)
    return score


def _level_for(score: int) -> str:
    if score >= 90:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _pick_scam_type(votes: dict[str, float], score: int) -> str:
    votes = {key: value for key, value in votes.items() if value > 0}
    if not votes:
        return "暂无明确诈骗类型" if score < 20 else "信息窃取"
    ranked = sorted(votes.items(), key=lambda item: item[1], reverse=True)
    first, first_score = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= first_score * 0.6:
        return f"{first} + {ranked[1][0]}"
    return first


def _summary_for(level: str, scam_type: str, score: int, signals: int, pii: int) -> str:
    if level == "critical":
        head = f"检测到 {signals} 个高危特征，综合风险 {score}%，极可能是「{scam_type}」。"
        tail = "请立即停止沟通与转账，保存证据并报警。"
    elif level == "high":
        head = f"检测到 {signals} 个可疑特征，综合风险 {score}%，疑似「{scam_type}」。"
        tail = "请立即停止沟通，不要转账、不要提供验证码或开启屏幕共享。"
    elif level == "medium":
        head = f"发现 {signals} 个可疑信号，综合风险 {score}%，需要进一步核实。"
        tail = "请通过官方渠道确认对方身份，不要在陌生链接中填写个人信息。"
    else:
        head = f"暂未发现明显诈骗话术，综合风险 {score}%。"
        tail = "仍请保持警惕，涉及转账、验证码、屏幕共享时务必核实。"
    if pii:
        tail += f" 同时检测到 {pii} 处个人信息暴露，建议立即打码或删除。"
    return head + tail


def _suggestions_for(level: str, scam_type: str, pii: list[dict[str, Any]], links: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    if level in {"high", "critical"}:
        items.append("立即停止与对方沟通，不要转账、不要提供验证码、不要开启屏幕共享。")
    items.append("通过官方 App、官网客服或拨打 96110 核实身份，不要使用对方提供的链接或电话。")
    if "刷单返利" in scam_type:
        items.append("所有要求先垫付的兼职都是诈骗；已垫付资金请立即报警并联系银行止付。")
    if "冒充客服" in scam_type:
        items.append("退款理赔只在原购物 App 内操作，官方客服不会要求屏幕共享或索要验证码。")
    if "冒充公检法" in scam_type:
        items.append("公检法不会电话办案，也没有“安全账户”；挂断电话后拨打 110 核实。")
    if "投资理财" in scam_type:
        items.append("不要向陌生平台充值或提现，投资请认准持牌机构官方渠道。")
    if "贷款" in scam_type:
        items.append("放款前收取保证金、解冻费、认证费的都是诈骗，征信不能靠转账修复。")
    if "游戏" in scam_type:
        items.append("游戏交易请走官方平台，不要脱离平台私下转账。")
    if "情感" in scam_type:
        items.append("网恋对象频繁谈钱、推荐投资平台时，立即停止投入并保留证据。")
    if links:
        items.append("不要点击陌生链接，尤其是要求登录、支付或下载安装包的页面。")
    if pii:
        items.append("已检测到个人信息暴露：请打码或删除敏感信息，必要时修改密码并冻结相关账户。")
    items.append("保留聊天记录、转账凭证、对方账号和链接，尽快通过 110 或国家反诈中心 App 举报。")
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped[:7]


def _signals_payload(evidence: list[dict[str, Any]], scores: dict[str, int],
                     votes: dict[str, float], pii: list[dict[str, Any]],
                     links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = list(evidence)
    if pii:
        pii_weight = sum(PII_WEIGHTS.get(item["type"], 0) * min(item["count"], 2) for item in pii)
        payload.append({
            "id": "pii_exposure",
            "label": "个人信息暴露",
            "dim": "info",
            "weight": min(25, pii_weight),
            "severity": "high",
            "count": sum(item["count"] for item in pii),
            "evidence": "、".join(item["label"] for item in pii),
            "protective": False,
        })
        votes["信息窃取"] = votes.get("信息窃取", 0) + min(25, pii_weight)
    if links:
        max_link = links[0]
        payload.append({
            "id": "suspicious_link",
            "label": "可疑链接",
            "dim": "channel",
            "weight": min(15, round(max_link["risk"] * 0.18)),
            "severity": "high" if max_link["risk"] >= 60 else "medium",
            "count": len(links),
            "evidence": max_link["url"][:80],
            "protective": False,
        })
        scores["channel"] += min(15, round(max_link["risk"] * 0.18))
        votes["钓鱼链接/木马"] = votes.get("钓鱼链接/木马", 0) + max_link["risk"] * 0.2
    return payload


def analyze_text(text: str, *, engine_name: str = "guardian-rule-v1") -> dict[str, Any]:
    started = time.perf_counter()
    raw_text = text or ""
    clean = preprocess_text(raw_text)
    empty = not clean or len(clean) < 2
    scores = _empty_dimensions()
    evidence: list[dict[str, Any]] = []
    votes: dict[str, float] = {}
    protective_count = 0

    if not empty:
        for sig in SIGNALS:
            spans: list[tuple[int, int, str]] = []
            for pattern in sig["compiled"]:
                for match in pattern.finditer(clean):
                    if match.end() > match.start():
                        spans.append((match.start(), match.end(), match.group()))
            if not spans:
                continue
            spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
            unique: list[tuple[int, int, str]] = []
            for span in spans:
                if unique and span[0] < unique[-1][1] and span[1] <= unique[-1][1]:
                    continue
                unique.append(span)
            protective = all(_is_protective(clean, start) for start, _, _ in unique)
            count = len(unique)
            weight = sig["weight"] * (0.15 if protective else 1 + min(count - 1, 2) * 0.15)
            if protective:
                protective_count += count
            else:
                scores[sig["dim"]] += weight
                for scam_type in sig["scam_types"]:
                    votes[scam_type] = votes.get(scam_type, 0) + weight
            first = unique[0]
            line_start = clean.rfind("\n", 0, first[0]) + 1
            line_end = clean.find("\n", first[1])
            if line_end == -1:
                line_end = len(clean)
            snippet = clean[line_start:line_end].strip()
            if len(snippet) > 800:
                snippet = snippet[:800] + "…"
            evidence.append({
                "id": sig["id"],
                "label": sig["label"],
                "dim": sig["dim"],
                "weight": round(weight, 1),
                "severity": "low" if protective else sig["severity"],
                "count": count,
                "evidence": snippet,
                "protective": protective,
            })

    pii = detect_pii(clean) if not empty else []
    links = analyze_links(clean) if not empty else []
    evidence = _signals_payload(evidence, scores, votes, pii, links)
    if pii:
        for item in pii:
            votes["信息窃取"] = votes.get("信息窃取", 0) + PII_WEIGHTS.get(item["type"], 0)
    if links:
        votes["钓鱼链接/木马"] = votes.get("钓鱼链接/木马", 0) + links[0]["risk"] * 0.2

    for key, meta in DIMENSIONS.items():
        scores[key] = max(0, min(meta["max"], scores[key]))
    score = int(round(sum(scores.values())))
    score = _pii_risk_floor(score, pii)
    score = max(0, min(100, score))
    level = _level_for(score)
    scam_type = _pick_scam_type(votes, score)
    summary = _summary_for(level, scam_type, score, len([item for item in evidence if not item.get("protective")]), len(pii))
    suggestions = _suggestions_for(level, scam_type, pii, links)
    matched = []
    for item in sorted(evidence, key=lambda row: row["weight"], reverse=True):
        if item["label"] not in matched:
            matched.append(item["label"])
    for item in pii:
        if item["label"] not in matched:
            matched.append(item["label"])

    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "risk_score": score,
        "risk_level": level,
        "risk_label": LEVELS[level]["label"],
        "risk_hint": LEVELS[level]["hint"],
        "scam_type": scam_type,
        "summary": summary,
        "dimensions": _dimension_payload(scores),
        "signals": evidence,
        "matched_keywords": matched[:10],
        "pii": pii,
        "pii_score": min(25, sum(PII_WEIGHTS.get(item["type"], 0) * min(item["count"], 2) for item in pii)),
        "links": links,
        "suggestions": suggestions,
        "stats": {
            "chars": len(clean),
            "lines": len([line for line in clean.splitlines() if line.strip()]),
            "signals": len([item for item in evidence if not item.get("protective")]),
            "protective": protective_count,
        },
        "engine": {"name": engine_name, "ai": False, "duration_ms": elapsed},
        "modalities": [],
    }


def empty_result() -> dict[str, Any]:
    return analyze_text("")


# --------------------------------------------------------------------------
# 五、多模态合并（Qwen 图片 / 语音结果 + 文本结果）
# --------------------------------------------------------------------------
def merge_modalities(base: dict[str, Any], parts: list[dict[str, Any]]) -> dict[str, Any]:
    """把文本、图片、语音的分析结果合并为一个可展示的综合结论。

    parts: [{"type": "image|audio", "filename": str, "result": analyze_text(...), "extra": {...}}]
    """
    if not parts:
        return base

    dims = {item["key"]: item["score"] for item in base["dimensions"]}
    signals: list[dict[str, Any]] = list(base["signals"])
    pii: list[dict[str, Any]] = list(base["pii"])
    links: list[dict[str, Any]] = list(base["links"])
    suggestions: list[str] = list(base["suggestions"])
    modalities: list[dict[str, Any]] = []
    max_part_score = base["risk_score"]
    votes: dict[str, float] = {}

    for part in parts:
        result = part["result"]
        max_part_score = max(max_part_score, result["risk_score"])
        for dim in result["dimensions"]:
            dims[dim["key"]] = max(dims.get(dim["key"], 0), dim["score"])
        known = {item.get("id") for item in signals}
        for item in result["signals"]:
            marker = item.get("id") or item.get("label")
            if marker not in known:
                signals.append(item)
                known.add(marker)
        known_pii = {f"{item['type']}:{item['value']}" for item in pii}
        for item in result["pii"]:
            marker = f"{item['type']}:{item['value']}"
            if marker not in known_pii:
                item["source"] = "media"
                pii.append(item)
                known_pii.add(marker)
        known_links = {item["url"] for item in links}
        for item in result["links"]:
            if item["url"] not in known_links:
                links.append(item)
                known_links.add(item["url"])
        for item in result["suggestions"]:
            if item not in suggestions:
                suggestions.append(item)
        votes[result["scam_type"]] = votes.get(result["scam_type"], 0) + result["risk_score"]
        modalities.append({
            "type": part["type"],
            "filename": part.get("filename"),
            "score": result["risk_score"],
            "level": result["risk_level"],
            "label": result["risk_label"],
            "summary": result["summary"],
            "text": part.get("text") or "",
            "engine": result.get("engine", {}),
            "extra": part.get("extra", {}),
        })

    score = max(sum(dims.values()), max_part_score)
    high_modalities = len([item for item in modalities if item["score"] >= 50])
    if high_modalities >= 2:
        score += 5
    score = _pii_risk_floor(int(round(score)), pii)
    score = min(100, int(round(score)))
    level = _level_for(score)
    votes[base["scam_type"]] = votes.get(base["scam_type"], 0) + base["risk_score"]
    scam_type = _pick_scam_type(votes, score) if votes else base["scam_type"]
    if scam_type == "暂无明确诈骗类型" and max_part_score >= 20:
        top = max(parts, key=lambda item: item["result"]["risk_score"])
        scam_type = top["result"]["scam_type"]

    dim_payload = []
    for key, meta in DIMENSIONS.items():
        value = max(0, min(int(round(dims.get(key, 0))), meta["max"]))
        dim_payload.append({
            "key": key,
            "name": meta["name"],
            "score": value,
            "max": meta["max"],
            "percent": round(value / meta["max"] * 100) if meta["max"] else 0,
            "desc": meta["desc"],
        })

    all_signals = signals
    matched: list[str] = []
    for item in sorted(all_signals, key=lambda row: row.get("weight", 0), reverse=True):
        if item.get("label") and item["label"] not in matched:
            matched.append(item["label"])
    for item in pii:
        if item["label"] not in matched:
            matched.append(item["label"])

    summary = _summary_for(level, scam_type, score,
                           len([item for item in all_signals if not item.get("protective")]), len(pii))
    if len(parts) >= 1:
        summary += " 已融合 " + "、".join(
            {"image": "图片", "audio": "语音"}.get(item["type"], item["type"]) for item in parts
        ) + " 检测结果。"

    base_engine = base.get("engine", {})
    part_engines = [part["result"].get("engine", {}) for part in parts]
    all_engines = [base_engine] + part_engines
    ai_engines = [engine for engine in all_engines if engine.get("ai")]
    if ai_engines:
        providers = {engine.get("provider") for engine in ai_engines if engine.get("provider")}
        provider = "deepseek" if "deepseek" in providers else "qwen"
        provider_label = "DeepSeek V4.1" if provider == "deepseek" else "Qwen"
        base["engine"] = {
            "name": f"guardian-{provider}",
            "ai": True,
            "provider": provider,
            "note": f"Guardian-AI · {provider_label} 多模态 + 本地规则引擎",
        }
    elif any(engine.get("name") == "database-image-cache" for engine in part_engines):
        base["engine"] = {
            "name": "guardian-image-cache",
            "ai": False,
            "provider": "database",
            "note": "Guardian-AI 图片库命中 · 复用缓存视觉结果",
        }
    elif any("ocr" in str(engine.get("note", "")).lower() for engine in part_engines):
        base["engine"] = {
            "name": "guardian-ocr",
            "ai": False,
            "note": "Guardian-AI · Windows OCR + 本地规则",
        }
    elif part_engines:
        base["engine"] = {
            "name": "guardian-multimodal",
            "ai": False,
            "note": "Guardian-AI 多模态文件校验 + 本地规则",
        }

    base.update({
        "risk_score": score,
        "risk_level": level,
        "risk_label": LEVELS[level]["label"],
        "risk_hint": LEVELS[level]["hint"],
        "scam_type": scam_type,
        "summary": summary,
        "dimensions": dim_payload,
        "signals": all_signals,
        "matched_keywords": matched[:12],
        "pii": pii,
        "pii_score": min(25, sum(PII_WEIGHTS.get(item["type"], 0) * min(item["count"], 2) for item in pii)),
        "links": links,
        "suggestions": suggestions[:8],
        "modalities": modalities,
        "stats": {
            "chars": max(base.get("stats", {}).get("chars", 0), sum(item["extra"].get("chars", 0) for item in modalities)),
            "lines": base.get("stats", {}).get("lines", 0),
            "signals": len([item for item in all_signals if not item.get("protective")]),
            "protective": base.get("stats", {}).get("protective", 0),
            "modalities": len(parts),
        },
    })
    return base


def recompute_level(result: dict[str, Any]) -> dict[str, Any]:
    score = int(result.get("risk_score", 0))
    level = _level_for(score)
    result["risk_level"] = level
    result["risk_label"] = LEVELS[level]["label"]
    result["risk_hint"] = LEVELS[level]["hint"]
    return result
