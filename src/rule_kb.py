import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RuleEntry:
    rule_id: str
    priority: int
    patterns: tuple[str, ...]
    knowledge: str


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    priority: int
    pattern: str
    knowledge: str


RULES: tuple[RuleEntry, ...] = (
    RuleEntry(
        rule_id="eligibility_age",
        priority=10,
        patterns=(
            r"投保.*年龄",
            r"多大.*能买",
            r"几岁.*能买",
            r"年龄限制",
            r"老人.*能买",
        ),
        knowledge="投保年龄需以具体产品条款和投保页为准。先确认客户年龄，再给可投保范围与备选方案。",
    ),
    RuleEntry(
        rule_id="waiting_period",
        priority=20,
        patterns=(
            r"等待期",
            r"多久.*生效",
            r"生效.*多久",
            r"什么时候.*生效",
        ),
        knowledge="等待期和生效时间按产品条款执行。要说明等待期内外责任差异，并提醒以保单生效时间为准。",
    ),
    RuleEntry(
        rule_id="deductible",
        priority=30,
        patterns=(
            r"免赔",
            r"免赔额",
            r"起付线",
            r"自付.*多少",
        ),
        knowledge="免赔额与起付规则按具体责任和版本而定。先确认产品和责任模块，再给结论。",
    ),
    RuleEntry(
        rule_id="renewal",
        priority=40,
        patterns=(
            r"续保",
            r"保证续保",
            r"能不能续",
            r"第二年.*还能买",
        ),
        knowledge="续保需区分保证续保与非保证续保，按条款和当期规则说明，不做绝对承诺。",
    ),
    RuleEntry(
        rule_id="coverage_scope",
        priority=50,
        patterns=(
            r"报销范围",
            r"保障范围",
            r"赔什么",
            r"保什么",
            r"门诊.*报",
            r"住院.*报",
        ),
        knowledge="保障范围应按责任模块解释（住院、门急诊、特药等），同时提示除外责任与条款定义。",
    ),
    RuleEntry(
        rule_id="pre_existing",
        priority=60,
        patterns=(
            r"既往症",
            r"以前.*病",
            r"带病.*能买",
            r"有病史.*能买",
            r"糖尿病.*能买",
            r"高血压.*能买",
        ),
        knowledge="既往症能否承保或理赔，取决于健康告知、核保结论与条款约定，不能直接承诺一定可赔。",
    ),
    RuleEntry(
        rule_id="hospital_scope",
        priority=70,
        patterns=(
            r"医院范围",
            r"什么医院",
            r"公立医院",
            r"私立医院",
            r"医院.*能报",
        ),
        knowledge="医院范围按条款约定的医疗机构范围执行，先确认客户城市与就医场景再回答。",
    ),
    RuleEntry(
        rule_id="claim_process",
        priority=80,
        patterns=(
            r"理赔",
            r"怎么赔",
            r"赔付流程",
            r"报案",
            r"要什么材料",
        ),
        knowledge="理赔答复应包含报案入口、材料清单、审核与赔付环节，并提示以官方理赔指引为准。",
    ),
    RuleEntry(
        rule_id="health_disclosure",
        priority=90,
        patterns=(
            r"健康告知",
            r"告知",
            r"问卷",
            r"核保",
            r"体检",
        ),
        knowledge="健康告知需如实填写。未如实告知可能影响理赔；不确定病史时应建议客户按实际情况逐项确认。",
    ),
    RuleEntry(
        rule_id="target_customers",
        priority=100,
        patterns=(
            r"适合.*人",
            r"推荐.*人群",
            r"谁适合",
            r"我适不适合",
            r"给父母买",
            r"给小孩买",
        ),
        knowledge="推荐人群需结合年龄、预算、家庭结构和现有保障做分层建议，不做一刀切推荐。",
    ),
)


_COMPILED_RULES: tuple[tuple[RuleEntry, tuple[re.Pattern[str], ...]], ...] = tuple(
    (
        entry,
        tuple(re.compile(pattern, re.IGNORECASE) for pattern in entry.patterns),
    )
    for entry in RULES
)


def normalize_user_text(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    return compact.lower()


def match_rules(user_text: str, *, max_hits: int = 2) -> list[RuleHit]:
    if not user_text:
        return []

    normalized = normalize_user_text(user_text)
    hits: list[RuleHit] = []

    for entry, patterns in sorted(_COMPILED_RULES, key=lambda item: item[0].priority):
        for pattern in patterns:
            if pattern.search(user_text) or pattern.search(normalized):
                hits.append(
                    RuleHit(
                        rule_id=entry.rule_id,
                        priority=entry.priority,
                        pattern=pattern.pattern,
                        knowledge=entry.knowledge,
                    )
                )
                break

        if len(hits) >= max_hits:
            break

    return hits


def build_user_context_block(hits: list[RuleHit]) -> str:
    if not hits:
        return ""

    lines = ["[对话参考要点]"]
    for hit in hits:
        lines.append(f"- {hit.knowledge}")
    lines.append("[请自然融入以上要点后再回答]")
    return "\n".join(lines)
