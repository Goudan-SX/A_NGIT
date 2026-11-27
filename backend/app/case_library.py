"""真实案例库：从 CSV 导入青少年被骗案例，提供科普、反诈小知识、问答与分省案例。

数据来源：backend/data/case_library.csv（411 条真实案例，含省份/类型/案情/来源）。
所有接口纯内存计算，不依赖外部数据库，启动时一次性加载并缓存。
"""
from __future__ import annotations

import csv
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "case_library.csv"

PROVINCES = [
    "北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
]

# 各诈骗类型的科普概述与防范要点
SCIENCE_TEMPLATES: dict[str, dict[str, Any]] = {
    "游戏相关诈骗": {
        "overview": "以免费皮肤、低价账号、代练报酬等为诱饵，诱导未成年人下载远控插件、开启屏幕共享或提供验证码，进而窃取家长账户资金。是针对青少年最高发的诈骗类型，占收录案例近三成。",
        "prevention": ["不下载陌生插件/辅助软件", "不开启屏幕共享", "不向任何人提供验证码", "游戏交易只走官方平台", "家长管好支付密码与免密支付"],
    },
    "学生高频类型诈骗": {
        "overview": "针对在校学生群体，以刷单返利、兼职赚佣金、冒充客服退款等话术实施诈骗。利用学生群体社会经验不足、急于赚钱的心理，小额返利建立信任后诱导大额垫付。",
        "prevention": ["刷单本身违法，凡垫付刷单都是诈骗", "兼职不充值、不下载陌生APP", "退款只在官方平台核实", "不扫陌生二维码、不点陌生链接"],
    },
    "恐吓操控型诈骗": {
        "overview": "冒充公检法、公司客服等身份，以未成年人操作违规致账户冻结、需赔偿否则坐牢等话术恐吓受害人，诱导拿家长手机转账。利用青少年的恐惧心理实施精神控制。",
        "prevention": ["公检法不会网上办案、更不会要付款码", "未成年人不因闯祸担责赔偿", "遇到恐吓第一时间告诉家长", "不向陌生人转账解冻"],
    },
    "追星相关诈骗": {
        "overview": "利用粉丝追星热情，以明星周边、演唱会门票、粉丝群福利等为诱饵，诱导扫码付款后拉黑，或冒充明星律师恐吓侵权需赔偿。",
        "prevention": ["票务只走官方渠道", "不向陌生粉丝群转账", "冒充明星/律师恐吓都是诈骗", "不扫来路不明的二维码"],
    },
    "大学生侵财与涉罪工具人": {
        "overview": "以兼职、赚快钱为名，诱导大学生出租出借银行卡、电话卡或帮转账，实则沦为电诈洗钱工具人，不仅损失钱财还可能承担刑事责任。",
        "prevention": ["不出租出借银行卡、电话卡", "不帮陌生人转账取现", "警惕帮信罪法律风险", "兼职看清资质，拒绝资金中转"],
    },
    "冒充身份类诈骗": {
        "overview": "冒充熟人、老师、领导、客服等身份，以紧急借钱、代付、退款等理由要求转账。利用对熟人和权威的信任降低防备。",
        "prevention": ["转账前电话或视频核实身份", "不轻信社交软件中的熟人借钱", "老师/领导不会私下要求转账", "官方客服不会主动来电退款"],
    },
    "虚假金融类诈骗": {
        "overview": "以高收益投资、低息贷款、内部渠道等为诱饵，诱导充值或缴纳保证金。前期允许小额提现建立信任，大额投入后平台失联。",
        "prevention": ["高收益必然高风险，警惕保本高息承诺", "贷款不走非官方渠道", "不缴纳保证金、解冻金", "投资只选持牌正规机构"],
    },
    "留学生相关诈骗": {
        "overview": "针对海外留学生，冒充使领馆、公检法或快递公司，以涉案、签证问题、包裹违禁等理由恐吓，诱导转账或隔离操作。利用留学生远离家人、信息不对称的弱点。",
        "prevention": ["使领馆不会电话要求转账", "不轻信来电显示的号码", "遇到恐吓先联系家人核实", "不按陌生人指示做隔离操作"],
    },
    "情感操控类诈骗": {
        "overview": "通过社交平台建立恋爱或友谊关系，长期培养信任后诱导投资、充值或借钱，即杀猪盘。利用情感依赖降低判断力。",
        "prevention": ["网恋对象不轻信", "不向未见面的人转账投资", "警惕完美人设与紧迫借款", "投资平台先核实资质"],
    },
    "招生与境外诱骗类": {
        "overview": "以虚假招生、内部名额、境外高薪工作等为诱饵，诱导缴费或出国后陷入困境。针对升学焦虑和求职需求。",
        "prevention": ["招生信息以官方公告为准", "不轻信内部名额/关系户", "境外工作先核实劳务资质", "不缴纳所谓疏通费"],
    },
    "敲诈勒索类": {
        "overview": "通过裸聊录屏、隐私照片等手段获取把柄，威胁公开索要钱财。利用受害人羞耻心理不敢报警。",
        "prevention": ["不与陌生人视频裸聊", "不发送隐私照片", "被勒索立即报警，不给钱", "删除陌生APP，关闭摄像头权限"],
    },
    "钓鱼信息与信息窃取类": {
        "overview": "通过钓鱼链接、伪造页面窃取账号密码、身份证、银行卡等信息，进而盗刷或冒用身份。信息一旦泄露危害持久。",
        "prevention": ["不点来路不明链接", "不在非官方页面输入密码", "定期更换重要账号密码", "开启二次验证"],
    },
}

