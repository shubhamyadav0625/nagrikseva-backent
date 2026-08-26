"""
Decision table + rule engine for NagrikSeva Enterprise.
This is a 1:1 port of the DECISION_TABLE / findMissingFields / recommendAction
logic that used to live in the frontend's <script> tag, so the recommendation
logic behaves identically now that it's running on the server.
"""

CATEGORIES = ["water_supply", "road_pothole", "sanitation_garbage", "electricity", "ration_card"]

DECISION_TABLE = {
    "categories": CATEGORIES,
    "actions": {
        "grievance": {
            "label": "File a Grievance",
            "typical_portal": "CPGRAMS (Centralized Public Grievance Redress and Monitoring System) or state grievance portal",
            "statutory_response_days": 21,
        },
        "rti": {
            "label": "File an RTI Application",
            "typical_portal": "RTI Online Portal (rtionline.gov.in) or state RTI portal",
            "statutory_response_days": 30,
        },
        "escalation": {
            "label": "Escalate the Unresolved Complaint",
            "typical_portal": "Grievance portal's escalation/reminder feature, or written escalation to the next-level officer",
            "statutory_response_days": None,
        },
        "appeal": {
            "label": "File a First Appeal",
            "typical_portal": "First Appellate Authority (for RTI) or departmental appellate officer (for grievances)",
            "statutory_response_days": 30,
        },
    },
    "rules": [
        {
            "id": "R1_no_prior_complaint",
            "condition": {"prior_complaint_filed": False, "wants_information_only": False},
            "action": "grievance",
            "authority_type_by_category": {
                "water_supply": "Municipal Corporation / Water Supply Department",
                "road_pothole": "Municipal Corporation / PWD (Public Works Department)",
                "sanitation_garbage": "Municipal Corporation / Solid Waste Management Dept",
                "electricity": "MSEDCL (Maharashtra State Electricity Distribution Co.) / local discom",
                "ration_card": "Food, Civil Supplies and Consumer Protection Department",
            },
            "explanation_template": "You haven't filed a formal complaint yet, so the first step is a Grievance to the relevant department. This creates an official record and starts the statutory response clock.",
        },
        {
            "id": "R2_wants_information",
            "condition": {"wants_information_only": True},
            "action": "rti",
            "authority_type_by_category": {
                "water_supply": "Public Information Officer, Municipal Corporation",
                "road_pothole": "Public Information Officer, PWD",
                "sanitation_garbage": "Public Information Officer, Municipal Corporation",
                "electricity": "Public Information Officer, MSEDCL",
                "ration_card": "Public Information Officer, Food & Civil Supplies Dept",
            },
            "explanation_template": "You're asking for records, reasons, or status of a decision — that's an information request, not a service complaint. RTI is the correct legal route to compel a documented answer within 30 days.",
        },
        {
            "id": "R3_complaint_filed_deadline_passed_no_response",
            "condition": {"prior_complaint_filed": True, "days_since_complaint": {"gte": 21}, "response_received": False},
            "action": "escalation",
            "authority_type_by_category": {
                "water_supply": "Next-level officer / Ward Officer above original recipient",
                "road_pothole": "Next-level officer / Divisional PWD Officer",
                "sanitation_garbage": "Next-level officer / Assistant Commissioner (Ward)",
                "electricity": "Nodal Officer / Superintending Engineer, MSEDCL",
                "ration_card": "District Supply Officer",
            },
            "explanation_template": "It has been over 21 days since your grievance was filed and you haven't received a response. The statutory window has passed, so escalating to the next-level officer is the appropriate step — you don't need to file a fresh grievance.",
        },
        {
            "id": "R4_complaint_rejected_or_unsatisfactory",
            "condition": {"prior_complaint_filed": True, "response_received": True, "response_satisfactory": False},
            "action": "appeal",
            "authority_type_by_category": {
                "water_supply": "Appellate Authority, Municipal Corporation",
                "road_pothole": "Appellate Authority, PWD",
                "sanitation_garbage": "Appellate Authority, Municipal Corporation",
                "electricity": "Consumer Grievance Redressal Forum, MSEDCL",
                "ration_card": "Appellate Authority, Food & Civil Supplies Dept",
            },
            "explanation_template": "You received a response but it did not resolve your issue. Rather than re-filing, the correct next step is a formal appeal to the appellate authority, which is legally required to review the original decision.",
        },
        {
            "id": "R5_rti_filed_no_response",
            "condition": {"prior_rti_filed": True, "days_since_rti": {"gte": 30}, "rti_response_received": False},
            "action": "appeal",
            "authority_type_by_category": {"_all": "First Appellate Authority (RTI), same department"},
            "explanation_template": "Your RTI application has crossed the 30-day statutory response window with no reply. Under the RTI Act, you can now file a First Appeal directly — this is treated as a deemed refusal.",
        },
    ],
    # NOTE: "location" and "duration_or_since_when" are intentionally NOT in this
    # list. Every rule's `condition` only ever checks category, prior_complaint_filed,
    # wants_information_only, and their conditional follow-ups (days_since_complaint,
    # response_received, response_satisfactory, prior_rti_filed, days_since_rti,
    # rti_response_received) — location/duration are purely informational and never
    # affect which action gets recommended, so requiring them just adds friction.
    "required_fields": ["category", "prior_complaint_filed", "wants_information_only"],
    "conditionally_required_fields": {
        "if_prior_complaint_filed_true": ["days_since_complaint", "response_received"],
        "if_response_received_true": ["response_satisfactory"],
        "if_wants_information_only_true": ["what_information_or_record"],
    },
}


