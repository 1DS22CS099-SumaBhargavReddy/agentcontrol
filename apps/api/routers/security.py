"""
Security Guard Scanner Router
Live scanning endpoints for Browser URL SSRF defense, prompt injection detection, and untrusted payload wrapping.
"""

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from apps.api.auth.service import AuthenticatedUser, get_current_user
from packages.security_guard.scanner import (
    BrowserScanner,
    InjectionScanResult,
    PromptInjectionScanner,
    UrlScanResult,
)

router = APIRouter(prefix="/security", tags=["Security & Scanners"])


class UrlScanRequest(BaseModel):
    url: str = Field(..., description="Target URL to validate for SSRF, IP leakage, and protocol safety")


class PromptScanRequest(BaseModel):
    text: str = Field(..., description="Text or prompt snippet to evaluate for prompt injection patterns")


class ContentWrapRequest(BaseModel):
    content: str
    source_tag: str = "tool_output"


class ContentWrapResponse(BaseModel):
    wrapped_content: str


@router.post("/scan-url", response_model=UrlScanResult)
async def scan_browser_url(
    payload: UrlScanRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    return BrowserScanner.scan_url(payload.url)


@router.post("/scan-prompt", response_model=InjectionScanResult)
async def scan_prompt_text(
    payload: PromptScanRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    return PromptInjectionScanner.scan_text(payload.text)


@router.post("/wrap-content", response_model=ContentWrapResponse)
async def wrap_untrusted_data(
    payload: ContentWrapRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    wrapped = PromptInjectionScanner.wrap_untrusted_content(payload.content, source_tag=payload.source_tag)
    return ContentWrapResponse(wrapped_content=wrapped)
