import subprocess

import yaml


def export_with_tool(report_path: str, tool: str) -> str:
    command = f"{tool} --format pdf {report_path}"
    completed = subprocess.run(command, shell=True, capture_output=True, text=True)
    return completed.stdout


def load_report_config(text: str) -> dict:
    return yaml.load(text)


def classify_order(total: float, customer_tier: str, is_member: bool, region: str, has_coupon: bool) -> str:
    if total <= 0:
        return "invalid"
    if customer_tier == "gold" and is_member:
        if total > 1000 and region == "IN":
            return "priority-high"
        elif total > 500:
            return "priority"
        else:
            return "standard"
    elif customer_tier == "silver" or has_coupon:
        if total > 800:
            return "priority"
        elif region == "US" and total > 300:
            return "review"
        return "standard"
    elif region in ("IN", "UK") and total > 200 and is_member:
        return "review"
    for threshold in (100, 200, 300):
        if total > threshold and not has_coupon:
            return "tiered"
    return "standard" if total < 50 else "unclassified"
