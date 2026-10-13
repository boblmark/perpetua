#!/usr/bin/env python3
"""平台安全策略预检（prompt 级，生成前最后一道政策门）。

背景（2026-10-10 用户要求）：
  视频生成提示 QC 此前只有通用 SAFETY_FIREWALL 块（防未成年/真人/血腥等，
  2026-10-09 议会决议），Ask Studio 终审只问爆款度+原创性——没有任何环节
  按各平台安全策略做合规审查。政策问题只能在上传后被平台检测到，代价最高。
  本模块把政策审查前移到 prompt 级。

设计原则：
  - 确定性规则预检（本模块）+ Ask Studio 终审第 4 问（语义复核）双保险；
  - FLAG 只走人工复核（needs_manual），绝不自动改写 prompt 重试——
    2026-10-09 已废除 sanitize+重试（改措辞绕过安全拒绝属于违规）；
  - 规则只增不减：SAFETY_FIREWALL 仍是第一道，缺失即 FLAG（防绕过组装）。

平台清单：
  - youtube：Community Guidelines（误导信息/危险模仿/仇恨骚扰/儿童安全/
    欺骗性做法）+ AI 合成内容披露义务提示 + "不真实内容"政策（频道 #1 风险，
    D20261009-001）。
  - douyin：中国《生成式 AI 服务管理暂行办法》《深度合成管理规定》
    （AI 生成内容显著标识——发布侧由抖音适配器 AI 声明覆盖）+ 抖音社区公约
    （低俗/血腥暴力/危险行为/极限词）。

用法：
    from platform_policy import prescreen_policy
    verdict, reasons = prescreen_policy(prompt, title, description, platform="youtube")
    # verdict: "PASS" | "FLAG"；reasons: [rule_id, ...]
"""

import re

# ---------------------------------------------------------------------------
# 规则表：(rule_id, 平台, 正则, 说明)
# ---------------------------------------------------------------------------
_RULES = [
    # 0. 防火墙完整性：prompt 必须含 SAFETY FIREWALL 块（防绕过 viral_prompt 组装）
    ("firewall_missing", "both",
     None,  # 特殊规则，见代码
     "prompt 缺失 SAFETY FIREWALL 块"),

    # 1. 未成年人（YouTube 儿童安全 / 中国未成年人保护，均为高压线）
    # 2026-10-10 红队评审：去掉 school/kindergarten/playground（无未成年人的
    # 校园场景喜剧会被误伤；真有小孩时 child/kid 已覆盖），补 youngster/youth
    # （同义词绕过）。
    ("minor", "both",
     re.compile(r"\b(child|children|kid(s)?|baby|babies|toddler|teen(ager)?s?|"
                r"minors?|youngster|youth)\b|"
                r"(儿童|小孩|未成年|少年|婴儿|学生|幼儿园)",
                re.I),
     "含未成年人相关表述"),

    # 2. 真人/名人/品牌/IP（肖像权+版权，"不真实内容"政策关联风险）
    ("real_person_brand", "both",
     re.compile(r"\b(celebrity|celebrities|public figure|real person|"
                r"likeness of|based on a real|brand logo|trademarked|"
                r"marvel|disney|pixar|nintendo|warner|netflix|apple|samsung|"
                r"coca-?cola|nike|adidas|mcdonald|starbucks|tesla|"
                r"taylor swift|elon musk|mrbeast|beyonce|drake)\b",
                re.I),
     "含真人/名人/品牌/IP 表述"),

    # 3. 血腥暴力/武器/性内容（SAFETY_FIREWALL 的确定性复核）
    # 2026-10-10 红队评审（续）：补 viscera/entrails（gore 同义词绕过）、
    # blade/cleaver/firearm（武器同义词绕过）。
    ("graphic", "both",
     re.compile(r"\b(gore|gory|viscera|entrails|intestines|dismember|decapitat|"
                r"blood\s*(splatter|soak|drip|pool|stain|bath)|"
                r"blood-?soaked|bloodied|"
                r"(?<!ink\s)(?<!paint\s)(?<!dye\s)bleeding|"
                r"gun(s)?|rifle|pistol|firearm|knife|blade|cleaver|"
                r"stab(bing|bed)?|shoot(s|ing)?|"
                r"kill(s|ed|ing)?\s+(him|her|them|yourself|himself|herself|"
                r"themselves|people|person|everyone)|"
                r"killing spree|kill list|kill count|"
                r"murder|suicide|torture|"
                r"sexual|nude|naked|porn|erotic|seduce)\b",
                re.I),
     "含血腥/暴力/武器/性相关表述"),

    # 4. 误导性信息（YouTube misinformation：医疗/选举/灾难）
    ("misinformation", "youtube",
     re.compile(r"\b(vaccine|covid|miracle cure|guaranteed cure|"
                r"election (fraud|rigged|stolen)|fake news|"
                r"government cover-?up|chemtrail|flat earth)\b",
                re.I),
     "含误导性信息高风险表述"),

    # 5. 危险行为模仿（YouTube harmful/dangerous content）
    ("dangerous_imitable", "both",
     re.compile(r"\b(tide pod|fire challenge|blackout challenge|"
                r"drink(s|ing)?\s+bleach|jump off (a|the) (roof|bridge|building)|"
                r"play chicken with traffic|hold(ing)? (a|the) breath until)\b",
                re.I),
     "含可模仿的危险行为"),

    # 6. 仇恨/骚扰（YouTube hate & harassment）
    ("hate_harassment", "both",
     re.compile(r"\b(slur|racial slur|hate (speech|crime)|"
                r"harass(es|ment)? (a|the) (minority|protected)|"
                r"doxx(ing|ed)?|swat(ting)?)\b",
                re.I),
     "含仇恨/骚扰/人肉相关表述"),

    # 7. 抖音极限词（广告法+社区公约，标题侧）
    # 2026-10-10 评审修正：排除编号（第一号/第一集…）与时间副词（最后/最近），
    # "甲字第一号" 是档案编号不是极限词。
    ("extreme_claim_cn", "douyin",
     re.compile(r"(最(?![后终近])([A-Za-z\u4e00-\u9fff]{1,6})|"
                r"第一(?![号集期章回卷部])|国家级|顶级|首选|"
                r"绝无仅有|史无前例|万能|根治|包治百病)",
                re.I),
     "标题含极限词/绝对化用语"),

    # 8. 医疗断言（双平台：YouTube misinformation + 中国广告法）
    ("medical_claim", "both",
     re.compile(r"\b(cure(s|d)? (cancer|diabetes|aids)|lose \d+ (pounds|kg) "
                r"in \d+ days|guaranteed (weight|fat) loss)\b|"
                r"(包治|根治|药到病除|三天见效|无效退款)",
                re.I),
     "含医疗效果断言"),
]


