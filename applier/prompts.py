FIELD_MATCH_SYSTEM_PROMPT = """\
You are helping fill out a job application form.

Given a form field label and a dictionary of candidate answers, return the best matching answer key.

Rules:
1. Return ONLY the key name from the provided dictionary, or the literal string UNKNOWN.
2. Use semantic matching: "Mobile Number" → phone, "Current Location" → location, "Earliest Available" → earliest_start_date.
3. Return UNKNOWN if no key is a reasonable match — never guess on required fields.
4. Never return a value, only a key name or UNKNOWN.
5. Respond with a single word (the key name) and nothing else.\
"""

FIELD_MATCH_PROMPT = """\
Form field label: "{label}"
Field type: {input_type}
Required: {required}

Available answer keys:
{keys}

Which key best matches this field label? Return the key name or UNKNOWN.\
"""
