"""
AgentControl Security Guard
Browser URL security scanning (SSRF defense, protocol checks) and prompt-injection detection.
"""

import ipaddress
import re
import socket
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field


class UrlScanResult(BaseModel):
    is_safe: bool
    url: str
    risk_level: str  # low, high, critical
    reason: Optional[str] = None
    resolved_ip: Optional[str] = None
    blocked_category: Optional[str] = None


class InjectionScanResult(BaseModel):
    is_safe: bool
    risk_score: float = Field(..., ge=0.0, le=1.0)
    detected_patterns: List[str] = Field(default_factory=list)
    sanitized_text: Optional[str] = None
    reason: Optional[str] = None


class BrowserScanner:
    """
    Validates web links and tool network targets.
    Protects against:
    - Server-Side Request Forgery (SSRF)
    - Cloud metadata endpoint access (AWS/GCP/Azure 169.254.169.254)
    - Localhost and private loopback/RFC1918 networks
    - Dangerous URL protocols (file://, javascript:, gopher:, data:)
    """

    ALLOWED_SCHEMES = {"http", "https"}
    BLOCKED_HOSTNAMES = {
        "localhost", "127.0.0.1", "::1", "metadata.google.internal",
        "instance-data", "kubernetes.default.svc"
    }

    @classmethod
    def scan_url(cls, url: str) -> UrlScanResult:
        if not url or not isinstance(url, str):
            return UrlScanResult(is_safe=False, url=url, risk_level="critical", reason="Empty or invalid URL type")

        try:
            parsed = urlparse(url)
        except Exception as e:
            return UrlScanResult(is_safe=False, url=url, risk_level="critical", reason=f"Failed to parse URL: {e}")

        # 1. Scheme check
        scheme = (parsed.scheme or "").lower()
        if scheme not in cls.ALLOWED_SCHEMES:
            return UrlScanResult(
                is_safe=False,
                url=url,
                risk_level="critical",
                reason=f"Forbidden protocol '{scheme}'. Only HTTP and HTTPS are permitted.",
                blocked_category="unsupported_protocol"
            )

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return UrlScanResult(is_safe=False, url=url, risk_level="critical", reason="Missing hostname")

        # 2. Hostname blacklist check
        if hostname in cls.BLOCKED_HOSTNAMES:
            return UrlScanResult(
                is_safe=False,
                url=url,
                risk_level="critical",
                reason=f"Host '{hostname}' is in restricted internal blocklist",
                blocked_category="ssrf_internal_host"
            )

        # 3. IP address resolution and private range verification
        try:
            # Check if hostname is direct IP literal
            try:
                ip_obj = ipaddress.ip_address(hostname)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_multicast:
                    return UrlScanResult(
                        is_safe=False,
                        url=url,
                        risk_level="critical",
                        reason=f"Direct IP {hostname} is a private/loopback/link-local address (SSRF protection)",
                        resolved_ip=str(ip_obj),
                        blocked_category="ssrf_private_ip"
                    )
            except ValueError:
                # Not a direct IP literal, resolve DNS safely
                pass

            # Resolve DNS
            addr_info = socket.getaddrinfo(hostname, None)
            for item in addr_info:
                ip_str = item[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                    return UrlScanResult(
                        is_safe=False,
                        url=url,
                        risk_level="critical",
                        reason=f"Hostname '{hostname}' resolves to private/internal IP {ip_str} (SSRF protection)",
                        resolved_ip=ip_str,
                        blocked_category="ssrf_private_dns"
                    )

            # Check for cloud metadata IP 169.254.169.254 explicitly
            if "169.254.169.254" in url:
                return UrlScanResult(
                    is_safe=False,
                    url=url,
                    risk_level="critical",
                    reason="Cloud instance metadata service access blocked",
                    blocked_category="cloud_metadata_ssrf"
                )

        except socket.gaierror:
            # DNS resolution failed or unreachable host
            pass

        return UrlScanResult(
            is_safe=True,
            url=url,
            risk_level="low",
            reason="URL passed safety and SSRF validation"
        )


class PromptInjectionScanner:
    """
    Detects attempts in user prompts or untrusted tool outputs to:
    - Hijack or override system prompt instructions
    - Force jailbreak / developer mode
    - Bypass security policies or permissions
    - Extract secrets or system prompts
    """

    INJECTION_PATTERNS = [
        (r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|directives|rules)", "ignore_previous_instructions"),
        (r"(?i)disregard\s+(the\s+)?(system\s+prompt|guidelines|safety|policies)", "disregard_system_rules"),
        (r"(?i)you\s+are\s+now\s+in\s+(developer|unrestricted|god|dan)\s+mode", "jailbreak_mode_activation"),
        (r"(?i)bypass\s+(all\s+)?(policy|policies|guardrails|security\s+checks)", "bypass_security_guardrails"),
        (r"(?i)<\|(im_start|im_end|endoftext)\|>", "special_token_injection"),
        (r"(?i)reveal\s+(your\s+)?(system\s+prompt|initial\s+prompt|api\s+keys|secrets)", "system_prompt_extraction"),
        (r"(?i)do\s+not\s+(enforce|check|validate)\s+(permissions|approval)", "disable_permission_enforcement"),
        (r"(?i)system:\s*override", "role_spoofing"),
    ]

    @classmethod
    def scan_text(cls, text: str) -> InjectionScanResult:
        if not text or not isinstance(text, str):
            return InjectionScanResult(is_safe=True, risk_score=0.0)

        matches: List[str] = []
        for pattern, label in cls.INJECTION_PATTERNS:
            if re.search(pattern, text):
                matches.append(label)

        if not matches:
            return InjectionScanResult(
                is_safe=True,
                risk_score=0.0,
                detected_patterns=[]
            )

        # Calculate risk score based on matches
        score = min(1.0, 0.40 + (len(matches) * 0.30))
        return InjectionScanResult(
            is_safe=False,
            risk_score=score,
            detected_patterns=matches,
            reason=f"Detected suspicious prompt injection pattern(s): {', '.join(matches)}"
        )

    @classmethod
    def wrap_untrusted_content(cls, content: str, source_tag: str = "tool_output") -> str:
        """
        Implements strict boundary separation for external data:
        Encloses untrusted content in XML boundaries so agent models treat it as data, not instruction.
        """
        escaped = content.replace("```", "'''")
        return f"<{source_tag} is_untrusted='true'>\n{escaped}\n</{source_tag}>"
