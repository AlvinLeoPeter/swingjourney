"""AI coaching notes from computed metrics via the Claude API.

Privacy/honesty rules:
- Only numbers go to the API — never video, never images.
- The system prompt forbids inventing numbers not present in the input.
- Low-confidence metrics are passed with their flags so the coach can
  acknowledge uncertainty instead of pretending precision.
"""

import json

from anthropic import Anthropic

MODEL = "claude-sonnet-5"
COACH_VERSION = "coach-v1"

SYSTEM_PROMPT = """You are an encouraging but precise golf coach reviewing \
face-on 2D swing-analysis metrics for an amateur golfer.

Hard rules:
- NEVER invent, estimate, or extrapolate numbers that are not present in the \
input. Only reference values exactly as given.
- Metrics marked confidence "low" or with null values must not be treated as \
facts — either skip them or note they couldn't be measured reliably.
- These metrics come from 2D pose estimation: rotation values are \
foreshortening estimates, and there is no club or ball data. Never comment \
on club path, face angle, or ball flight.
- Be specific and reference the actual numbers. Encouraging but honest — \
no empty praise.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "one_liner": {
            "type": "string",
            "description": "One sentence (max 20 words) summarizing this swing, quick-glance style.",
        },
        "strengths": {
            "type": "array",
            "description": "Exactly 3 strengths, each one sentence referencing a metric.",
            "items": {"type": "string"},
        },
        "fixes": {
            "type": "array",
            "description": "Exactly 3 priority fixes, most important first.",
            "items": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string", "description": "The problem, tied to a metric."},
                    "drill": {"type": "string", "description": "One specific practice drill for this fix."},
                },
                "required": ["issue", "drill"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["one_liner", "strengths", "fixes"],
    "additionalProperties": False,
}


def generate_coaching(metrics: dict, swing_meta: dict, quality: dict) -> dict:
    """metrics: the named-metric dict; swing_meta: club/swing_type/date;
    quality: landmark-visibility summary. Returns the coaching dict."""
    client = Anthropic()  # reads ANTHROPIC_API_KEY from env

    payload = {
        "swing": swing_meta,
        "metrics": metrics,
        "landmark_quality": quality,
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        output_config={
            "effort": "low",  # simple structured task; keeps cost/latency down
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is the swing analysis data as JSON. Produce your "
                    "coaching notes.\n\n" + json.dumps(payload, indent=2)
                ),
            }
        ],
    )

    coaching = json.loads(response.content[0].text)
    coaching["version"] = COACH_VERSION
    return coaching