# 反诈小知识（30 条，含案例提炼与通用知识）
ANTI_FRAUD_TIPS = [
    "验证码是最后一道防线，任何索要验证码的人都是骗子。",
    "公检法不会通过电话、QQ、微信办案，更不会要求转账到安全账户。",
    "刷单本身违法，任何垫付刷单都是诈骗。",
    "屏幕共享等于把手机交给陌生人，不熟悉的人要求共享立即拒绝。",
    "游戏皮肤、账号低价或免费送，背后都是盗号或盗刷陷阱。",
    "96110 是全国反诈专线，接到来电务必接听。",
    "国家反诈中心 APP 可开启来电预警，建议全民安装。",
    "不明链接不点击，不明二维码不扫描。",
    "熟人借钱先电话核实，社交软件账号可能被盗。",
    "高收益零风险的投资不存在，保本高息都是骗局。",
    "贷款不走非官方渠道，先交费的贷款都是诈骗。",
    "客服主动来电退款又让你转账的，100% 是假冒。",
    "机票退改签只在航空公司官网或 APP 操作，不点短信链接。",
    "不出租出借银行卡和电话卡，帮转账可能构成帮信罪。",
    "网恋对象带你投资赚钱的，大概率是杀猪盘。",
    "未成年人被恐吓闯祸要赔偿，第一时间告诉家长。",
    "不下载陌生人发来的插件、辅助、会议软件。",
    "报警拨 110，举报不良信息拨 12321。",
    "转账前默念三遍：核实了吗？核实了吗？核实了吗？",
    "社交软件收到转账请求，先视频确认对方身份。",
    "快递丢失理赔只在购物平台核实，不脱离平台操作。",
    "不向陌生人提供身份证号、银行卡号、人脸信息。",
    "兼职要求先充值、先垫付的，立即退出。",
    "追星花钱进粉丝群、买低价票，大概率被骗。",
    "不轻信高薪境外工作，先核实劳务派遣资质。",
    "裸聊敲诈不给钱，给了也无底洞，直接报警。",
    "定期检查手机是否有陌生 APP，及时卸载。",
    "支付密码不要设成简单数字，不告诉任何人。",
    "家长应开启未成年人支付限额，管好免密支付。",
    "遇到诈骗保留聊天记录和转账凭证，便于警方追查。",
]


def extract_province(region: str) -> str:
    """从地区字段提取省份。"""
    region = (region or "").strip()
    for p in PROVINCES:
        if region.startswith(p):
            return p
    return "其他"


def _parse_case(row: dict[str, str]) -> dict[str, Any]:
    """将 CSV 行解析为结构化案例。"""
    return {
        "code": row.get("编号", "").strip(),
        "time": row.get("发生时间", "").strip(),
        "region": row.get("地区", "").strip(),
        "province": extract_province(row.get("地区", "")),
        "age_group": row.get("受害人年龄段", "").strip(),
        "age": row.get("年龄（岁）", "").strip(),
        "group": row.get("所属群体", "").strip(),
        "category": row.get("一级类型", "").strip(),
        "subtype": row.get("细分类型", "").strip(),
        "scam_type": row.get("诈骗类型", "").strip(),
        "channel": row.get("接触渠道", "").strip(),
        "method": row.get("作案手法", "").strip(),
        "keywords": row.get("话术/关键词", "").strip(),
        "loss": row.get("损失情况（元）", "").strip(),
        "result": row.get("处理结果", "").strip(),
        "source": row.get("来源", "").strip() or row.get("案例来源", "").strip(),
        "identify_basis": row.get("识别依据", "").strip(),
        "risk_labels": row.get("风险标签", "").strip(),
        "tips": row.get("防范提示", "").strip(),
    }


