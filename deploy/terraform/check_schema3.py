import json

d = json.load(open("provider_schema.json", encoding="utf-8-sig"))
rs = d["provider_schemas"]["registry.terraform.io/tencentcloudstack/tencentcloud"]

schema = rs["resource_schemas"]["tencentcloud_eip"]
attrs = schema.get("block", {}).get("attributes", {})
print("=== tencentcloud_eip full schema ===")
for a, v in sorted(attrs.items()):
    opt = v.get("optional", False)
    comp = v.get("computed", False)
    req = v.get("required", False)
    typ = v.get("type", "")
    print(f"  {a}: optional={opt}, computed={comp}, required={req}, type={typ}")

# Also check instance for user_data_raw vs user_data
schema2 = rs["resource_schemas"]["tencentcloud_instance"]
attrs2 = schema2.get("block", {}).get("attributes", {})
print("\n=== tencentcloud_instance user_data attrs ===")
for a in ["user_data", "user_data_raw", "user_data_replace_on_change"]:
    v = attrs2.get(a, {})
    print(f"  {a}: {v}")
