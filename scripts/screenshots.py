"""Capture UI screenshots with headless Chromium (Playwright). Server must be running.

usage: python scripts/screenshots.py [base_url]
"""
import asyncio, sys
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = "docs/screenshots"


async def page(b, url, w=1440, h=900):
    pg = await b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
    await pg.goto(BASE + url)
    return pg, errors


async def main():
    all_errors = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        # 1. Analyst, demo mode: SPC signal + 5 whys + pundits
        pg, err = await page(b, "/?autoplay=demo&persona=analyst&club=HAR")
        await pg.wait_for_selector("#whys li .q", timeout=90000)
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f"{OUT}/01-analyst-control-room.png")
        await pg.locator(".chart-card").screenshot(path=f"{OUT}/02-control-chart.png")
        all_errors += err
        await pg.close()
        # 2. Casual fan, Spanish, focus player, second half live (the fatigue story)
        pg, err = await page(b, "/?autoplay=live&persona=casual&club=MIL&player=HAR-3&lang=es&start=58&speed=40")
        await pg.wait_for_selector(".badge", timeout=120000)
        await pg.wait_for_selector("#focusChip:not([hidden])", timeout=60000)
        await pg.wait_for_function("document.getElementById('ltText').textContent.length > 0 && !document.getElementById('lowerThird').hidden", timeout=60000)
        await pg.wait_for_timeout(700)
        await pg.screenshot(path=f"{OUT}/03-casual-spanish-focus.png")
        all_errors += err
        await pg.close()
        # 3. Fact-check corrections in the pundit panel
        pg, err = await page(b, "/?autoplay=demo&persona=analyst")
        await pg.wait_for_selector(".badge.corrected", timeout=150000)
        await pg.wait_for_timeout(600)
        await pg.locator(".panel-card").screenshot(path=f"{OUT}/04-pundit-factcheck.png")
        all_errors += err
        await pg.close()
        # 4. Chaos mode: agent ops with retries / fallbacks / deferrals
        pg, err = await page(b, "/?autoplay=live&persona=analyst&chaos=0.3&speed=120", h=1100)
        await pg.wait_for_timeout(20000)
        await pg.locator(".ops-card").screenshot(path=f"{OUT}/05-agent-ops-chaos.png")
        await pg.screenshot(path=f"{OUT}/06-chaos-full.png", full_page=False)
        all_errors += err
        # 5. Settings drawer
        await pg.click("#settingsBtn")
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=f"{OUT}/07-settings-drawer.png")
        await pg.close()
        # 6. Mobile
        pg, err = await page(b, "/?autoplay=demo&persona=casual&club=HAR", 390, 844)
        await pg.wait_for_selector(".lower-third:not([hidden])", timeout=90000)
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=f"{OUT}/08-mobile.png")
        all_errors += err
        await b.close()
    print("console/page errors:", all_errors or "none")


asyncio.run(main())
