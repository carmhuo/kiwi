import re
from typing import List, Dict, Any


class DataMasker:
    SENSITIVE_PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b(?:\d[ -]*?){13,16}\b"
    }

    MASK_RULES = {
        "email": lambda m: m.group(0)[0] + "***@" + m.group(0).split("@")[1],
        "phone": lambda m: "***-***-" + m.group(0)[-4:],
        "ssn": lambda _: "***-**-****",
        "credit_card": lambda m: "****-****-****-" + m.group(0)[-4:]
    }

    @classmethod
    def mask_sensitive_data(cls, data: List[Dict[str, Any]], project_id: str) -> List[Dict[str, Any]]:
        # 获取项目特定的脱敏规则
        masking_config = cls._get_project_masking_config(project_id)

        masked_data = []
        for row in data:
            masked_row = {}
            for key, value in row.items():
                if key in masking_config:
                    masked_row[key] = cls._apply_masking(str(value), masking_config[key])
                else:
                    masked_row[key] = value
            masked_data.append(masked_row)

        return masked_data

    @classmethod
    def _apply_masking(cls, value: str, rule_name: str) -> str:
        if rule_name in cls.SENSITIVE_PATTERNS:
            return re.sub(
                cls.SENSITIVE_PATTERNS[rule_name],
                cls.MASK_RULES[rule_name],
                value
            )
        return value

    @classmethod
    def _get_project_masking_config(cls, project_id: str) -> Dict[str, str]:
        # 实际实现中应从数据库获取项目脱敏配置
        # 这里返回示例配置
        return {
            "email": "email",
            "phone_number": "phone",
            "social_security": "ssn",
            "credit_card": "credit_card"
        }