def prescreen_policy(prompt, title="", description="", platform="youtube",
                     require_firewall=True):
    """确定性政策预检。

    返回 (verdict, reasons)：verdict 为 "PASS" 或 "FLAG"；
    reasons 为命中的 [(rule_id, 说明, 命中片段), ...]。
    只读，不修改任何输入。

    require_firewall：要求 prompt 含 SAFETY FIREWALL 块。管线经
      build_viral_prompt 组装的 prompt 必须为 True；手写 prompt 批次
      （如抖音 pilot）若未走组装流程，传 False 并在调用处记录豁免原因。
      2026-10-10 评审：71 个手写 pilot prompt 无防火墙块，属预期内，
      不应视为违规——规则只约束管线组装路径。
    """
    blob = "%s\n%s\n%s" % (prompt or "", title or "", description or "")
    reasons = []

    # 先做防火墙完整性检查，然后把防火墙块本身从待检文本中剔除——
    # 2026-10-10 评审发现：防火墙块自带 "No minors…celebrities…gore" 等否定式
    # 声明，会被后继规则误命中（自己查自己）。
    # 注意：用 (?=\n|\Z) 而非 (?=\n\n)——若块后无空行，\n\n 会让 .*? 一直吞到
    # 文末，把真正的违规内容也剔掉（评审实测抓到）。
    _FIREWALL_RE = re.compile(
        r"SAFETY FIREWALL \(hard gate\):.*?(?=\n|\Z)", re.I | re.S)
    fw_present = bool(_FIREWALL_RE.search(blob))
    blob_scan = _FIREWALL_RE.sub("", blob)

    for rule_id, scope, rx, note in _RULES:
        if scope != "both" and scope != platform:
            continue
        if rule_id == "firewall_missing":
            if require_firewall and not fw_present:
                reasons.append((rule_id, note, ""))
            continue
        m = rx.search(blob_scan)
        if m:
            reasons.append((rule_id, note, m.group(0)[:40]))

    verdict = "FLAG" if reasons else "PASS"
    return verdict, reasons


# 各平台终审提问用的政策清单摘要（供 prompt_review.review_question 引用）
POLICY_SUMMARY = {
    "youtube": (
        "YouTube Community Guidelines: misinformation, dangerous or harmful "
        "behavior imitation, hate/harassment, child safety, deceptive practices; "
        "realistic AI-generated content may need an altered-content disclosure; "
        "'inauthentic content' is a standing channel risk."
    ),
    "douyin": (
        "Douyin community rules + Chinese generative-AI regulations: AI-generated "
        "content must be labeled at publish time; no vulgar/graphic/violent content, "
        "no dangerous behavior, no extreme/absolute claims in titles."
    ),
}
