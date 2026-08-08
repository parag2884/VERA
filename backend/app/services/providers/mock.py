from __future__ import annotations

import json
import re
from typing import Any

from app.stores.vector import local_embed


class MockLLMProvider:
    mode = "mock"

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        system = next((m["content"] for m in messages if m["role"] == "system"), "")

        # Graph extraction
        if "extract entities" in system.lower() or "extract entities" in user.lower():
            return self._extract_json(user)

        # Entity resolve assist
        if "resolve entities" in system.lower():
            return json.dumps({"entities": re.findall(r"[A-Z][A-Za-z0-9\- ]{2,}", user)[:8]})

        # Answer generation with evidence
        if "evidence pack" in system.lower() or "cited answer" in system.lower():
            return json.dumps(
                {
                    "decision": "answer",
                    "answer": "Based on the Trust Trail evidence, MFA is required for VPN access.",
                    "claims": [
                        {
                            "claim_text": "MFA is required for VPN access.",
                            "support_status": "supported",
                        }
                    ],
                }
            )

        # Voice rewrite for agent tone / verbosity
        if "rewrite the answer for voice only" in system.lower():
            return json.dumps({"answer": user.strip()})

        # GPT search-term expansion for retrieval
        if "literal search terms" in system.lower() or "extract 3-8 literal" in system.lower():
            words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", user)
            return json.dumps({"terms": words[:6]})

        # Evidence-bound GPT answerer
        if "evidence-bound answerer" in system.lower() or "use only the provided source quotes" in system.lower():
            quotes = re.findall(r"Quote:\s*(.+)", user)
            qmatch = re.search(r"Question:\s*(.+)", user)
            question = (qmatch.group(1).strip() if qmatch else "").lower()
            if not quotes:
                return json.dumps(
                    {
                        "sufficient": False,
                        "answer": "",
                        "reason": "No quotes in mock pack.",
                    }
                )
            snippet = quotes[0].strip()
            if "sl3000" in question or "sl2000" in question:
                answer = (
                    "SL2000 and SL3000 are PlayReady security levels. "
                    f"From sources: {snippet[:240]}"
                )
            else:
                answer = f"Based on connected sources: {snippet[:320]}"
            return json.dumps(
                {"sufficient": True, "answer": answer, "reason": "mock_grounded"}
            )

        # Document overview grounded on quotes
        if "summarize what the source document covers" in system.lower():
            quotes = re.findall(r"\[\d+\]\s*\([^)]*\)\s*(.+)", user)
            bullets = []
            for q in quotes[:4]:
                snip = q.strip()
                if len(snip) > 160:
                    snip = snip[:157] + "…"
                bullets.append(f"• {snip}")
            if not bullets:
                bullets = ["• Sample document content from connected sources."]
            title = "Connected document"
            m = re.search(r"\((\s*[^)]+\.pdf)\)", user, re.I)
            if m:
                title = m.group(1).strip()
            return json.dumps(
                {
                    "summary": f"{title} covers:\n" + "\n".join(bullets),
                }
            )

        if "route" in system.lower():
            q = user.lower()
            if any(x in q for x in ("password", "secret", "api key", "ssn")):
                intent = "secret"
            elif any(
                x in q
                for x in (
                    "summarize",
                    "overview",
                    "whats there",
                    "what's there",
                    "what is there",
                    "what's in",
                    "in the agreement",
                    "in this document",
                )
            ):
                intent = "fuzzy"
            else:
                intent = "structural"
            return json.dumps({"intent": intent, "reason": "mock_route"})

        return json.dumps({"ok": True, "text": "Mock response"})

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return local_embed(texts)

    def _extract_json(self, text: str) -> str:
        entities = []
        relations = []
        patterns = [
            (r"\bMFA\b", "Control", "MFA"),
            (r"Multi-Factor Authentication", "Control", "Multi-Factor Authentication"),
            (r"\bVPN\b", "System", "VPN"),
            (r"Access Policy", "Policy", "Access Policy"),
            (r"Remote Access Policy", "Policy", "Remote Access Policy"),
            (r"IT Security Team", "Team", "IT Security Team"),
            (r"Okta", "System", "Okta"),
        ]
        found: dict[str, str] = {}
        for pat, typ, name in patterns:
            if re.search(pat, text, re.I):
                found[name] = typ
                entities.append({"name": name, "type": typ, "aliases": []})

        lower = text.lower()
        if "mfa" in lower and "vpn" in lower and ("require" in lower or "must" in lower):
            relations.append(
                {
                    "src": "VPN",
                    "rel": "REQUIRES",
                    "dst": "MFA",
                    "quote": self._find_span(text, "MFA"),
                    "confidence": 0.92,
                }
            )
        if "okta" in lower and "mfa" in lower:
            relations.append(
                {
                    "src": "Okta",
                    "rel": "PART_OF",
                    "dst": "MFA",
                    "quote": self._find_span(text, "Okta"),
                    "confidence": 0.8,
                }
            )
        if "it security team" in lower and "owns" in lower:
            relations.append(
                {
                    "src": "IT Security Team",
                    "rel": "OWNS",
                    "dst": "VPN",
                    "quote": self._find_span(text, "IT Security"),
                    "confidence": 0.85,
                }
            )
        if "supersede" in lower or "replaces" in lower:
            relations.append(
                {
                    "src": "Remote Access Policy",
                    "rel": "SUPERSEDES",
                    "dst": "Access Policy",
                    "quote": self._find_span(text, "supersede"),
                    "confidence": 0.9,
                }
            )
        if "conflict" in lower:
            relations.append(
                {
                    "src": "Access Policy",
                    "rel": "CONFLICTS_WITH",
                    "dst": "Remote Access Policy",
                    "quote": self._find_span(text, "conflict"),
                    "confidence": 0.88,
                }
            )

        return json.dumps({"entities": entities, "relations": relations})

    def _find_span(self, text: str, needle: str) -> str:
        idx = text.lower().find(needle.lower())
        if idx < 0:
            return text[:160]
        start = max(0, idx - 40)
        end = min(len(text), idx + 120)
        return text[start:end].strip()