@lru_cache(maxsize=1)
def _all_cases() -> tuple[dict[str, Any], ...]:
    """加载并缓存全部案例。"""
    if not CSV_PATH.exists():
        return ()
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        return tuple(_parse_case(row) for row in csv.DictReader(f) if row.get("编号", "").strip())


def list_cases(province: str = "", category: str = "", limit: int = 20) -> list[dict[str, Any]]:
    cases = _all_cases()
    if province:
        cases = [c for c in cases if c["province"] == province]
    if category:
        cases = [c for c in cases if c["category"] == category]
    return list(cases[:limit])


def random_case(province: str = "") -> dict[str, Any] | None:
    cases = _all_cases()
    if province:
        pool = [c for c in cases if c["province"] == province]
    else:
        pool = list(cases)
    return random.choice(pool) if pool else None


def random_cases(province: str = "", count: int = 1) -> list[dict[str, Any]]:
    cases = _all_cases()
    if province:
        pool = [c for c in cases if c["province"] == province]
    else:
        pool = list(cases)
    if not pool:
        return []
    count = min(count, len(pool))
    return random.sample(pool, count)


def list_categories() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for c in _all_cases():
        cat = c["category"]
        counts[cat] = counts.get(cat, 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


def list_provinces() -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for c in _all_cases():
        p = c["province"]
        counts[p] = counts.get(p, 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1]) if k != "其他"]


def _pick_cases(category: str, count: int = 2) -> list[dict[str, Any]]:
    pool = [c for c in _all_cases() if c["category"] == category and c["method"]]
    return random.sample(pool, min(count, len(pool))) if pool else []


def get_science(category: str = "") -> dict[str, Any]:
    """按类型生成科普内容：概述 + 防范要点 + 真实案例。"""
    cases = _all_cases()
    if not category:
        # 未指定类型时随机选一个案例较多的类型
        cats = list_categories()
        category = cats[0]["name"] if cats else ""
    template = SCIENCE_TEMPLATES.get(category, {})
    type_cases = [c for c in cases if c["category"] == category]
    subtypes: dict[str, int] = {}
    for c in type_cases:
        st = c["subtype"]
        if st:
            subtypes[st] = subtypes.get(st, 0) + 1
    top_subtypes = [k for k, _ in sorted(subtypes.items(), key=lambda x: -x[1])[:5]]
    real_cases = _pick_cases(category, 2)
    return {
        "category": category,
        "overview": template.get("overview", f"{category}是针对青少年的诈骗类型，共收录 {len(type_cases)} 起真实案例。"),
        "common_subtypes": top_subtypes,
        "prevention": template.get("prevention", ["不轻信、不透露、不转账", "遇到可疑情况拨打 96110"]),
        "case_count": len(type_cases),
        "cases": [
            {
                "code": c["code"],
                "region": c["region"],
                "scam_type": c["scam_type"],
                "method": c["method"],
                "loss": c["loss"],
                "source": c["source"],
                "tips": c["tips"],
            }
            for c in real_cases
        ],
    }


# 检测结果诈骗类型 → 案例库一级类型的映射
_TYPE_MAP = [
    ("刷单", "学生高频类型诈骗"),
    ("返利", "学生高频类型诈骗"),
    ("兼职", "学生高频类型诈骗"),
    ("客服", "冒充身份类诈骗"),
    ("退款", "学生高频类型诈骗"),
    ("公检法", "恐吓操控型诈骗"),
    ("警察", "恐吓操控型诈骗"),
    ("恐吓", "恐吓操控型诈骗"),
    ("投资", "虚假金融类诈骗"),
    ("贷款", "虚假金融类诈骗"),
    ("游戏", "游戏相关诈骗"),
    ("皮肤", "游戏相关诈骗"),
    ("账号", "游戏相关诈骗"),
    ("验证码", "游戏相关诈骗"),
    ("屏幕共享", "游戏相关诈骗"),
    ("追星", "追星相关诈骗"),
    ("明星", "追星相关诈骗"),
    ("银行卡", "大学生侵财与涉罪工具人"),
    ("转账", "冒充身份类诈骗"),
    ("杀猪盘", "情感操控类诈骗"),
    ("网恋", "情感操控类诈骗"),
    ("留学", "留学生相关诈骗"),
    ("使馆", "留学生相关诈骗"),
    ("招生", "招生与境外诱骗类"),
    ("裸聊", "敲诈勒索类"),
    ("勒索", "敲诈勒索类"),
    ("钓鱼", "钓鱼信息与信息窃取类"),
]


