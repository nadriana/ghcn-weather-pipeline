from typing import Optional
from google.genai import types
from pydantic import BaseModel


class NarrativeValidatorResponse(BaseModel):
    is_valid: bool
    reason: Optional[str] = None

def validation_prompt(text, data):
    validation = f"""
        You are fact-checking a weather narrative against its source data before publication.

        Narrative:
        '{text}'

        Source data (the only facts the narrative is allowed to state):
        {data}

        Check for:
        - Numeric accuracy: every number in the narrative (temperature, precipitation, snowfall, wind, etc.) must match a value in the source data. 
        Reasonable rounding or unit-appropriate phrasing is fine; invented or contradicted numbers are not.
        - No hallucinated facts: the narrative must not mention values, elements, or conditions absent from the source data.
        - Core elements handled correctly: temperature range, precipitation, and snowfall must be reported accurately, 
        or explicitly stated as unavailable if missing from the data — not silently omitted.
        - Internal coherence: the narrative should read as a sensible, self-consistent weather summary.

        Return is_valid: true only if all checks pass.
        If any check fails, return is_valid: false and a short (max 50 characters) reason naming the specific problem, 
        e.g. "TMAX mismatch: says 30C, data says 24C".
    """
    return validation


def validate_narrative(client,text,data)-> NarrativeValidatorResponse:
    response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=validation_prompt(text,data),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=NarrativeValidatorResponse,
            )
        )
    if response is None or response.parsed is None:
            raise ValueError("Failed to validate narrative")

    return response.parsed
