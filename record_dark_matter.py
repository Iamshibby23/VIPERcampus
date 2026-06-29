#!/usr/bin/env python3
"""
Dark Matter Creative Agency — Playwright screen recorder
Resolution : 1080 × 1920  (portrait / Instagram Reels)
Output     : dark_matter_recording.mp4 @ 60 fps, H.264

Setup (one-time):
    pip install playwright
    playwright install chromium          # or: playwright install --with-deps chromium

Run:
    python3 record_dark_matter.py

Output is written to ./dark_matter_output/dark_matter_recording.mp4

Requirements:
    - Python 3.10+
    - playwright  (pip install playwright)
    - ffmpeg      (brew install ffmpeg  /  apt install ffmpeg  /  choco install ffmpeg)

Note: CHROMIUM_BIN / FFMPEG_BIN below point to the pre-installed binaries in the
Claude Code remote environment. On a local machine, set both to "" to let
Playwright and ffmpeg be found on PATH automatically.
"""

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

# ── Configuration ─────────────────────────────────────────────────────────────
SITE          = "https://darkmattercreativeagency.com"
VIEWPORT_W    = 1080
VIEWPORT_H    = 1920
OUTPUT_DIR    = Path("./dark_matter_output")
RAW_VIDEO_DIR = OUTPUT_DIR / "raw"
FINAL_VIDEO   = OUTPUT_DIR / "dark_matter_recording.mp4"

# Binary paths — override these if playwright/ffmpeg aren't on PATH.
# Set to "" to fall back to PATH lookup (normal local machine usage).
_REMOTE_CHROMIUM = "/opt/pw-browsers/chromium"
_REMOTE_FFMPEG   = "/opt/pw-browsers/ffmpeg-1011/ffmpeg-linux"
CHROMIUM_BIN  = _REMOTE_CHROMIUM if Path(_REMOTE_CHROMIUM).exists() else ""
FFMPEG_BIN    = _REMOTE_FFMPEG   if Path(_REMOTE_FFMPEG).exists()   else "ffmpeg"

# ── Easing kernel (cubic ease-in-out) ─────────────────────────────────────────
# Injected as inline JS so scroll animations run at browser frame rate (~60 fps).
_EASE_FN = """
function easeInOutCubic(t) {
    return t < 0.5
        ? 4 * t * t * t
        : 1 - Math.pow(-2 * t + 2, 3) / 2;
}
"""

# ── Scroll helpers ─────────────────────────────────────────────────────────────

async def smooth_scroll_to(page: Page, target_y: float, duration_s: float) -> None:
    """Scroll to *target_y* over *duration_s* seconds using cubic ease-in-out.

    Driven by requestAnimationFrame inside the browser so the motion is
    captured at the browser's native frame rate. Returns only when the
    animation is complete.
    """
    target_y = max(0.0, float(target_y))
    duration_ms = max(200, duration_s * 1000)

    await page.evaluate(f"""
        () => new Promise(resolve => {{
            {_EASE_FN}
            const startY    = window.scrollY;
            const delta     = {target_y} - startY;
            const duration  = {duration_ms};
            const startTime = performance.now();

            if (Math.abs(delta) < 1) {{ resolve(); return; }}

            function step(now) {{
                const t     = Math.min((now - startTime) / duration, 1);
                const eased = easeInOutCubic(t);
                window.scrollTo(0, startY + delta * eased);
                if (t < 1) {{ requestAnimationFrame(step); }}
                else       {{ resolve(); }}
            }}
            requestAnimationFrame(step);
        }})
    """)


async def page_scroll_height(page: Page) -> float:
    return await page.evaluate(
        "document.documentElement.scrollHeight - window.innerHeight"
    )


async def scroll_to_bottom(page: Page, duration_s: float) -> None:
    h = await page_scroll_height(page)
    await smooth_scroll_to(page, h, duration_s)


async def scroll_to_top(page: Page) -> None:
    await page.evaluate("window.scrollTo(0, 0)")


# ── UI helpers ────────────────────────────────────────────────────────────────

async def hide_cursor(page: Page) -> None:
    """Inject CSS that makes every cursor invisible."""
    await page.add_style_tag(
        content="*, *::before, *::after { cursor: none !important; }"
    )


async def settle(page: Page, extra_s: float = 0) -> None:
    """Wait for network idle then hide the cursor."""
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await hide_cursor(page)
    if extra_s:
        await asyncio.sleep(extra_s)


async def element_top(page: Page, selector: str) -> Optional[float]:
    """Return the document-absolute top of the first matching element, or None."""
    return await page.evaluate(f"""
        (() => {{
            const el = document.querySelector(`{selector}`);
            if (!el) return null;
            return el.getBoundingClientRect().top + window.scrollY;
        }})()
    """)


async def click_nav(page: Page, *labels: str) -> bool:
    """Click the first nav link whose visible text matches any of *labels*."""
    for label in labels:
        for sel in [
            f"nav a:has-text('{label}')",
            f"header a:has-text('{label}')",
            f"[role='navigation'] a:has-text('{label}')",
            f"a:has-text('{label}')",
        ]:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    return True
            except Exception:
                continue
    return False