def match_science_by_text(risk_label: str = "", scam_type: str = "", score: int = 0) -> dict[str, Any]:
    """根据检测结果的风险标签/诈骗类型匹配科普内容。

    疑似度 ≥70 时按命中的诈骗类型展示对应科普；未命中则随机展示。
    """
    clue = f"{risk_label} {scam_type}"
    category = ""
    for keyword, cat in _TYPE_MAP:
        if keyword in clue:
            category = cat
            break
    if not category and score >= 70:
        # 高风险但未匹配到具体类型，随机选一个高频类型
        category = random.choice(["学生高频类型诈骗", "游戏相关诈骗", "恐吓操控型诈骗"])
    return get_science(category)


def list_tips(count: int = 0) -> list[str]:
    """返回反诈小知识，count=0 返回全部，否则随机取 count 条。"""
    if count <= 0:
        return list(ANTI_FRAUD_TIPS)
    return random.sample(ANTI_FRAUD_TIPS, min(count, len(ANTI_FRAUD_TIPS)))


def _quiz_type_judgment(case: dict[str, Any], all_cats: list[str]) -> dict[str, Any]:
    """题型一：给作案手法，判断诈骗类型。"""
    correct = case["category"]
    options = [correct]
    pool = [c for c in all_cats if c != correct]
    options += random.sample(pool, min(3, len(pool)))
    random.shuffle(options)
    return {
        "type": "type_judgment",
        "question": f"以下作案手法属于哪种诈骗类型？\n「{case['method'][:80]}」",
        "options": options,
        "answer": correct,
        "explanation": f"该案例编号 {case['code']}，发生于 {case['region']}，属于{correct}，"
                       f"损失 {case['loss'] or '未明'}。来源：{case['source'][:40]}。",
    }


def _quiz_correct_action(case: dict[str, Any]) -> dict[str, Any]:
    """题型二：给场景，选择正确应对。"""
    correct_action = case["tips"] or "不轻信、不透露、不转账，拨打 96110。"
    wrong_actions = [
        "按对方要求操作，配合完成任务",
        "先转账解冻，事后会退还",
        "提供验证码加快处理进度",
        "下载对方推荐的软件继续沟通",
    ]
    options = [correct_action] + random.sample(wrong_actions, 3)
    random.shuffle(options)
    return {
        "type": "correct_action",
        "question": f"对方说：「{case['keywords'][:60] or case['method'][:60]}」你该怎么做？",
        "options": options,
        "answer": correct_action,
        "explanation": f"这是 {case['scam_type']} 的典型话术。正确做法：{correct_action}",
    }


def _quiz_risk_identify(case: dict[str, Any]) -> dict[str, Any]:
    """题型三：判断某话术是否有诈骗风险。"""
    return {
        "type": "risk_identify",
        "question": f"以下信息是否存在诈骗风险？\n「{case['keywords'][:70] or case['method'][:70]}」",
        "options": ["是，属于诈骗话术，应立即停止沟通", "否，看起来是正常交流", "不确定，可以先配合看看", "是，但可以先小额尝试"],
        "answer": "是，属于诈骗话术，应立即停止沟通",
        "explanation": f"该话术出自 {case['region']} 的真实案例（{case['scam_type']}），"
                       f"受害人损失 {case['loss'] or '未明'}。来源：{case['source'][:40]}。",
    }


def list_quiz(count: int = 5) -> list[dict[str, Any]]:
    """从案例库随机生成问答题目，每次 count 道（默认 5）。"""
    cases = _all_cases()
    if not cases:
        return []
    all_cats = list({c["category"] for c in cases if c["category"]})
    pool = [c for c in cases if c["method"]]
    selected = random.sample(pool, min(count, len(pool)))
    generators = [_quiz_type_judgment, _quiz_correct_action, _quiz_risk_identify]
    quiz = []
    for i, case in enumerate(selected):
        gen = generators[i % len(generators)]
        if gen is _quiz_type_judgment:
            quiz.append(gen(case, all_cats))
        else:
            quiz.append(gen(case))
    random.shuffle(quiz)
    return quiz
