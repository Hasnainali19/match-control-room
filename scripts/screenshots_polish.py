"""Screenshots for the UI polish + Debugger panel. usage: python scripts/screenshots_polish.py [base_url]"""
import asyncio, sys
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = "docs/screenshots"


async def main():
    errs = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={"width": 1440, "height": 900})
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        await pg.goto(BASE + "/")  # first visit -> welcome
        await pg.wait_for_selector("#welcome:not([hidden])")
        await pg.wait_for_timeout(700)
        await pg.screenshot(path=f"{OUT}/09-polish.png")
        await pg.click("#wSkip")
        await pg.hover(".chart-card .info")
        await pg.wait_for_timeout(400)
        await pg.screenshot(path=f"{OUT}/09b-polish-tooltips-empty-states.png")
        await pg.keyboard.press("?")
        await pg.wait_for_timeout(400)
        await pg.screenshot(path=f"{OUT}/09c-shortcuts.png", clip={"x": 420, "y": 560, "width": 600, "height": 340})
        await pg.goto(BASE + "/?autoplay=live&persona=analyst&chaos=0.3&speed=120")
        await pg.wait_for_timeout(15000)
        await pg.keyboard.press("b")
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=f"{OUT}/10-debugger.png")
        await b.close()
    print("errors:", errs or "none")

asyncio.run(main())