def find_missing_fields(fields: dict) -> list[str]:
    missing = [f for f in DECISION_TABLE["required_fields"] if fields.get(f) is None]
    cond = DECISION_TABLE["conditionally_required_fields"]

    if fields.get("prior_complaint_filed") is True:
        missing += [f for f in cond["if_prior_complaint_filed_true"] if fields.get(f) is None]
    if fields.get("response_received") is True:
        missing += [f for f in cond["if_response_received_true"] if fields.get(f) is None]
    if fields.get("wants_information_only") is True:
        missing += [f for f in cond["if_wants_information_only_true"] if fields.get(f) is None]

    return missing


def _condition_matches(condition: dict, fields: dict) -> bool:
    for key, expected in condition.items():
        actual = fields.get(key)
        if isinstance(expected, dict) and "gte" in expected:
            if actual is None or actual < expected["gte"]:
                return False
        else:
            if actual != expected:
                return False
    return True


def _match_rule(fields: dict):
    for rule in DECISION_TABLE["rules"]:
        if _condition_matches(rule["condition"], fields):
            return rule
    return None


def recommend_action(fields: dict) -> dict:
    missing = find_missing_fields(fields)
    if missing:
        return {"status": "incomplete", "missing_fields": missing}

    rule = _match_rule(fields)
    if not rule:
        return {
            "status": "no_rule_matched",
            "note": "This combination of facts isn't covered by the current decision table. Needs human review / decision table update.",
        }

    category = fields.get("category")
    authority_map = rule.get("authority_type_by_category", {})
    authority = authority_map.get(category) or authority_map.get("_all") or authority_map.get("_note") or "—"
    action_info = DECISION_TABLE["actions"][rule["action"]]

    return {
        "status": "recommended",
        "rule_id": rule["id"],
        "action": rule["action"],
        "action_label": action_info["label"],
        "authority": authority,
        "statutory_response_days": action_info["statutory_response_days"],
        "portal": action_info["typical_portal"],
        "explanation_template": rule["explanation_template"],
    }


def generate_explanation(recommendation: dict) -> str:
    # Purely local — no AI call. Same design decision as the frontend: the
    # rule engine's own explanation_template is already the right wording.
    if recommendation.get("status") != "recommended":
        return ""
    return recommendation["explanation_template"]
