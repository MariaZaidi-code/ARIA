import asyncio
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})

        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("console", lambda msg: print(f"  [console.{msg.type}] {msg.text[:150]}") if msg.type == "error" else None)

        # Login
        print("1. Loading app...")
        await page.goto("http://localhost:5173", timeout=30000)
        await asyncio.sleep(2)
        email_input = page.locator('input[type="email"]')
        if await email_input.count() > 0:
            await email_input.first.fill("test@test.com")
            pwd = page.locator('input[type="password"]')
            if await pwd.count() > 0:
                await pwd.first.fill("password123")
            btn = page.locator('button:has-text("Sign In")')
            if await btn.count() > 0:
                await btn.first.click()
                await asyncio.sleep(3)

        # Select CLOUD LLM
        print("2. Selecting Cloud LLM...")
        llm = page.locator('button:has-text("Use Cloud LLM")')
        if await llm.count() > 0:
            await llm.first.click()
            await asyncio.sleep(3)
            print("   Cloud LLM selected")
        else:
            print("   Cloud LLM button not found, trying Local LLM...")
            llm2 = page.locator('button:has-text("Use Local LLM")')
            if await llm2.count() > 0:
                await llm2.first.click()
                await asyncio.sleep(3)

        # Wait for dashboard + auto-connect + schema
        print("3. Waiting for dashboard...")
        for i in range(30):
            await asyncio.sleep(1)
            body = await page.locator("body").inner_text()
            if "ARIA Intelligence" in body:
                print(f"   Dashboard ready after {i+1}s")
                break

        # Wait a bit more for suggestions to load
        await asyncio.sleep(3)
        body = await page.locator("body").inner_text()
        has_suggestions = "top" in body.lower() or "customer" in body.lower() or "product" in body.lower()
        print(f"   Suggestions loaded: {has_suggestions}")

        # Print what suggestions look like
        print("\n=== SUGGESTIONS CHECK ===")
        sugg_items = page.locator('.ai-suggestion-item')
        sugg_count = await sugg_items.count()
        print(f"   .ai-suggestion-item count: {sugg_count}")
        # Try alternative selectors
        sugg_items2 = page.locator('.ai-panel-suggestions button')
        sugg_count2 = await sugg_items2.count()
        print(f"   .ai-panel-suggestions button count: {sugg_count2}")

        # Type a question
        print("\n4. Typing question...")
        ai_input = page.locator('.ai-panel-input, input[placeholder*="Ask"]')
        if await ai_input.count() > 0:
            await ai_input.first.fill("How many customers are there?")
            await asyncio.sleep(1)

            # Check if submit button is enabled
            submit = page.locator('.ai-panel-submit')
            is_disabled = True
            if await submit.count() > 0:
                is_disabled = await submit.first.is_disabled()
                print(f"   Submit button disabled: {is_disabled}")

            # Click submit
            if not is_disabled:
                await submit.first.click()
                print("   Submitted!")
            else:
                # Try pressing Enter
                await ai_input.first.press("Enter")
                print("   Pressed Enter")

            # Wait for Goal Agent (cloud is fast)
            print("\n5. Waiting for analysis (cloud LLM)...")
            for i in range(60):
                await asyncio.sleep(1)
                body = await page.locator("body").inner_text()
                if i % 5 == 0:
                    has_analyzing = "Analyzing" in body
                    has_try = "Try again" in body
                    has_result_view = "Analysis" in body and ("chart" in body.lower() or "finding" in body.lower() or "result" in body.lower() or "Total Results" in body)
                    has_error = "couldn" in body or "failed" in body.lower()
                    print(f"  [{i+1}s] analyzing={has_analyzing} result={has_result_view} error={has_error} try_again={has_try}")

                if "Analysis complete" in body:
                    print(f"  ANALYSIS COMPLETE at {i+1}s")
                    break
                if ("couldn" in body or "failed" in body.lower()) and i > 10:
                    print(f"  ERROR detected at {i+1}s")
                    break
                if "Try again" in body and i > 5:
                    # Check for error details
                    for line in body.split("\n"):
                        if "couldn" in line.lower() or "failed" in line.lower() or "error" in line.lower():
                            print(f"  ERROR: {line.strip()[:200]}")
                    break

        # Print result
        print("\n=== DASHBOARD RESULT (last 2000 chars) ===")
        body = await page.locator("body").inner_text()
        print(body[-2000:].encode('ascii', 'replace').decode('ascii'))

        # Navigate to Insights
        print("\n6. INSIGHTS PAGE ===")
        await page.locator('text=Insights').first.click()
        await asyncio.sleep(2)
        body = await page.locator("body").inner_text()
        print(body[-800:].encode('ascii', 'replace').decode('ascii'))

        # Navigate to Analysis
        print("\n7. ANALYSIS PAGE ===")
        await page.locator('text=Analysis').first.click()
        await asyncio.sleep(2)
        body = await page.locator("body").inner_text()
        print(body[-800:].encode('ascii', 'replace').decode('ascii'))

        # Check for errors
        if errors:
            print(f"\n=== PAGE ERRORS ({len(errors)}) ===")
            for e in errors[:5]:
                print(f"  {e[:200]}")

        await browser.close()
        print("\nDone!")

asyncio.run(test())