async def click_first_visible(page: Page, *selectors: str) -> bool:
    """Click the first visible element matching any selector."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.count() > 0 and await el.is_visible():
                await el.scroll_into_view_if_needed()
                await asyncio.sleep(0.25)
                await el.click()
                return True
        except Exception:
            continue
    return False


# ── Section scripts ───────────────────────────────────────────────────────────

async def do_homepage(page: Page) -> None:
    print("  → homepage")
    await page.goto(SITE, wait_until="networkidle", timeout=30_000)
    await hide_cursor(page)
    await asyncio.sleep(2)                      # initial dwell

    total_h = await page_scroll_height(page)

    # Locate stat bar and Selected Work anchors to produce timed pauses.
    stat_y = await element_top(page,
        ".stats, .stat-bar, .statistics, [class*='stat'], "
        "[class*='counter'], [class*='metric'], [class*='number']"
    )
    work_y = await element_top(page,
        "[class*='selected-work'], [class*='featured-work'], "
        "[class*='work-section'], .portfolio-preview, "
        "section:has(h2)"                        # broad fallback
    )

    if stat_y and work_y and stat_y < work_y:
        seg1 = stat_y / total_h * 8
        seg2 = (work_y - stat_y) / total_h * 8
        seg3 = (total_h - work_y) / total_h * 8

        await smooth_scroll_to(page, max(0, stat_y - 80), max(seg1, 1.5))
        await asyncio.sleep(1)                   # pause: stat bar

        await smooth_scroll_to(page, max(0, work_y - 80), max(seg2, 1.5))
        await asyncio.sleep(1)                   # pause: Selected Work

        await scroll_to_bottom(page, max(seg3, 1.0))
    else:
        # No landmarks found — scroll the full page over 8 s
        await scroll_to_bottom(page, 8)

    await asyncio.sleep(1)


async def do_services(page: Page) -> None:
    print("  → services")
    await scroll_to_top(page)
    await hide_cursor(page)

    ok = await click_nav(page, "Services")
    if not ok:
        await page.goto(f"{SITE}/services", wait_until="networkidle", timeout=30_000)
    await settle(page, extra_s=1)

    # Discover service-tier cards and pause on each one.
    tier_ys: list = await page.evaluate("""
        (() => {
            const tries = [
                '.service-tier', '.pricing-tier', '.plan', '.package',
                '[class*="tier"]', '[class*="plan"]', '[class*="package"]',
                '.pricing-card', '.service-card', '.offering', '.price-box'
            ];
            for (const sel of tries) {
                const els = [...document.querySelectorAll(sel)];
                if (els.length >= 2) {
                    return els.map(el =>
                        Math.max(0, el.getBoundingClientRect().top + window.scrollY - 80)
                    );
                }
            }
            return [];
        })()
    """)

    if tier_ys and len(tier_ys) >= 2:
        total_h  = await page_scroll_height(page)
        per_tier = 6 / len(tier_ys)
        for ty in tier_ys:
            await smooth_scroll_to(page, min(ty, total_h), max(per_tier, 0.8))
            await asyncio.sleep(1)               # pause on each tier
    else:
        await scroll_to_bottom(page, 6)

    await asyncio.sleep(0.5)


async def do_portfolio(page: Page) -> None:
    print("  → portfolio")
    await scroll_to_top(page)
    await hide_cursor(page)

    ok = await click_nav(page, "Portfolio", "Work", "Projects", "Case Studies")
    if not ok:
        await page.goto(f"{SITE}/portfolio", wait_until="networkidle", timeout=30_000)
    await settle(page, extra_s=2)               # let cards render

    await scroll_to_bottom(page, 5)
    await asyncio.sleep(0.5)

    # Click the first case-study / portfolio card.
    await scroll_to_top(page)
    await hide_cursor(page)

    case_href: Optional[str] = await page.evaluate("""
        (() => {
            const selectors = [
                '.case-study a', '.portfolio-card a', '.work-card a',
                '[class*="case-study"] a', '[class*="portfolio-item"] a',
                '[class*="work-item"] a', '.grid-item a', 'article a',
                '[class*="portfolio"] a[href]', '[class*="work-grid"] a[href]'
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.href && !el.href.includes('#')) return el.href;
            }
            return null;
        })()
    """)

    if case_href:
        await page.goto(case_href, wait_until="networkidle", timeout=25_000)
        await hide_cursor(page)
        await asyncio.sleep(1)
    else:
        # Fallback: click whatever looks like a card
        await click_first_visible(page,
            ".case-study", ".portfolio-card", ".work-card",
            "[class*='portfolio'] a", "article.card", ".grid a"
        )
        await settle(page, extra_s=1)

    await scroll_to_bottom(page, 6)
    await asyncio.sleep(0.5)


async def do_quote(page: Page) -> None:
    print("  → get a quote")
    await scroll_to_top(page)
    await hide_cursor(page)

    ok = await click_nav(page, "Get a Quote", "Get Quote", "Quote", "Contact", "Start a Project")
    if not ok:
        await page.goto(f"{SITE}/quote", wait_until="networkidle", timeout=30_000)
    await settle(page, extra_s=1)

    CONTINUE_SELS = (
        "button:has-text('Continue')",
        "button:has-text('Next')",
        "a:has-text('Continue')",
        "a:has-text('Next')",
        "[class*='continue']",
        "[class*='next-step']",
        "input[type='submit']",
        "button[type='submit']",
    )

    # ── Step 1: scroll then click Continue
    page_h = await page_scroll_height(page)
    await smooth_scroll_to(page, page_h * 0.45, 1.5)
    await asyncio.sleep(0.3)
    await smooth_scroll_to(page, page_h, 1.5)
    await asyncio.sleep(0.5)

    await click_first_visible(page, *CONTINUE_SELS)
    await asyncio.sleep(1)
    await hide_cursor(page)

    # ── Step 2: scroll then click Continue (stop here per brief)
    await scroll_to_top(page)
    page_h = await page_scroll_height(page)
    await smooth_scroll_to(page, page_h * 0.45, 1.5)
    await asyncio.sleep(0.3)
    await smooth_scroll_to(page, page_h, 1.5)
    await asyncio.sleep(0.5)

    await click_first_visible(page, *CONTINUE_SELS)
    await asyncio.sleep(1.5)                    # ← stop here


async def do_about(page: Page) -> None:
    print("  → about")
    await scroll_to_top(page)
    await hide_cursor(page)

    ok = await click_nav(page, "About", "About Us", "Our Story", "Team")
    if not ok:
        await page.goto(f"{SITE}/about", wait_until="networkidle", timeout=30_000)
    await settle(page, extra_s=1)

    await scroll_to_bottom(page, 5)
    await asyncio.sleep(1.5)                    # linger at bottom


# ── Video conversion ──────────────────────────────────────────────────────────

def convert_to_mp4(raw_dir: Path, out_path: Path) -> None:
    """Convert Playwright's WebM output to a 60-fps H.264 MP4."""
    webm_files = sorted(raw_dir.glob("*.webm"), key=lambda f: f.stat().st_mtime)
    if not webm_files:
        print("ERROR: no WebM file was produced — nothing to convert.")
        return

    src = webm_files[-1]
    print(f"  converting {src.name} → {out_path.name} …")

    # Prefer the bundled ffmpeg; fall back to system PATH.
    ffmpeg = FFMPEG_BIN if Path(FFMPEG_BIN).exists() else "ffmpeg"

    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-i",        str(src),
            # Ensure exact portrait dimensions; pad if source differs.
            "-vf",       f"scale={VIEWPORT_W}:{VIEWPORT_H}:force_original_aspect_ratio=decrease,"
                         f"pad={VIEWPORT_W}:{VIEWPORT_H}:(ow-iw)/2:(oh-ih)/2",
            "-r",        "60",           # constant 60 fps output
            "-fps_mode", "cfr",          # duplicate/drop frames to hit exactly 60
            "-c:v",      "libx264",
            "-preset",   "slow",         # better compression at cost of encode time
            "-crf",      "18",           # near-lossless perceptual quality
            "-pix_fmt",  "yuv420p",      # broad compatibility (iPhones, web)
            "-movflags", "+faststart",   # progressive download / web playback
            "-an",                       # no audio track
            str(out_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        size_mb = out_path.stat().st_size / 1_048_576
        print(f"  saved → {out_path}  ({size_mb:.1f} MB)")
    else:
        print("ffmpeg error output (last 60 lines):")
        print("\n".join(result.stderr.splitlines()[-60:]))


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    print("Launching browser …")
    async with async_playwright() as pw:
        launch_kwargs = dict(headless=True)
        if CHROMIUM_BIN:
            launch_kwargs["executable_path"] = CHROMIUM_BIN

        browser = await pw.chromium.launch(
            **launch_kwargs,
            args=[
                "--headless=new",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",          # no scroll-bar chrome in video
                "--disable-infobars",
                "--no-default-browser-check",
                "--force-device-scale-factor=1",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
            ],
        )

        context: BrowserContext = await browser.new_context(
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
            record_video_dir=str(RAW_VIDEO_DIR),
            record_video_size={"width": VIEWPORT_W, "height": VIEWPORT_H},
            device_scale_factor=1,
            ignore_https_errors=True,
        )

        page = await context.new_page()

        # Global: disable CSS transitions/animations that fight scroll timing,
        # and guarantee the cursor is always hidden after any navigation.
        await context.add_init_script("""
            // Kill CSS transitions & animations so page renders instantly
            const style = document.createElement('style');
            style.textContent = `
                *, *::before, *::after {
                    transition: none !important;
                    animation-duration: 0.001s !important;
                    cursor: none !important;
                }
            `;
            document.addEventListener('DOMContentLoaded', () => {
                document.head.appendChild(style);
            });
        """)

        print("Recording …")
        await do_homepage(page)
        await do_services(page)
        await do_portfolio(page)
        await do_quote(page)
        await do_about(page)

        print("Closing context and flushing video …")
        await context.close()
        await browser.close()

    convert_to_mp4(RAW_VIDEO_DIR, FINAL_VIDEO)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
