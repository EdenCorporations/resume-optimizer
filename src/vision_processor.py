"""
VisionProcessor – Handles image classification and OCR via OpenRouter Vision LLM.

Uses the free nvidia/nemotron-nano-12b-v2-vl model on OpenRouter for:
1. Headshot vs. resume-content classification
2. OCR text extraction from images

Zero binary dependencies – works on Vercel serverless.
"""

import base64
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# OpenRouter chat completions endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class VisionProcessor:
    """Classify images and extract text using a vision LLM via OpenRouter."""

    def __init__(self, api_key: str = "", model: str = "nvidia/nemotron-nano-12b-v2-vl:free"):
        self.api_key = api_key
        self.model = model
        self.enabled = bool(api_key)
        if not self.enabled:
            logger.warning("VisionProcessor: No OPENROUTER_API_KEY – image processing disabled")

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def classify_image(self, image_bytes: bytes, mime_type: str = "image/png") -> dict:
        """
        Classify an image as either a headshot/portrait or resume/document content.

        Args:
            image_bytes: Raw image bytes
            mime_type: MIME type (image/png, image/jpeg, etc.)

        Returns:
            {"type": "headshot"|"resume_content"|"other", "confidence": float}
        """
        if not self.enabled:
            # Default: assume resume content when we can't classify
            return {"type": "resume_content", "confidence": 0.5}

        prompt = (
            "Analyze this image and classify it into exactly ONE of these categories:\n"
            "1. 'headshot' — a person's portrait, headshot, or profile photo\n"
            "2. 'resume_content' — contains text that is part of a resume or document "
            "(sections, bullet points, work experience, skills, etc.)\n"
            "3. 'other' — decorative element, logo, icon, or unrelated graphic\n\n"
            "Respond with ONLY valid JSON, nothing else:\n"
            '{"type": "<category>", "confidence": <0.0-1.0>}'
        )

        try:
            response_text = self._call_vision(image_bytes, mime_type, prompt)
            # Parse JSON from response (strip markdown fences if present)
            clean = response_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(clean)
            img_type = result.get("type", "resume_content")
            confidence = float(result.get("confidence", 0.5))

            if img_type not in ("headshot", "resume_content", "other"):
                img_type = "resume_content"

            logger.info("Image classified as '%s' (confidence: %.2f)", img_type, confidence)
            return {"type": img_type, "confidence": confidence}

        except Exception as e:
            logger.warning("Image classification failed: %s — defaulting to resume_content", e)
            return {"type": "resume_content", "confidence": 0.5}

    def ocr_image(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """
        Extract text from an image using the vision LLM as OCR.

        Args:
            image_bytes: Raw image bytes
            mime_type: MIME type

        Returns:
            Extracted text string (empty string on failure)
        """
        if not self.enabled:
            return ""

        prompt = (
            "Extract ALL text from this image exactly as written. "
            "Preserve the structure, line breaks, and formatting as closely as possible. "
            "If there are bullet points, keep them. If there are section headers, keep them.\n\n"
            "Return ONLY the extracted text, nothing else. No commentary, no explanations."
        )

        try:
            text = self._call_vision(image_bytes, mime_type, prompt)
            text = text.strip()
            logger.info("OCR extracted %d characters from image", len(text))
            return text
        except Exception as e:
            logger.warning("OCR extraction failed: %s", e)
            return ""

    # ------------------------------------------------------------------ #
    #  Internal
    # ------------------------------------------------------------------ #

    def _call_vision(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
        """
        Make a multimodal chat completion call to OpenRouter with an image.

        Args:
            image_bytes: Raw image bytes
            mime_type: MIME type for the data URI
            prompt: Text prompt to send alongside the image

        Returns:
            The model's text response

        Raises:
            Exception on API/network errors
        """
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64_image}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri},
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/EdenCorporations/resume-optimizer",
            "X-Title": "Resume Optimizer",
        }

        with httpx.Client(timeout=60) as client:
            resp = client.post(OPENROUTER_API_URL, json=payload, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter returned no choices")

        return choices[0]["message"]["content"]
