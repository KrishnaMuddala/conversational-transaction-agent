import json

d = json.load(open("provider_schema.json", encoding="utf-8-sig"))
rs = d["provider_schemas"]["registry.terraform.io/tencentcloudstack/tencentcloud"]

for name in [
    "tencentcloud_security_group_rule",
    "tencentcloud_eip",
    "tencentcloud_eip_association",
    "tencentcloud_cos_bucket",
]:
    schema = rs["resource_schemas"][name]
    attrs = schema.get("block", {}).get("attributes", {})
    print(f"=== {name} ===")
    for a, v in sorted(attrs.items()):
        opt = v.get("optional", False)
        comp = v.get("computed", False)
        req = v.get("required", False)
        print(f"  {a}: optional={opt}, computed={comp}, required={req}")
    print()
