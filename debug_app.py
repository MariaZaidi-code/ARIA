import asyncio
from playwright.async_api import async_playwright

async def debug():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            
            errors = []
            page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}"))
            
            print("Navigating to app...")
            await page.goto("http://localhost:5174", timeout=10000)
            await asyncio.sleep(2)
            await page.screenshot(path="C:/Users/Go/Desktop/ARIA/debug_01.png")
            print("Screenshot 1 saved")
            
            # Login
            email = page.locator('input[type="email"]')
            cnt = await email.count()
            print(f"Email inputs found: {cnt}")
            if cnt > 0:
                await email.first.fill("test@test.com")
                pwd = page.locator('input[type="password"]')
                if await pwd.count() > 0:
                    await pwd.first.fill("password123")
                btn = page.locator('button:has-text("Sign In")')
                if await btn.count() > 0:
                    await btn.first.click()
                    await asyncio.sleep(3)
            
            await page.screenshot(path="C:/Users/Go/Desktop/ARIA/debug_02.png")
            print("Screenshot 2 saved")
            
            # LLM selection
            llm = page.locator('button:has-text("Use Local LLM")')
            if await llm.count() > 0:
                await llm.first.click()
                await asyncio.sleep(3)
            
            await page.screenshot(path="C:/Users/Go/Desktop/ARIA/debug_03.png")
            print("Screenshot 3 saved - Dashboard")
            print(f"URL: {page.url}")
            
            # Try Insights
            insights_btn = page.locator('nav >> text=Insights, .sidebar >> text=Insights').first
            await insights_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="C:/Users/Go/Desktop/ARIA/debug_04.png")
            print("Screenshot 4 - Insights")
            
            # Try Analysis
            analysis_btn = page.locator('nav >> text=Analysis, .sidebar >> text=Analysis').first
            await analysis_btn.click()
            await asyncio.sleep(2)
            await page.screenshot(path="C:/Users/Go/Desktop/ARIA/debug_05.png")
            print("Screenshot 5 - Analysis")
            
            # Print console errors
            print("\n=== Console Errors ===")
            for e in errors:
                if "error" in e.lower() or "Error" in e:
                    print(e)
            
            await browser.close()
            print("\nDone!")
    except Exception as ex:
        print(f"Error: {ex}")
        import traceback
        traceback.print_exc()

asyncio.run(debug())
